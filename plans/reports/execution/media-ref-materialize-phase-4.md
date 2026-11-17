# media-ref-materialize — Phase 4: 前端用户上传解耦云存储 — Execution Report

## Overview

| Item | Content |
|------|---------|
| Plan File | plans/media-ref-materialize-plan.md |
| Phase | Phase 4: 前端用户上传解耦云存储 |
| Status | ✅ Pass |

## Plan Anchor Confirmation

- [x] 执行前重读 plan Phase 4 段（Task 4.1–4.4 + 阶段 AC）
- [x] 每个 Task 的 goal / steps / expected output / AC 已确认

## Task Completion

| Task | Status | Plan ACs | Actual Result | Deviation |
|:----:|:------:|----------|---------------|-----------|
| Task 4.1: 后端新增 `POST /files/upload` 本地落盘端点 | ✅ | ①上传返回 200，local_path 真实落盘、url 可被 /files/raw 访问 ②超限 413/400、非法扩展名拒绝 ③中文名正确落盘且 url 可访问 ④>2 天日期目录被清理 | 新增 `upload_file` 端点：落盘 `<broca_home>/uploads/YYYYMMDD/<encodedName>_<uuid6>.<ext>`（复用 `broca.tools.image._generate_unique_filename`），分块算 sha256/size/mime，返回 `{name,url,path,local_path,size,type,sha256}`。安全：50MB 上限(413)、扩展名白名单(400)、`quote()` 编码文件名防穿越、`_cleanup_old_uploads` 机会式 GC 删除早于 2 天日期目录。`tests/test_files_upload.py` 6 tests 全过（含中文名、超限、非法扩展名、GC、清理边界）。 | 无 |
| Task 4.2: 前端 `upload.ts` 双通道改造 | ✅ | ①无云→后端端点返回 local_path ②有云→S3 直传返回 storage_key ③两者含 sha256 ④非 secure context 用 js-sha256 兜底且与 crypto.subtle 一致 | `uploadFile` 双通道：`getStorageConfig()` 有值→`uploadToS3`（返回 `storage_key`），无值→`uploadToBackend`（`POST /files/upload`，返回 `local_path`）。新增 `computeSha256`/`computeSha256FromBuffer`：优先 `crypto.subtle.digest`，不可用/非 secure context 回退 `js-sha256`。`UploadResult` 扩展 `storage_key?/local_path?/sha256?`；`files.ts` 增 `filesApi.uploadFile(FormData)`。前端单测 4 passed。 | js-sha256 依赖用官方 registry tarball 手动解压到 node_modules + 手写 package.json（`npm install` 在本机挂起超时）。项目无 package-lock.json，无锁文件需同步。功能与官方包一致（0.11.0，`sha256('abc')` 校验正确）。 |
| Task 4.3: `ChatInput` 解除存储硬阻断 + 类型透传 | ✅ | ①无存储不再报"存储未配置" ②data.files 可见 local_path/storage_key、sha256 ③TS 编译通过 | 移除 `uploadSingleFile` 中 `isStorageConfigured()` 硬阻断（改用统一 `uploadFile` 内部选通道）及未用导入；`handleSendMessage` 透传 `storage_key/local_path/sha256`；`pendingFiles.uploadedData`、`chat.ts` 的 `userFiles` 与 `sendUserMessage.files`、`socket.ts`/`brocaSocket.ts` 类型均加可选字段。`vue-tsc --noEmit` 0 错误，eslint 干净。 | 额外同步了 `socket.ts`/`brocaSocket.ts` 的 files 类型（属类型完整性，非新增功能）。 |
| Task 4.4: 前端上传解耦的端到端验证 | ✅ | ①后端上传/回读字节一致 ②前端双通道选择测试 ③local ref 物化链路测试 ④同源/代理前提成立或文档标注 | 后端 `test_files_upload.py::test_upload_image_roundtrip`（上传→/files/raw 回读字节一致）；前端 `upload.test.ts`（双通道 + sha256）；`broca/tests/test_media_phase4_chain.py`（upload 输出→parse_message→local ref→get_stream_response→base64，且原 messages 不被就地修改）。同源前提：`/files/raw` 为同源相对 URL，部署需前后端同源或经 dev proxy（见下「部署说明」）。 | 无 |

## Deviations

