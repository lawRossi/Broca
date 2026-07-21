"""Integration tests for files API endpoints.

Tests /api/files endpoints for directory listing, file info, preview, and edit.
"""

from __future__ import annotations

import os
import tempfile

import pytest
from httpx import AsyncClient


class TestListFilesAPI:
    """Test GET /api/files."""

    @pytest.mark.asyncio
    async def test_list_files_current_dir(self, async_client: AsyncClient, auth_headers: dict):
        """List current directory should return files."""
        response = await async_client.get("/api/files?path=.", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "files" in data["data"]
        assert "current_path" in data["data"]
        assert "parent_path" in data["data"]

    @pytest.mark.asyncio
    async def test_list_files_specific_dir(self, async_client: AsyncClient, auth_headers: dict):
        """List specific directory should return its files."""
        response = await async_client.get("/api/files?path=/tmp", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["current_path"] == "/tmp"

    @pytest.mark.asyncio
    async def test_list_files_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent path should return 404."""
        response = await async_client.get("/api/files?path=/nonexistent_path_xyz", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_list_files_file(self, async_client: AsyncClient, auth_headers: dict):
        """Path to a file should return 400."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test")
            f.flush()
            fname = f.name

        try:
            response = await async_client.get(f"/api/files?path={fname}", headers=auth_headers)
            assert response.status_code == 400
        finally:
            os.unlink(fname)


class TestGetFileInfoAPI:
    """Test GET /api/files/info."""

    @pytest.mark.asyncio
    async def test_get_file_info_existing(self, async_client: AsyncClient, auth_headers: dict):
        """Existing file should return its info."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"hello world")
            f.flush()
            fname = f.name

        try:
            response = await async_client.get(f"/api/files/info?path={fname}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["name"] == os.path.basename(fname)
            assert data["data"]["size"] == 11
            assert data["data"]["is_dir"] is False
            assert data["data"]["readable"] is True
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_get_file_info_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent file should return 404."""
        response = await async_client.get("/api/files/info?path=/nonexistent.file", headers=auth_headers)
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_file_info_directory(self, async_client: AsyncClient, auth_headers: dict):
        """Directory should return info with is_dir=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = await async_client.get(f"/api/files/info?path={tmpdir}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["is_dir"] is True
            assert "permissions" in data["data"]


class TestPreviewFileAPI:
    """Test GET /api/files/preview."""

    @pytest.mark.asyncio
    async def test_preview_text_file(self, async_client: AsyncClient, auth_headers: dict):
        """Text file should return its content."""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
            f.write("Hello, this is a test file!\nLine 2\nLine 3")
            f.flush()
            fname = f.name

        try:
            response = await async_client.get(f"/api/files/preview?path={fname}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["preview"] is not None
            assert "Hello" in data["data"]["preview"]
            assert data["data"]["truncated"] is False
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_preview_directory(self, async_client: AsyncClient, auth_headers: dict):
        """Preview on directory should return 400."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = await async_client.get(f"/api/files/preview?path={tmpdir}", headers=auth_headers)
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_preview_binary_file(self, async_client: AsyncClient, auth_headers: dict):
        """Binary file should return preview=None with message."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"\x00\x01\x02\x03\xff\xfe\xfd\xfc")
            f.flush()
            fname = f.name

        try:
            response = await async_client.get(f"/api/files/preview?path={fname}", headers=auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["preview"] is None
            assert "Binary file" in data["data"].get("message", "")
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_preview_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent file should return 404."""
        response = await async_client.get("/api/files/preview?path=/nonexistent.txt", headers=auth_headers)
        assert response.status_code == 404


class TestEditFileAPI:
    """Test PUT /api/files/edit."""

    @pytest.mark.asyncio
    async def test_edit_text_file(self, async_client: AsyncClient, auth_headers: dict):
        """Edit file should write content and return success."""
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as f:
            f.write("original content")
            f.flush()
            fname = f.name

        try:
            response = await async_client.put(
                f"/api/files/edit?path={fname}",
                headers=auth_headers,
                json={"content": "new content"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["data"]["size"] == len("new content")

            # Verify file was actually written
            with open(fname) as f:
                assert f.read() == "new content"
        finally:
            os.unlink(fname)

    @pytest.mark.asyncio
    async def test_edit_file_not_found(self, async_client: AsyncClient, auth_headers: dict):
        """Non-existent file should return 404."""
        response = await async_client.put(
            "/api/files/edit?path=/nonexistent.txt",
            headers=auth_headers,
            json={"content": "new content"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_edit_directory(self, async_client: AsyncClient, auth_headers: dict):
        """Editing a directory should return 400."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = await async_client.put(
                f"/api/files/edit?path={tmpdir}",
                headers=auth_headers,
                json={"content": "content"},
            )
            assert response.status_code == 400


class TestGetHomeDirAPI:
    """Test GET /api/files/home."""

    @pytest.mark.asyncio
    async def test_get_home_directory(self, async_client: AsyncClient, auth_headers: dict):
        """Home directory should be returned."""
        response = await async_client.get("/api/files/home", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "home_dir" in data["data"]
        assert data["data"]["home_dir"] == os.path.expanduser("~")
