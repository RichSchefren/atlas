"""Authenticated localhost HTTP server for the Atlas cognitive service."""

from __future__ import annotations

import argparse
import hmac
import json
import os
import signal
import socket
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from service_core import CognitiveServiceCore, ServiceError

MAX_BODY_BYTES = 2 * 1024 * 1024


class CognitiveHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self) -> None:
        # Windows permits multiple listeners on one address unless the socket
        # explicitly requests exclusive ownership. Two simultaneous Hermes
        # launchers must converge on one sidecar, with the losing client
        # attaching to the winner after its child fails to bind.
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        super().server_bind()

    def __init__(
        self,
        address: tuple[str, int],
        core: CognitiveServiceCore,
        token: str,
        *,
        allow_test_reset: bool = False,
        owner_instance: str = "",
        parent_pid: int = 0,
    ):
        self.core = core
        self.token = token
        self.allow_test_reset = allow_test_reset
        self.owner_instance = owner_instance
        self.parent_pid = parent_pid
        super().__init__(address, CognitiveRequestHandler)


class CognitiveRequestHandler(BaseHTTPRequestHandler):
    server: CognitiveHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data: Any, status: int = HTTPStatus.OK) -> None:
        self._send(status, {"api_version": "v1", "ok": True, "data": data})

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {
            "api_version": "v1", "ok": False,
            "error": {"code": code, "message": message},
        })

    def _authorized(self) -> bool:
        expected = f"Bearer {self.server.token}"
        supplied = self.headers.get("Authorization", "")
        return hmac.compare_digest(supplied, expected)

    def _body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ServiceError("Content-Length is required")
        length = int(raw_length)
        if length < 0 or length > MAX_BODY_BYTES:
            raise ServiceError("request body is too large")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServiceError("request body must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ServiceError("request body must be a JSON object")
        if "scope_id" in parsed:
            raise ServiceError("scope_id is launch-fixed and forbidden in requests")
        return parsed

    def _dispatch(self) -> None:
        if not self._authorized():
            self._error(HTTPStatus.UNAUTHORIZED, "unauthorized", "valid bearer token required")
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        core = self.server.core
        if self.command == "GET" and path == "/v1/health":
            health = core.health()
            if self.server.owner_instance:
                health["managed_owner"] = {
                    "instance_id": self.server.owner_instance,
                    "parent_pid": self.server.parent_pid,
                    "server_pid": os.getpid(),
                }
            self._ok(health)
            return
        if self.command == "GET" and path == "/v1/items/get":
            root = query.get("root_kref", [""])[0]
            self._ok(core.get_item(root))
            return
        if self.command == "GET" and path == "/v1/items/audit":
            root = query.get("root_kref", [""])[0]
            self._ok(core.audit_item(root))
            return
        if self.command == "GET" and path == "/v1/items/list":
            limit = int(query.get("limit", ["100"])[0])
            self._ok(core.list_items(limit=limit))
            return
        if self.command != "POST":
            self._error(HTTPStatus.NOT_FOUND, "not_found", "unknown route")
            return
        body = self._body()
        if path == "/v1/control/shutdown" and self.server.owner_instance:
            if body.get("owner_instance") != self.server.owner_instance:
                self._error(
                    HTTPStatus.CONFLICT,
                    "owner_mismatch",
                    "managed service owner instance does not match",
                )
                return
            self._ok({"owner_instance": self.server.owner_instance, "stopping": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        elif path == "/v1/items/create":
            self._ok(core.create_item(**body), HTTPStatus.CREATED)
        elif path == "/v1/items/revise":
            self._ok(core.revise_item(**body))
        elif path == "/v1/dependencies":
            self._ok(core.declare_dependency(**body), HTTPStatus.CREATED)
        elif path == "/v1/items/search":
            self._ok(core.search_items(body["query"], limit=body.get("limit", 20)))
        elif path == "/v1/items/forget":
            payload = dict(body)
            root = payload.pop("root_kref")
            proposition = payload.pop("proposition")
            self._ok(core.forget_item(root, proposition, **payload))
        elif path == "/v1/cascades":
            self._ok(core.run_cascade(**body), HTTPStatus.CREATED)
        elif path == "/v1/admin/reset" and self.server.allow_test_reset:
            if body.get("confirm") != "reset-scope":
                raise ServiceError("reset requires confirm=reset-scope")
            self._ok(core.reset_scope())
        else:
            self._error(HTTPStatus.NOT_FOUND, "not_found", "unknown route")

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def _handle(self) -> None:
        try:
            self._dispatch()
        except ServiceError as exc:
            self._error(exc.status, exc.code, str(exc))
        except (KeyError, TypeError, ValueError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(exc))
        except Exception:
            self._error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal_error",
                "internal service error",
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "::1"))
    parser.add_argument("--port", type=int, default=8741)
    parser.add_argument("--token-env", default="ATLAS_COGNITIVE_TOKEN")
    parser.add_argument("--allow-test-reset", action="store_true")
    parser.add_argument("--owner-instance", default="")
    parser.add_argument("--parent-pid", type=int, default=0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    token = os.environ.get(args.token_env, "")
    if len(token) < 32:
        raise SystemExit(f"{args.token_env} must contain at least 32 characters")
    args.db.parent.mkdir(parents=True, exist_ok=True)
    core = CognitiveServiceCore(args.db, scope_id=args.scope)
    server = CognitiveHTTPServer(
        (args.host, args.port), core, token,
        allow_test_reset=args.allow_test_reset,
        owner_instance=args.owner_instance,
        parent_pid=args.parent_pid,
    )

    parent_watch_stopped = threading.Event()

    def watch_parent() -> None:
        while not parent_watch_stopped.wait(0.25):
            if args.parent_pid and os.getppid() != args.parent_pid:
                server.shutdown()
                return

    if args.parent_pid:
        threading.Thread(target=watch_parent, name="atlas-parent-watch", daemon=True).start()

    def stop(_: int, __: object) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        parent_watch_stopped.set()
        server.server_close()
        core.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
