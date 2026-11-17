"""Tests for GET /files/raw (Task 1.4): path whitelist, mime, size, traversal."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import files as files_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(files_api.router, prefix="/api")

    async def fake_roots():
        return [tmp_path.resolve()]

    monkeypatch.setattr(files_api, "_raw_allowed_roots", fake_roots)
    return TestClient(app)


@pytest.fixture
def image_file(tmp_path):
    p = tmp_path / "pic.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    return p


def test_serves_image(client, image_file):
    resp = client.get("/api/files/raw", params={"path": str(image_file)})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")
    assert resp.content == image_file.read_bytes()


def test_missing_file_404(client, tmp_path):
    resp = client.get("/api/files/raw", params={"path": str(tmp_path / "nope.png")})
    assert resp.status_code == 404


def test_directory_400(client, tmp_path):
    resp = client.get("/api/files/raw", params={"path": str(tmp_path)})
    assert resp.status_code == 400


def test_traversal_403(client, tmp_path):
    # /etc/passwd is outside the whitelisted root
    resp = client.get("/api/files/raw", params={"path": "/etc/passwd"})
    assert resp.status_code == 403


def test_traversal_via_dotdot_403(client, tmp_path, image_file):
    # even with .. tricks resolving outside root → 403
    sneaky = str(tmp_path / ".." / ".." / "etc" / "passwd")
    resp = client.get("/api/files/raw", params={"path": sneaky})
    assert resp.status_code == 403


def test_disallowed_type_403(client, tmp_path):
    p = tmp_path / "secret.txt"
    p.write_text("top secret")
    resp = client.get("/api/files/raw", params={"path": str(p)})
    assert resp.status_code == 403


def test_too_large_413(client, tmp_path, monkeypatch):
    p = tmp_path / "big.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(files_api, "_RAW_MAX_SIZE", 4)
    resp = client.get("/api/files/raw", params={"path": str(p)})
    assert resp.status_code == 413
