"""Receipt layout and ESC/POS encoding for 58mm Bluetooth thermal printers (PT-210 / MTP-2).

The layout step produces fixed-width rows. The on-screen preview and the bytes sent
to the printer are both built from those same rows, so what you see is what prints.
"""
import base64
import copy
import textwrap
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

ESC = b"\x1b"
GS = b"\x1d"
LF = b"\n"

# GS ! n: character width/height multipliers.
SIZES = {"normal": 0x00, "tall": 0x01, "wide": 0x10, "big": 0x11}
ALIGNS = ("left", "center", "right")

# The printer uses code page 437 (ESC t 0). Characters it lacks are swapped for close
# equivalents here; anything else prints as "?", and the preview shows the same "?".
REPLACEMENTS = {
    "₱": "P",  # peso sign
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", " ": " ",
}

DEFAULT_TEMPLATE = {
    "chars_per_line": 32,
    "header_lines": [],
    "title": "SALES INVOICE",
    "title_size": "normal",
    "invoice_label": "Invoice No.",
    "date_label": "Date",
    "date_format": "%m/%d/%Y %I:%M %p",
    "customer_fields": [
        {"key": "name", "label": "Sold to", "enabled": True},
        {"key": "address", "label": "Address", "enabled": True},
        {"key": "tin", "label": "TIN", "enabled": True},
        {"key": "business_style", "label": "Bus. Style", "enabled": False},
    ],
    "blank_customer_lines": True,
    "item_style": "detailed",
    "vat_mode": "vat",
    "vat_rate": 12,
    "show_exempt_zero_rated": True,
    "show_cashier": False,
    "footer_lines": [],
    "feed_lines": 4,
    "currency": "",
}

MAX_DOTS = 384  # printable width of a 58mm head at 203 dpi


def merged_template(template):
    out = copy.deepcopy(DEFAULT_TEMPLATE)
    out.update(template or {})
    return out


