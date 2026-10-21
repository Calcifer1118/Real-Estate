"""SQLite storage: businesses, their invoice counters, and every issued receipt."""
import json
import sqlite3
from datetime import datetime

from receipt import compute_totals, format_invoice_no, merged_template

SCHEMA = """
CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL DEFAULT '',
    next_number INTEGER NOT NULL DEFAULT 1,
    number_width INTEGER NOT NULL DEFAULT 6,
    series_end INTEGER,
    template TEXT NOT NULL DEFAULT '{}',
    logo TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    number INTEGER NOT NULL,
    invoice_no TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    total TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'issued',
    void_reason TEXT,
    print_count INTEGER NOT NULL DEFAULT 0,
    last_print_error TEXT,
    UNIQUE (business_id, invoice_no)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULT_SETTINGS = {"mode": "serial", "device": "", "chunk_size": 256, "chunk_delay_ms": 30, "timeout_s": 15}


class StoreError(ValueError):
    pass


def now():
    return datetime.now().replace(microsecond=0).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return _Closing(db)

    # --- businesses ---------------------------------------------------------

    def list_businesses(self):
        with self.connect() as db:
            return [self._business(r) for r in db.execute("SELECT * FROM businesses ORDER BY name COLLATE NOCASE")]

    def get_business(self, business_id, db=None):
        if db is None:
            with self.connect() as db:
                return self.get_business(business_id, db)
        row = db.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if not row:
            raise StoreError("Business not found")
        return self._business(row)

    def save_business(self, data, business_id=None):
        name = str(data.get("name") or "").strip()
        if not name:
            raise StoreError("Business name is required")
        prefix = str(data.get("prefix") or "")
        next_number = _int(data.get("next_number"), "Next invoice number", minimum=0)
        width = _int(data.get("number_width", 6), "Number of digits", minimum=0)
        if width > 12:
            raise StoreError("Number of digits must be 12 or fewer")
        series_end = data.get("series_end")
        series_end = None if series_end in (None, "") else _int(series_end, "Last number in series", minimum=0)
        if series_end is not None and series_end < next_number:
            raise StoreError("Last number in series is lower than the next invoice number")
        template = data.get("template")
        if template is None:
            template = {"header_lines": [{"text": name, "align": "center", "bold": True, "size": "tall"}]}
        template = merged_template(template)
        logo = data.get("logo") or None
        stamp = now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                if business_id is not None:
                    self.get_business(business_id, db)
                    candidate = format_invoice_no(prefix, next_number, width)
                    clash = db.execute("SELECT 1 FROM receipts WHERE business_id = ? AND invoice_no = ?",
                                       (business_id, candidate)).fetchone()
                    if clash:
                        raise StoreError(f"Invoice {candidate} was already issued. Set a higher next number.")
                    db.execute(
                        "UPDATE businesses SET name=?, prefix=?, next_number=?, number_width=?, series_end=?,"
                        " template=?, logo=?, updated_at=? WHERE id=?",
                        (name, prefix, next_number, width, series_end, json.dumps(template),
                         json.dumps(logo) if logo else None, stamp, business_id))
                else:
                    business_id = db.execute(
                        "INSERT INTO businesses (name, prefix, next_number, number_width, series_end, template, logo,"
                        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                        (name, prefix, next_number, width, series_end, json.dumps(template),
                         json.dumps(logo) if logo else None, stamp, stamp)).lastrowid
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get_business(business_id)

    def delete_business(self, business_id):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM receipts WHERE business_id = ? LIMIT 1", (business_id,)).fetchone():
                raise StoreError("This business has issued invoices and can't be deleted")
            db.execute("DELETE FROM businesses WHERE id = ?", (business_id,))

    # --- receipts -----------------------------------------------------------

    def issue(self, business_id, receipt, issued_at=None):
        """Take the next invoice number and record the sale, atomically.

        The business (name, layout, logo) is copied into the receipt so reprints look
        exactly like the original even if the layout is edited later.
        """
        issued_at = issued_at or now()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                biz = self.get_business(business_id, db)
                number = biz["next_number"]
                if biz["series_end"] is not None and number > biz["series_end"]:
                    raise StoreError(f"Invoice series is used up (last number {biz['series_end']}). "
                                     "Update the series in the business settings.")
                invoice_no = format_invoice_no(biz["prefix"], number, biz["number_width"])
                snapshot = {"business": {k: biz[k] for k in ("id", "name", "template", "logo")}, "receipt": receipt}
                total = compute_totals(receipt, biz["template"])["total"]
                try:
                    rid = db.execute(
                        "INSERT INTO receipts (business_id, number, invoice_no, issued_at, snapshot, total)"
                        " VALUES (?,?,?,?,?,?)",
                        (business_id, number, invoice_no, issued_at, json.dumps(snapshot), str(total))).lastrowid
                except sqlite3.IntegrityError:
                    raise StoreError(f"Invoice {invoice_no} was already issued. Check the next number.")
                db.execute("UPDATE businesses SET next_number = ? WHERE id = ?", (number + 1, business_id))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
        return self.get_receipt(rid)

    def get_receipt(self, receipt_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        if not row:
            raise StoreError("Receipt not found")
        return self._receipt(row)

    def list_receipts(self, business_id, limit=200, search=""):
        sql = "SELECT * FROM receipts WHERE business_id = ?"
        args = [business_id]
        if search:
            sql += " AND (invoice_no LIKE ? OR snapshot LIKE ?)"
            args += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(int(limit))
        with self.connect() as db:
            return [self._receipt(r) for r in db.execute(sql, args)]

    def record_print(self, receipt_id, error=None):
        with self.connect() as db:
            if error:
                db.execute("UPDATE receipts SET last_print_error = ? WHERE id = ?", (str(error), receipt_id))
            else:
                db.execute("UPDATE receipts SET print_count = print_count + 1, last_print_error = NULL WHERE id = ?",
                           (receipt_id,))

    def void(self, receipt_id, reason):
        if not str(reason or "").strip():
            raise StoreError("A reason is required to void an invoice")
        with self.connect() as db:
            db.execute("UPDATE receipts SET status = 'void', void_reason = ? WHERE id = ?", (reason.strip(), receipt_id))
        return self.get_receipt(receipt_id)

    # --- settings -----------------------------------------------------------

    def settings(self):
        out = dict(DEFAULT_SETTINGS)
        with self.connect() as db:
            for r in db.execute("SELECT key, value FROM settings"):
                out[r["key"]] = json.loads(r["value"])
        return out

    def save_settings(self, data):
        with self.connect() as db:
            for key in DEFAULT_SETTINGS:
                if key in data:
                    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json.dumps(data[key])))
        return self.settings()

    # --- helpers ------------------------------------------------------------

    @staticmethod
    def _business(row):
        b = dict(row)
        b["template"] = merged_template(json.loads(b["template"]))
        b["logo"] = json.loads(b["logo"]) if b["logo"] else None
        b["next_invoice_no"] = format_invoice_no(b["prefix"], b["next_number"], b["number_width"])
        return b

    @staticmethod
    def _receipt(row):
        r = dict(row)
        r["snapshot"] = json.loads(r["snapshot"])
        return r


def _int(value, label, minimum=None):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise StoreError(f"{label} must be a whole number")
    if minimum is not None and n < minimum:
        raise StoreError(f"{label} must be at least {minimum}")
    return n


class _Closing:
    """sqlite3's own context manager doesn't close the connection; this one does."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        self.db.close()
