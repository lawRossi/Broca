#!/usr/bin/env bash
# ============================================================================
# Broca - 一键安装脚本
# ============================================================================
# 本脚本会完成以下操作：
#   1. 检查系统依赖 (Python 3.12+, Node.js/pnpm)
#   2. 安装 broca Python 模块到当前 Python 环境
#   3. 配置前端文件上传存储 (交互式，可跳过)
#   4. 安装前端依赖并构建
#   5. 检测 nginx 情况，配置前端部署方式
#   6. 创建 supervisor 配置，管理后端/前端进程
#   7. 创建日志与运行目录，完成安装
# ============================================================================

set -euo pipefail

# ---- 颜色 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }
step()  { echo -e "\n${BLUE}==>${NC} $*"; }
prompt() { echo -e -n "${CYAN}==>${NC} $*"; }

# ---- 项目根目录 ----
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BROCA_HOME="${HOME}/.broca"

echo -e "${BLUE}"
echo "==========================================="
echo "       Broca - One-Click Installer"
echo "==========================================="
echo -e "${NC}"

# ============================================================================
# Step 1: 检查系统依赖
# ============================================================================
step "Step 1/8: 检查系统依赖..."

# --- Python ---
PYTHON=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
        major=${ver%.*}
        minor=${ver#*.}
        if [[ "$major" -ge 3 && "$minor" -ge 12 ]]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    error "需要 Python >= 3.12，请先安装。"
    exit 1
fi
info "Python: $($PYTHON --version)"

# --- pip ---
if ! $PYTHON -m pip --version &>/dev/null; then
    error "pip 未安装，请先安装 pip。"
    exit 1
fi
info "pip: $($PYTHON -m pip --version | awk '{print $2}')"

# --- Node.js / pnpm ---
USE_PNPM=false
if command -v pnpm &>/dev/null; then
    USE_PNPM=true
    info "pnpm: $(pnpm --version)"
elif command -v npm &>/dev/null; then
    info "npm: $(npm --version) — 将使用 npm 代替 pnpm"
else
    error "需要 Node.js (推荐 v18+)，请先安装：https://nodejs.org"
    exit 1
fi

# --- nginx 检测 ---
USE_NGINX=false
NGINX_CONF_DIR=""
if command -v nginx &>/dev/null; then
    USE_NGINX=true
    info "nginx: $(nginx -v 2>&1)"

    # 查找 nginx 配置目录 (常见位置)
    for dir in /etc/nginx /usr/local/etc/nginx /opt/homebrew/etc/nginx; do
        if [[ -d "$dir" ]]; then
            NGINX_CONF_DIR="$dir"
            break
        fi
    done
    if [[ -z "$NGINX_CONF_DIR" ]]; then
        warn "检测到 nginx 但未找到配置目录，将使用 vite preview 部署前端。"
        USE_NGINX=false
    else
        info "nginx 配置目录: $NGINX_CONF_DIR"
    fi
else
    info "未检测到 nginx，将使用 vite preview 部署前端。"
fi

# ============================================================================
# Step 2: 安装 broca Python 模块
# ============================================================================
step "Step 2/8: 安装 broca Python 模块..."

cd "$PROJECT_ROOT"

# 先安装 build 依赖
$PYTHON -m pip install --upgrade pip setuptools wheel build 2>&1 | grep -v "^$" | grep -v "Requirement already"

# 安装 broca 模块 (可编辑模式)
info "安装 broca 模块 (editable mode)..."
$PYTHON -m pip install -e "$PROJECT_ROOT" 2>&1 | grep -v "^$" | grep -v "Requirement already"

# 安装 supervisor (用于进程管理)
info "安装 supervisor..."
$PYTHON -m pip install supervisor 2>&1 | grep -v "^$" | grep -v "Requirement already"

info "broca 模块安装完成。"

# ============================================================================
# Step 3: 数据库迁移
# ============================================================================
step "Step 3/8: 数据库迁移..."

cd "$PROJECT_ROOT"

# 数据库文件统一存到 ~/.broca/data/
BROCA_DB_DIR="$BROCA_HOME/data"
mkdir -p "$BROCA_DB_DIR"
BROCA_DB_PATH="$BROCA_DB_DIR/sessions.db"
BACKEND_DB_PATH="$BROCA_DB_DIR/backend.db"

info "数据库目录: $BROCA_DB_DIR"

# ---- 更新 root alembic.ini 中的数据库路径 ----
ROOT_ALEMBIC_INI="$PROJECT_ROOT/alembic.ini"
if [[ -f "$ROOT_ALEMBIC_INI" ]]; then
    sed -i "s|^sqlalchemy.url = .*|sqlalchemy.url = sqlite:///${BROCA_DB_PATH}|" "$ROOT_ALEMBIC_INI"
    info "alembic.ini 数据库路径已更新"
fi

# ---- 迁移1: broca 主数据库 ----
info "迁移 broca 主数据库..."
cd "$PROJECT_ROOT"
BROCA_DATABASE_DIR="$BROCA_DB_DIR" $PYTHON -m alembic upgrade head 2>&1 | tail -5 && \
    info "broca 主数据库迁移完成" || \
    warn "broca 主数据库迁移失败（可之后手动执行: alembic upgrade head）"

# ---- 迁移2: 后端数据库 ----
info "迁移后端数据库..."
cd "$PROJECT_ROOT/broca-web/backend"
SQLITE_DATABASE_PATH="sqlite:///${BACKEND_DB_PATH}" $PYTHON -m alembic upgrade head 2>&1 | tail -5 && \
    info "后端数据库迁移完成" || \
    warn "后端数据库迁移失败（可之后手动执行: alembic upgrade head）"

cd "$PROJECT_ROOT"

echo ""

# ============================================================================
# 配置 LLM
# ============================================================================
echo ""
echo "  LLM 配置文件"
echo "  ────────────────────────────────────────────"
echo "  用户配置: $BROCA_HOME/llm_config.json"
echo ""
echo "  首次安装会自动创建用户配置副本，之后你可安全地编辑它。"
echo "  单个 Key 也可通过环境变量覆盖:"
echo "    export BROCA_API_KEY_{PROVIDER}=\"your-key\""
echo "  ────────────────────────────────────────────"
echo ""

LLM_DST="$BROCA_HOME/llm_config.json"
LLM_SRC="$PROJECT_ROOT/configs/llm_config.json"

if [[ ! -f "$LLM_DST" ]]; then
    if [[ -f "$LLM_SRC" ]]; then
        cp "$LLM_SRC" "$LLM_DST"
        info "已创建用户 LLM 配置: $LLM_DST"
        echo "  请编辑此文件配置你的 LLM API Key 和模型。"
    else
        warn "未找到默认 LLM 配置: $LLM_SRC"
        echo "  请手动创建 $LLM_DST"
    fi
else
    info "用户 LLM 配置已存在: $LLM_DST（跳过）"
fi

echo ""

# ============================================================================
# Step 4: 配置文件上传存储 (交互式)
# ============================================================================
step "Step 4/8: 配置文件上传存储..."

FRONTEND_DIR="$PROJECT_ROOT/broca-web/frontend"
ENV_FILE="$FRONTEND_DIR/.env.production"

# 检测是否已有配置
has_storage_config() {
    local env_file="$1"
    [[ ! -f "$env_file" ]] && return 1

    # Cloudflare R2 配置检测
    if grep -qE '^VITE_CLOUDFLARE_ACCOUNT_ID='   "$env_file" && \
       grep -qE '^VITE_CLOUDFLARE_ACCESS_KEY_ID=' "$env_file" && \
       grep -qE '^VITE_CLOUDFLARE_SECRET_ACCESS_KEY=' "$env_file"; then
        return 0
    fi

    # Supabase S3 配置检测
    if grep -qE '^VITE_SUPABASE_URL='                 "$env_file" && \
       grep -qE '^VITE_SUPABASE_S3_ACCESS_KEY_ID='    "$env_file" && \
       grep -qE '^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=' "$env_file"; then
        return 0
    fi

    return 1
}

if has_storage_config "$ENV_FILE"; then
    info "检测到文件上传存储已配置：$(grep -E '^VITE_(CLOUDFLARE_ACCOUNT_ID|SUPABASE_URL)=' "$ENV_FILE" | head -1)"
    echo "  如需要更改配置，请编辑 $ENV_FILE 后重新构建前端。"
else
    echo ""
    echo "  Broca 前端支持文件上传功能，需要配置 S3 兼容的存储后端。"
    echo "  支持的存储后端："
    echo "    (1) Cloudflare R2  — 推荐，免费额度高，全球加速"
    echo "    (2) Supabase S3    — 如已使用 Supabase 可复用"
    echo ""
    echo "  你可以现在配置，也可以跳过（之后手动编辑 .env.production 再构建）。"
    echo ""

    prompt "是否配置文件上传存储？(y/N) "
    read -r configure_storage
    echo ""

    if [[ "$configure_storage" =~ ^[Yy]([Ee][Ss])?$ ]]; then
        echo "  请选择存储后端："
        echo "    1) Cloudflare R2"
        echo "    2) Supabase S3"
        prompt "  请输入 1 或 2 [1] "
        read -r storage_choice
        echo ""

        # 生成 .env.production (保留可能已存在的非存储配置)
        touch "$ENV_FILE"

        case "${storage_choice:-1}" in
            2)
                # ---- Supabase S3 ----
                echo "  ┌─────────────────────────────────────────────────────┐"
                echo "  │          配置 Supabase S3 存储                       │"
                echo "  │                                                     │"
                echo "  │  获取方式: Supabase Dashboard → Storage → Settings  │"
                echo "  │  S3 Credentials → 生成新的 S3 Access Key            │"
                echo "  └─────────────────────────────────────────────────────┘"
                echo ""

                # 已有值检测（|| true 防止 set -e 因 grep 无匹配而退出）
                current_supabase_url=$(grep -E '^VITE_SUPABASE_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_s3_key=$(grep -E '^VITE_SUPABASE_S3_ACCESS_KEY_ID=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_s3_secret=$(grep -E '^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_bucket=$(grep -E '^VITE_SUPABASE_BUCKET=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)

                prompt "  Supabase Project URL (例如 https://xxx.supabase.co) [${current_supabase_url:-}]: "
                read -r input_supabase_url
                supabase_url="${input_supabase_url:-${current_supabase_url:-}}"

                prompt "  S3 Access Key ID [${current_s3_key:-}]: "
                read -r input_s3_key
                s3_key="${input_s3_key:-${current_s3_key:-}}"

                prompt "  S3 Secret Access Key [${current_s3_secret:-}]: "
                read -r -s input_s3_secret
                echo "  ********"

                prompt "  Bucket 名称 [${current_bucket:-upload}]: "
                read -r input_bucket
                bucket="${input_bucket:-${current_bucket:-upload}}"

                if [[ -n "$supabase_url" && -n "$s3_key" && -n "$s3_secret" ]]; then
                    # 写入 .env.production（清除同组旧配置）
                    sed -i '/^VITE_SUPABASE_URL=/d; /^VITE_SUPABASE_S3_ACCESS_KEY_ID=/d; /^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=/d; /^VITE_SUPABASE_BUCKET=/d; /^VITE_CLOUDFLARE_/d' "$ENV_FILE"
                    {
                        echo "VITE_SUPABASE_URL=$supabase_url"
                        echo "VITE_SUPABASE_S3_ACCESS_KEY_ID=$s3_key"
                        echo "VITE_SUPABASE_S3_SECRET_ACCESS_KEY=$s3_secret"
                        echo "VITE_SUPABASE_BUCKET=$bucket"
                        echo "# VITE_CLOUDFLARE_ACCOUNT_ID="
                        echo "# VITE_CLOUDFLARE_ACCESS_KEY_ID="
                        echo "# VITE_CLOUDFLARE_SECRET_ACCESS_KEY="
                        echo "# VITE_CLOUDFLARE_BUCKET="
                        echo "# VITE_CLOUDFLARE_PUBLIC_URL="
                    } >> "$ENV_FILE"
                    info "Supabase S3 存储配置已保存。"
                else
                    warn "配置不完整（URL、Access Key、Secret 为必填），已跳过。"
                    echo "  可之后编辑 $ENV_FILE 手动配置。"
                fi
                ;;
            *)
                # ---- Cloudflare R2 (default) ----
                echo "  ┌─────────────────────────────────────────────────────┐"
                echo "  │       配置 Cloudflare R2 存储                       │"
                echo "  │                                                     │"
                echo "  │  获取方式: Cloudflare Dashboard → R2 → 管理 API 令牌 │"
                echo "  └─────────────────────────────────────────────────────┘"
                echo ""

                current_account_id=$(grep -E '^VITE_CLOUDFLARE_ACCOUNT_ID=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_cf_key=$(grep -E '^VITE_CLOUDFLARE_ACCESS_KEY_ID=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_cf_secret=$(grep -E '^VITE_CLOUDFLARE_SECRET_ACCESS_KEY=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_cf_bucket=$(grep -E '^VITE_CLOUDFLARE_BUCKET=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
                current_cf_puburl=$(grep -E '^VITE_CLOUDFLARE_PUBLIC_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)

                prompt "  Account ID [${current_account_id:-}]: "
                read -r input_account_id
                account_id="${input_account_id:-${current_account_id:-}}"

                prompt "  Access Key ID [${current_cf_key:-}]: "
                read -r input_cf_key
                cf_key="${input_cf_key:-${current_cf_key:-}}"

                prompt "  Secret Access Key [${current_cf_secret:-}]: "
                read -r -s input_cf_secret
                echo "  ********"

                prompt "  Bucket 名称 [${current_cf_bucket:-upload}]: "
                read -r input_cf_bucket
                cf_bucket="${input_cf_bucket:-${current_cf_bucket:-upload}}"

                prompt "  公开访问域名 (可选，留空自动生成) [${current_cf_puburl:-}]: "
                read -r input_cf_puburl
                cf_puburl="${input_cf_puburl:-${current_cf_puburl:-}}"

                if [[ -n "$account_id" && -n "$cf_key" && -n "$cf_secret" ]]; then
                    # 写入 .env.production（清除同组旧配置）
                    sed -i '/^VITE_CLOUDFLARE_/d; /^VITE_SUPABASE_URL=/d; /^VITE_SUPABASE_S3_ACCESS_KEY_ID=/d; /^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=/d; /^VITE_SUPABASE_BUCKET=/d' "$ENV_FILE"
                    {
                        echo "VITE_CLOUDFLARE_ACCOUNT_ID=$account_id"
                        echo "VITE_CLOUDFLARE_ACCESS_KEY_ID=$cf_key"
                        echo "VITE_CLOUDFLARE_SECRET_ACCESS_KEY=$cf_secret"
                        echo "VITE_CLOUDFLARE_BUCKET=$cf_bucket"
                        if [[ -n "$cf_puburl" ]]; then
                            echo "VITE_CLOUDFLARE_PUBLIC_URL=$cf_puburl"
                        else
                            echo "# VITE_CLOUDFLARE_PUBLIC_URL=https://pub-xxxx.r2.dev"
                        fi
                        echo "# VITE_SUPABASE_URL="
                        echo "# VITE_SUPABASE_S3_ACCESS_KEY_ID="
                        echo "# VITE_SUPABASE_S3_SECRET_ACCESS_KEY="
                        echo "# VITE_SUPABASE_BUCKET="
                    } >> "$ENV_FILE"
                    info "Cloudflare R2 存储配置已保存。"
                else
                    warn "配置不完整（Account ID、Access Key、Secret 为必填），已跳过。"
                    echo "  可之后编辑 $ENV_FILE 手动配置。"
                fi
                ;;
        esac
    else
        info "跳过文件上传存储配置。"
        echo "  如需后续配置，请编辑 $ENV_FILE 后重新构建前端。"
    fi
fi

# ============================================================================
# 配置后端连接地址 (REST API + Socket.IO)
# ============================================================================
echo ""
echo "  Broca 前端需要连接后端两个服务："
echo "    REST API      端口 9000  (axios 请求)"
echo "    Socket.IO     端口 6868  (WebSocket 通信)"
echo ""

if $USE_NGINX; then
    # nginx 模式：代理 /api/ → 9000，/socket.io/ → 6868
    info "检测到 nginx 模式，将自动代理 API 和 Socket.IO 到后端。"
    echo "  建议将两个地址都留空，前端直接使用当前页面地址，由 nginx 代理转发。"
    echo ""

    # VITE_API_BASE_URL
    current_api_url=$(grep -E '^VITE_API_BASE_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$current_api_url" ]]; then
        echo "  API 地址当前为: $current_api_url"
        prompt "  是否改为留空(使用 nginx 代理 /api/)？(y/N) "
        read -r reset_api
        if [[ "$reset_api" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            touch "$ENV_FILE"
            sed -i '/^VITE_API_BASE_URL=/d' "$ENV_FILE"
            echo "# VITE_API_BASE_URL=" >> "$ENV_FILE"
            info "API 地址已重置为留空（nginx 代理）"
        fi
    else
        echo "  API 地址: ✅ 留空（使用 nginx 代理 /api/）"
    fi

    # VITE_BROCA_SOCKET_SERVER_URL
    current_socket_url=$(grep -E '^VITE_BROCA_SOCKET_SERVER_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$current_socket_url" ]]; then
        echo "  Socket.IO 地址当前为: $current_socket_url"
        prompt "  是否改为留空(使用 nginx 代理 /socket.io/)？(y/N) "
        read -r reset_socket
        if [[ "$reset_socket" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            touch "$ENV_FILE"
            sed -i '/^VITE_BROCA_SOCKET_SERVER_URL=/d' "$ENV_FILE"
            echo "# VITE_BROCA_SOCKET_SERVER_URL=" >> "$ENV_FILE"
            info "Socket.IO 地址已重置为留空（nginx 代理）"
        fi
    else
        echo "  Socket.IO 地址: ✅ 留空（使用 nginx 代理 /socket.io/）"
    fi
else
    # vite preview 模式：无代理，前端必须直连两个后端服务
    echo "  当前使用 vite preview 部署前端（端口 5166），该模式无代理功能。"
    echo ""
    echo "  前端必须直接连接后端服务，请提供浏览器可访问到的服务器地址："
    echo ""
    echo "    服务        端口   示例 (本机)           示例 (公网)"
    echo "    ─────────────────────────────────────────────────────────"
    echo "    REST API    9000   http://localhost:9000  http://81.71.49.200:9000"
    echo "    Socket.IO   6868   http://localhost:6868  http://81.71.49.200:6868"
    echo ""
    echo "  提示：API 地址只需输服务器地址，/api 前缀会自动补上。"
    echo "  请确保服务器防火墙已放行 9000 和 6868 端口。"
    echo ""

    # VITE_API_BASE_URL
    current_api_url=$(grep -E '^VITE_API_BASE_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$current_api_url" ]]; then
        echo "  当前 API 地址: $current_api_url"
        prompt "  是否更改？(y/N) "
        read -r change_api
        if [[ "$change_api" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            prompt "  REST API 地址 (例如 http://81.71.49.200:9000): "
            read -r input_api_url
            input_api_url="${input_api_url:-}"
        else
            input_api_url="$current_api_url"
        fi
    else
        echo "  ⚠  必须配置 REST API 地址，否则无法加载历史消息等数据！"
        prompt "  REST API 地址 (例如 http://81.71.49.200:9000): "
        read -r input_api_url
        input_api_url="${input_api_url:-}"
    fi

    # VITE_BROCA_SOCKET_SERVER_URL
    current_socket_url=$(grep -E '^VITE_BROCA_SOCKET_SERVER_URL=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- || true)
    if [[ -n "$current_socket_url" ]]; then
        echo ""
        echo "  当前 Socket.IO 地址: $current_socket_url"
        prompt "  是否更改？(y/N) "
        read -r change_socket
        if [[ "$change_socket" =~ ^[Yy]([Ee][Ss])?$ ]]; then
            prompt "  Socket.IO 地址 (例如 http://81.71.49.200:6868): "
            read -r input_socket_url
            input_socket_url="${input_socket_url:-}"
        else
            input_socket_url="$current_socket_url"
        fi
    else
        echo ""
        echo "  ⚠  必须配置 Socket.IO 地址，否则前端无法实时通信！"
        prompt "  Socket.IO 地址 (例如 http://81.71.49.200:6868): "
        read -r input_socket_url
        input_socket_url="${input_socket_url:-}"
    fi

    # 写入 .env.production
    touch "$ENV_FILE"

    # 写 API 地址（自动补上 /api 前缀）
    sed -i '/^VITE_API_BASE_URL=/d' "$ENV_FILE"
    if [[ -n "$input_api_url" ]]; then
        # 去掉末尾的 /
        input_api_url="${input_api_url%/}"
        # 如果用户没输 /api 就自动补上
        if [[ "$input_api_url" != */api ]]; then
            input_api_url="${input_api_url}/api"
        fi
        echo "VITE_API_BASE_URL=$input_api_url" >> "$ENV_FILE"
        info "REST API 地址已配置: $input_api_url"
    else
        echo "# VITE_API_BASE_URL=" >> "$ENV_FILE"
        warn "REST API 地址未配置！前端将使用默认 /api（仅 nginx 模式有效）。"
    fi

    # 写 Socket.IO 地址
    sed -i '/^VITE_BROCA_SOCKET_SERVER_URL=/d' "$ENV_FILE"
    if [[ -n "$input_socket_url" ]]; then
        echo "VITE_BROCA_SOCKET_SERVER_URL=$input_socket_url" >> "$ENV_FILE"
        info "Socket.IO 地址已配置: $input_socket_url"
    else
        echo "# VITE_BROCA_SOCKET_SERVER_URL=" >> "$ENV_FILE"
        warn "Socket.IO 地址未配置！前端将无法连接 Socket.IO 服务。"
    fi
fi

echo ""

# ============================================================================
# Step 5: 安装前端依赖并构建
# ============================================================================
step "Step 5/8: 安装前端依赖并构建..."

if [[ ! -d "$FRONTEND_DIR" ]]; then
    error "前端目录不存在: $FRONTEND_DIR"
    exit 1
fi

cd "$FRONTEND_DIR"

if $USE_PNPM; then
    info "使用 pnpm 安装前端依赖..."
    pnpm install 2>&1 | tail -5
    info "构建前端 (production mode, 加载 .env.production)..."
    npx vite build 2>&1 | tail -10
else
    info "使用 npm 安装前端依赖 (如项目需要 pnpm，请先安装: npm install -g pnpm)..."
    npm install 2>&1 | tail -5
    info "构建前端 (production mode, 加载 .env.production)..."
    npx vite build 2>&1 | tail -10
fi

if [[ ! -d "$FRONTEND_DIR/dist" ]]; then
    error "前端构建失败，dist 目录不存在。"
    exit 1
fi
info "前端构建完成: $FRONTEND_DIR/dist"

# ============================================================================
# Step 6: 部署前端 (nginx / vite preview)
# ============================================================================
step "Step 6/8: 配置前端部署方式..."

mkdir -p "$BROCA_HOME"

if $USE_NGINX; then
    info "配置 nginx 站点..."

    # 复制前端构建产物到 broca home
    rsync -a "$FRONTEND_DIR/dist/" "$BROCA_HOME/frontend-dist/" 2>/dev/null || \
        cp -r "$FRONTEND_DIR/dist" "$BROCA_HOME/frontend-dist"

    # 生成 nginx 配置
    NGINX_SITE_CONF="$BROCA_HOME/nginx-broca.conf"
    cat > "$NGINX_SITE_CONF" << 'NGINXEOF'
# Broca Web - Nginx 配置
# 请将此文件软链接到 nginx 的 sites-enabled 目录:
#   sudo ln -sf ~/.broca/nginx-broca.conf /etc/nginx/sites-enabled/broca.conf
#   sudo nginx -t && sudo systemctl reload nginx

server {
    listen       5166;
    server_name  _;

    # 前端静态文件
    root __BROCA_HOME__/frontend-dist;
    index index.html;

    # gzip 压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # API 反向代理 (后端)
    location /api/ {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Socket.IO 反向代理
    location /socket.io/ {
        proxy_pass http://127.0.0.1:6868;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SPA 路由: 所有非文件请求返回 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }
}
NGINXEOF

    # 替换占位符
    BROCA_HOME_ESC=$(echo "$BROCA_HOME" | sed 's/\//\\\//g')
    sed -i "s/__BROCA_HOME__/$BROCA_HOME_ESC/g" "$NGINX_SITE_CONF"

    info "nginx 配置文件已生成: $NGINX_SITE_CONF"
    echo ""
    echo "  ----- 后续步骤 -----"
    echo "  运行以下命令启用 nginx 站点:"
    echo ""
    echo "    sudo ln -sf $NGINX_SITE_CONF ${NGINX_CONF_DIR}/sites-enabled/broca.conf"
    echo "    sudo nginx -t && sudo systemctl reload nginx"
    echo ""
    echo "  或手动复制配置到 nginx。"
    echo "  --------------------"
    echo ""
else
    info "使用 vite preview 部署前端 (由 supervisor 管理)。"
fi

# ============================================================================
# Step 7: 创建 supervisor 配置
# ============================================================================
step "Step 7/8: 创建 supervisor 进程管理配置..."

SUPERVISOR_DIR="$BROCA_HOME/supervisor"
RUN_DIR="$BROCA_HOME/run"
LOG_DIR="$BROCA_HOME/logs"

mkdir -p "$SUPERVISOR_DIR" "$RUN_DIR" "$LOG_DIR"

# 生成 supervisor 配置
SUPERVISOR_CONF="$SUPERVISOR_DIR/supervisord.conf"

# 根据部署模式选择后端监听地址
if $USE_NGINX; then
    # nginx 模式：后端只需监听本机，由 nginx 代理转发
    BACKEND_HOST="127.0.0.1"
else
    # vite preview 模式：外部浏览器直连后端，必须监听 0.0.0.0
    BACKEND_HOST="0.0.0.0"
fi

cat > "$SUPERVISOR_CONF" << SUPEOF
; Broca - Supervisor 配置
; 由 broca service install 自动生成

[unix_http_server]
file=$SUPERVISOR_DIR/supervisor.sock
chmod=0700

[supervisord]
logfile=$LOG_DIR/supervisord.log
logfile_maxbytes=50MB
logfile_backups=10
loglevel=info
pidfile=$RUN_DIR/supervisord.pid
nodaemon=false
user=$USER

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://$SUPERVISOR_DIR/supervisor.sock

; ====================
; Backend (FastAPI / Uvicorn)
; ====================
[program:backend]
command=uvicorn app.main:app --host $BACKEND_HOST --port 9000 --log-level info
directory=$PROJECT_ROOT/broca-web/backend
user=$USER
autostart=true
autorestart=true
startretries=3
stderr_logfile=$LOG_DIR/backend.err.log
stdout_logfile=$LOG_DIR/backend.out.log
stdout_logfile_maxbytes=20MB
stderr_logfile_maxbytes=20MB
environment=PYTHONPATH="$PROJECT_ROOT:\$PYTHONPATH",BROCA_DATABASE_DIR="$BROCA_HOME/data",BROCA_LLM_CONFIG="$BROCA_HOME/llm_config.json",SQLITE_DATABASE_PATH="sqlite:///${BROCA_HOME}/data/backend.db"
stopasgroup=true
killasgroup=true
SUPEOF

# 前端进程配置 (仅在非 nginx 模式下)
if ! $USE_NGINX; then
    cat >> "$SUPERVISOR_CONF" << 'SUPEOF2'

; ====================
; Frontend (Vite Preview)
; ====================
[program:frontend]
command=npx vite preview --host 0.0.0.0 --port 5166 --strictPort
directory=__FRONTEND_DIR__
user=__USER__
autostart=true
autorestart=true
startretries=3
stderr_logfile=__LOG_DIR__/frontend.err.log
stdout_logfile=__LOG_DIR__/frontend.out.log
stdout_logfile_maxbytes=20MB
stderr_logfile_maxbytes=20MB
stopasgroup=true
killasgroup=true
SUPEOF2

    # 替换占位符
    sed -i "s|__FRONTEND_DIR__|$FRONTEND_DIR|g" "$SUPERVISOR_CONF"
    sed -i "s|__USER__|$USER|g" "$SUPERVISOR_CONF"
    sed -i "s|__LOG_DIR__|$LOG_DIR|g" "$SUPERVISOR_CONF"
fi

info "supervisor 配置已生成: $SUPERVISOR_CONF"
echo ""
echo "  ----- 管理命令 (通过 broca CLI) -----"
echo "  broca service start     启动所有服务"
echo "  broca service stop      停止所有服务"
echo "  broca service restart   重启所有服务"
echo "  broca service status    查看服务状态"
echo "  -----------------------------------"
echo ""

# ============================================================================
# Step 8: 配置持久化 & 收尾
# ============================================================================
step "Step 8/8: 完成安装..."

# 保存安装信息到 broca home
cat > "$BROCA_HOME/install.json" << JSONEOF
{
  "version": "0.1.0",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "python": "$($PYTHON --version 2>&1)",
  "python_path": "$(which $PYTHON)",
  "project_root": "$PROJECT_ROOT",
  "frontend_mode": "$($USE_NGINX && echo 'nginx' || echo 'vite-preview')",
  "frontend_dist": "$FRONTEND_DIR/dist",
  "storage_configured": $([ -f "$ENV_FILE" ] && grep -qE '^VITE_(CLOUDFLARE_ACCOUNT_ID|SUPABASE_URL)=' "$ENV_FILE" && echo "true" || echo "false"),
  "backend_port": 9000,
  "frontend_port": 5166
}
JSONEOF

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Broca 安装完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  项目目录: $PROJECT_ROOT"
echo "  配置目录: $BROCA_HOME"
echo "  日志目录: $LOG_DIR"
echo "  前端模式: $($USE_NGINX && echo 'nginx' || echo 'vite preview')"
if [[ -f "$ENV_FILE" ]] && grep -qE '^VITE_(CLOUDFLARE_ACCOUNT_ID|SUPABASE_URL)=' "$ENV_FILE" 2>/dev/null; then
    echo "  文件存储: ✅ 已配置"
else
    echo -e "  文件存储: ${YELLOW}⚠ 未配置${NC} (编辑 ${ENV_FILE} 后重新构建)"
fi
echo ""
echo "  快速开始:"
echo "    broca service start      # 启动所有服务"
echo "    broca service status     # 查看状态"
echo "    broca web                # 启动开发模式 (前后端同时启动)"
echo ""
echo "  访问: http://localhost:5166"
echo ""

if $USE_NGINX; then
    echo -e "${YELLOW}  ⚠  别忘了配置 nginx 站点:${NC}"
    echo "    sudo ln -sf $NGINX_SITE_CONF ${NGINX_CONF_DIR}/sites-enabled/broca.conf"
    echo "    sudo nginx -t && sudo systemctl reload nginx"
fi
echo ""
