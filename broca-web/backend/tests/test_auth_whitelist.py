"""Auth whitelist for /api/files/raw (local media display via <img src>).

<img> cannot send a Bearer token, so /api/files/raw must be reachable without
auth for non-loopback clients. The endpoint itself enforces a root-directory
whitelist + mime whitelist + size cap + traversal rejection.
"""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.main import WHITE_LIST_PREFIXES, verify_token


def _make_request(path: str, client_ip: str = "203.0.113.5") -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "query_string": b"",
        "headers": [(b"x-real-ip", client_ip.encode())],
    }
    return Request(scope)


def test_files_raw_covered_by_whitelist():
    assert any("/api/files/raw".startswith(p) for p in WHITE_LIST_PREFIXES)


def test_verify_token_allows_files_raw_without_token_from_remote():
    # Non-loopback, no credentials → must NOT raise (whitelisted).
    verify_token(_make_request("/api/files/raw"), None)


def test_verify_token_still_rejects_upload_without_token_from_remote():
    with pytest.raises(HTTPException) as ei:
        verify_token(_make_request("/api/files/upload"), None)
    assert ei.value.status_code == 401
