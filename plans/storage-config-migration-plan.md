# 文件上传存储配置迁移至基础配置页

## 概述
- **目标**：将文件上传存储配置（Cloudflare R2 / Supabase S3）从 `install.sh` 的构建时 VITE_* 环境变量方式，迁移到"基础配置" tab 的运行时 API 配置方式
- **背景**：当前存储配置通过 `install.sh` Step 4/9 交互式向导写入 `.env.production`，在 `vite build` 时编译进 JS bundle，运行时不可修改，改配置需重新构建
- **约束条件**：
  - 完全迁移，彻底移除 VITE_* 环境变量方式
  - 配置存储在 `configs.json` 的 `storage` 分组中
  - 前端运行时通过 API 获取配置，无需重新构建

## 相关材料
- `broca/configs.py` — BrocaConfig / ExecutionConfig 数据模型
- `broca-web/backend/app/api/config.py` — 后端配置 API（KNOWN_GENERAL_CONFIG_FIELDS、校验、过滤）
- `broca-web/frontend/src/api/config.ts` — 前端 API 类型定义（GeneralConfig、ASRConfig 等）
- `broca-web/frontend/src/views/settings/GeneralConfigPanel.vue` — 基础配置 tab UI
- `broca-web/frontend/src/utils/upload.ts` — 文件上传模块（当前从 import.meta.env 读取）
- `scripts/install.sh` Step 4/9（lines 560–751）— 当前存储配置向导
- `broca-web/frontend/src/views/Settings.vue` — Settings 页面主框架

## 总体方案

**配置存储结构**：在 `configs.json` 中新增 `storage` 分组，与 `execution`、`asr` 同级：

```json
{
  "storage": {
    "backend": "cloudflare",        // "cloudflare" | "supabase" | ""
    "cloudflare_account_id": "...",
    "cloudflare_access_key_id": "...",
    "cloudflare_secret_access_key": "...",
    "cloudflare_bucket": "upload",
    "cloudflare_public_url": "...",
    "supabase_url": "...",
    "supabase_s3_access_key_id": "...",
    "supabase_s3_secret_access_key": "...",
    "supabase_bucket": "upload"
  }
}
```

**运行时流程变更**：
1. `upload.ts` 改为通过 API（`GET /api/config/general`）获取存储配置，构建 S3 client
2. 不再依赖 `import.meta.env` 的 VITE_* 变量
3. 配置变更即时生效（无需重新构建），因为每次 upload 时读取最新配置或监听配置变化

**install.sh 变更**：
- 删除 Step 4/9（存储配置向导，lines 560–751）
- 后续 step 编号从 5/9 起不变（只删一个 step，但编号已硬编码，需要全部重新编号为 /8）
- 移除 `install.json` 中的 `storage_configured` 字段（如有）

## 执行计划

### Phase 1: 后端 — BrocaConfig 数据模型 + API 层扩展

**目标**：后端支持 `storage` 分组的读写、校验、过滤

**阶段验收标准**：
- [ ] `GET /api/config/general` 返回含 `storage` 字段的完整配置
- [ ] `PUT /api/config/general` 接受并持久化 `storage` 分组，校验逻辑正确
- [ ] 未知字段仍被丢弃（白名单机制完整）
- [ ] `BrocaConfig` 类包含 `storage` 字段

#### Task 1.1: BrocaConfig 添加 StorageConfig

