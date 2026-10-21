# Receipt Printer

A local app for the PT-210 (MTP-2) 58mm Bluetooth thermal printer. It replaces Loyverse for invoicing, so each business can:

- continue its own invoice number series (for example `SI-004521`), with its own counter,
- print in a layout matching its old receipts (header lines, logo, labels, VAT breakdown, footer),
- keep a history of every invoice, with reprint, void and CSV export.

It runs entirely on the Mac with no internet and nothing to install beyond Python 3, which macOS provides.

## Start it

Double-click `start.command` in Finder. The first time, macOS may block it: right-click it, choose **Open**, then **Open** again.

Or in Terminal:

```sh
python3 server.py
```

The app opens in your browser at http://127.0.0.1:8765. Keep the Terminal window open while you use it.

## Connect the printer (once)

1. Remove the yellow tape from the battery, charge the printer and switch it on.
2. System Settings → Bluetooth → **Connect** next to **MTP-2** (PIN `0000` if asked).
3. In the app's **Printer** tab, click **Refresh**, choose the MTP-2 port (or leave it on auto-detect), select **Bluetooth printer**, **Save**, then **Print test page**.
4. The row of digits on the test page should fit on exactly one line. If it wraps, lower **Characters per line** in each business's settings.

If no MTP-2 port shows up, run `ls /dev/cu.*` in Terminal and send the output to whoever maintains this app.

### Without the printer

On the **Printer** tab, choose **Test mode**. Printing then saves the exact bytes the printer would receive to `data/test-prints/` instead. The on-screen preview shows each printed line, so you can set up every business's layout before the printer arrives.

Invoices issued in test mode still use real invoice numbers. To try layouts without using numbers, use **Sample print** on the Businesses tab.

## Set up a business

On the **Businesses** tab, click **+ Add business** and fill it in from one of the business's old receipts:

- **Next invoice number**: one more than the last invoice the business issued. Prefix and digits control the format (`SI-` + 6 digits → `SI-004521`).
- **Last number in series** (optional): the end of the approved range. The app refuses to issue past it, and warns when fewer than 50 numbers are left.
- **Header and footer lines**: copy the old receipt line by line. Each line can be left, center or right aligned, bold, and normal, tall, wide or big size.
- **Logo** (optional): upload an image. It is converted to black and white for the printer.

The preview updates as you type.

## How invoice numbers are protected

- Each number is taken and saved in a single database transaction, so two invoices can never get the same number.
- The app connects to the printer **before** taking a number. If the printer is off or out of range, no number is used.
- If printing fails midway, the invoice stays recorded and can be reprinted from **History**. Reprints are marked `REPRINT`.
- The next number can't be set back to one that was already issued.
- Voiding needs a reason and keeps the number on record.
- Each invoice stores a copy of the layout used, so reprints match the original even after the layout changes.

## Back up

Everything is in the `data/` folder (`data/receipts.db`). Back it up regularly, for example by copying it to iCloud Drive or an external drive. If it's lost, the app no longer knows each business's next number.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| "Couldn't connect to the printer" | Turn the printer on, check the battery, bring it closer, and make sure it shows as connected in Bluetooth settings. No invoice number was used. |
| Long receipts print garbled or stop halfway | Printer tab → Advanced: lower **Chunk size** (try 128) or raise **Pause between chunks** (try 60). |
| Lines wrap unexpectedly | Lower **Characters per line** for that business. |
| `ñ` or the peso sign look wrong | The printer uses a basic character set; `₱` is printed as `P`. |

## Developers

Python standard library only. `server.py` is the web server and API, `store.py` the SQLite storage and numbering, `receipt.py` the layout and ESC/POS encoding, `printer.py` the Bluetooth serial connection, and `static/index.html` the interface.

```sh
python3 -m unittest -v test_app.py
```

The tests use a pseudo-terminal in place of the printer's serial port to check the exact bytes sent.
