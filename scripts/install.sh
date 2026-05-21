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
NGINX_CONF_DIR=""
if command -v nginx &>/dev/null; then
    info "nginx: $(nginx -v 2>&1)"

    # 查找 nginx 配置目录 (常见位置)
    for dir in /etc/nginx /usr/local/etc/nginx /opt/homebrew/etc/nginx; do
        if [[ -d "$dir" ]]; then
            NGINX_CONF_DIR="$dir"
            break
        fi
    done

    if [[ -z "$NGINX_CONF_DIR" ]]; then
        error "已检测到 nginx 但未找到配置目录（已安装但未运行？）。"
        error "请先启动 nginx: sudo systemctl start nginx"
        exit 1
    fi

    info "nginx 配置目录: $NGINX_CONF_DIR"
else
    error "未检测到 nginx，生产部署需要 nginx。"
    error "请先安装 nginx: sudo apt install nginx  (或 brew install nginx)"
    exit 1
fi

# ============================================================================
# Step 2: 安装 broca Python 模块
# ============================================================================
step "Step 2/8: 安装 broca Python 模块..."

cd "$PROJECT_ROOT"

# 先安装 build 依赖
$PYTHON -m pip install --upgrade pip setuptools wheel build 2>&1 | grep -v "^$" | grep -v "Requirement already"

# 安装 broca 模块
info "安装 broca 模块..."
$PYTHON -m pip install "$PROJECT_ROOT" 2>&1 | grep -v "^$" | grep -v "Requirement already"

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

# ---- 迁移1: broca 主数据库 ----
info "迁移 broca 主数据库..."
cd "$PROJECT_ROOT"
BROCA_DATABASE_DIR="$BROCA_DB_DIR" $PYTHON -m alembic -c broca/alembic.ini upgrade head 2>&1 | tail -5 && \
    info "broca 主数据库迁移完成" || \
    warn "broca 主数据库迁移失败（可之后手动执行: alembic -c broca/alembic.ini upgrade head）"

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
echo "  配置文件"
echo "  ────────────────────────────────────────────"
echo "  configs.json   → $BROCA_HOME/configs.json"  
echo "  llm_config.json → $BROCA_HOME/llm_config.json"
echo ""
echo "  首次安装会自动创建用户配置副本，之后你可安全地编辑它们。"
echo "  单个 LLM Key 也可通过环境变量覆盖:"
echo "    export BROCA_API_KEY_{PROVIDER}=\"your-key\""
echo "  ────────────────────────────────────────────"
echo ""

# ---- 复制 configs.json ----
CONFIG_DST="$BROCA_HOME/configs.json"
CONFIG_SRC="$PROJECT_ROOT/configs/configs.json"

if [[ ! -f "$CONFIG_DST" ]]; then
    if [[ -f "$CONFIG_SRC" ]]; then
        cp "$CONFIG_SRC" "$CONFIG_DST"
        # 将路径改为指向 ~/.broca/
        sed -i "s|\"database_dir\":.*|\"database_dir\": \"$BROCA_HOME/data\",|" "$CONFIG_DST"
        sed -i "s|\"llm_config_file\":.*|\"llm_config_file\": \"$BROCA_HOME/llm_config.json\",|" "$CONFIG_DST"
        sed -i "s|\"log_file\":.*|\"log_file\": \"$BROCA_HOME/logs/agent.log\"|" "$CONFIG_DST"
        info "已创建用户配置: $CONFIG_DST"
    else
        warn "未找到默认配置: $CONFIG_SRC"
    fi
else
    info "用户配置已存在: $CONFIG_DST（跳过）"
fi

# ---- 复制 llm_config.json ----
LLM_DST="$BROCA_HOME/llm_config.json"
LLM_SRC="$PROJECT_ROOT/configs/llm_config.json"

if [[ ! -f "$LLM_DST" ]]; then
    if [[ -f "$LLM_SRC" ]]; then
        cp "$LLM_SRC" "$LLM_DST"
        info "已创建用户 LLM 配置: $LLM_DST"
    else
        warn "未找到默认 LLM 配置: $LLM_SRC"
        echo "  请手动创建 $LLM_DST"
    fi
