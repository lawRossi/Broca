# Vite + Vue3 + FastAPI + Supabase 全栈项目脚手架

一个现代化的前后端分离全栈项目模板，集成了最新的前端和后端技术栈。

## 🚀 技术栈

### 前端技术栈
- **Vue 3** - 使用组合式API的渐进式框架
- **TypeScript** - 类型安全的JavaScript超集
- **Vite** - 快速的构建工具和开发服务器
- **Element Plus** - Vue 3的组件库
- **TailwindCSS** - 实用优先的CSS框架
- **Pinia** - Vue 3的官方状态管理库
- **Vue Router** - Vue.js的官方路由
- **Axios** - HTTP客户端
- **MSW** - Mock Service Worker用于API模拟
- **Prettier + ESLint** - 代码格式化和质量检查

### 后端技术栈
- **FastAPI** - 现代化的Python Web框架
- **SQLModel** - SQL数据库的ORM（基于SQLAlchemy和Pydantic）
- **Alembic** - 数据库迁移工具
- **PyJWT** - JWT令牌处理
- **Python-dotenv** - 环境变量管理
- **Ruff + Mypy** - 代码格式化和质量检查

### 数据库和云服务
- **Supabase** - 开源的Firebase替代方案
  - PostgreSQL数据库
  - 实时订阅
  - 用户认证和授权
  - Edge Functions (Deno运行时)
  - 文件存储
  - 自动API生成

### DevOps和部署
- **Docker** - 容器化部署
- **Nginx** - 反向代理和静态文件服务
- **Poetry** - Python依赖管理
- **GitHub Actions** - CI/CD流水线

## 📋 环境要求

- **Node.js**: >= 18.0.0
- **Python**: >= 3.12
- **Poetry**: >= 1.0.0
- **Docker**: >= 20.0.0 (可选，用于容器化部署)
- **Supabase CLI**: >= 1.0.0 (可选，用于本地Supabase开发)

## 🛠️ 安装和配置

### 1. 克隆项目

```bash
git clone <your-repo-url>
cd fastapi-template
```

### 2. 后端设置

#### 安装Python依赖

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install poetry
poetry config virtualenvs.in-project true
# 添加腾讯云源并设为最高优先级
poetry source add --priority=primary tencent https://mirrors.cloud.tencent.com/pypi/simple/

# 可选：保留 PyPI 官方源作为补充（镜像优先+官方兜底）
poetry source add --priority=supplemental pypi
poetry install
```

#### 环境变量配置

编辑 `.env.local` 文件：

```env
# Supabase配置
SUPABASE_URL=your_supabase_url
SUPABASE_KEY=your_supabase_anon_key
SUPABASE_SERVICE_KEY=your_supabase_service_role_key
SUPABASE_DB_PASSWORD=your_database_password
SUPABASE_JWT_SECRET=your_jwt_secret

# 其他配置...
```

#### 数据库迁移

dev 环境有**两个**库，都需要迁移：

| 库 | 内容 | 默认路径（dev） |
|----|------|-----------------|
| `sessions.db` | session / turn / message / session_runner 等 | `backend/.local-data/sessions.db` |
| `backend.db` | 登录用户 / 用户资料 | `backend/dev.db` |

`./dev.sh` 启动时会**自动迁移**（幂等，已在 head 时是 no-op），通常无需手动执行。
切换 `BROCA_CONFIG` 指向新的数据目录后也不用管，重启 dev.sh 即可。

需要手动迁移时，**必须用 `-x db_url=` 显式指定目标库**：`broca/configs.py` 和
`app/core/config.py` 都是纯文件驱动（不读 `os.environ`），环境变量会被静默忽略，
而裸 `alembic upgrade head` 会回退到仓库 `configs/configs.json` ——
把迁移应用到**生产库** `~/.broca/data/sessions.db`。

```bash
cd broca-web/backend

# 会话库（broca 核心）
PYTHONPATH=$(cd ../.. && pwd) python -m alembic -c ../../broca/alembic.ini \
  -x "db_url=sqlite:///$PWD/.local-data/sessions.db" upgrade head

# 后端库（登录/用户）
python -m alembic -x "db_url=sqlite:///$PWD/dev.db" upgrade head
```

> 忘了迁移的症状：启动日志里出现
> `Failed to restore active sessions: ... no such table: session_runner`。
> 原因是 SQLAlchemy 连接时 SQLite 会自动创建一个 0 表空文件，看起来"库存在"但表不存在。

### 3. 前端设置

#### 安装Node.js依赖

```bash
cd frontend
pnpm install
```

#### 环境变量配置

编辑 `.env.development` 文件：

```env
# Supabase配置
VITE_SUPABASE_URL=your_supabase_url
VITE_SUPABASE_KEY=your_supabase_anon_key

# API配置
VITE_API_BASE_URL=http://127.0.0.1:9001
VITE_API_MOCK=false

# LLM配置（可选）
VITE_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
VITE_LLM_API_KEY=your_llm_api_key
```

### 4. Supabase设置

#### 创建Supabase项目

1. 访问 [Supabase](https://supabase.com) 并创建新项目
2. 获取项目URL和API密钥
3. 在Supabase仪表板中配置以下设置：
   - 启用身份验证
   - 配置邮箱设置
   - 设置行级安全策略(RLS)

#### 本地Supabase开发（可选）

如果您想在本地运行Supabase：

```bash
# 安装Supabase CLI
npm install -g supabase