- **目标**：在 `broca/configs.py` 中新增 `StorageConfig` 数据类，并挂到 `BrocaConfig`
- **步骤**：
  1. 在 `broca/configs.py` 中新增 `StorageConfig` 类（在 `ExecutionConfig` 之后）：
     ```python
     class StorageConfig:
         """文件上传存储配置（configs.json 的 storage 分组）"""
         def __init__(self):
             self.backend = ""  # "cloudflare" | "supabase" | ""
             # Cloudflare R2
             self.cloudflare_account_id = ""
             self.cloudflare_access_key_id = ""
             self.cloudflare_secret_access_key = ""
             self.cloudflare_bucket = "upload"
             self.cloudflare_public_url = ""
             # Supabase S3
             self.supabase_url = ""
             self.supabase_s3_access_key_id = ""
             self.supabase_s3_secret_access_key = ""
             self.supabase_bucket = "upload"

         @classmethod
         def from_config(cls, config):
             storage_config = cls()
             for key in list(config.keys()):
                 if key not in storage_config.__dict__:
                     del config[key]
             storage_config.__dict__.update(config)
             return storage_config
     ```
  2. 在 `BrocaConfig.__init__` 中添加 `self.storage = StorageConfig()`
  3. 在 `BrocaConfig.from_config` 中添加对 `storage` 字段的特殊处理（类似 `execution` 的处理方式）：
     ```python
     elif key == "storage" and isinstance(config[key], dict):
         agent_config.storage = StorageConfig.from_config(config[key])
         config[key] = agent_config.storage
     ```
- **预期产出**：`broca/configs.py` 包含 `StorageConfig` 类
- **验收标准**：
  - [ ] `StorageConfig` 类包含上述所有字段，有合理的默认值
  - [ ] `BrocaConfig` 实例有 `storage` 属性，类型为 `StorageConfig`
  - [ ] `BrocaConfig.from_config({"storage": {"backend": "supabase"}})` 正确解析，未知字段被删除
  - [ ] 不传 `storage` 时，`config.storage` 为默认值

#### Task 1.2: 后端 API 层扩展 storage 字段

- **目标**：在 `broca-web/backend/app/api/config.py` 中扩展 `storage` 分组的校验、过滤逻辑
- **步骤**：
  1. 在 `KNOWN_GENERAL_CONFIG_FIELDS` 元组中添加 `"storage"`（追加到末尾）
  2. 新增 `KNOWN_STORAGE_CONFIG_FIELDS` 元组：
     ```python
     KNOWN_STORAGE_CONFIG_FIELDS = (
         "backend",
         "cloudflare_account_id",
         "cloudflare_access_key_id",
         "cloudflare_secret_access_key",
         "cloudflare_bucket",
         "cloudflare_public_url",
         "supabase_url",
         "supabase_s3_access_key_id",
         "supabase_s3_secret_access_key",
         "supabase_bucket",
     )
     ```
  3. 新增 `VALID_STORAGE_BACKENDS = {"cloudflare", "supabase"}` 常量
  4. 新增 `_validate_storage_config(config)` 函数（参照 `_validate_asr_config` 模式）：
     - 必须为 dict
     - 未知字段报错
     - `backend` 若存在必须是空字符串或合法值
     - 所有字段值必须为字符串类型（允许空字符串）
  5. 在 `_validate_general_config` 中添加 `elif key == "storage": _validate_storage_config(value)` 分支
  6. 在 `_filter_general_config` 中添加 `storage` 分组的过滤逻辑（参照 `asr` 的模式）
- **预期产出**：`config.py` 支持 storage 分组的完整校验和过滤
- **验收标准**：
  - [ ] `PUT /api/config/general` 发送含 `storage` 分组的合法配置时返回 200 且正确持久化
  - [ ] `PUT /api/config/general` 发送含 `storage.unknown_field` 时返回 400
  - [ ] `PUT /api/config/general` 发送 `storage.backend = "invalid"` 时返回 400
  - [ ] `GET /api/config/general` 返回含 storage 分组的完整数据
  - [ ] 过滤后仅保留 `KNOWN_STORAGE_CONFIG_FIELDS` 中的字段

---

### Phase 2: 前端 — 类型定义 + 配置 UI + 上传模块重构

**目标**：前端"基础配置" tab 新增存储配置区域，上传模块改为运行时从 API 读取配置