else
    info "用户 LLM 配置已存在: $LLM_DST（跳过）"
fi

# ---- 复制 Agent 配置 ----
AGENTS_SRC="$PROJECT_ROOT/configs/agents"
AGENTS_DST="$BROCA_HOME/configs/agents"

if [[ -d "$AGENTS_SRC" ]]; then
    if [[ ! -d "$AGENTS_DST" ]]; then
        mkdir -p "$AGENTS_DST"
        cp -r "$AGENTS_SRC/"* "$AGENTS_DST/" 2>/dev/null
        info "已创建 Agent 配置: $AGENTS_DST"
    else
        info "Agent 配置已存在: $AGENTS_DST（跳过）"
    fi
else
    warn "未找到 Agent 配置目录: $AGENTS_SRC"
fi

echo ""

# ============================================================================
# 部署 Web 代码到 ~/.broca/web/
# ============================================================================
echo ""
echo "  部署后端和前端代码到 $BROCA_HOME/web/ ..."
echo ""

BROCA_WEB_DIR="$BROCA_HOME/web"
mkdir -p "$BROCA_WEB_DIR"

# 复制后端代码
if [[ -d "$PROJECT_ROOT/broca-web/backend" ]]; then
    rsync -a --delete "$PROJECT_ROOT/broca-web/backend/" "$BROCA_WEB_DIR/backend/" 2>/dev/null || \
        cp -r "$PROJECT_ROOT/broca-web/backend" "$BROCA_WEB_DIR/"
    info "后端代码已部署: $BROCA_WEB_DIR/backend/"
else
    error "后端代码目录不存在: $PROJECT_ROOT/broca-web/backend"
    exit 1
fi

# 复制前端源码（不含 node_modules/dist）
if [[ -d "$PROJECT_ROOT/broca-web/frontend" ]]; then
    rsync -a --delete \
        --exclude='node_modules' --exclude='dist' --exclude='.env.*' \
        "$PROJECT_ROOT/broca-web/frontend/" "$BROCA_WEB_DIR/frontend/" 2>/dev/null || \
        cp -r "$PROJECT_ROOT/broca-web/frontend" "$BROCA_WEB_DIR/frontend"
    info "前端源码已部署: $BROCA_WEB_DIR/frontend/"
else
    error "前端源码目录不存在: $PROJECT_ROOT/broca-web/frontend"
    exit 1
fi

echo ""

# ============================================================================
# Step 4: 配置文件上传存储 (交互式)
# ============================================================================
step "Step 4/8: 配置文件上传存储..."

FRONTEND_DIR="$BROCA_WEB_DIR/frontend"
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
                s3_secret="${input_s3_secret:-${current_s3_secret:-}}"

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
                cf_secret="${input_cf_secret:-${current_cf_secret:-}}"

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

# nginx 代理 API 和 Socket.IO，前端用同域路径即可
touch "$ENV_FILE"
sed -i '/^VITE_API_BASE_URL=/d' "$ENV_FILE"
echo "# VITE_API_BASE_URL=" >> "$ENV_FILE"
sed -i '/^VITE_BROCA_SOCKET_SERVER_URL=/d' "$ENV_FILE"
echo "# VITE_BROCA_SOCKET_SERVER_URL=" >> "$ENV_FILE"

echo ""

# ============================================================================
# Step 5: 安装前端依赖并构建

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
# Step 6: 部署前端
# ============================================================================
step "Step 6/8: 配置前端部署方式..."

mkdir -p "$BROCA_HOME"

