"""Thin managed HTTP client for the authoritative Atlas cognitive service."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SERVICE_VERSION = "0.1.0"
STATE_TEMP_STALE_SECONDS = 3600


class CognitiveServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "service_error", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


class CognitiveServiceUnavailable(CognitiveServiceError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class ManagedCognitiveClient:
    """Profile-scoped transport and sidecar lifecycle; contains no cognition."""

    def __init__(
        self,
        *,
        scope_id: str,
        hermes_home: Path,
        data_dir: Path,
        configured_url: str = "",
        expected_scope: str = "",
        timeout_seconds: float = 5.0,
    ) -> None:
        self.scope_id = scope_id
        self.hermes_home = hermes_home
        self.data_dir = data_dir
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[Any] | None = None
        self._log_handle: Any = None
        self._managed = not configured_url.strip()
        self._owner_instance = secrets.token_hex(16)
        self._owns_running_instance = False

        if self._managed:
            state = self._managed_state()
            self.base_url = f"http://127.0.0.1:{state['port']}"
            self.token = str(state["token"])
            self.expected_scope = scope_id
            self._database = self.data_dir / f"cognitive-service-{scope_id[:16]}.db"
        else:
            self.base_url = self._validate_local_url(configured_url)
            self.token = os.environ.get("ATLAS_COGNITIVE_TOKEN", "")
            if len(self.token) < 32:
                raise CognitiveServiceError(
                    "Configured cognitive_url requires ATLAS_COGNITIVE_TOKEN with at least 32 characters"
                )
            if not expected_scope:
                raise CognitiveServiceError(
                    "Configured cognitive_url requires cognitive_expected_scope"
                )
            if expected_scope != scope_id:
                raise CognitiveServiceError(
                    "cognitive_expected_scope must equal this Hermes profile's internal scope"
                )
            self.expected_scope = expected_scope
            self._database = None

    @staticmethod
    def _validate_local_url(value: str) -> str:
        parsed = urllib.parse.urlparse(value.strip())
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise CognitiveServiceError("cognitive_url must be an HTTP loopback address")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CognitiveServiceError("cognitive_url cannot contain credentials, query, or fragment")
        if parsed.path not in {"", "/"}:
            raise CognitiveServiceError("cognitive_url must not contain a path")
        return value.rstrip("/")

    def _managed_state(self) -> dict[str, Any]:
        state_dir = self.hermes_home / "atlas" / "service"
        state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(state_dir, 0o700)
        state_path = state_dir / f"{self.scope_id}.json"
        temporary_prefix = f".{self.scope_id}."
        instance_key = f"{self.scope_id}\0{self.hermes_home.resolve()}"
        digest = hashlib.sha256(instance_key.encode("utf-8")).digest()
        port = 20000 + int.from_bytes(digest[:8], "big") % 30000

        def publish(payload: dict[str, Any], *, overwrite: bool) -> None:
            temporary_path: Path | None = None
            try:
                if not overwrite and state_path.exists():
                    return
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=temporary_prefix, suffix=".tmp", dir=state_dir
                )
                temporary_path = Path(temporary_name)
                if os.name != "nt":
                    os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, sort_keys=True) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                if overwrite:
                    os.replace(temporary_path, state_path)
                    temporary_path = None
                else:
                    try:
                        os.link(temporary_path, state_path)
                    except OSError as exc:
                        if not state_path.exists():
                            raise CognitiveServiceError(
                                "Managed state requires same-directory atomic hard-link support"
                            ) from exc
                if os.name != "nt":
                    os.chmod(state_path, 0o600)
                try:
                    directory_descriptor = os.open(state_dir, os.O_RDONLY)
                    try:
                        os.fsync(directory_descriptor)
                    finally:
                        os.close(directory_descriptor)
                except OSError:
                    pass
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)

        def clean_temporary_debris() -> None:
            cutoff = time.time() - STATE_TEMP_STALE_SECONDS
            for candidate in state_dir.glob(f"{temporary_prefix}*.tmp"):
                try:
                    if candidate.stat().st_mtime <= cutoff:
                        candidate.unlink(missing_ok=True)
                except OSError:
                    continue

        if not state_path.exists():
            publish(
                {
                    "scope_id": self.scope_id,
                    "port": port,
                    "token": secrets.token_urlsafe(32),
                    "service_version": SERVICE_VERSION,
                },
                overwrite=False,
            )
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CognitiveServiceError(f"Invalid managed cognitive state file: {state_path}") from exc
        if state.get("scope_id") != self.scope_id:
            raise CognitiveServiceError(f"Managed cognitive state does not match profile: {state_path}")
        if len(str(state.get("token") or "")) < 32:
            raise CognitiveServiceError(f"Managed cognitive token is invalid: {state_path}")
        if state.get("port") != port:
            state["port"] = port
            state["service_version"] = SERVICE_VERSION
            publish(state, overwrite=True)
        clean_temporary_debris()
        return state

    @staticmethod
    def operation_key(prefix: str, session_id: str, payload: dict[str, Any]) -> str:
        raw = _canonical({"prefix": prefix, "session_id": session_id, "payload": payload})
        return f"hermes-{prefix}-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def memory_id(idempotency_key: str) -> str:
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return f"hermes-{digest[:32]}"

    def _service_root(self) -> Path:
        source = Path(__file__).resolve()
        candidates = [source.parent / "cognitive-service", source.parents[2] / "cognitive-service"]
        root = next((item for item in candidates if (item / "server.py").is_file()), None)
        if root is None:
            raise CognitiveServiceUnavailable(
                "Managed cognitive service assets are missing; reinstall the Atlas Hermes package"
            )
        return root

    def _launch(self) -> None:
        if not self._managed or self._database is None:
            raise CognitiveServiceUnavailable(
                f"Atlas cognitive service is unavailable at {self.base_url}"
            )
        if self._process is not None and self._process.poll() is not None:
            self._process.wait()
            self._process = None
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
        root = self._service_root()
        self._database.parent.mkdir(parents=True, exist_ok=True)
        log_path = self.hermes_home / "atlas" / "service" / f"{self.scope_id}.log"
        self._log_handle = log_path.open("ab", buffering=0)
        command = [
            sys.executable,
            str(root / "server.py"),
            "--db",
            str(self._database),
            "--scope",
            self.scope_id,
            "--port",
            str(urllib.parse.urlparse(self.base_url).port),
            "--owner-instance",
            self._owner_instance,
            "--parent-pid",
            str(os.getpid()),
        ]
        environment = os.environ.copy()
        environment["ATLAS_COGNITIVE_TOKEN"] = self.token
        options: dict[str, Any] = {
            "cwd": str(root),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": self._log_handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            options["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        else:
            options["start_new_session"] = True
        self._process = subprocess.Popen(command, **options)
        self._owns_running_instance = True

    def _health(self) -> dict[str, Any]:
        health = self._raw("GET", "/v1/health")
        if health.get("scope_id") != self.expected_scope:
            raise CognitiveServiceError(
                "Cognitive service scope mismatch; refusing cross-profile access"
            )
        if health.get("service_version") != SERVICE_VERSION:
            raise CognitiveServiceError(
                f"Cognitive service version mismatch: expected {SERVICE_VERSION}, "
                f"received {health.get('service_version')!r}"
            )
        return health

    def ensure_available(self) -> dict[str, Any]:
        try:
            health = self._health()
        except CognitiveServiceUnavailable:
            if not self._managed:
                raise
        else:
            if not self._managed:
                return health
            owner = health.get("managed_owner") or {}
            if owner.get("instance_id") == self._owner_instance:
                self._owns_running_instance = True
                return health
            if not owner.get("instance_id"):
                raise CognitiveServiceError(
                    "Managed endpoint has no owner metadata; refusing unsafe attachment"
                )
            self._owns_running_instance = False
            return health
        self._launch()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                health = self._health()
                owner = health.get("managed_owner") or {}
                if owner.get("instance_id") != self._owner_instance:
                    # A concurrent healthy launcher won the stable scoped port.
                    # Attach without ownership; only that launcher's watchdog or
                    # clean shutdown may stop the shared service.
                    self._owns_running_instance = False
                return health
            except CognitiveServiceUnavailable:
                time.sleep(0.05)
        raise CognitiveServiceUnavailable(
            f"Managed cognitive service did not become ready at {self.base_url}; "
            f"inspect {self.hermes_home / 'atlas' / 'service' / (self.scope_id + '.log')}"
        )

    def _stop_managed_instance(self, owner_instance: str) -> None:
        self._raw(
            "POST",
            "/v1/control/shutdown",
            {"owner_instance": owner_instance},
        )
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                self._raw("GET", "/v1/health")
            except CognitiveServiceUnavailable:
                return
            time.sleep(0.05)
        raise CognitiveServiceError("Managed cognitive service did not stop for reclamation")

    def _raw(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        encoded = None if body is None else _canonical(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if encoded is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                envelope = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                envelope = json.loads(exc.read())
                error = envelope.get("error") or {}
            except (json.JSONDecodeError, AttributeError):
                error = {}
            raise CognitiveServiceError(
                str(error.get("message") or f"Cognitive service HTTP {exc.code}"),
                code=str(error.get("code") or "http_error"),
                status=exc.code,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CognitiveServiceUnavailable(
                f"Atlas cognitive service is unavailable at {self.base_url}"
            ) from exc
        if not isinstance(envelope, dict) or envelope.get("api_version") != "v1":
            raise CognitiveServiceError("Cognitive service returned an invalid v1 envelope")
        if envelope.get("ok") is not True:
            error = envelope.get("error") or {}
            raise CognitiveServiceError(
                str(error.get("message") or "Cognitive service request failed"),
                code=str(error.get("code") or "service_error"),
            )
        return envelope.get("data")

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        self.ensure_available()
        try:
            return self._raw(method, path, body)
        except CognitiveServiceUnavailable:
            if not self._managed:
                raise
            # The healthy owner may exit after the health check but before the
            # request. Fail over and replay this transport-safe request once.
            self._owns_running_instance = False
            self.ensure_available()
            return self._raw(method, path, body)

    def get(self, memory_id: str) -> dict[str, Any] | None:
        path = "/v1/items/get?" + urllib.parse.urlencode({"root_kref": memory_id})
        try:
            return self.request("GET", path)
        except CognitiveServiceError as exc:
            if exc.code == "not_found":
                return None
            raise

    def audit(self, memory_id: str) -> dict[str, Any] | None:
        path = "/v1/items/audit?" + urllib.parse.urlencode({"root_kref": memory_id})
        try:
            return self.request("GET", path)
        except CognitiveServiceError as exc:
            if exc.code == "not_found":
                return None
            raise

    def search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        return self.request("POST", "/v1/items/search", {"query": query, "limit": limit})

    def list(self, *, limit: int) -> list[dict[str, Any]]:
        path = "/v1/items/list?" + urllib.parse.urlencode({"limit": limit})
        return self.request("GET", path)

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/items/create", payload)

    def revise(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/items/revise", payload)

    def depend(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/dependencies", payload)

    def forget(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/items/forget", payload)

    def shutdown(self) -> None:
        if self._managed and self._owns_running_instance:
            try:
                self._stop_managed_instance(self._owner_instance)
            except CognitiveServiceUnavailable:
                pass
            except CognitiveServiceError as exc:
                if exc.code != "owner_mismatch":
                    raise
        if self._process is not None:
            try:
                self._process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=2.0)
        self._process = None
        self._owns_running_instance = False
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
