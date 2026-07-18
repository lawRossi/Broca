"""
Blackboard 单元测试

覆盖：
- 基本读写操作
- 版本化机制
- 事件通知和订阅
- 嵌套路径访问
- delete / clear / exists / keys
- 序列化/反序列化
- get_changes 变更日志
"""

from __future__ import annotations

import pytest

from broca.orchestration.blackboard import (
    Blackboard,
    BlackboardEntry,
    BlackboardEvent,
    BlackboardEventType,
)


class TestBlackboard:
    """测试 Blackboard 类"""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """测试设置和获取值"""
        bb = Blackboard()
        await bb.set("key1", "value1", producer="test")
        result = await bb.get("key1")
        assert result == "value1"

    @pytest.mark.asyncio
    async def test_get_default(self):
        """测试获取不存在的 key 返回默认值"""
        bb = Blackboard()
        result = await bb.get("nonexistent", "default_val")
        assert result == "default_val"

    @pytest.mark.asyncio
    async def test_get_nonexistent_no_default(self):
        """测试获取不存在的 key 不指定默认值"""
        bb = Blackboard()
        result = await bb.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_overwrite_value(self):
        """测试覆盖已存在的值"""
        bb = Blackboard()
        await bb.set("key1", "value1", producer="test")
        await bb.set("key1", "value2", producer="test")
        result = await bb.get("key1")
        assert result == "value2"

    @pytest.mark.asyncio
    async def test_dict_value(self):
        """测试存储字典值"""
        bb = Blackboard()
        await bb.set("user", {"name": "Alice", "age": 30}, producer="test")
        result = await bb.get("user")
        assert result["name"] == "Alice"
        assert result["age"] == 30

    @pytest.mark.asyncio
    async def test_list_value(self):
        """测试存储列表值"""
        bb = Blackboard()
        await bb.set("items", [1, 2, 3], producer="test")
        result = await bb.get("items")
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_deep_copy_on_get(self):
        """测试 get 返回深拷贝"""
        bb = Blackboard()
        original = {"data": [1, 2, 3]}
        await bb.set("key1", original, producer="test")
        result = await bb.get("key1")
        # 修改结果不应影响黑板中的值
        result["data"].append(4)
        direct = await bb.get("key1")
        assert direct["data"] == [1, 2, 3]

    # ── 版本化 ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_version_increments(self):
        """测试版本号递增"""
        bb = Blackboard()
        v0 = await bb.get_version()
        await bb.set("key1", "v1", producer="test")
        v1 = await bb.get_version()
        await bb.set("key2", "v2", producer="test")
        v2 = await bb.get_version()
        assert v1 > v0
        assert v2 > v1

    @pytest.mark.asyncio
    async def test_get_entry_contains_version(self):
        """测试获取条目含版本号"""
        bb = Blackboard()
        await bb.set("key1", "value1", producer="test")
        entry = await bb.get_entry("key1")
        assert entry is not None
        assert entry.key == "key1"
        assert entry.value == "value1"
        assert entry.version > 0
        assert entry.producer == "test"

    @pytest.mark.asyncio
    async def test_get_entry_nonexistent(self):
        """测试获取不存在的条目"""
        bb = Blackboard()
        entry = await bb.get_entry("nonexistent")
        assert entry is None

    # ── 事件通知 ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_subscribe_created_event(self):
        """测试订阅创建事件"""
        bb = Blackboard()
        events = []

        def callback(event):
            events.append(event)

        bb.subscribe(callback)
        await bb.set("key1", "value1", producer="test")

        assert len(events) == 1
        assert events[0].event_type == BlackboardEventType.CREATED
        assert events[0].key == "key1"
        assert events[0].new_value == "value1"
        assert events[0].producer == "test"

    @pytest.mark.asyncio
    async def test_subscribe_updated_event(self):
        """测试订阅更新事件"""
        bb = Blackboard()
        await bb.set("key1", "old", producer="test")

        events = []

        def callback(event):
            events.append(event)

        bb.subscribe(callback)
        await bb.set("key1", "new", producer="other")

        assert len(events) == 1
        assert events[0].event_type == BlackboardEventType.UPDATED
        assert events[0].old_value == "old"
        assert events[0].new_value == "new"

    @pytest.mark.asyncio
    async def test_subscribe_delete_event(self):
        """测试订阅删除事件"""
        bb = Blackboard()
        await bb.set("key1", "value1", producer="test")

        events = []

        def callback(event):
            events.append(event)

        bb.subscribe(callback)
        await bb.delete("key1", producer="test")

        assert len(events) == 1
        assert events[0].event_type == BlackboardEventType.DELETED

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """测试取消订阅"""
        bb = Blackboard()
        events = []

        def callback(event):
            events.append(event)

        unsubscribe = bb.subscribe(callback)
        unsubscribe()

        await bb.set("key1", "value1", producer="test")
        assert len(events) == 0

    # ── 嵌套路径 ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_nested_path_get(self):
        """测试嵌套路径访问"""
        bb = Blackboard()
        await bb.set("user", {"name": "Alice", "address": {"city": "Paris"}}, producer="test")
        name = await bb.get("user.name")
        assert name == "Alice"
        city = await bb.get("user.address.city")
        assert city == "Paris"

    @pytest.mark.asyncio
    async def test_nested_path_invalid(self):
        """测试无效的嵌套路径"""
        bb = Blackboard()
        await bb.set("user", {"name": "Alice"}, producer="test")
        result = await bb.get("user.nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_dotted_key_preference(self):
        """测试点号分隔的扁平 key 优先于嵌套"""
        bb = Blackboard()
        await bb.set("a.b", "flat_value", producer="test")
        await bb.set("a", {"b": "nested_value"}, producer="test")
        # 精确匹配优先
        result = await bb.get("a.b")
        assert result == "flat_value"

    # ── 删除/存在/清空 ────────────────────────────────

    @pytest.mark.asyncio
    async def test_delete_existing(self):
        """测试删除存在的 key"""
        bb = Blackboard()
        await bb.set("key1", "value1", producer="test")
        event = await bb.delete("key1", producer="test")
        assert event is not None
        assert event.event_type == BlackboardEventType.DELETED
        assert await bb.exists("key1") is False

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        """测试删除不存在的 key"""
        bb = Blackboard()
        event = await bb.delete("nonexistent", producer="test")
        assert event is None

    @pytest.mark.asyncio
    async def test_exists(self):
        """测试存在性检查"""
        bb = Blackboard()
        assert await bb.exists("key1") is False
        await bb.set("key1", "value1", producer="test")
        assert await bb.exists("key1") is True

    @pytest.mark.asyncio
    async def test_keys(self):
        """测试获取所有 key"""
        bb = Blackboard()
        await bb.set("a", 1, producer="test")
        await bb.set("b", 2, producer="test")
        keys = await bb.keys()
        assert set(keys) == {"a", "b"}

    @pytest.mark.asyncio
    async def test_clear(self):
        """测试清空"""
        bb = Blackboard()
        await bb.set("a", 1, producer="test")
        await bb.set("b", 2, producer="test")
        await bb.clear()
        assert await bb.exists("a") is False
        assert await bb.keys() == []
        assert await bb.get_version() == 0

    # ── 导出 ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_to_dict(self):
        """测试导出为字典"""
        bb = Blackboard()
        await bb.set("a", 1, producer="test")
        await bb.set("b", 2, producer="test")
        d = await bb.to_dict()
        assert d == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_all_entries(self):
        """测试获取所有条目"""
        bb = Blackboard()
        await bb.set("a", 1, producer="p1")
        entries = await bb.all_entries()
        assert "a" in entries
        assert entries["a"].value == 1
        assert entries["a"].producer == "p1"

    # ── 序列化/反序列化 ──────────────────────────────

    @pytest.mark.asyncio
    async def test_serialization_roundtrip(self):
        """测试序列化往返"""
        bb = Blackboard()
        await bb.set("a", 1, producer="test")
        await bb.set("b", {"nested": True}, producer="test")

        serialized = bb.to_serializable()
        restored = Blackboard.from_serializable(serialized)

        assert await restored.get("a") == 1
        assert await restored.get("b") == {"nested": True}

    # ── 变更日志 ──────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_changes(self):
        """测试获取变更"""
        bb = Blackboard()
        await bb.set("a", 1, producer="p1")
        await bb.set("a", 2, producer="p1")
        changes = await bb.get_changes(since_version=0)
        # 应该至少有一条变更
        assert len(changes) > 0

    @pytest.mark.asyncio
    async def test_initial_entries(self):
        """测试初始条目"""
        bb = Blackboard(initial_entries={"a": 1, "b": 2})
        assert await bb.get("a") == 1
        assert await bb.get("b") == 2

    def test_event_serialization(self):
        """测试事件序列化"""
        from datetime import datetime, timezone
        event = BlackboardEvent(
            key="test",
            old_value="old",
            new_value="new",
            producer="test",
            timestamp=datetime.now(timezone.utc),
            event_type=BlackboardEventType.UPDATED,
        )
        d = event.to_dict()
        assert d["key"] == "test"
        assert d["event_type"] == "updated"
        assert d["producer"] == "test"

    def test_entry_serialization(self):
        """测试条目序列化"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        entry = BlackboardEntry(
            key="test",
            value={"data": 42},
            version=3,
            producer="test",
            created_at=now,
            updated_at=now,
        )
        d = entry.to_dict()
        assert d["key"] == "test"
        assert d["version"] == 3
        assert d["value"] == {"data": 42}
