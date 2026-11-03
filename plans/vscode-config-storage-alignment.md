# VSCode 配置页对齐 Web — Storage 迁移至基础配置

## 概述
- **目标**：将 VSCode 配置页的 Storage 配置从「客户端设置」tab 迁移到「基础配置」tab，同时对齐 Web 版的字段 hints、执行引擎参数等细节
- **背景**：Web 版 GeneralConfigPanel 包含 4 个分组（基础/执行引擎/ASR/存储），VSCode 版缺少存储分组（放在 ClientConfigPanel），且缺少字段 hints 和执行引擎的 step 参数
- **约束条件**：保留「客户端设置」tab（VSCode 专属：Server URL + Default LLM）；VSCode 面板使用纯 HTML/CSS + VSCode theme variables，不使用 Element Plus

## 相关材料
- **VSCode GeneralConfigPanel**: `broca-vscode/src/webview/src/components/settings/GeneralConfigPanel.vue`
- **VSCode ClientConfigPanel**: `broca-vscode/src/webview/src/components/settings/ClientConfigPanel.vue`
- **VSCode 共享样式**: `broca-vscode/src/webview/src/components/settings/settings.css`（已有 `.storage-section`/`.storage-divider`/`.subsection-title` 类）
- **VSCode 类型 (extension)**: `broca-vscode/src/extension/types.ts`
- **VSCode 类型 (webview)**: `broca-vscode/src/webview/src/types.ts`
- **Web GeneralConfigPanel (参考)**: `broca-web/frontend/src/views/settings/GeneralConfigPanel.vue`
- **Web 类型 (参考)**: `broca-web/frontend/src/api/config.ts`（StorageConfig 定义 + GeneralConfig.storage 字段）

## 总体方案

**单阶段、3 个任务**：类型扩展 → General 面板增加存储分组 → Client 面板移除存储分组。

API 层无需改动（`getGeneralConfig`/`saveGeneralConfig` 已支持完整 GeneralConfig 含 storage）。消息协议也无需改动（webview 发送 `saveGeneralConfig` 的 payload 就是完整 config 对象，storage 子对象自动跟随）。

## 执行计划

### Phase 1: Storage 迁移 + 细节对齐
**目标**：Storage 配置从 ClientConfigPanel 迁至 GeneralConfigPanel，同时对齐 Web 的字段 hints 和执行引擎参数

**阶段验收标准**：
- [ ] VSCode「基础配置」tab 包含 4 个分组：基础配置 / 执行引擎配置 / ASR 语音识别 / 文件上传存储
- [ ] VSCode「客户端设置」tab 仅保留 Server Configuration + Default LLM 两个分组
- [ ] `StorageConfig` 接口和 `GeneralConfig.storage` 字段在 extension/types.ts 和 webview/src/types.ts 中均存在
- [ ] 执行引擎字段包含 `min` 和 `step` 属性，值与 Web 版一致
- [ ] 基础配置字段（database_dir 等 6 个）有 hint 提示文字
- [ ] 构建通过，无类型错误

#### Task 1.1: 扩展类型定义
- **目标**：在 VSCode 的 extension 和 webview 两份 types 中添加 `StorageConfig` 接口，并在 `GeneralConfig` 中增加 `storage` 字段
- **步骤**：
  1. 在 `broca-vscode/src/extension/types.ts` 中：
     - 在 `ASRConfig` 接口之后添加 `StorageConfig` 接口（字段与 Web 版 `broca-web/frontend/src/api/config.ts` 的 `StorageConfig` 一致）
     - 在 `GeneralConfig` 接口中 `asr?: ASRConfig` 后添加 `storage?: StorageConfig`
  2. 在 `broca-vscode/src/webview/src/types.ts` 中做完全相同的修改
- **预期产出**：两份 types 文件均包含 `StorageConfig` 和 `GeneralConfig.storage`
- **验收标准**：
  - [ ] `StorageConfig` 包含 10 个可选字段：`backend`, `cloudflare_account_id`, `cloudflare_access_key_id`, `cloudflare_secret_access_key`, `cloudflare_bucket`, `cloudflare_public_url`, `supabase_url`, `supabase_s3_access_key_id`, `supabase_s3_secret_access_key`, `supabase_bucket`
  - [ ] `GeneralConfig` 接口包含 `storage?: StorageConfig`
  - [ ] 两份文件定义完全一致

