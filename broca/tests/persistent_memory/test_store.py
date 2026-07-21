"""
持久化记忆 store.py 单元测试
"""

import tempfile
import shutil
from pathlib import Path
from datetime import date, timedelta

from broca.persistent_memory import (
    MemoryType,
    MemoryEntry,
    MemoryStore,
)


class TestMemoryStore:
    def setup_method(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="mem_store_test_"))
        self.store = MemoryStore(
            memory_dir=self.tmpdir,
            freshness_warning_days=7,
        )

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_store(self):
        assert self.store.read_index() == []

    def test_write_and_read(self):
        entry = MemoryEntry(
            name="test_memory",
            description="a test memory entry",
            type=MemoryType.PROJECT,
            content="This is the body of the memory.",
        )
        idx_entry = self.store.write_memory(entry)
        assert idx_entry.name == "test_memory"
        assert (self.tmpdir / "test_memory.md").exists()

        # Verify index
        index = self.store.read_index()
        assert len(index) == 1
        assert index[0].name == "test_memory"

        # Verify read_memory
        read_entry = self.store.read_memory("test_memory")
        assert read_entry is not None
        assert read_entry.name == "test_memory"
        assert read_entry.content == "This is the body of the memory."

    def test_update_memory(self):
        entry1 = MemoryEntry(
            name="updatable", description="v1", type=MemoryType.USER,
            content="version 1",
        )
        self.store.write_memory(entry1)

        entry2 = MemoryEntry(
            name="updatable", description="v2", type=MemoryType.USER,
            content="version 2",
        )
        self.store.write_memory(entry2)

        read_entry = self.store.read_memory("updatable")
        assert read_entry.description == "v2"
        assert read_entry.content == "version 2"

    def test_delete_memory(self):
        entry = MemoryEntry(
            name="deletable", description="to delete", type=MemoryType.REFERENCE,
            content="delete me",
        )
        self.store.write_memory(entry)
        assert (self.tmpdir / "deletable.md").exists()

        result = self.store.delete_memory("deletable")
        assert result is True
        assert not (self.tmpdir / "deletable.md").exists()
        assert self.store.read_index() == []

    def test_read_nonexistent(self):
        assert self.store.read_memory("nonexistent") is None

    def test_index_freshness_labels(self):
        old_date = date.today() - timedelta(days=10)
        entry_old = MemoryEntry(
            name="old_mem", description="old entry", type=MemoryType.USER,
            content="old", created=old_date, updated=old_date,
        )
        entry_fresh = MemoryEntry(
            name="fresh_mem", description="fresh entry", type=MemoryType.USER,
            content="fresh",
        )
        self.store.write_memory(entry_old)
        self.store.write_memory(entry_fresh)

        index_content = (self.tmpdir / "MEMORY.md").read_text()
        # Verify dates are stored in the index
        assert old_date.isoformat() in index_content
        assert date.today().isoformat() in index_content
        # Verify freshness warning
        assert "older than 7 days" in index_content

    def test_index_date_roundtrip(self):
        old_date = date.today() - timedelta(days=10)
        entry = MemoryEntry(
            name="dated_mem", description="dated", type=MemoryType.PROJECT,
            content="dated content", created=old_date, updated=old_date,
        )
        self.store.write_memory(entry)

        # Re-read from a fresh store instance
        store2 = MemoryStore(memory_dir=self.tmpdir)
        index = store2.read_index()
        assert len(index) == 1
        assert index[0].name == "dated_mem"
        assert index[0].updated == old_date

    def test_ordering_by_update_time(self):
        old_date = date.today() - timedelta(days=5)
        self.store.write_memory(MemoryEntry(
            name="older", description="older", type=MemoryType.USER,
            content="older", updated=old_date,
        ))
        self.store.write_memory(MemoryEntry(
            name="newer", description="newer", type=MemoryType.USER,
            content="newer",
        ))
        index = self.store.read_index()
        assert index[0].name == "newer"  # most recent first
        assert index[1].name == "older"

    def test_path_security(self):
        # Should reject paths outside memory dir
        try:
            self.store._validate_path(Path("/etc/passwd"))
            assert False, "Should have raised"
        except PermissionError:
            pass

        # Should accept paths inside memory dir
        self.store._validate_path(self.tmpdir / "test.md")

    def test_index_truncation(self):
        # Create more than 200 entries
        for i in range(210):
            self.store.write_memory(MemoryEntry(
                name=f"mem_{i:03d}",
                description=f"entry {i}",
                type=MemoryType.REFERENCE,
                content=f"content {i}",
            ))

        index = self.store.read_index()
        assert len(index) <= 200
        # Verify TRUNCATED comment
        index_content = (self.tmpdir / "MEMORY.md").read_text()
        assert "TRUNCATED" in index_content