def money(value):
    try:
        return Decimal(str(value if value not in (None, "") else 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    except Exception:
        raise ValueError(f"Not a valid amount: {value!r}")


def qty_value(value):
    try:
        q = Decimal(str(value if value not in (None, "") else 1))
    except Exception:
        raise ValueError(f"Not a valid quantity: {value!r}")
    return q.normalize() if q == q.to_integral() else q


def fmt_money(d):
    return f"{d:,.2f}"


def printable(text):
    """Return text exactly as the printer will render it."""
    text = "".join(REPLACEMENTS.get(c, c) for c in str(text))
    text = text.replace("\t", " ").replace("\r", "")
    return text.encode("cp437", "replace").decode("cp437")


def format_invoice_no(prefix, number, width):
    return f"{prefix or ''}{str(number).zfill(int(width or 0))}"


def compute_totals(receipt, template):
    items = []
    subtotal = Decimal("0.00")
    for raw in receipt.get("items") or []:
        desc = str(raw.get("description") or "").strip()
        if not desc and raw.get("price") in (None, ""):
            continue
        qty = qty_value(raw.get("qty"))
        price = money(raw.get("price"))
        amount = (qty * price).quantize(Decimal("0.01"), ROUND_HALF_UP)
        items.append({"description": desc, "qty": qty, "price": price, "amount": amount})
        subtotal += amount
    discount = money(receipt.get("discount"))
    total = subtotal - discount
    totals = {"items": items, "subtotal": subtotal, "discount": discount, "total": total}
    if template["vat_mode"] == "vat":
        rate = Decimal(str(template.get("vat_rate") or 0))
        vatable = (total / (1 + rate / 100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
        totals.update(vat_rate=rate, vatable=vatable, vat=total - vatable)
    cash = receipt.get("cash")
    if cash not in (None, ""):
        cash = money(cash)
        totals.update(cash=cash, change=cash - total)
    return totals


class Layout:
    def __init__(self, cols):
        self.cols = int(cols)
        self.rows = []

    def width(self, size):
        return self.cols // 2 if size in ("wide", "big") else self.cols

    def text(self, text, align="left", bold=False, size="normal"):
        size = size if size in SIZES else "normal"
        align = align if align in ALIGNS else "left"
        w = self.width(size)
        for chunk in _wrap(printable(text), w):
            if align == "center":
                chunk = chunk.center(w).rstrip()
            elif align == "right":
                chunk = chunk.rjust(w)
            self.rows.append({"text": chunk, "bold": bool(bold), "size": size})

    def pair(self, left, right, bold=False, size="normal"):
        """Left text with right text flush to the right edge, wrapping left if needed."""
        w = self.width(size)
        left, right = printable(left), printable(right)
        if len(left) + 1 + len(right) <= w:
            self.rows.append({"text": left + right.rjust(w - len(left)), "bold": bool(bold), "size": size})
            return
        lines = _wrap(left, w)
        last = lines.pop()
        for line in lines:
            self.rows.append({"text": line, "bold": bool(bold), "size": size})
        if len(last) + 1 + len(right) <= w:
            self.rows.append({"text": last + right.rjust(w - len(last)), "bold": bool(bold), "size": size})
        else:
            self.rows.append({"text": last, "bold": bool(bold), "size": size})
            self.rows.append({"text": right.rjust(w), "bold": bool(bold), "size": size})

    def rule(self, char="-"):
        self.rows.append({"text": char * self.cols, "bold": False, "size": "normal"})

    def blank(self):
        self.rows.append({"text": "", "bold": False, "size": "normal"})

    def logo(self):
        self.rows.append({"logo": True})


def _wrap(text, width):
    out = []
    for para in str(text).split("\n"):
        out.extend(textwrap.wrap(para, width, break_long_words=True, break_on_hyphens=False) or [""])
    return out


def _fill(template_text, values):
    for key, value in values.items():
        template_text = template_text.replace("{" + key + "}", str(value))
    return template_text


def build_layout(business, receipt, invoice_no, issued_at, copy_label=None):
    """Lay out one receipt. `business` holds name/template/logo; `receipt` is the sale."""
    t = merged_template(business.get("template"))
    lay = Layout(t["chars_per_line"])
    totals = compute_totals(receipt, t)
    when = issued_at if isinstance(issued_at, datetime) else datetime.fromisoformat(issued_at)
    date_text = when.strftime(t["date_format"] or "%m/%d/%Y %I:%M %p")
    placeholders = {"invoice_no": invoice_no, "date": date_text, "business": business.get("name", "")}
    cur = t.get("currency") or ""

    if business.get("logo"):
        lay.logo()
    for line in t["header_lines"]:
        lay.text(_fill(line.get("text", ""), placeholders), line.get("align", "center"),
                 line.get("bold", False), line.get("size", "normal"))
    if t["title"]:
        lay.blank()
        lay.text(t["title"], "center", True, t.get("title_size") or "normal")
    if copy_label:
        lay.text(copy_label, "center", True)
    lay.rule()
    lay.pair(f"{t['invoice_label']}", invoice_no, bold=True)
    lay.pair(f"{t['date_label']}", date_text)
    if t["show_cashier"] and receipt.get("cashier"):
        lay.pair("Cashier", receipt["cashier"])

    customer = receipt.get("customer") or {}
    fields = [f for f in t["customer_fields"] if f.get("enabled")]
    if fields:
        lay.rule()
        for f in fields:
            value = str(customer.get(f["key"]) or "").strip()
            label = f"{f['label']}: "
            if value:
                lay.text(label + value)
            elif t["blank_customer_lines"]:
                lay.text(label + "_" * max(lay.cols - len(printable(label)), 0))

    lay.rule()
    for item in totals["items"]:
        qty = item["qty"]
        if t["item_style"] == "compact":
            prefix = f"{qty} " if qty != 1 else ""
            lay.pair(prefix + item["description"], fmt_money(item["amount"]))
        else:
            lay.text(item["description"] or "(item)")
            lay.pair(f"  {qty} x {fmt_money(item['price'])}", fmt_money(item["amount"]))
    lay.rule()

    if totals["discount"]:
        lay.pair("Subtotal", fmt_money(totals["subtotal"]))
        lay.pair("Discount", "-" + fmt_money(totals["discount"]))
    lay.pair("TOTAL", cur + fmt_money(totals["total"]), bold=True, size="tall")
    if "cash" in totals:
        lay.pair("Cash", fmt_money(totals["cash"]))
        lay.pair("Change", fmt_money(totals["change"]))

    if t["vat_mode"] == "vat":
        lay.rule()
        lay.pair("VATable Sales", fmt_money(totals["vatable"]))
        if t["show_exempt_zero_rated"]:
            lay.pair("VAT-Exempt Sales", "0.00")
            lay.pair("Zero-Rated Sales", "0.00")
        lay.pair(f"VAT ({totals['vat_rate'].normalize()}%)", fmt_money(totals["vat"]))

    if receipt.get("notes"):
        lay.rule()
        lay.text(receipt["notes"])

    if t["footer_lines"]:
        lay.blank()
        for line in t["footer_lines"]:
            lay.text(_fill(line.get("text", ""), placeholders), line.get("align", "center"),
                     line.get("bold", False), line.get("size", "normal"))
    return lay, totals, t


def logo_bytes(logo):
    """Validate a stored logo ({width, height, data: base64 1-bit rows}) and return its raw bits."""
    width, height = int(logo["width"]), int(logo["height"])
    if width <= 0 or width % 8 or width > MAX_DOTS or height <= 0:
        raise ValueError("Logo must be a multiple of 8 dots wide, at most 384")
    data = base64.b64decode(logo["data"])
    if len(data) != width // 8 * height:
        raise ValueError("Logo data does not match its size")
    return width, height, data


def encode_escpos(layout, logo=None, feed_lines=4):
    out = bytearray(ESC + b"@" + ESC + b"t\x00")
    for row in layout.rows:
        if row.get("logo"):
            if logo:
                out += ESC + b"a\x01" + _raster(*logo_bytes(logo)) + ESC + b"a\x00"
            continue
        out += ESC + b"E" + bytes([1 if row["bold"] else 0])
        out += GS + b"!" + bytes([SIZES[row["size"]]])
        out += row["text"].rstrip().encode("cp437", "replace") + LF
    out += ESC + b"E\x00" + GS + b"!\x00"
    out += ESC + b"d" + bytes([max(0, min(int(feed_lines), 10))])
    return bytes(out)


def _raster(width, height, data, band=24):
    # Cheap printers have small buffers, so send the image in short horizontal bands.
    xbytes = width // 8
    out = bytearray()
    for top in range(0, height, band):
        rows = min(band, height - top)
        out += GS + b"v0\x00" + bytes([xbytes & 0xFF, xbytes >> 8, rows & 0xFF, rows >> 8])
        out += data[top * xbytes:(top + rows) * xbytes]
    return bytes(out)


def test_page(cols=32):
    lay = Layout(cols)
    lay.text("PRINTER TEST", "center", True, "big")
    lay.rule()
    lay.text("Normal text, left")
    lay.text("Centered", "center")
    lay.text("Right", "right")
    lay.text("Bold text", bold=True)
    lay.text("Tall text", size="tall")
    lay.text("Wide text", size="wide")
    lay.text("Big", "center", size="big")
    lay.rule()
    lay.text(("1234567890" * 10)[:cols])
    lay.text(f"^ should be exactly one line")
    lay.text("Ñ ñ  P1,234.56")
    lay.rule("=")
    return lay
