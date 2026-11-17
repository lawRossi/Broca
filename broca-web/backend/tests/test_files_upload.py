"""Tests for POST /files/upload (Task 4.1) and upload->raw byte round-trip (Task 4.4).

Covers: successful image upload (local_path + /files/raw accessible), size
limit, illegal extension, Chinese filename, and >2-day date-dir GC.
"""

import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import files as files_api


@pytest.fixture
def client(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(files_api.router, prefix="/api")

    uploads_root = tmp_path / "uploads"
    uploads_root.mkdir()

    # Uploads land under tmp; /files/raw must allow reading from there too.
    monkeypatch.setattr(files_api, "_uploads_root", lambda: uploads_root)

    async def fake_roots():
        return [uploads_root.resolve()]

    monkeypatch.setattr(files_api, "_raw_allowed_roots", fake_roots)
    return TestClient(app)


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


def test_upload_image_roundtrip(client):
    """Upload returns metadata; /files/raw serves identical bytes (Task 4.4)."""
    payload = _png_bytes()
    resp = client.post(
        "/api/files/upload",
        files={"file": ("pic.png", io.BytesIO(payload), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]

    assert data["name"] == "pic.png"
    assert data["size"] == len(payload)
    assert data["type"].startswith("image/")
    assert len(data["sha256"]) == 64
    assert data["local_path"] == data["path"]
    assert Path(data["local_path"]).exists()
    assert data["url"].startswith("/files/raw?path=")

    # URL must be servable by /files/raw and return the same bytes.
    raw = client.get(data["url"].replace("/files/raw", "/api/files/raw"))
    assert raw.status_code == 200
    assert raw.headers["content-type"].startswith("image/")
    assert raw.content == payload


def test_reject_illegal_extension(client):
    resp = client.post(
        "/api/files/upload",
        files={"file": ("evil.exe", io.BytesIO(b"MZ..."), "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_too_large_413(client, monkeypatch):
    monkeypatch.setattr(files_api, "_UPLOAD_MAX_SIZE", 10)
    resp = client.post(
        "/api/files/upload",
        files={"file": ("big.png", io.BytesIO(b"\x89PNG" + b"\x00" * 100), "image/png")},
    )
    assert resp.status_code == 413


def test_chinese_filename_roundtrip(client):
    payload = _png_bytes()
    resp = client.post(
        "/api/files/upload",
        files={"file": ("中文图片.png", io.BytesIO(payload), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "中文图片.png"
    # Percent-encoded ASCII-safe name on disk.
    assert Path(data["local_path"]).exists()
    assert Path(data["local_path"]).name.isascii()

    raw = client.get(data["url"].replace("/files/raw", "/api/files/raw"))
    assert raw.status_code == 200
    assert raw.content == payload


def test_old_date_dirs_cleaned(client, tmp_path):
    uploads_root = files_api._uploads_root()
    old_dir = uploads_root / "20200101"
    old_dir.mkdir()
    (old_dir / "old.png").write_bytes(b"\x89PNG")

    # A fresh dir (today) must survive cleanup.
    from datetime import datetime

    today_dir = uploads_root / datetime.now().strftime("%Y%m%d")
    today_dir.mkdir()
    (today_dir / "keep.png").write_bytes(b"\x89PNG")

    # Trigger cleanup via a new upload.
    resp = client.post(
        "/api/files/upload",
        files={"file": ("new.png", io.BytesIO(_png_bytes()), "image/png")},
    )
    assert resp.status_code == 200
    assert not old_dir.exists(), "expired (>2 days) date dir should be removed"
    assert today_dir.exists(), "today's date dir must be kept"


def test_cleanup_keeps_recent_dirs(tmp_path):
    """_cleanup_old_uploads removes only dirs older than retention window."""
    from datetime import datetime, timedelta

    root = tmp_path / "uploads"
    root.mkdir()
    cutoff = datetime.now() - timedelta(days=2)
    old = root / (cutoff - timedelta(days=1)).strftime("%Y%m%d")
    edge = root / cutoff.strftime("%Y%m%d")
    fresh = root / datetime.now().strftime("%Y%m%d")
    for d in (old, edge, fresh):
        d.mkdir()
        (d / "f.png").write_bytes(b"x")
    # non-date dir untouched
    other = root / "not_a_date"
    other.mkdir()

    files_api._cleanup_old_uploads(root, retention_days=2)
    assert not old.exists()
    assert edge.exists()  # exactly at cutoff is kept ("more than 2 days" removed)
    assert fresh.exists()
    assert other.exists()
