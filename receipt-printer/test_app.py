"""Tests. Run: python3 -m unittest -v test_app.py"""
import base64
import json
import os
import pty
import tempfile
import threading
import unittest
import urllib.request
from datetime import datetime
from decimal import Decimal
from http.server import ThreadingHTTPServer
from pathlib import Path

import printer
from receipt import build_layout, compute_totals, encode_escpos, merged_template, test_page
from server import App, make_handler
from store import Store, StoreError

SALE = {
    "customer": {"name": "Maria Santos"},
    "items": [{"description": "Haircut", "qty": 2, "price": "150"}, {"description": "Hair color treatment, premium", "qty": 1, "price": "1200"}],
    "cash": "2000",
}
WHEN = datetime(2026, 10, 21, 14, 30)


def biz(**template):
    return {"name": "Test Shop", "template": merged_template(template), "logo": None}


class LayoutTests(unittest.TestCase):
    def test_rows_fit_paper_width(self):
        for cols in (32, 42):
            lay, _, _ = build_layout(biz(chars_per_line=cols, header_lines=[
                {"text": "A very long business name that will need wrapping", "align": "center", "size": "big"},
                {"text": "Right side", "align": "right"}]), SALE, "INV-000123", WHEN, "REPRINT")
            for row in lay.rows:
                limit = cols // 2 if row["size"] in ("wide", "big") else cols
                self.assertLessEqual(len(row["text"]), limit, row)

    def test_invoice_number_and_total_right_aligned(self):
        lay, totals, _ = build_layout(biz(), SALE, "INV-000123", WHEN)
        texts = [r["text"] for r in lay.rows]
        self.assertIn("Invoice No." + "INV-000123".rjust(32 - len("Invoice No.")), texts)
        self.assertEqual(totals["total"], Decimal("1500.00"))
        self.assertTrue(any(t.startswith("TOTAL") and t.endswith("1,500.00") for t in texts))
        self.assertTrue(any(t.startswith("Change") and t.endswith("500.00") for t in texts))

    def test_vat_inclusive_breakdown(self):
        t = compute_totals({"items": [{"description": "x", "qty": 1, "price": "1120"}]}, merged_template({}))
        self.assertEqual(t["vatable"], Decimal("1000.00"))
        self.assertEqual(t["vat"], Decimal("120.00"))
        t = compute_totals({"items": [{"description": "x", "qty": 3, "price": "33.33"}]}, merged_template({}))
        self.assertEqual(t["vatable"] + t["vat"], t["total"])

    def test_non_vat_has_no_breakdown(self):
        lay, _, _ = build_layout(biz(vat_mode="none"), SALE, "1", WHEN)
        self.assertFalse(any("VAT" in r["text"] for r in lay.rows if "text" in r))

    def test_blank_customer_lines(self):
        lay, _, _ = build_layout(biz(), {"items": SALE["items"]}, "1", WHEN)
        tin = [r["text"] for r in lay.rows if r.get("text", "").startswith("TIN:")]
        self.assertEqual(tin, ["TIN: " + "_" * 27])

    def test_placeholders_and_peso_sign(self):
        lay, _, _ = build_layout(biz(footer_lines=[{"text": "Ref {invoice_no} ₱"}]), SALE, "A-9", WHEN)
        self.assertTrue(any(r.get("text", "").strip() == "Ref A-9 P" for r in lay.rows))

    def test_bad_amount_is_rejected(self):
        with self.assertRaises(ValueError):
            compute_totals({"items": [{"description": "x", "price": "abc"}]}, merged_template({}))


