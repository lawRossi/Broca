# Phase 1: 新记忆存储层 — Test Mapping
> Plan: plans/memory-system-upgrade-plan.md

## Task 1.1: 定义新记忆文件格式和数据结构

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| MemoryType 枚举含 user/feedback/project/reference 四值 | `test_types.py` | `TestMemoryType::test_enum_values` | ✅ |
| MemoryEntry 和 MemoryIndexEntry 定义完整 | `test_types.py` | `TestMemoryFileRoundtrip::test_roundtrip` | ✅ |
| 能正确解析带 YAML frontmatter 的 .md 文件 | `test_types.py` | `TestFrontmatter::test_build_and_parse`, `TestMemoryFileRoundtrip::test_roundtrip` | ✅ |
| 能正确从 MemoryEntry 序列化为带 frontmatter 的 .md 文件 | `test_types.py` | `TestMemoryFileRoundtrip::test_roundtrip` | ✅ |
| 解析异常时（无效 YAML、缺字段）返回清晰错误 | `test_types.py` | `TestFrontmatter::test_parse_missing_frontmatter`, `test_parse_missing_required_fields`, `test_parse_invalid_type` | ✅ |
| days_old() 正确计算新旧日期差值 | `test_types.py` | `TestFreshness::test_days_old` | ✅ |
| freshness_warning() 在无超龄记忆时返回空字符串 | `test_types.py` | `TestFreshness::test_freshness_warning_no_old_entries`, `test_freshness_warning_empty_list` | ✅ |

## Task 1.2: 实现 MemoryStore

| AC | Test File | Test Function | Status |
|----|-----------|---------------|--------|
| read_index() 正确解析 MEMORY.md（含新鲜度标注） | `test_store.py` | `TestMemoryStore::test_empty_store`, `test_write_and_read`, `test_index_date_roundtrip` | ✅ |
| write_memory() 创建 .md 文件 + 更新索引 | `test_store.py` | `TestMemoryStore::test_write_and_read`, `test_update_memory` | ✅ |
| delete_memory() 删除文件 + 移除索引条目 | `test_store.py` | `TestMemoryStore::test_delete_memory` | ✅ |
| 索引条目自动标注新鲜度 | `test_store.py` | `TestMemoryStore::test_index_freshness_labels` | ✅ |
| 索引底部自动附加老化总览警告 | `test_store.py` | `TestMemoryStore::test_index_freshness_labels` | ✅ |
| 索引超 200 行时自动截断并添加注释 | `test_store.py` | `TestMemoryStore::test_index_truncation` | ✅ |
| 路径穿越攻击被阻止 | `test_store.py` | `TestMemoryStore::test_path_security` | ✅ |

## Phase Integration Tests

| Test File | What It Verifies |
|-----------|------------------|
| (types + store combined) | 完整读写流程：创建记忆 → 写入文件 → 更新索引 → 重新读取 → 删除 | ✅ |