#### Task 1.2: GeneralConfigPanel 增加存储分组 + 细节对齐
- **目标**：在 GeneralConfigPanel 的 ASR 分组之后新增「文件上传存储」分组，同时对齐 Web 版的字段 hints 和执行引擎参数
- **步骤**：
  1. **Script 部分**：
     - 导入 `StorageConfig` 类型
     - 添加 `STORAGE_BACKENDS` 常量：`[{value:'cloudflare', label:'Cloudflare R2'}, {value:'supabase', label:'Supabase S3'}]`
     - 添加 `storageValue(key)` 辅助函数（读取 `config.storage[key]`，同 asrValue 模式）
     - 添加 `setStorageValue(key, value)` 辅助函数（copy-on-write 写回，同 setAsrField 模式）
     - 更新 `EXECUTION_FIELDS`：为每个字段添加 `step` 属性，对齐 Web 版值（参考下方表格）
     - 更新 `validateBeforeSave()`：增加 storage 后端必填字段校验（cloudflare: account_id/access_key_id/secret_access_key; supabase: url/access_key_id/secret_access_key）
  2. **Template 部分**：
     - 在 ASR 分组之后新增 `<section class="section">`，标题「文件上传存储」
     - 存储后端：`<select>` (STORAGE_BACKENDS 选项 + 默认空选项)
     - `v-if="storageValue('backend') === 'cloudflare'"` 时显示 5 个 Cloudflare 字段（Account ID / Access Key ID / Secret Access Key [type=password] / Bucket 名称 / 公开访问域名）
     - `v-if="storageValue('backend') === 'supabase'"` 时显示 4 个 Supabase 字段（Project URL / S3 Access Key ID / S3 Secret Access Key [type=password] / Bucket 名称）
     - 每个字段添加 `<p class="field-hint">` 提示文字（对齐 Web 版）
     - 在基础配置 6 个字段中也各添加 `<p class="field-hint">`（对齐 Web 版 hints）
  3. **执行引擎 EXECUTION_FIELDS 对齐**（label 保持英文，增加 step 和 hint）：

     | key | VSCode 现有 min | Web min | Web step |
     |---|---|---|---|
     | step_max_errors | 无 | 1 | 1 |
     | llm_retry_delay | 无 | 0 | 1 |
     | tool_call_timeout | 无 | 1 | 10 |
     | assign_task_timeout | 无 | 1 | 60 |
     | llm_timeout | 无 | 1 | 10 |
     | llm_first_chunk_timeout | 无 | 5 | 5 |
     | dead_loop_window | 无 | 2 | 1 |
     | message_queue_size | 无 | 1 | 1 |
     | permission_request_timeout | 无 | 10 | 10 |
     | agent_query_timeout | 无 | 30 | 30 |

- **预期产出**：GeneralConfigPanel.vue 包含 4 个分组，功能与 Web 版完全对齐
- **验收标准**：
  - [ ] 存储分组有 backend select，选中 cloudflare 时显示 5 个 CF 字段，选中 supabase 时显示 4 个 SB 字段，未选时仅显示 select
  - [ ] 每个基础字段（database_dir 等）下方有 `field-hint` 提示
  - [ ] 每个执行引擎字段有正确的 `min` 和 `step` 值（与 Web 版一致）
  - [ ] `validateBeforeSave()` 在 backend=cloudflare 时校验 3 个必填字段，backend=supabase 时校验 3 个必填字段
  - [ ] 执行引擎字段的 `<input type="number">` 增加了 `:step="f.step"`

#### Task 1.3: ClientConfigPanel 移除存储分组
- **目标**：从 ClientConfigPanel 中移除 Storage 相关的所有 UI 和数据，仅保留 Server Configuration + Default LLM
- **步骤**：
  1. **Script 部分**：
     - 从 `config` ref 中移除 9 个 storage 字段（`cloudflareAccountId`, `cloudflareAccessKeyId`, `cloudflareSecretAccessKey`, `cloudflareBucket`, `cloudflarePublicUrl`, `supabaseUrl`, `supabaseS3AccessKeyId`, `supabaseS3SecretAccessKey`）
  2. **Template 部分**：
     - 删除整个 `<section class="section">` 的 "Storage Configuration" 块（从 `<!-- Storage Configuration -->` 注释到 `</section>` 结束，包括 Cloudflare R2 区块、"— 或 —" 分隔线、Supabase S3 区块）
- **预期产出**：ClientConfigPanel 只剩 Server Configuration + Default LLM 两个 section
- **验收标准**：
  - [ ] ClientConfigPanel 中无任何 "storage"/"cloudflare"/"supabase" 相关 UI 或数据
  - [ ] Server Configuration 和 Default LLM 两个 section 正常显示
  - [ ] saveConfig 发送的 payload 不再包含 storage 字段

## 风险与应对
| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 已有用户的 storage 配置存在 ClientConfig 而非 GeneralConfig 中 | 迁移后旧 storage 数据丢失 | 后端 `getGeneralConfig` 已返回完整 config（含 storage），只要 API 层正确即可。ClientConfig 的 storage 是 VSCode 本地 config，与后端 config 分离，迁移后旧本地值不再使用但不会报错 |
| settings.css 中 `.storage-section` / `.storage-divider` / `.subsection-title` 类在移除 Client 的 storage UI 后变成死代码 | 无功能影响 | 保留不删——GeneralConfigPanel 的存储分组如果采用 subsection 结构可复用；即使不复用也只是几个无引用的 CSS 类 |
