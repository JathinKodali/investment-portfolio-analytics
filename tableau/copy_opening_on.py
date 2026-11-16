"""
copy_opening_on.py
------------------
Makes a copy of a packaged workbook that opens on a chosen dashboard
(that dashboard's window is the maximized one). Used to check or export one
dashboard at a time without touching the real workbook.

Usage:
    python tableau/copy_opening_on.py <in.twbx> "<Dashboard Name>" <out.twbx>
"""
import sys
import zipfile
from xml.sax.saxutils import escape


def main(src, dashboard, out):
    name = escape(dashboard, {"'": "&apos;"})
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename.endswith(".twb"):
                text = data.decode("utf-8").replace(" maximized='true'", "")
                target = f"<window class='dashboard' name='{name}'>"
                if target not in text:
                    raise SystemExit(f"Dashboard window not found: {dashboard}")
                text = text.replace(target, f"<window class='dashboard' maximized='true' name='{name}'>", 1)
                data = text.encode("utf-8")
            zout.writestr(item, data)


if __name__ == "__main__":
    main(*sys.argv[1:4])