**阶段验收标准**：
- [ ] 基础配置 tab 显示"文件上传存储"区域，支持选择后端、填写凭证
- [ ] 配置保存后，上传功能立即可用（无需重启或重新构建）
- [ ] 未配置存储时，上传按钮禁用并提示"请在设置页配置存储"
- [ ] 已移除所有 `import.meta.env.VITE_CLOUDFLARE_*` 和 `VITE_SUPABASE_*` 引用
- [ ] 前端构建成功（`npx vite build` 无错误）

#### Task 2.1: 前端类型定义扩展

- **目标**：在 `broca-web/frontend/src/api/config.ts` 中添加 `StorageConfig` 接口
- **步骤**：
  1. 在 `ASRConfig` 接口之后新增：
     ```typescript
     /** 文件上传存储配置（configs.json 中的 storage 分组） */
     export interface StorageConfig {
       /** 存储后端: cloudflare | supabase | 空（未配置） */
       backend?: string
       // Cloudflare R2
       cloudflare_account_id?: string
       cloudflare_access_key_id?: string
       cloudflare_secret_access_key?: string
       cloudflare_bucket?: string
       cloudflare_public_url?: string
       // Supabase S3
       supabase_url?: string
       supabase_s3_access_key_id?: string
       supabase_s3_secret_access_key?: string
       supabase_bucket?: string
     }
     ```
  2. 在 `GeneralConfig` 接口中添加 `storage?: StorageConfig`
- **预期产出**：`config.ts` 包含 `StorageConfig` 类型定义
- **验收标准**：
  - [ ] `StorageConfig` 接口包含所有字段
  - [ ] `GeneralConfig` 接口包含 `storage?: StorageConfig`
  - [ ] TypeScript 编译无错误

#### Task 2.2: GeneralConfigPanel.vue 添加存储配置区域

- **目标**：在基础配置 tab 中添加"文件上传存储"表单区域
- **步骤**：
  1. 新增辅助函数（参照 `asrValue` / `setAsrValue` 模式）：
     ```typescript
     const storageValue = (fieldKey: keyof StorageConfig): string | undefined => {
       const storage = config.value.storage
       return storage && typeof storage === 'object' ? (storage[fieldKey] as string) : undefined
     }
     const setStorageValue = (fieldKey: keyof StorageConfig, value: string | undefined | null) => {
       const current = config.value.storage
       const storage: StorageConfig = current ? { ...current } : {}
       if (value === undefined || value === null || value === '') {
         delete storage[fieldKey]
       } else {
         storage[fieldKey] = value as any
       }
       config.value = { ...config.value, storage }
     }
     ```
  2. 在 `<script setup>` 中导入 `type StorageConfig`
  3. 定义后端选项常量：
     ```typescript
     const STORAGE_BACKENDS = [
       { value: 'cloudflare', label: 'Cloudflare R2（推荐，免费额度高，全球加速）' },
       { value: 'supabase', label: 'Supabase S3' },
     ]
     ```
  4. 在模板中，ASR 区域之后添加存储配置区域：
     - 标题："文件上传存储"
     - 说明文字："配置文件上传的 S3 兼容存储后端（configs.json 的 storage 分组，修改后即时生效）"
     - 后端选择：`el-select`，选项为 cloudflare / supabase，支持清空（未配置）
     - 根据选中后端动态显示对应的凭证表单：
       - **Cloudflare R2**：Account ID、Access Key ID、Secret Access Key（password 类型）、Bucket 名称（默认 upload）、公开访问域名（可选）
       - **Supabase S3**：Project URL、S3 Access Key ID、S3 Secret Access Key（password 类型）、Bucket 名称（默认 upload）
     - 当后端未选择时，显示提示"请选择存储后端以启用文件上传功能"
     - Secret 类型字段使用 `el-input` 的 `type="password"` + `show-password`
  5. 在 `validateBeforeSave` 中添加 storage 校验：
     - 若 `backend` 为 cloudflare，则 `cloudflare_account_id`、`cloudflare_access_key_id`、`cloudflare_secret_access_key` 必填
     - 若 `backend` 为 supabase，则 `supabase_url`、`supabase_s3_access_key_id`、`supabase_s3_secret_access_key` 必填
