"""
持久化记忆 上下文注入测试
"""

import tempfile
import shutil
from pathlib import Path
from datetime import date, timedelta

from broca.persistent_memory import MemoryStore, MemoryEntry, MemoryType


class TestContextInjection:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ctx_inject_test_"))
        self.mem_dir = self.tmpdir / ".broca" / "memories"
        self.mem_dir.mkdir(parents=True)
        self.store = MemoryStore(memory_dir=self.mem_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_index_returns_empty_string(self):
        """无记忆文件时返回空字符串"""
        from broca.persistent_memory import MemoryStore
        store = MemoryStore(memory_dir=self.mem_dir)
        if not store.index_path.exists():
            content = ""
        else:
            content = store._read_file(store.index_path)
        assert content == "" or not content.strip()

    def test_index_format_has_header_entries_and_warning(self):
        """记忆格式化输出包含 header、条目列表、老化总览三部分"""
        entry1 = MemoryEntry(
            name="mem1", description="first memory", type=MemoryType.USER,
            content="content 1",
        )
        entry2 = MemoryEntry(
            name="mem2", description="second memory", type=MemoryType.PROJECT,
            content="content 2",
            updated=date.today() - timedelta(days=10),
        )
        self.store.write_memory(entry1)
        self.store.write_memory(entry2)

        index_content = self.store._read_file(self.store.index_path)
        # Should have the date in the index line
        assert date.today().isoformat() in index_content
        # Should have freshness warning
        assert "older than 7 days" in index_content

        # Verify index entries are present
        assert "mem1" in index_content
        assert "mem2" in index_content

    def test_old_memory_store_removed(self):
        """验证旧的 memory 存储方式不再使用"""
        import broca.context as ctx
        assert not hasattr(ctx, "MEMORY_ENTRY_DELIMITER")
        assert not hasattr(ctx, "MEMORY_CHAR_LIMIT")
        assert not hasattr(ctx, "USER_CHAR_LIMIT")
        assert not hasattr(ctx.Context, "_read_memory_file")
        assert not hasattr(ctx.Context, "_format_memory_block")
        assert not hasattr(ctx.Context, "_load_memory_store")
