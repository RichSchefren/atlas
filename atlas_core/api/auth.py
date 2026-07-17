"""Per-install authentication material for the localhost Atlas API."""

from __future__ import annotations

import os
import secrets
import stat
import subprocess
from pathlib import Path


def _secure_windows_token_file(token_path: Path) -> None:
    """Replace inherited Windows ACLs with one explicit user grant."""
    username = os.environ.get("USERNAME")
    if not username:
        raise RuntimeError("USERNAME is required to secure the Atlas HTTP token")
    domain = os.environ.get("USERDOMAIN")
    principal = f"{domain}\\{username}" if domain else username
    subprocess.run(
        [
            "icacls",
            str(token_path),
            "/inheritance:r",
            "/grant:r",
            f"{principal}:(F)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _read_token_file(token_path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(token_path, flags)
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"Atlas HTTP token is not a regular file: {token_path}")
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, encoding="utf-8") as handle:
            descriptor = -1
            token = handle.read().strip()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if os.name == "nt":
        _secure_windows_token_file(token_path)
    return token


def load_or_create_http_token(data_dir: Path) -> str:
    """Load a configured token or create an owner-readable per-install token."""
    configured = os.environ.get("ATLAS_HTTP_TOKEN")
    if configured:
        if len(configured) < 32:
            raise ValueError("ATLAS_HTTP_TOKEN must contain at least 32 characters")
        return configured

    token_path = data_dir / "http-token"
    try:
        token = _read_token_file(token_path)
    except FileNotFoundError:
        token = secrets.token_urlsafe(32)
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open(token_path, flags, 0o600)
        except FileExistsError:
            token = _read_token_file(token_path)
        else:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"{token}\n")
            if os.name == "nt":
                _secure_windows_token_file(token_path)
    if len(token) < 32:
        raise ValueError(f"invalid Atlas HTTP token in {token_path}")
    return token