- **预期产出**：基础配置 tab 显示存储配置表单
- **验收标准**：
  - [ ] 选择 Cloudflare R2 后端时显示 Account ID、Access Key ID、Secret Access Key、Bucket、Public URL 字段
  - [ ] 选择 Supabase S3 后端时显示 Project URL、S3 Access Key ID、S3 Secret Access Key、Bucket 字段
  - [ ] 切换后端时表单字段正确切换
  - [ ] 未选择后端时显示提示文字
  - [ ] Secret 字段使用密码输入框
  - [ ] 配置修改后自动保存（1.2s 防抖）正常工作
  - [ ] 保存失败时显示错误提示
  - [ ] 校验：选择后端但必填字段为空时，保存被阻止

#### Task 2.3: 重构 upload.ts — 运行时配置

- **目标**：`upload.ts` 改为从 API 获取存储配置，移除所有 VITE_* 环境变量依赖
- **步骤**：
  1. 移除 `detectConfig()` 函数（不再从 `import.meta.env` 读取）
  2. 新增 `fetchStorageConfig()` 异步函数：
     ```typescript
     import configApi from '@/api/config'

     /** 从 API 获取并缓存存储配置 */
     let cachedStorageConfig: S3Config | null = null
     let cachedAt = 0
     const CACHE_TTL = 30_000 // 30 秒缓存

     async function getStorageConfig(forceRefresh = false): Promise<S3Config | null> {
       const now = Date.now()
       if (!forceRefresh && cachedStorageConfig !== null && now - cachedAt < CACHE_TTL) {
         return cachedStorageConfig
       }
       if (cachedStorageConfig === null && !forceRefresh && now - cachedAt < 5_000) {
         return null // 未配置的短期缓存，避免频繁请求
       }
       try {
         const general = await configApi.getGeneralConfig()
         const storage = general?.storage
         cachedStorageConfig = buildS3Config(storage)
         cachedAt = now
         return cachedStorageConfig
       } catch {
         return null
       }
     }

     function buildS3Config(storage?: StorageConfig): S3Config | null {
       if (!storage || !storage.backend) return null
       if (storage.backend === 'cloudflare' &&
           storage.cloudflare_account_id &&
           storage.cloudflare_access_key_id &&
           storage.cloudflare_secret_access_key) {
         const accountId = storage.cloudflare_account_id
         const bucket = storage.cloudflare_bucket || 'upload'
         return {
           type: 'cloudflare', region: 'auto',
           endpoint: `https://${accountId}.r2.cloudflarestorage.com`,
           bucket,
           credentials: {
             accessKeyId: storage.cloudflare_access_key_id,
             secretAccessKey: storage.cloudflare_secret_access_key,
           },
           publicUrlBase: storage.cloudflare_public_url ||
             `https://${bucket}.${accountId}.r2.dev`,
         }
       }
       if (storage.backend === 'supabase' &&
           storage.supabase_url &&
           storage.supabase_s3_access_key_id &&
           storage.supabase_s3_secret_access_key) {
         const url = storage.supabase_url
         const bucket = storage.supabase_bucket || 'upload'
         return {
           type: 'supabase', region: 'auto',
           endpoint: `${url}/storage/v1/s3`,
           bucket,
           credentials: {
             accessKeyId: storage.supabase_s3_access_key_id,
             secretAccessKey: storage.supabase_s3_secret_access_key,
           },
           publicUrlBase: `${url}/storage/v1/object/public/${bucket}`,
         }
       }
       return null
     }
     ```
  3. 修改 `uploadFile()` 为异步获取配置：
     - `const cfg = await getStorageConfig()`
     - `if (!cfg) throw new Error('存储未配置，请在设置页「基础配置」中配置文件上传存储')`
     - 使用 `cfg` 替代全局 `s3Config` 创建 S3 client
  4. 修改 `getClient()` 接受 `S3Config` 参数：
     ```typescript
     function getClient(cfg: S3Config): S3Client {
       // 按 cfg 创建或复用 client
     }
     ```
     注意：由于配置可能变化，需要管理 client 的生命周期。方案：维护一个 Map<configKey, S3Client>，当配置变更时创建新 client。
  5. 修改 `isStorageConfigured()` 为异步 `async function isStorageConfigured()` 或提供同步版本（基于缓存）。考虑使用：
     - `async function isStorageConfigured()`: 获取最新配置判断
     - 调用方需要改为 `await isStorageConfigured()`
  6. 修改 `getStorageType()` 类似处理
  7. 移除旧的 `const s3Config = detectConfig()` 模块级初始化
  8. 搜索并更新所有 `import.meta.env.VITE_CLOUDFLARE_*` 和 `VITE_SUPABASE_S3_*` / `VITE_SUPABASE_URL` 的引用（主要在 upload.ts 内部）
- **预期产出**：`upload.ts` 完全通过 API 获取配置
- **验收标准**：
  - [ ] 文件中无任何 `import.meta.env` 引用
  - [ ] `uploadFile(file)` 正常上传到配置的 S3 后端
  - [ ] 未配置存储时 `uploadFile` 抛出明确错误
  - [ ] 配置变更后 30 秒内（或强制刷新后）生效
  - [ ] `isStorageConfigured()` 和 `getStorageType()` 正确反映配置状态

#### Task 2.4: 更新 upload.ts 调用方

- **目标**：更新 `upload.ts` 的调用方以适配异步 API 变更
- **步骤**：
  1. **`ChatInput.vue`**：
     - 搜索 `isStorageConfigured()` 和 `uploadFile()` 的调用
     - 将 `isStorageConfigured()` 改为 `await isStorageConfigured()`
     - `uploadSingleFile` 中 `uploadFile(file)` 已经返回 Promise，无需改
     - 错误提示文案更新为"存储未配置，请在设置页「基础配置」中配置"
  2. **`Home.vue`**：
     - 搜索 `isStorageConfigured()` 调用，改为 `await isStorageConfigured()`
     - 搜索 `uploadFile()` 调用，确保在 async 上下文中
  3. 搜索整个 frontend 目录确认无其他 `isStorageConfigured` / `getStorageType` / `uploadFile` 的调用被遗漏
- **预期产出**：所有调用方适配异步 API
- **验收标准**：
  - [ ] ChatInput.vue 中上传功能正常工作
  - [ ] Home.vue 中头像上传功能正常工作
  - [ ] 未配置存储时，上传按钮/区域正确显示禁用状态和提示
  - [ ] 无 TypeScript 类型错误
  - [ ] 前端构建成功

---

### Phase 3: install.sh 清理

**目标**：移除 install.sh 中的存储配置向导，更新步骤编号

**阶段验收标准**：
- [ ] `install.sh` 不再包含任何 `VITE_CLOUDFLARE_*` / `VITE_SUPABASE_S3_*` 的写入逻辑
- [ ] 步骤编号从 `/9` 变为 `/8`（删除了一个步骤）
- [ ] `install.sh` 语法检查通过（`bash -n`）
- [ ] 不再向 `.env.production` 写入存储相关变量

#### Task 3.1: 删除 install.sh Step 4/9 并重编号

- **目标**：删除存储配置向导代码，更新步骤编号
- **步骤**：
  1. 删除 `scripts/install.sh` 中 "Step 4/9: 配置文件上传存储" 整个代码块（约 lines 560–751，从 `step "Step 4/9: 配置文件上传存储..."` 到对应的 `fi  # SKIP_FRONTEND` 前的内容）
     - 具体：删除 `has_storage_config()` 函数、交互式向导逻辑
     - 保留 `if $SKIP_FRONTEND` / `else` / `fi` 外壳中非存储相关的部分（即 `touch "$ENV_FILE"` + sed 注释 VITE_API_BASE_URL 和 VITE_BROCA_SOCKET_SERVER_URL 的逻辑可以保留，因为那两个变量虽然注释掉了但 install.sh 仍然写它们）
     - 实际上整个 Step 4/9 块（包括 `if $SKIP_FRONTEND` 包裹）都可以删除，因为它的唯一目的就是配置存储 + 注释掉两个 URL 变量。那两个 URL 变量可以移到 Step 5/9（前端构建步骤）中，或者确认它们不再需要
  2. 更新所有步骤编号：原 `Step 5/9` → `Step 4/8`，`Step 6/9` → `Step 5/8`，以此类推
  3. 检查 `install.json` 中是否有 `storage_configured` 字段，如有则移除
  4. 确认 `.env.production` 不再被写入任何 `VITE_CLOUDFLARE_*` / `VITE_SUPABASE_*` 变量