class EscPosTests(unittest.TestCase):
    def test_bytes(self):
        lay, _, t = build_layout(biz(header_lines=[{"text": "Niño's Bakery", "bold": True, "size": "big"}]), SALE, "1", WHEN)
        data = encode_escpos(lay, None, 3)
        self.assertTrue(data.startswith(b"\x1b@\x1bt\x00"))
        self.assertIn(b"\x1bE\x01\x1d!\x11", data)          # bold + double size
        self.assertIn("Niño's".encode("cp437"), data)       # ñ survives in code page 437
        self.assertTrue(data.endswith(b"\x1bd\x03"))

    def test_logo_raster_in_bands(self):
        width, height = 16, 30
        logo = {"width": width, "height": height, "data": base64.b64encode(bytes([0xFF, 0x00]) * height).decode()}
        b = biz(); b["logo"] = logo
        lay, _, _ = build_layout(b, SALE, "1", WHEN)
        data = encode_escpos(lay, logo)
        self.assertIn(b"\x1dv0\x00\x02\x00\x18\x00", data)  # first band: 2 bytes wide, 24 rows
        self.assertIn(b"\x1dv0\x00\x02\x00\x06\x00", data)  # second band: 6 rows

    def test_test_page_digits_fill_one_line(self):
        self.assertIn("1234567890" * 3 + "12", [r["text"] for r in test_page(32).rows])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "t.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_numbering_continues_from_old_series(self):
        b = self.store.save_business({"name": "Shop A", "prefix": "SI-", "next_number": 4521, "number_width": 6})
        self.assertEqual(b["next_invoice_no"], "SI-004521")
        nos = [self.store.issue(b["id"], SALE)["invoice_no"] for _ in range(3)]
        self.assertEqual(nos, ["SI-004521", "SI-004522", "SI-004523"])
        self.assertEqual(self.store.get_business(b["id"])["next_invoice_no"], "SI-004524")

    def test_businesses_have_separate_counters(self):
        a = self.store.save_business({"name": "A", "next_number": 100, "number_width": 5})
        b = self.store.save_business({"name": "B", "next_number": 100, "number_width": 5})
        self.assertEqual(self.store.issue(a["id"], SALE)["invoice_no"], "00100")
        self.assertEqual(self.store.issue(b["id"], SALE)["invoice_no"], "00100")
        self.assertEqual(self.store.issue(a["id"], SALE)["invoice_no"], "00101")

    def test_cannot_rewind_onto_used_number(self):
        b = self.store.save_business({"name": "A", "next_number": 1})
        self.store.issue(b["id"], SALE)
        with self.assertRaises(StoreError):
            self.store.save_business({**b, "next_number": 1}, b["id"])
        self.store.save_business({**b, "next_number": 50}, b["id"])  # skipping ahead is fine

    def test_series_end_stops_issuing(self):
        b = self.store.save_business({"name": "A", "next_number": 9, "series_end": 10})
        self.store.issue(b["id"], SALE)
        self.store.issue(b["id"], SALE)
        with self.assertRaises(StoreError):
            self.store.issue(b["id"], SALE)

    def test_concurrent_issues_get_unique_numbers(self):
        b = self.store.save_business({"name": "A", "next_number": 1})
        got, errors = [], []

        def work():
            try:
                for _ in range(10):
                    got.append(self.store.issue(b["id"], SALE)["number"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=work) for _ in range(5)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(sorted(got), list(range(1, 51)))

    def test_snapshot_keeps_layout_used_at_issue(self):
        b = self.store.save_business({"name": "Old Name", "next_number": 1})
        rec = self.store.issue(b["id"], SALE)
        self.store.save_business({**b, "name": "New Name", "next_number": 2}, b["id"])
        self.assertEqual(self.store.get_receipt(rec["id"])["snapshot"]["business"]["name"], "Old Name")

    def test_void_needs_reason_and_keeps_number(self):
        b = self.store.save_business({"name": "A", "next_number": 1})
        rec = self.store.issue(b["id"], SALE)
        with self.assertRaises(StoreError):
            self.store.void(rec["id"], " ")
        self.assertEqual(self.store.void(rec["id"], "Wrong amount")["status"], "void")
        self.assertEqual(self.store.issue(b["id"], SALE)["number"], 2)

    def test_delete_blocked_once_invoices_exist(self):
        b = self.store.save_business({"name": "A", "next_number": 1})
        self.store.issue(b["id"], SALE)
        with self.assertRaises(StoreError):
            self.store.delete_business(b["id"])


class PrinterTests(unittest.TestCase):
    """A pseudo-terminal stands in for the Mac's /dev/cu.MTP-2 Bluetooth serial port."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name)
        self.biz = self.app.store.save_business({"name": "A", "prefix": "INV-", "next_number": 77, "number_width": 4})

    def tearDown(self):
        self.tmp.cleanup()

    def fake_printer(self):
        master, slave = pty.openpty()
        received = bytearray()

        def reader():
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    return
                if not chunk:
                    return
                received.extend(chunk)

        threading.Thread(target=reader, daemon=True).start()
        return os.ttyname(slave), slave, master, received

    def test_issue_prints_exact_bytes_over_serial(self):
        path, slave, master, received = self.fake_printer()
        self.app.store.save_settings({"mode": "serial", "device": path, "chunk_size": 64, "chunk_delay_ms": 1})
        result = self.app.issue(self.biz["id"], SALE)
        self.assertTrue(result["printed"], result.get("print_error"))
        _, expected = self.app.render_receipt(result["receipt"])
        for _ in range(100):
            if len(received) >= len(expected):
                break
            threading.Event().wait(0.02)
        self.assertEqual(bytes(received), expected)  # no \n -> \r\n translation
        self.assertIn(b"INV-0077", received)
        self.assertEqual(result["receipt"]["print_count"], 1)
        os.close(slave); os.close(master)

    def test_unreachable_printer_uses_no_number(self):
        self.app.store.save_settings({"mode": "serial", "device": "/dev/cu.does-not-exist", "timeout_s": 2})
        with self.assertRaises(printer.PrinterError):
            self.app.issue(self.biz["id"], SALE)
        self.assertEqual(self.app.store.get_business(self.biz["id"])["next_number"], 77)

    def test_test_mode_writes_file(self):
        self.app.store.save_settings({"mode": "file"})
        result = self.app.issue(self.biz["id"], SALE)
        self.assertEqual(Path(result["saved_to"]).read_bytes()[:2], b"\x1b@")

    def test_reprint_is_labelled(self):
        self.app.store.save_settings({"mode": "file"})
        rec = self.app.issue(self.biz["id"], SALE)["receipt"]
        saved = self.app.reprint(rec["id"])["saved_to"]
        self.assertIn(b"REPRINT", Path(saved).read_bytes())


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = App(self.tmp.name)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as res:
                raw = res.read()
                return res.status, (json.loads(raw) if res.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_full_flow(self):
        status, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Receipt Printer", page)
        _, b = self.call("POST", "/api/businesses", {"name": "Shop", "prefix": "OR-", "next_number": 501, "number_width": 5})
        status, prev = self.call("POST", "/api/preview", {"business_id": b["id"], "receipt": SALE})
        self.assertEqual(status, 200)
        self.assertIn("OR-00501", json.dumps(prev["rows"]))
        self.call("PUT", "/api/settings", {"mode": "file"})
        status, res = self.call("POST", "/api/receipts", {"business_id": b["id"], "receipt": SALE})
        self.assertEqual((status, res["receipt"]["invoice_no"], res["printed"]), (200, "OR-00501", True))
        status, err = self.call("POST", "/api/receipts", {"business_id": b["id"], "receipt": {"items": []}})
        self.assertEqual(status, 400)
        status, lst = self.call("GET", f"/api/receipts?business_id={b['id']}")
        self.assertEqual(len(lst), 1)
        status, csv_data = self.call("GET", f"/api/receipts.csv?business_id={b['id']}")
        self.assertIn(b"OR-00501", csv_data)
        status, err = self.call("PUT", f"/api/businesses/{b['id']}", {**b, "next_number": 501})
        self.assertEqual(status, 400)
        self.assertIn("already issued", err["error"])


if __name__ == "__main__":
    unittest.main()
