#!/usr/bin/env python3
"""Generic HTTP conformance-plan client; contains no cognitive semantics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _pointer(document: Any, pointer: str) -> Any:
    value = document
    if pointer == "":
        return value
    for part in pointer.lstrip("/").split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _substitute(value: Any, captures: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return captures[value[2:-1]]
    if isinstance(value, list):
        return [_substitute(item, captures) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, captures) for key, item in value.items()}
    return value


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _subset(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            _subset(left, right) for left, right in zip(expected, actual, strict=True)
        )
    return expected == actual


def _request(base_url: str, token: str, step: dict[str, Any]) -> tuple[int, Any]:
    spec = step["request"]
    body = spec.get("json")
    encoded = None if body is None else json.dumps(
        body, ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + spec["path"],
        data=encoded,
        method=spec["method"],
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if encoded is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=step.get("timeout_seconds", 10)) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def run_plan(plan: dict[str, Any], base_url: str, token: str, captures: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in plan["cases"]:
        case_result: dict[str, Any] = {"id": case["id"], "passed": True, "steps": []}
        for raw_step in case["steps"]:
            step = _substitute(raw_step, captures)
            status, response = _request(base_url, token, step)
            expected = step["expect"]
            passed = status == expected["status"]
            if "json" in expected:
                passed = passed and response == expected["json"]
            if "json_subset" in expected:
                passed = passed and _subset(expected["json_subset"], response)
            for pointer, capture_name in step.get("capture", {}).items():
                captures[capture_name] = _pointer(response, pointer)
            for pointer, capture_name in expected.get("equals_capture", {}).items():
                passed = passed and _pointer(response, pointer) == captures[capture_name]
            case_result["steps"].append({
                "name": step.get("name", step["request"]["path"]),
                "passed": passed,
                "status": status,
                **({"response": response} if not passed else {}),
            })
            case_result["passed"] = case_result["passed"] and passed
        results.append(case_result)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8741")
    parser.add_argument("--token-env", default="ATLAS_COGNITIVE_TOKEN")
    parser.add_argument("--captures-in", type=Path)
    parser.add_argument("--captures-out", type=Path)
    args = parser.parse_args()
    token = os.environ.get(args.token_env)
    if not token:
        raise SystemExit(f"missing bearer token environment variable: {args.token_env}")
    captures = json.loads(args.captures_in.read_text()) if args.captures_in else {}
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    results = run_plan(plan, args.base_url, token, captures)
    if args.captures_out:
        args.captures_out.write_text(json.dumps(captures, sort_keys=True), encoding="utf-8")
    for result in results:
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"HTTP conformance client failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