info "配置 nginx 站点..."

    # nginx 以 www-data 运行，家目录不可读，静态文件放到系统路径
    NGINX_DIST_DIR="/var/www/broca/frontend"
    echo ""
    echo "  注意：nginx 以 www-data 用户运行，不能读取 ~/.broca/ 下的文件。"
    echo "  静态文件将部署到 $NGINX_DIST_DIR"
    echo ""

    if command -v sudo &>/dev/null; then
        sudo mkdir -p "$NGINX_DIST_DIR"
        sudo cp -r "$FRONTEND_DIR/dist/"* "$NGINX_DIST_DIR/"
        sudo chown -R www-data:www-data "$NGINX_DIST_DIR" 2>/dev/null || true
        info "前端静态文件已部署到: $NGINX_DIST_DIR"
    else
        warn "未找到 sudo，请手动复制前端文件:"
        echo "    sudo mkdir -p $NGINX_DIST_DIR"
        echo "    sudo cp -r $FRONTEND_DIR/dist/* $NGINX_DIST_DIR/"
        echo "    sudo chown -R www-data:www-data $NGINX_DIST_DIR"
        # 回退到 ~/.broca/（需要手工修权限）
        NGINX_DIST_DIR="$BROCA_HOME/frontend-dist"
        mkdir -p "$NGINX_DIST_DIR"
        cp -r "$FRONTEND_DIR/dist/"* "$NGINX_DIST_DIR/"
        warn "已回退部署到 $NGINX_DIST_DIR"
        echo "  如遇权限错误，运行: chmod o+x ~ ~/.broca $NGINX_DIST_DIR"
    fi

    # 生成 nginx 配置（使用转义保留 nginx 变量）
    NGINX_SITE_CONF="$BROCA_HOME/nginx-broca.conf"
    cat > "$NGINX_SITE_CONF" <<- NGINXEOF
# Broca Web - Nginx 配置
# 由 broca service install 自动生成

server {
    listen       5166;
    server_name  _;

    # 前端静态文件
    root ${NGINX_DIST_DIR};
    index index.html;

    # gzip 压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # API 反向代理 (后端)
    location /api/ {
        proxy_pass http://127.0.0.1:9000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Socket.IO 反向代理
    location /socket.io/ {
        proxy_pass http://127.0.0.1:6868;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # SPA 路由: 所有非文件请求返回 index.html
    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINXEOF

    info "nginx 配置文件已生成: $NGINX_SITE_CONF"

    # 启用 nginx 站点
    if command -v sudo &>/dev/null; then
        info "启用 nginx 站点..."
        sudo ln -sf "$NGINX_SITE_CONF" "${NGINX_CONF_DIR}/sites-enabled/broca.conf" 2>&1 || \
            warn "符号链接失败，请手动执行: sudo ln -sf $NGINX_SITE_CONF ${NGINX_CONF_DIR}/sites-enabled/broca.conf"

        if sudo nginx -t 2>&1; then
            sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload 2>/dev/null || \
                warn "nginx 重载失败，请手动执行: sudo nginx -t && sudo systemctl reload nginx"
            info "nginx 站点已启用"
        else
            warn "nginx 配置测试失败，请检查: sudo nginx -t"
        fi
    else
        warn "未找到 sudo，请手动执行以下命令:"
        echo "    sudo ln -sf $NGINX_SITE_CONF ${NGINX_CONF_DIR}/sites-enabled/broca.conf"
        echo "    sudo nginx -t && sudo systemctl reload nginx"
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

# nginx 代理后端，后端只需监听本机
BACKEND_HOST="127.0.0.1"

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
directory=$BROCA_WEB_DIR/backend
user=$USER
autostart=true
autorestart=true
startretries=3
stderr_logfile=$LOG_DIR/backend.err.log
stdout_logfile=$LOG_DIR/backend.out.log
stdout_logfile_maxbytes=20MB
stderr_logfile_maxbytes=20MB
environment=PYTHONPATH="$BROCA_WEB_DIR/backend:\$PYTHONPATH",BROCA_CONFIG="$BROCA_HOME/configs.json",BROCA_DATABASE_DIR="$BROCA_HOME/data",BROCA_LLM_CONFIG="$BROCA_HOME/llm_config.json",BROCA_AGENTS_CONFIG_DIR="$BROCA_HOME/configs/agents",BROCA_LOG_DIR="$BROCA_HOME/logs",SQLITE_DATABASE_PATH="sqlite:///${BROCA_HOME}/data/backend.db"
stopasgroup=true
killasgroup=true
SUPEOF

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
  "frontend_mode": "nginx",
  "frontend_dist": "$FRONTEND_DIR/dist",
  "nginx_dist_dir": "$NGINX_DIST_DIR",
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
echo "  前端模式: nginx"
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
echo "  nginx: ✅ 站点已配置 ($NGINX_SITE_CONF)"
echo ""
