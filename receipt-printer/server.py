#!/usr/bin/env python3
"""Local receipt printing app. Run: python3 server.py, then open http://127.0.0.1:8765

Uses only the Python standard library, so there is nothing to install.
"""
import argparse
import contextlib
import csv
import io
import json
import mimetypes
import os
import re
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import printer  # noqa: E402
from receipt import build_layout, compute_totals, encode_escpos, format_invoice_no, merged_template, test_page  # noqa: E402
from store import Store, StoreError  # noqa: E402

STATIC = HERE / "static"
SAMPLE_RECEIPT = {
    "customer": {"name": "Juan Dela Cruz", "address": "123 Rizal St., Quezon City", "tin": "123-456-789-000"},
    "items": [
        {"description": "Sample item", "qty": 2, "price": "150.00"},
        {"description": "Another item with a longer name", "qty": 1, "price": "1250.50"},
    ],
    "cash": "2000",
}


class App:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir / "receipts.db")
        self.out_dir = self.data_dir / "test-prints"

    # Rendering ---------------------------------------------------------------

    def render(self, business, receipt, invoice_no, issued_at, copy_label=None):
        layout, totals, template = build_layout(business, receipt, invoice_no, issued_at, copy_label)
        data = encode_escpos(layout, business.get("logo"), template["feed_lines"])
        logo = business.get("logo") or {}
        return {
            "rows": layout.rows,
            "cols": layout.cols,
            "logo_preview": logo.get("preview"),
            "logo_width": logo.get("width"),
            "invoice_no": invoice_no,
            "totals": {k: v for k, v in totals.items() if k != "items"},
            "bytes": len(data),
        }, data

    def render_receipt(self, rec, copy_label=None):
        snap = rec["snapshot"]
        return self.render(snap["business"], snap["receipt"], rec["invoice_no"], rec["issued_at"], copy_label)

    def send(self, data):
        with printer.Connection(self.store.settings(), self.out_dir) as conn:
            return conn.write(data)

    # Receipts ----------------------------------------------------------------

    def issue(self, business_id, receipt, do_print=True):
        biz = self.store.get_business(business_id)
        totals = compute_totals(receipt, biz["template"])
        if not totals["items"]:
            raise StoreError("Add at least one item")
        if totals["total"] < 0:
            raise StoreError("Total can't be negative")
        with contextlib.ExitStack() as stack:
            # Connect before taking a number, so an unreachable printer doesn't use one up.
            conn = stack.enter_context(printer.Connection(self.store.settings(), self.out_dir)) if do_print else None
            rec = self.store.issue(business_id, receipt)
            view, data = self.render_receipt(rec)
            result = {"receipt": rec, "preview": view, "printed": False}
            if conn:
                try:
                    result["saved_to"] = conn.write(data)
                    self.store.record_print(rec["id"])
                    result["printed"] = True
                except printer.PrinterError as e:
                    self.store.record_print(rec["id"], e)
                    result["print_error"] = str(e)
            result["receipt"] = self.store.get_receipt(rec["id"])
            return result

    def reprint(self, receipt_id):
        rec = self.store.get_receipt(receipt_id)
        if rec["status"] == "void":
            raise StoreError("This invoice is void and can't be reprinted")
        label = "REPRINT" if rec["print_count"] else None
        _, data = self.render_receipt(rec, label)
        try:
            saved = self.send(data)
        except printer.PrinterError as e:
            self.store.record_print(receipt_id, e)
            raise
        self.store.record_print(receipt_id)
        return {"receipt": self.store.get_receipt(receipt_id), "printed": True, "saved_to": saved}

    def csv_export(self, business_id):
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Invoice No.", "Date", "Customer", "TIN", "Items", "Total", "Status", "Void reason", "Times printed"])
        for r in reversed(self.store.list_receipts(business_id, limit=1_000_000)):
            sale = r["snapshot"]["receipt"]
            cust = sale.get("customer") or {}
            items = "; ".join(f"{i.get('qty', 1)} x {i.get('description', '')} @ {i.get('price', '')}"
                              for i in sale.get("items") or [])
            w.writerow([r["invoice_no"], r["issued_at"].replace("T", " "), cust.get("name", ""), cust.get("tin", ""),
                        items, r["total"], r["status"], r["void_reason"] or "", r["print_count"]])
        return buf.getvalue()


