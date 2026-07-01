from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import operator
from src.utils import SITE_DIR, ensure_dirs


class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class RailwayHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/operator/status":
            self._send_json(operator.status())
            return
        if parsed.path == "/api/operator/packet":
            if not self._authorized():
                self._send_json({"error": "operator token required"}, HTTPStatus.UNAUTHORIZED)
                return
            payload = operator._safe_json(operator.INSIGHT_PACKET_PATH)
            self._send_json(payload if payload else {"error": "packet not found"}, HTTPStatus.OK if payload else HTTPStatus.NOT_FOUND)
            return
        if parsed.path == "/api/operator/chat-context":
            if not self._authorized():
                self._send_json({"error": "operator token required"}, HTTPStatus.UNAUTHORIZED)
                return
            self._send_json(operator.build_chat_context_markdown())
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        routes = {
            "/api/operator/refresh": self._refresh,
            "/api/operator/build-packet": self._build_packet,
            "/api/operator/generate-insights": self._generate_insights,
            "/api/operator/import-insights": self._import_insights,
            "/api/operator/validate-insights": self._validate_insights,
            "/api/operator/rebuild-browser": self._rebuild_browser,
        }
        handler = routes.get(parsed.path)
        if handler is None:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not self._authorized():
            self._send_json({"error": "operator token required"}, HTTPStatus.UNAUTHORIZED)
            return
        self._send_json(handler())

    def end_headers(self) -> None:
        self.send_header("Connection", "close")
        super().end_headers()

    def _refresh(self) -> dict:
        def job() -> dict:
            from scripts.refresh_all import main as refresh_all

            refresh_all(force=True)
            return {"state": "complete", "message": "Data refresh complete."}

        return operator.start_job("refresh", job)

    def _build_packet(self) -> dict:
        return operator.start_job("build-packet", operator.build_insight_packet)

    def _generate_insights(self) -> dict:
        return operator.start_job("generate-insights", operator.generate_insights_automatically)

    def _validate_insights(self) -> dict:
        return operator.start_job("validate-insights", operator.validate_insight_output)

    def _rebuild_browser(self) -> dict:
        return operator.start_job("rebuild-browser", operator.rebuild_browser)

    def _import_insights(self) -> dict:
        payload = self._read_json_body()
        return operator.start_job("import-insights", lambda: operator.import_insight_output(payload))

    def _authorized(self) -> bool:
        return operator.token_valid({key.lower(): value for key, value in self.headers.items()})

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(port: int = 8765, host: str = "127.0.0.1") -> None:
    ensure_dirs()
    if not (SITE_DIR / "index.html").exists():
        raise SystemExit("No browser site found. Run `python scripts/refresh_all.py` first.")
    handler = lambda *args, **kwargs: RailwayHTTPRequestHandler(*args, directory=str(SITE_DIR), **kwargs)
    with ReusableTCPServer((host, port), handler) as httpd:
        display_host = "localhost" if host in {"127.0.0.1", "localhost"} else host
        print(f"Serving browser surface at http://{display_host}:{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    selected_port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "8765"))
    selected_host = os.environ.get("HOST", "127.0.0.1")
    main(selected_port, selected_host)
