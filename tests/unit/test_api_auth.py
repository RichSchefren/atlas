"""Per-install HTTP token lifecycle tests."""

import os

import pytest


def test_token_is_created_owner_only_and_reused(tmp_path, monkeypatch):
    from atlas_core.api.auth import load_or_create_http_token

    monkeypatch.delenv("ATLAS_HTTP_TOKEN", raising=False)
    first = load_or_create_http_token(tmp_path)
    second = load_or_create_http_token(tmp_path)

    assert len(first) >= 32
    assert second == first
    assert (tmp_path / "http-token").stat().st_mode & 0o777 == 0o600


def test_environment_token_takes_precedence(tmp_path, monkeypatch):
    from atlas_core.api.auth import load_or_create_http_token

    configured = "configured-token-with-at-least-32-characters"
    monkeypatch.setenv("ATLAS_HTTP_TOKEN", configured)

    assert load_or_create_http_token(tmp_path) == configured
    assert not (tmp_path / "http-token").exists()


def test_short_environment_token_is_rejected(tmp_path, monkeypatch):
    from atlas_core.api.auth import load_or_create_http_token

    monkeypatch.setenv("ATLAS_HTTP_TOKEN", "too-short")

    with pytest.raises(ValueError, match="at least 32"):
        load_or_create_http_token(tmp_path)


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform lacks O_NOFOLLOW")
def test_symlink_token_is_rejected(tmp_path, monkeypatch):
    from atlas_core.api.auth import load_or_create_http_token

    monkeypatch.delenv("ATLAS_HTTP_TOKEN", raising=False)
    target = tmp_path / "target"
    target.write_text("x" * 40, encoding="utf-8")
    (tmp_path / "http-token").symlink_to(target)

    with pytest.raises(OSError):
        load_or_create_http_token(tmp_path)
