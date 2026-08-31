from __future__ import annotations

import socket
import sys
import threading
import webbrowser
from pathlib import Path

import paths  # noqa: F401
import pdf_import  # noqa: F401
import practice_mode  # noqa: F401
import progress_view  # noqa: F401
import storage  # noqa: F401
import updates  # noqa: F401
import version  # noqa: F401
from streamlit.web import cli as stcli


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def bundled_path(filename: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / filename


def main() -> int:
    app_path = bundled_path("app.py")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.4, lambda: webbrowser.open(url)).start()

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]
    return int(stcli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
