from __future__ import annotations

import os
import socket
import sys
import threading
import time
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
from streamlit.runtime.runtime import Runtime, RuntimeState
from streamlit.web import cli as stcli

TAB_CLOSE_GRACE_SECONDS = 8.0


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


def _exit_after_last_browser_tab_closes() -> None:
    """Stop the packaged process shortly after its last browser tab disconnects."""
    seen_browser_session = False
    disconnected_since: float | None = None

    while True:
        time.sleep(1.0)
        try:
            if not Runtime.exists():
                continue
            state = Runtime.instance().state

            if state == RuntimeState.ONE_OR_MORE_SESSIONS_CONNECTED:
                seen_browser_session = True
                disconnected_since = None
                continue

            if not seen_browser_session:
                continue

            if state == RuntimeState.NO_SESSIONS_CONNECTED:
                if disconnected_since is None:
                    disconnected_since = time.monotonic()
                elif time.monotonic() - disconnected_since >= TAB_CLOSE_GRACE_SECONDS:
                    os._exit(0)
            else:
                disconnected_since = None
        except Exception:
            disconnected_since = None


def main() -> int:
    shortlist_review.install_runtime_behavior()
    app_path = bundled_path("app.py")
    port = selected_port()
    url = f"http://127.0.0.1:{port}"

    threading.Thread(
        target=_exit_after_last_browser_tab_closes,
        name="flash-trombi-browser-watch",
        daemon=True,
    ).start()

    if os.environ.get("FLASH_TROMBI_SKIP_BROWSER") != "1":
        threading.Timer(1.4, lambda: webbrowser.open(url)).start()

    sys.argv = streamlit_args(app_path, port)
    return int(stcli.main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