1. **js-sha256 依赖安装方式**：`npm install js-sha256` 在本机长时间挂起（网络元数据解析阻塞，非无网），改为从官方 registry 直接下载 tarball（`https://registry.npmjs.org/js-sha256/-/js-sha256-0.11.0.tgz`）解压到 `node_modules/js-sha256` 并手写 `package.json` 的 `"js-sha256": "^0.11.0"`。项目无 `package-lock.json`，无需同步锁文件。功能验证：`sha256('abc') = ba7816bf...` 正确。**不影响任何 AC**。

## 部署说明（同源/代理前提）

`data.files[].url` 对本地图片为 `/files/raw?path=...` 相对 URL，`<img>` 以同源请求加载。因此前端必须与后端**同源**部署，或通过 dev proxy 将 `/api/files/raw` 代理到后端。跨机/容器部署且前后端不共享文件系统时，应配置云存储走 cloud ref（与现有 `/files/preview` 同假设）。

## Quality Checklist

- [x] All phase-level ACs satisfied
- [x] All task-level ACs satisfied
- [x] No missing tasks (Task 4.1–4.4 全覆盖)
- [x] No extra functionality (仅类型完整性同步，无越界功能)
- [x] Manually verified key behaviors（round-trip / 双通道 / 链路）
- [x] Code follows project conventions（ruff/eslint 干净，仅余 3 处 pre-existing）
- [x] Compatible with existing work（broca 全量 1719 passed / 后端 13 passed / 前端 26 passed）

## Test Summary

| Suite | Result |
|-------|--------|
| `broca-web/backend/tests` | 13 passed（raw 7 + upload 6） |
| `broca/tests`（全量） | 1719 passed, 2 skipped, 1 deselected（+1 新增 chain） |
| `broca-web/frontend` vitest（全量） | 26 passed（+4 新增 upload） |
| `vue-tsc --noEmit` | 0 errors |
| eslint（改动文件） | 0 errors |

## 后续修正（Phase 4 后，用户问答触发）：`/files/raw` 本地展示可达性

用户询问「install.sh 部署后前后是否同源」，核查确认**同源成立**（nginx 单 server 块：`root` 指向前端 dist，`/api/`→backend，`/socket.io/`→socketio；`.env.production` 的 `VITE_API_BASE_URL` 被注释 → axios baseURL=`/api`）。但顺带发现 `/files/raw` 本地图片展示存在两个真实可达性问题（Phase 1 遗留、Phase 4 上传端点沿用）：

1. **缺 `/api` 前缀**：后端本地媒体 URL 生成的是 `/files/raw?path=...`，而 backend 实际挂在 `/api/files/raw`；nginx/vite 均无 `/files` 代理，`<img>` 请求会被 SPA 兜底 → 加载失败。
2. **`<img>` 无法携带 Bearer token**：`verify_token` 仅对 loopback 免鉴权；经 nginx 访问时 `X-Real-IP` 为真实客户端 IP，非本机 401。

用户选择方案 A（前端补前缀 + 后端白名单），已实施：

- **前端**：新增 `src/utils/media.ts` 的 `resolveMediaUrl(url)`——对 `/files/` 前缀补 API base（默认 `/api`），https/data/blob 原样返回；在 `ChatTurnCard.vue`（缩略图 `<img :src>`）与 `ChatMessageItem.vue`（预览 `previewFileUrl`）应用；`FilePreview.vue` 的 `new URL(fileUrl)` 加 `window.location.origin` base 以兼容相对路径。
- **后端**：`broca-web/backend/app/main.py` 的 `WHITE_LIST_PREFIXES` 加入 `/api/files/raw`（端点自身已有根白名单 + mime 白名单 + 50MB 上限 + 穿越拒绝，安全性不降级）。
- **测试**：前端 `src/utils/__tests__/media.test.ts`（5 tests）；后端 `tests/test_auth_whitelist.py`（3 tests：白名单覆盖 / files/raw 免鉴权放行 / 其他路径仍 401）。

> 安全说明：加入白名单后 `/api/files/raw` 对远程匿名可达。其根白名单当前包含 `<broca_home>`（较宽，含 uploads 与 ~/.broca 下其它目录的 image/video/audio）。单用户本地部署可接受；若面向多用户/公网，建议将根白名单收紧到 `~/.broca/uploads` + 会话 workspace（属 Phase 1 设计范畴，未擅自改动）。

修正后测试：前端 vitest 31 passed、vue-tsc 0 错误、eslint 0 error；后端 tests 16 passed（原 13 + 3）。
