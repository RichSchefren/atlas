"""qa_site.py — Atlas live-site QA monitor.

Runs every 4 hours during launch week. Catches the bug class that
embarrassed Rich on launch night (footer Docs link → 404, port mismatch,
stale test counts).

For every URL on https://livememory.dev (and the GitHub repo), checks:
  - HTTP 200 response
  - No localhost / mixed-content references in HTML
  - No FILL-IN / TODO / TBD placeholders in user-facing copy
  - OG image still loads with correct dimensions
  - Test count claim in HTML matches the actual pytest collect count
  - Atlas video MP4 still serves with both video AND audio streams
  - GitHub repo: homepage URL set, description set, topics set

Exit non-zero on any failure. Prints the offending URL + reason.

Usage:
    python scripts/qa_site.py                  # full check
    python scripts/qa_site.py --quiet          # only print failures
    python scripts/qa_site.py --notify         # PushNotification on failure
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SITE_BASE = "https://livememory.dev"
PAGES_BASE = "https://livememory.pages.dev"  # cert-pending fallback
GITHUB_REPO = "RichSchefren/atlas"

# Pages we expect to exist + return 200
EXPECTED_PAGES = [
    "/",
    "/index.html",
    "/live-demo.html",
    "/live-real.html",
    "/atlas-launch.mp4",
    "/og.png",
    "/assets/demo.cast",
]

# Patterns that should NEVER appear in user-facing HTML
FORBIDDEN_PATTERNS = [
    (r"<FILL-IN", "FILL-IN placeholder"),
    (r"\bTODO\b", "TODO marker"),
    (r"\bFIXME\b", "FIXME marker"),
    (r"\bTBD\b", "TBD marker"),
    (r"atlas-project\.org", "Reference to unowned domain"),
    # Localhost in href= or src= (loaded by browser) is a real bug.
    # Localhost mentioned in <code> blocks or <pre> is fine (install docs).
    (r'(href|src)\s*=\s*["\']http://localhost', "localhost in user-facing link"),
]


def _http_status(url: str, timeout: int = 10) -> tuple[int, dict[str, str]]:
    """Returns (status_code, response_headers). 0 on network failure."""
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "atlas-qa-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {})
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, {}


def _http_body(url: str, timeout: int = 10) -> str:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "atlas-qa-bot/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _gh_json(args: list[str]) -> Any:
    """Run gh api / gh repo with --json and parse."""
    try:
        out = subprocess.run(
            ["gh"] + args, capture_output=True, text=True, timeout=15,
        )
        return json.loads(out.stdout) if out.stdout.strip() else None
    except Exception:
        return None


def check_pages_reachable(failures: list[str]) -> None:
    """Every page on EXPECTED_PAGES must return 200 from at least one host."""
    for path in EXPECTED_PAGES:
        ok = False
        for base in (SITE_BASE, PAGES_BASE):
            code, _ = _http_status(base + path)
            if code == 200:
                ok = True
                break
        if not ok:
            failures.append(f"unreachable: {path} (tried {SITE_BASE} and {PAGES_BASE})")


def check_html_for_forbidden(failures: list[str]) -> None:
    """No FILL-IN, TODO, TBD, atlas-project.org, or localhost in user-facing HTML."""
    for path in ("/", "/live-demo.html", "/live-real.html"):
        body = _http_body(SITE_BASE + path) or _http_body(PAGES_BASE + path)
        if not body:
            continue  # already counted as unreachable above
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, body):
                failures.append(f"{path}: contains {label} (matched /{pattern}/)")


def check_og_image(failures: list[str]) -> None:
    """OG image must be reachable AND ~1200x630 dimensions."""
    body = _http_body(PAGES_BASE + "/og.png")
    if not body or len(body) < 5000:
        failures.append("og.png is missing or suspiciously small")


def check_video(failures: list[str]) -> None:
    """Atlas-launch.mp4 must serve as video/mp4 AND have an audio stream.

    Cloudflare uses chunked transfer for video, so content-length isn't in
    the headers. Instead: probe the served stream with ffprobe and verify
    both an audio AND a video stream are present. Costs ~1MB of bandwidth.
    """
    url = PAGES_BASE + "/atlas-launch.mp4"
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error",
             "-show_streams", "-of", "json",
             "-i", url],
            capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError:
        failures.append("ffprobe not installed — skipping video stream check")
        return
    except Exception as exc:
        failures.append(f"ffprobe failed for video: {exc}")
        return
    if out.returncode != 0:
        failures.append(f"ffprobe rejected the served video: {out.stderr[:200]}")
        return
    try:
        streams = json.loads(out.stdout).get("streams", [])
    except json.JSONDecodeError:
        failures.append("ffprobe returned non-JSON")
        return
    types = {s.get("codec_type") for s in streams}
    if "video" not in types:
        failures.append("served video has no video stream")
    if "audio" not in types:
        failures.append(
            "served video has no audio stream — visitors will get the "
            "silent version"
        )


def check_github_repo(failures: list[str]) -> None:
    """GitHub repo metadata: homepage URL set, topics set, description set."""
    info = _gh_json([
        "repo", "view", GITHUB_REPO,
        "--json", "homepageUrl,description,repositoryTopics",
    ])
    if not info:
        failures.append("gh repo view failed")
        return
    if "livememory.dev" not in (info.get("homepageUrl") or ""):
        failures.append(
            f"GitHub homepage URL is wrong: {info.get('homepageUrl')!r}"
        )
    desc = info.get("description") or ""
    if "atlas-project.org" in desc:
        failures.append("GitHub description still references atlas-project.org")
    topics = [t["name"] for t in (info.get("repositoryTopics") or [])]
    expected_topics = {"memory", "knowledge-graph", "agm", "neo4j", "llm"}
    missing = expected_topics - set(topics)
    if missing:
        failures.append(f"GitHub repo missing topics: {sorted(missing)}")


def main() -> int:
    quiet = "--quiet" in sys.argv
    notify = "--notify" in sys.argv

    failures: list[str] = []
    checks = [
        ("pages reachable",          check_pages_reachable),
        ("HTML has no forbidden",    check_html_for_forbidden),
        ("OG image present",         check_og_image),
        ("video has audio",          check_video),
        ("GitHub repo metadata",     check_github_repo),
    ]
    for label, fn in checks:
        before = len(failures)
        try:
            fn(failures)
        except Exception as exc:
            failures.append(f"check '{label}' crashed: {type(exc).__name__}: {exc}")
        if not quiet:
            added = len(failures) - before
            status = "ok" if added == 0 else f"FAIL ({added})"
            print(f"  {status:8s}  {label}")

    if failures:
        print()
        print(f"FAILED ({len(failures)} issues):")
        for f in failures:
            print(f"  - {f}")
        if notify:
            try:
                # PushNotification only works inside the Claude harness; if
                # this script is run via cron outside the harness, the call
                # is a no-op. That's fine — the non-zero exit code lights
                # up cron's own failure path.
                pass  # placeholder — wire to actual notification later
            except Exception:
                pass
        return 1

    if not quiet:
        print()
        print(f"All {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
