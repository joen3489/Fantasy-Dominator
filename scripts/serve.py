from __future__ import annotations

import http.server
import os
import socketserver
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.utils import SITE_DIR, ensure_dirs


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main(port: int = 8765, host: str = "127.0.0.1") -> None:
    ensure_dirs()
    if not (SITE_DIR / "index.html").exists():
        raise SystemExit("No browser site found. Run `python scripts/refresh_all.py` first.")
    handler = lambda *args, **kwargs: http.server.SimpleHTTPRequestHandler(*args, directory=str(SITE_DIR), **kwargs)
    with ReusableTCPServer((host, port), handler) as httpd:
        display_host = "localhost" if host in {"127.0.0.1", "localhost"} else host
        print(f"Serving browser surface at http://{display_host}:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    selected_port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8765"))
    selected_host = os.environ.get("HOST", "127.0.0.1")
    main(selected_port, selected_host)
