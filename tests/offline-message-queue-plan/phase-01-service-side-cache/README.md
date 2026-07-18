# Phase 1: 服务端消息缓存与投递 — Test Mapping
> Plan: plans/offline-message-queue-plan.md

## Task 1.1: 添加缓存数据结构和基础方法

| AC | Test Function | How to Run |
|----|---------------|------------|
| 缓存条目包含消息原文、过期时间、request_id | `test_ac01_cache_entry_contains_message_expire_at_request_id` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac01_cache_entry_contains_message_expire_at_request_id -v` |
| msg_key 生成方式为 "{message_type}_{request_id}"，保证唯一 | `test_ac02_msg_key_format` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac02_msg_key_format -v` |
| 反向索引 request_id → (subscription, msg_key) 维护正确 | `test_ac03_reverse_index_correct` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac03_reverse_index_correct -v` |
| 投递方法不过滤已发送的客户端（全部投递） | `test_ac04_deliver_all_clients` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac04_deliver_all_clients -v` |
| 投递后不清空缓存 | `test_ac05_cache_not_cleared_after_deliver` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac05_cache_not_cleared_after_deliver -v` |
| 所有方法在 self._lock 保护下 | `test_ac06_*` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_01_cache_data_structures.py::test_ac06_cache_pending_message_uses_lock -v` |

## Task 1.2: 发送时缓存 PERMISSION_REQUEST / AGENT_QUERY

| AC | Test Function | How to Run |
|----|---------------|------------|
| PERMISSION_REQUEST 和 AGENT_QUERY 发送后立即缓存 | `test_ac01_permission_request_cached_on_send`, `test_ac01_agent_query_cached_on_send` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_02_cache_on_send.py::test_ac01_permission_request_cached_on_send -v` |
| 其他消息类型不缓存 | `test_ac02_regular_message_not_cached`, `test_ac02_other_message_types_not_cached` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_02_cache_on_send.py::test_ac02_regular_message_not_cached -v` |
| 缓存在发送完成后进行，不影响正常发送流程 | `test_ac03_*` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_02_cache_on_send.py::test_ac03_cache_after_send_no_subscribers -v` |

## Task 1.3: 订阅时投递缓存消息

| AC | Test Function | How to Run |
|----|---------------|------------|
| 订阅成功后自动投递该频道的所有未过期缓存消息 | `test_ac01_deliver_on_subscribe`, `test_ac01_deliver_multiple_cached_messages` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_03_deliver_on_subscribe.py::test_ac01_deliver_on_subscribe -v` |
| 投递在 subscribe ack 之后 | `test_ac02_deliver_after_ack` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_03_deliver_on_subscribe.py::test_ac02_deliver_after_ack -v` |
| 无缓存或全部过期时，订阅行为不变 | `test_ac03_no_cache_subscribe_still_works`, `test_ac03_expired_cache_subscribe_still_works` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_03_deliver_on_subscribe.py::test_ac03_no_cache_subscribe_still_works -v` |

## Task 1.4: 收到响应时清理缓存

| AC | Test Function | How to Run |
|----|---------------|------------|
| PERMISSION_RESPONSE 到达时通过 request_id 移除对应缓存及反向索引 | `test_ac01_permission_response_removes_cache`, `test_ac01_permission_response_via_process_message` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_04_cleanup_on_response.py::test_ac01_permission_response_removes_cache -v` |
| USER_ANSWER 到达时通过 request_id 移除对应缓存及反向索引 | `test_ac02_user_answer_removes_cache`, `test_ac02_user_answer_via_process_message` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_04_cleanup_on_response.py::test_ac02_user_answer_removes_cache -v` |
| 无匹配 request_id 时无副作用 | `test_ac03_no_matching_request_id_no_side_effects`, `test_ac03_empty_request_id_no_error` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_04_cleanup_on_response.py::test_ac03_no_matching_request_id_no_side_effects -v` |
| 清理在响应被路由到 Agent 之后进行 | `test_ac04_cleanup_after_routing`, `test_ac04_only_one_cache_entry_removed` | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/test_task_04_cleanup_on_response.py::test_ac04_cleanup_after_routing -v` |

## Phase Integration Tests

| Test File | What It Verifies | How to Run |
|-----------|------------------|------------|
| `test_phase_integration.py` | Phase-level ACs: 发送并缓存、订阅投递、响应清理、TTL过期、无需修改Agent/前端 | `pytest tests/offline-message-queue-plan/phase-01-service-side-cache/phase-ac-tests/ -v` |
