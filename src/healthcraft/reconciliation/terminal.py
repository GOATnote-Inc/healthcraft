"""Standalone, stdlib-only client for the synthetic reconciliation service.

Copy this file alone into an agent container. The service owns world state;
this client contains no scenario, expected answer, model provider or retry loop.
The socket timeout is bounded, while the caller supervises the whole attempt.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PARAMS_BYTES = 1024 * 1024
MAX_TIMEOUT_SECONDS = 30
_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "host.docker.internal", "healthcraft-ehr"}


class TerminalError(Exception):
    """A controlled receipt; exception detail must never expose credentials."""

    def __init__(
        self,
        code: str,
        message: str,
        dispatch_state: str = "not_dispatched",
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.dispatch_state = dispatch_state
        self.http_status = http_status

    def receipt(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": "error",
            "code": self.code,
            "message": str(self),
            "dispatch_state": self.dispatch_state,
        }
        if self.http_status is not None:
            result["http_status"] = self.http_status
        return result


def _reject_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _check_json(value: Any) -> None:
    """Reject lossy Python-to-JSON coercions and exponent overflow."""
    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float and math.isfinite(value):
        return
    if type(value) is list:
        for item in value:
            _check_json(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("JSON keys must be strings")
            _check_json(item)
        return
    raise ValueError("Not a finite JSON value")


def _json_text(value: Any) -> str:
    _check_json(value)
    result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    result.encode("utf-8")  # Reject unpaired surrogate escapes before dispatch/output.
    return result


def _json_object(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(result) is not dict:
        raise ValueError("Expected a JSON object")
    _json_text(result)
    return result


def _service_origin(url: str) -> str:
    try:
        if not isinstance(url, str) or not url or any(ord(c) <= 32 for c in url):
            raise ValueError
        parsed = urlsplit(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in _ALLOWED_HOSTS
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or "?" in url
            or "#" in url
        ):
            raise ValueError
        host = parsed.hostname
        authority = f"[{host}]" if host == "::1" else host
        return f"http://{authority}:{parsed.port}"
    except (TypeError, ValueError):
        raise TerminalError(
            "invalid_configuration", "Service URL must be an allowed local HTTP origin with port."
        ) from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TerminalError("redirect_refused", "Service redirect refused.", "outcome_unknown")


def request_json(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    url: str,
    token: str,
    timeout: float = MAX_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Issue one bounded request without retries; preserve response JSON exactly.

    ``timeout`` bounds socket waits, not the entire caller's execution. A write
    whose request or response fails after dispatch has an unknown outcome.
    """
    origin = _service_origin(url)
    if (
        not isinstance(token, str)
        or not token
        or any(not 33 <= ord(char) <= 126 for char in token)
        or type(timeout) not in {int, float}
        or not 0 < timeout <= MAX_TIMEOUT_SECONDS
        or not math.isfinite(timeout)
    ):
        raise TerminalError(
            "invalid_configuration", "A valid token and bounded timeout are required."
        )
    data = None
    try:
        if method == "GET" and path == "/tools" and payload is None:
            pass
        elif (
            method == "POST"
            and path == "/call"
            and type(payload) is dict
            and set(payload) == {"name", "params"}
            and type(payload["name"]) is str
            and bool(payload["name"])
            and type(payload["params"]) is dict
        ):
            data = _json_text(payload).encode("utf-8")
        else:
            raise ValueError
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise TerminalError(
            "invalid_request", "Expected a tools read or a finite JSON tool call."
        ) from None

    request = Request(
        origin + path,
        data=data,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # Do not print arbitrary server bodies, reason strings, URLs or headers.
        raise TerminalError(
            "http_error", "Service returned an HTTP error.", "outcome_unknown", http_status=exc.code
        ) from None
    except (URLError, OSError, TimeoutError, HTTPException):
        raise TerminalError(
            "transport_error", "Service request failed.", "outcome_unknown"
        ) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise TerminalError(
            "response_too_large", "Service response exceeded 1 MiB.", "outcome_unknown"
        )
    try:
        return _json_object(raw)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise TerminalError(
            "invalid_response", "Service returned invalid finite JSON.", "outcome_unknown"
        ) from None


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise TerminalError(
            "invalid_arguments", "Use tools, or call NAME with one JSON parameter source."
        )


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("tools")
    call = commands.add_parser("call")
    call.add_argument("name")
    source = call.add_mutually_exclusive_group(required=True)
    source.add_argument("--params-json")
    source.add_argument("--params-file", type=Path)
    return parser.parse_args(argv)


def _params(args: argparse.Namespace) -> dict[str, Any]:
    try:
        if args.params_file is not None:
            with args.params_file.open("rb") as source:
                raw = source.read(MAX_PARAMS_BYTES + 1)
        else:
            raw = args.params_json.encode("utf-8")
        if len(raw) > MAX_PARAMS_BYTES:
            raise ValueError
        return _json_object(raw)
    except (OSError, ValueError, TypeError, RecursionError, OverflowError):
        raise TerminalError(
            "invalid_params", "Parameters must be a finite JSON object of at most 1 MiB."
        ) from None


def main(argv: list[str] | None = None) -> int:
    """Print a tool response on stdout or a controlled failure receipt on stderr."""
    try:
        args = _arguments(argv)
        payload = {"name": args.name, "params": _params(args)} if args.command == "call" else None
        response = request_json(
            "POST" if args.command == "call" else "GET",
            "/call" if args.command == "call" else "/tools",
            payload,
            url=os.environ.get("HC_RECONCILIATION_URL", ""),
            token=os.environ.get("HC_RECONCILIATION_TOKEN", ""),
        )
        print(_json_text(response))
        return 1 if response.get("status") == "error" else 0
    except TerminalError as exc:
        print(_json_text(exc.receipt()), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