def make_handler(app):
    routes = []

    def route(method, pattern):
        def deco(fn):
            routes.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return deco

    @route("GET", "/api/state")
    def state(req, body, q):
        return {"businesses": app.store.list_businesses(), "settings": app.store.settings(),
                "ports": printer.list_ports(), "data_dir": str(app.data_dir)}

    @route("POST", "/api/businesses")
    def create_business(req, body, q):
        return app.store.save_business(body)

    @route("PUT", r"/api/businesses/(\d+)")
    def update_business(req, body, q, bid):
        return app.store.save_business(body, int(bid))

    @route("DELETE", r"/api/businesses/(\d+)")
    def delete_business(req, body, q, bid):
        app.store.delete_business(int(bid))
        return {"ok": True}

    @route("POST", "/api/preview")
    def preview(req, body, q):
        biz = _business_from(body)
        receipt = body.get("receipt") or SAMPLE_RECEIPT
        number = body.get("invoice_no") or biz.get("next_invoice_no") or "000001"
        view, _ = app.render(biz, receipt, number, datetime.now(), body.get("copy_label"))
        return view

    @route("POST", "/api/sample-print")
    def sample_print(req, body, q):
        biz = _business_from(body)
        view, data = app.render(biz, body.get("receipt") or SAMPLE_RECEIPT, "SAMPLE", datetime.now(),
                                "SAMPLE ONLY - NOT AN INVOICE")
        return {"printed": True, "saved_to": app.send(data), "preview": view}

    @route("POST", "/api/receipts")
    def create_receipt(req, body, q):
        return app.issue(int(body["business_id"]), body.get("receipt") or {}, body.get("print", True))

    @route("GET", "/api/receipts")
    def list_receipts(req, body, q):
        return app.store.list_receipts(int(q["business_id"]), int(q.get("limit", 200)), q.get("search", ""))

    @route("GET", r"/api/receipts/(\d+)")
    def get_receipt(req, body, q, rid):
        rec = app.store.get_receipt(int(rid))
        view, _ = app.render_receipt(rec, "VOID" if rec["status"] == "void" else None)
        return {"receipt": rec, "preview": view}

    @route("POST", r"/api/receipts/(\d+)/reprint")
    def reprint(req, body, q, rid):
        return app.reprint(int(rid))

    @route("POST", r"/api/receipts/(\d+)/void")
    def void(req, body, q, rid):
        return app.store.void(int(rid), body.get("reason", ""))

    @route("PUT", "/api/settings")
    def save_settings(req, body, q):
        return app.store.save_settings(body)

    @route("GET", "/api/printer/ports")
    def ports(req, body, q):
        return printer.list_ports()

    @route("POST", "/api/printer/test")
    def print_test(req, body, q):
        layout = test_page(int(body.get("cols") or 32))
        return {"printed": True, "saved_to": app.send(encode_escpos(layout))}

    def _business_from(body):
        if body.get("business"):
            biz = dict(body["business"])
            biz["template"] = merged_template(biz.get("template"))
            try:
                biz["next_invoice_no"] = format_invoice_no(biz.get("prefix"), int(biz.get("next_number") or 1),
                                                           int(biz.get("number_width") or 0))
            except ValueError:
                biz["next_invoice_no"] = "000001"
            return biz
        return app.store.get_business(int(body["business_id"]))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if os.environ.get("RECEIPT_DEBUG"):
                super().log_message(fmt, *args)

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def do_PUT(self):
            self.dispatch("PUT")

        def do_DELETE(self):
            self.dispatch("DELETE")

        def dispatch(self, method):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            if method == "GET" and url.path == "/api/receipts.csv":
                return self.csv(int(q["business_id"]))
            if method == "GET" and not url.path.startswith("/api/"):
                return self.static(url.path)
            for m, pattern, fn in routes:
                match = pattern.match(url.path)
                if m == method and match:
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                        body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                        return self.json(200, fn(self, body, q, *match.groups()))
                    except printer.PrinterError as e:
                        return self.json(409, {"error": str(e), "printer_error": True})
                    except (StoreError, ValueError, KeyError) as e:
                        msg = f"Missing field: {e}" if isinstance(e, KeyError) else str(e)
                        return self.json(400, {"error": msg})
                    except Exception as e:  # keep the app running and show the problem
                        return self.json(500, {"error": f"Unexpected error: {e!r}"})
            self.json(404, {"error": "Not found"})

        def json(self, status, payload):
            data = json.dumps(payload, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def csv(self, business_id):
            biz = app.store.get_business(business_id)
            data = app.csv_export(business_id).encode("utf-8-sig")
            name = re.sub(r"[^A-Za-z0-9]+", "-", biz["name"]).strip("-") or "receipts"
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{name}-invoices.csv"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def static(self, path):
            target = (STATIC / (path.lstrip("/") or "index.html")).resolve()
            if not str(target).startswith(str(STATIC)) or not target.is_file():
                target = STATIC / "index.html"
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="Local receipt printing app")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default=os.environ.get("RECEIPT_DATA_DIR", str(HERE / "data")),
                        help="folder for the database and test prints (default: ./data)")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    app = App(args.data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    url = f"http://127.0.0.1:{args.port}"
    print(f"Receipt printer app running at {url}")
    print(f"Data folder: {app.data_dir}  (back this up)")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
