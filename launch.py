"""One-click launcher: start the web app and open it in the default browser.

Run via the double-clickable Start-Schedule-Tool.command (macOS/Linux) or
Start-Schedule-Tool.bat (Windows), or directly with ``python launch.py``.
"""

from __future__ import annotations

import threading
import webbrowser

from app import create_app

HOST = "127.0.0.1"
PORT = 5000
URL = f"http://{HOST}:{PORT}/"


def _open_browser() -> None:
    webbrowser.open(URL)


def main() -> None:
    app = create_app()
    print(f"\n  Schedule Manipulation Analysis Tool is running at {URL}")
    print("  Your browser should open automatically. Close this window to stop the tool.\n")
    # Open the browser shortly after the server starts accepting connections.
    threading.Timer(1.2, _open_browser).start()
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
