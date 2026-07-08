"""
持久化记忆 types.py 单元测试
"""

from datetime import date, timedelta

from broca.persistent_memory.types import (
    MemoryType,
    MemoryEntry,
    MemoryIndexEntry,
    parse_frontmatter,
    build_frontmatter,
    parse_memory_file,
    build_memory_file,
    days_old,
    freshness_label,
    freshness_warning,
)


class TestMemoryType:
    def test_enum_values(self):
        values = [t.value for t in MemoryType]
        assert values == ["user", "feedback", "project", "reference"]

    def test_values_classmethod(self):
        assert MemoryType.values() == ["user", "feedback", "project", "reference"]


class TestFrontmatter:
    def test_build_and_parse(self):
        fm = build_frontmatter(
            "test_mem", "test description", MemoryType.USER,
            date(2025, 6, 15), date(2025, 6, 16),
        )
        assert "name: test_mem" in fm
        assert "type: user" in fm
        assert "created: 2025-06-15" in fm
        assert "updated: 2025-06-16" in fm

        parsed = parse_frontmatter(fm)
        assert parsed["name"] == "test_mem"
        assert parsed["type"] == "user"
        assert parsed["description"] == "test description"
        assert parsed["created"] == "2025-06-15"

    def test_parse_missing_frontmatter(self):
        try:
            parse_frontmatter("no frontmatter here")
            assert False, "Should have raised"
        except ValueError as e:
            assert "未找到" in str(e)

    def test_parse_missing_required_fields(self):
        try:
            parse_frontmatter("---\nname: only_name\n---")
            assert False, "Should have raised"
        except ValueError as e:
            assert "缺少必填字段" in str(e)

    def test_parse_invalid_type(self):
        try:
            parse_frontmatter("---\nname: x\ndescription: y\ntype: invalid\n---")
            assert False, "Should have raised"
        except ValueError as e:
            assert "无效的记忆类型" in str(e)


class TestMemoryFileRoundtrip:
    def test_roundtrip(self):
        entry = MemoryEntry(
            name="my_memory",
            description="a test memory",
            type=MemoryType.PROJECT,
            content="This is the body content.\n\nWith multiple paragraphs.",
            created=date(2025, 6, 15),
            updated=date(2025, 6, 16),
        )
        file_content = build_memory_file(entry)
        parsed = parse_memory_file(file_content)
        assert parsed.name == "my_memory"
        assert parsed.description == "a test memory"
        assert parsed.type == MemoryType.PROJECT
        assert parsed.content == "This is the body content.\n\nWith multiple paragraphs."
        assert parsed.created == date(2025, 6, 15)
        assert parsed.updated == date(2025, 6, 16)

    def test_default_dates(self):
        entry = MemoryEntry(
            name="default_dates",
            description="test",
            type=MemoryType.REFERENCE,
            content="content",
        )
        file_content = build_memory_file(entry)
        parsed = parse_memory_file(file_content)
        assert parsed.created == date.today()
        assert parsed.updated == date.today()


class TestFreshness:
    def test_days_old(self):
        today = date.today()
        assert days_old(today) == 0
        assert days_old(today - timedelta(days=1)) == 1
        assert days_old(today - timedelta(days=14)) == 14

    def test_freshness_label(self):
        today = date.today()
        assert freshness_label(today) == "_(today)_"
        assert freshness_label(today - timedelta(days=1)) == "_(1 day old)_"
        assert freshness_label(today - timedelta(days=14)) == "_(14 days old)_"

    def test_freshness_warning_with_old_entries(self):
        today = date.today()
        entries = [
            MemoryIndexEntry("a", "a.md", "desc", today),
            MemoryIndexEntry("b", "b.md", "desc", today - timedelta(days=10)),
        ]
        warn = freshness_warning(entries, 7)
        assert "1/2" in warn
        assert "older than 7 days" in warn

    def test_freshness_warning_no_old_entries(self):
        today = date.today()
        entries = [
            MemoryIndexEntry("a", "a.md", "desc", today),
            MemoryIndexEntry("b", "b.md", "desc", today - timedelta(days=3)),
        ]
        assert freshness_warning(entries, 7) == ""

    def test_freshness_warning_empty_list(self):
        assert freshness_warning([], 7) == ""
