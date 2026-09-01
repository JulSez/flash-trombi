from __future__ import annotations

import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

import paths  # noqa: F401
import pdf_import  # noqa: F401
import practice_mode  # noqa: F401
import progress_view  # noqa: F401
import shortlist_review
import storage  # noqa: F401
import updates  # noqa: F401
import version  # noqa: F401
from streamlit.web import cli as stcli

shortlist_review.install_runtime_behavior()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def selected_port() -> int:
    configured = os.environ.get("FLASH_TROMBI_PORT", "").strip()
    if configured:
        port = int(configured)
        if not 1 <= port <= 65535:
            raise ValueError("Port invalide")
        return port
    return free_port()


def bundled_path(filename: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / filename


def streamlit_args(app_path: Path, port: int) -> list[str]:
    return [
        "streamlit",
        "run",
        str(app_path),
        "--global.developmentMode=false",
        "--client.toolbarMode=minimal",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.fileWatcherType=none",
    ]


def main() -> int:
    app_path = bundled_path("app.py")
    port = selected_port()
    url = f"http://127.0.0.1:{port}"

    if os.environ.get("FLASH_TROMBI_SKIP_BROWSER") != "1":
        threading.Timer(1.4, lambda: webbrowser.open(url)).start()

    sys.argv = streamlit_args(app_path, port)
    return int(stcli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
