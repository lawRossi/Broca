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
        # macOS 下 /tmp 会 resolve 为 /private/tmp，用 realpath 对比保证平台无关
        assert data["data"]["current_path"] == os.path.realpath("/tmp")

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


class TestFileCompleteAPI:
    """Test GET /api/files/complete (ChatInput # 路径补全)."""

    @staticmethod
    def _make_tree(tmpdir: str) -> None:
        """Create a test directory tree under tmpdir."""
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "zeta_dir"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "src", "utils"), exist_ok=True)
        for name in ("alpha.txt", "beta.txt", "src/main.py", "src/notes.md", "src/utils/helpers.py"):
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write("x")

    @pytest.mark.asyncio
    async def test_complete_root_listing(self, async_client: AsyncClient, auth_headers: dict):
        """prefix 为空 → 列出根目录全部条目，目录在前文件在后，各自按名称排序。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": ""}, headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["base"] == os.path.realpath(tmpdir)
            assert data["prefix"] == ""
            names = [c["name"] for c in data["completions"]]
            # 目录在前（src、zeta_dir），文件在后（alpha.txt、beta.txt）
            assert names == ["src", "zeta_dir", "alpha.txt", "beta.txt"]
            assert [c["is_dir"] for c in data["completions"]] == [True, True, False, False]
            assert data["total"] == len(data["completions"]) == 4

    @pytest.mark.asyncio
    async def test_complete_relative_paths(self, async_client: AsyncClient, auth_headers: dict):
        """返回的 path 为相对 base 的相对路径，path+base 拼接后与实际路径一致。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": ""}, headers=auth_headers
            )
            data = response.json()["data"]
            base = data["base"]
            for c in data["completions"]:
                joined = os.path.realpath(os.path.join(base, c["path"]))
                if c["is_dir"]:
                    assert joined == os.path.realpath(os.path.join(tmpdir, c["path"]))
                else:
                    assert os.path.exists(joined)
                    assert joined == os.path.realpath(os.path.join(tmpdir, c["path"]))

    @pytest.mark.asyncio
    async def test_complete_prefix_filter(self, async_client: AsyncClient, auth_headers: dict):
        """prefix=al 只返回名字以 al 开头的条目。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": "al"}, headers=auth_headers
            )
            data = response.json()["data"]
            completions = data["completions"]
            assert [c["name"] for c in completions] == ["alpha.txt"]
            assert all(c["name"].startswith("al") for c in completions)
            assert [c["path"] for c in completions] == ["alpha.txt"]

    @pytest.mark.asyncio
    async def test_complete_dir_drill(self, async_client: AsyncClient, auth_headers: dict):
        """prefix=src/ → 返回 src 下条目，path 形如 src/<name>。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": "src/"}, headers=auth_headers
            )
            data = response.json()["data"]
            completions = data["completions"]
            # 目录在前：src/utils；文件在后：main.py、notes.md
            assert [c["path"] for c in completions] == ["src/utils", "src/main.py", "src/notes.md"]
            assert [c["is_dir"] for c in completions] == [True, False, False]

    @pytest.mark.asyncio
    async def test_complete_dir_prefix_with_name(self, async_client: AsyncClient, auth_headers: dict):
        """prefix=src/ma → 在 src 目录下按名字前缀过滤。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_tree(tmpdir)
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": "src/ma"}, headers=auth_headers
            )
            data = response.json()["data"]
            assert [c["path"] for c in data["completions"]] == ["src/main.py"]

    @pytest.mark.asyncio
    async def test_complete_dotdot_rejected(self, async_client: AsyncClient, auth_headers: dict):
        """prefix 含 .. 段 → 返回空 completions（父目录穿越被拒绝）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = await async_client.get(
                "/api/files/complete", params={"base": tmpdir, "prefix": "../x"}, headers=auth_headers
            )
            data = response.json()["data"]
            assert data["completions"] == []
            assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_complete_missing_base(self, async_client: AsyncClient, auth_headers: dict):
        """base 不存在 → 返回空 completions。"""
        response = await async_client.get(
            "/api/files/complete",
            params={"base": "/nonexistent_xyz_12345", "prefix": ""},
            headers=auth_headers,
        )
        data = response.json()["data"]
        assert data["completions"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_complete_empty_base_falls_back_to_cwd(self, async_client: AsyncClient, auth_headers: dict):
        """base 为空 → 回退到后端进程 cwd 并列出条目。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = await async_client.get(
                "/api/files/complete", params={"base": "", "prefix": ""}, headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()["data"]
            assert data["base"] == os.path.realpath(os.getcwd())
            assert data["total"] >= 1
