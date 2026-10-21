"""Sending bytes to the printer.

On a Mac, a paired Bluetooth printer shows up as a serial port like /dev/cu.MTP-2.
Opening that port makes macOS connect to the printer; writing to it prints.
"Test mode" saves the bytes to a file instead, for working without the printer.
"""
import glob
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

LIKELY = re.compile(r"MTP|PT-?210|print", re.I)
IGNORED = ("Bluetooth-Incoming-Port", "debug-console", "wlan-debug")

_lock = threading.Lock()  # one print job at a time


class PrinterError(Exception):
    pass


def list_ports():
    ports = [p for p in sorted(glob.glob("/dev/cu.*")) if not any(x in p for x in IGNORED)]
    return [{"path": p, "likely": bool(LIKELY.search(os.path.basename(p)))} for p in ports]


def resolve_device(settings):
    if settings.get("device"):
        return settings["device"]
    likely = [p["path"] for p in list_ports() if p["likely"]]
    if not likely:
        raise PrinterError("No printer found. Pair MTP-2 in System Settings > Bluetooth, "
                           "then pick it on the Printer tab.")
    return likely[0]


class Connection:
    """An open connection to the printer (or to a test-mode file)."""

    def __init__(self, settings, out_dir):
        self.settings = settings
        self.out_dir = Path(out_dir)
        self.fd = None
        self.path = None

    def __enter__(self):
        _lock.acquire()
        try:
            self._open()
        except BaseException:
            _lock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            if self.fd is not None:
                os.close(self.fd)
        finally:
            self.fd = None
            _lock.release()

    def _open(self):
        if self.settings.get("mode") == "file":
            self.out_dir.mkdir(parents=True, exist_ok=True)
            self.path = str(self.out_dir / f"print-{datetime.now():%Y%m%d-%H%M%S-%f}.bin")
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            return
        self.path = resolve_device(self.settings)
        self.fd = _with_timeout(lambda: _open_serial(self.path), self._timeout(),
                                f"Couldn't connect to the printer at {self.path}. "
                                "Is it switched on, charged and within range?")

    def write(self, data):
        chunk = max(16, int(self.settings.get("chunk_size") or 256))
        delay = max(0, int(self.settings.get("chunk_delay_ms") or 0)) / 1000
        is_file = self.settings.get("mode") == "file"

        def run():
            for i in range(0, len(data), chunk):
                view = memoryview(data)[i:i + chunk]
                while view:
                    n = os.write(self.fd, view)
                    view = view[n:]
                if not is_file and delay:
                    time.sleep(delay)
            if not is_file:
                try:
                    import termios
                    termios.tcdrain(self.fd)
                except Exception:
                    pass

        _with_timeout(run, self._timeout() + len(data) / 1000,
                      "The printer stopped responding while printing. Check paper and battery, then reprint.")
        return self.path

    def _timeout(self):
        return float(self.settings.get("timeout_s") or 15)


def _open_serial(path):
    fd = os.open(path, os.O_WRONLY | os.O_NOCTTY)
    try:
        import termios
        attrs = termios.tcgetattr(fd)
        attrs[1] &= ~termios.OPOST  # send bytes exactly as given (no \n -> \r\n)
        attrs[4] = attrs[5] = termios.B9600
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:
        pass  # not a tty (e.g. a plain file); raw writes still work
    return fd


def _with_timeout(fn, seconds, message):
    result = {}

    def target():
        try:
            result["value"] = fn()
        except BaseException as e:
            result["error"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise PrinterError(message)
    if "error" in result:
        e = result["error"]
        raise PrinterError(f"{message} ({e})") if isinstance(e, OSError) else e
    return result.get("value")