- **预期产出**：`install.sh` 不再有存储配置步骤，步骤编号连续
- **验收标准**：
  - [ ] `grep -n "VITE_CLOUDFLARE\|VITE_SUPABASE_S3" scripts/install.sh` 返回空
  - [ ] `grep -n "storage" scripts/install.sh` 返回空（或仅出现在无关上下文中）
  - [ ] `bash -n scripts/install.sh` 无语法错误
  - [ ] 步骤编号连续（Step 1/8, 2/8, ..., 8/8）
  - [ ] `install.json` 无 `storage_configured` 字段

#### Task 3.2: 清理前端 .env 文件中的存储变量

- **目标**：清理 `.env.production` 和 `.env.development` 中不再使用的 VITE_ 存储变量
- **步骤**：
  1. 检查 `broca-web/frontend/.env.production`，移除所有 `VITE_CLOUDFLARE_*` 和 `VITE_SUPABASE_S3_*` 行（保留非存储的变量如 `VITE_API_MOCK`）
  2. 检查 `broca-web/frontend/.env.development`（如存在），同样清理
  3. 检查 `broca-web/frontend/vite.config.ts`，确认没有对 VITE_ 存储变量的特殊处理
  4. 搜索 frontend 目录确认无残留引用
- **预期产出**：`.env` 文件中无存储相关变量
- **验收标准**：
  - [ ] `grep "VITE_CLOUDFLARE\|VITE_SUPABASE_S3\|VITE_SUPABASE_URL\|VITE_SUPABASE_BUCKET" broca-web/frontend/.env.*` 返回空
  - [ ] `grep -r "VITE_CLOUDFLARE\|VITE_SUPABASE" broca-web/frontend/src/` 返回空
  - [ ] 前端构建成功

## 风险与应对

| 风险 | 影响 | 应对策略 |
|------|------|----------|
| 已有部署通过 VITE_* 变量配置了存储 | 升级后存储配置丢失，上传不可用 | 用户需在新版设置页重新配置。可在发布说明中注明迁移步骤 |
| 前端 API 调用失败（如后端未启动） | 上传功能不可用 | `getStorageConfig` 中 catch 错误返回 null，提示用户检查后端 |
| 频繁调用 `getGeneralConfig` API | 性能开销 | 30 秒缓存机制 + 未配置时 5 秒短缓存 |
| configs.json 中存储了敏感凭证（secret access key） | 安全风险 | 与当前 VITE_* 方案安全模型一致（前端均可访问）；配置文件权限由 OS 控制 |
| `upload.ts` 异步化导致调用方遗漏 `await` | 运行时 bug | Task 2.4 系统性搜索并更新所有调用方 |

## 未解决的问题
- 无（所有关键决策已与用户确认：完全迁移，移除 VITE_* 方式）