# 登录Supabase
supabase login

# 启动本地Supabase
supabase start
```

## 🚀 运行项目

### 开发模式

#### 启动后端服务

```bash
cd backend
poetry run uvicorn app.main:app --reload --host 0.0.0.0 --port 9001
```

#### 启动前端服务

```bash
cd frontend
pnpm dev
```

#### 访问应用

- 前端应用: http://localhost:5173
- 后端API文档: http://localhost:9001/docs
- Supabase Studio: http://localhost:54323

### 生产构建

#### 构建前端

```bash
cd frontend
pnpm build
```

#### 构建后端

```bash
cd backend
poetry build
```

### Docker部署

```bash
# 构建并启动所有服务
docker-compose up --build

# 后台运行
docker-compose up -d
```

## 📁 项目结构

```
fastapi-template/
├── backend/                    # 后端目录
│   ├── app/
│   │   ├── api/               # API路由
│   │   │   └── user.py        # 用户相关API
│   │   ├── core/              # 核心配置
│   │   │   ├── config.py      # 应用配置
│   │   │   ├── db.py          # 数据库连接
│   │   │   └── deps.py        # 依赖注入
│   │   ├── models/            # 数据模型
│   │   │   └── user.py        # User模型
│   │   ├── schemas/           # Pydantic模式
│   │   ├── services/          # 业务逻辑
│   │   │   └── user_service.py
│   │   ├── utils/             # 工具函数
│   │   │   └── supabase_utils.py
│   │   ├── tests/             # 测试文件
│   │   └── main.py            # FastAPI应用入口
│   ├── alembic/               # 数据库迁移
│   ├── pyproject.toml         # Python项目配置
│   ├── alembic.ini           # Alembic配置
│   └── Dockerfile             # 后端Dockerfile
├── frontend/                   # 前端目录
│   ├── src/
│   │   ├── api/              # API调用
│   │   ├── components/       # Vue组件
│   │   ├── stores/           # Pinia状态管理
│   │   ├── router/           # Vue路由
│   │   ├── views/            # 页面视图
│   │   ├── utils/            # 工具函数
│   │   ├── mock/             # MSW模拟数据
│   │   ├── styles/           # 样式文件
│   │   ├── App.vue           # 根组件
│   │   └── main.ts           # 前端入口
│   ├── public/               # 静态资源
│   ├── package.json          # Node.js项目配置
│   ├── vite.config.ts        # Vite配置
│   ├── tailwind.config.js    # TailwindCSS配置
│   └── Dockerfile            # 前端Dockerfile
├── supabase/                  # Supabase配置
│   ├── config.toml          # Supabase本地配置
│   ├── functions/           # Edge Functions
│   │   ├── llm/             # LLM功能
│   │   └── stream-llm/      # 流式LLM
│   └── migrations/          # 数据库迁移
├── nginx.conf               # Nginx配置
├── docker-compose.yml       # Docker编排配置
├── start.sh                # 启动脚本
└── README.md              # 项目文档
```

## 🔧 开发指南

### 代码风格

#### 前端
- 使用TypeScript严格模式
- 遵循Vue 3组合式API最佳实践
- 使用Prettier格式化代码
- 使用ESLint检查代码质量

```bash
# 前端代码检查和修复
cd frontend
pnpm lint
pnpm lint:fix

# 代码格式化
pnpm format
```

#### 后端
- 遵循PEP 8 Python代码规范
- 使用Ruff进行代码检查和格式化
- 使用MyPy进行类型检查

```bash
# 后端代码检查
cd backend
poetry run ruff check .
poetry run ruff format .
poetry run mypy .
```

## 🧪 测试

### 前端测试

```bash
cd frontend
pnpm test        # 运行单元测试
pnpm test:e2e    # 运行端到端测试
```

### 后端测试

```bash
cd backend
poetry run pytest           # 运行所有测试
poetry run pytest --cov     # 运行测试并生成覆盖率报告
```

## 📚 API文档

项目启动后，您可以访问以下URL查看API文档：

- **Swagger UI**: http://localhost:9001/docs
- **ReDoc**: http://localhost:9001/redoc
- **OpenAPI JSON**: http://localhost:9001/openapi.json


## 🚀 部署

### Docker部署

```bash
# 构建生产镜像
docker-compose -f docker-compose.prod.yml build

# 启动生产服务
docker-compose -f docker-compose.prod.yml up -d
```

### 手动部署

#### 后端部署

1. 构建Python包：
```bash
cd backend
poetry build
```

2. 部署到服务器并安装依赖：
```bash
pip install dist/*.whl
```

3. 使用Gunicorn运行：
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

#### 前端部署

1. 构建前端：
```bash
cd frontend
pnpm build
```

2. 将 `dist/` 目录内容部署到Web服务器

### 环境变量配置

确保在生产环境中正确配置所有必需的环境变量。


## 📝 许可证

本项目采用MIT许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。
