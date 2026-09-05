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

# 获取当前用户名（避免 set -u 下 $USER 未定义时触发 "unbound variable"）
# $USER 通常在登录 shell 中已定义，但经 sudo/su/env -i 或容器环境调用时可能缺失，
# 用 id -un 作为可靠回退。
USER="${USER:-$(id -un)}"

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

# ---- OS 检测 ----
OS="$(uname -s)"
case "$OS" in
    Darwin)
        IS_MACOS=true
        # Homebrew nginx 配置目录 (Apple Silicon / Intel)
        HOMEBREW_NGINX_DIR=""
        if [[ -d "/opt/homebrew/etc/nginx" ]]; then
            HOMEBREW_NGINX_DIR="/opt/homebrew"
        elif [[ -d "/usr/local/etc/nginx" ]]; then
            HOMEBREW_NGINX_DIR="/usr/local"
        fi
        if [[ -z "$HOMEBREW_NGINX_DIR" ]]; then
            # macOS 上 nginx 是可选的，后续会询问是否跳过前端
            NGINX_SITES_DIR="/opt/homebrew/etc/nginx/sites-enabled"
            NGINX_CONF_BASE="/opt/homebrew/etc/nginx"
        else
            NGINX_SITES_DIR="${HOMEBREW_NGINX_DIR}/etc/nginx/sites-enabled"
            NGINX_CONF_BASE="${HOMEBREW_NGINX_DIR}/etc/nginx"
        fi
        NGINX_USER="_www"
        SED_INPLACE=("sed" "-i" "")
        ;;
    *)
        IS_MACOS=false
        NGINX_SITES_DIR="/etc/nginx/sites-enabled"
        NGINX_CONF_BASE="/etc/nginx"
        NGINX_USER="www-data"
        SED_INPLACE=("sed" "-i")
        ;;
esac

# sed -i 跨平台辅助函数
sed_inplace() {
    "${SED_INPLACE[@]}" "$@"
}

# ---- 工具函数 ----
# 根据 pnpm 版本生成 build 权限配置（v10: .npmrc, v11+: pnpm-workspace.yaml）
write_pnpm_build_config() {
    local dir="$1"
    local major="${2:-0}"
    if [[ "$major" -ge 11 ]]; then
        cat > "$dir/pnpm-workspace.yaml" << 'YAMLEOF'
allowBuilds:
  esbuild: true
  msw: true
  vue-demi: true
YAMLEOF
    else
        # pnpm v10 及以下使用 .npmrc
        cat > "$dir/.npmrc" << 'NPMEOF'
onlyBuiltDependencies[]=esbuild
onlyBuiltDependencies[]=msw
onlyBuiltDependencies[]=vue-demi
NPMEOF
    fi
}
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
step "Step 1/9: 检查系统依赖..."

# --- Python ---
PYTHON=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
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
# 检测 pip：优先使用当前 Python 的 -m pip 模块；
# 若该 Python 未绑定 pip 模块（多版本共存或系统仅提供 pip/pip3 命令），
# 回退到系统 pip / pip3 命令，避免误报"pip 未安装"。
PIP_CMD=""
if $PYTHON -m pip --version &>/dev/null; then
    PIP_CMD="$PYTHON -m pip"
elif command -v pip &>/dev/null; then
    PIP_CMD="pip"
elif command -v pip3 &>/dev/null; then
    PIP_CMD="pip3"
fi

if [[ -z "$PIP_CMD" ]]; then
    error "pip 未安装，请先安装 pip。"
    exit 1
fi
info "pip: $($PIP_CMD --version | awk '{print $2}')"

# --- Node.js / pnpm ---
USE_PNPM=false
PNPM_MAJOR_VERSION=0
HAS_NODE=false
if command -v pnpm &>/dev/null; then
    HAS_NODE=true
    USE_PNPM=true
    PNPM_MAJOR_VERSION=$(pnpm --version | cut -d. -f1)
    info "pnpm: $(pnpm --version) (major v$PNPM_MAJOR_VERSION)"
elif command -v npm &>/dev/null; then
    HAS_NODE=true
    info "npm: $(npm --version) — 将使用 npm 代替 pnpm"
else
    warn "未检测到 Node.js，将跳过前端构建和 VS Code 插件打包。"
    warn "如需前端页面或 VS Code 插件，请先安装 Node.js (推荐 v18+)：https://nodejs.org"
    SKIP_FRONTEND=true
fi

# --- nginx 检测 ---
NGINX_CONF_DIR=""
NGINX_DIST_DIR=""
NGINX_SITE_CONF=""
FRONTEND_DIR=""
ENV_FILE=""
# 如果 Node.js 不可用则已设为 true，否则初始为 false
SKIP_FRONTEND="${SKIP_FRONTEND:-false}"
if ! $SKIP_FRONTEND && command -v nginx &>/dev/null; then
    info "nginx: $(nginx -v 2>&1)"

    # 查找 nginx 配置目录
    NGINX_CONF_DIR=""
    for dir in "$NGINX_CONF_BASE" /etc/nginx /usr/local/etc/nginx /opt/homebrew/etc/nginx; do
        if [[ -d "$dir" ]]; then
            NGINX_CONF_DIR="$dir"
            break
        fi
    done

    if [[ -z "$NGINX_CONF_DIR" ]]; then
        if $IS_MACOS; then
            warn "已检测到 nginx 但未找到配置目录。"
            warn "请先确保 nginx 已正确安装: brew info nginx"
        else
            warn "已检测到 nginx 但未找到配置目录（已安装但未运行？）。"
            warn "请先启动 nginx: sudo systemctl start nginx"
        fi
        echo ""
        prompt "nginx 配置不完整，是否跳过前端部署，仅安装后端？(Y/n) "
        read -r skip_frontend_input
        if [[ ! "${skip_frontend_input:-y}" =~ ^[Nn]([Oo])?$ ]]; then
            SKIP_FRONTEND=true
            warn "将跳过前端部署，仅安装后端"
        else
            error "请修复 nginx 后重新运行安装脚本"
            exit 1
        fi
    else
        info "nginx 配置目录: $NGINX_CONF_DIR"
        # 确保 sites-enabled 目录存在
        if $IS_MACOS && [[ ! -d "$NGINX_SITES_DIR" ]]; then
            mkdir -p "$NGINX_SITES_DIR"
            # 如果 nginx.conf 没有引入 sites-enabled，尝试引入
            if ! grep -q "sites-enabled" "$NGINX_CONF_DIR/nginx.conf" 2>/dev/null; then
                warn "nginx.conf 未包含 sites-enabled 目录，自动添加..."
                sed_inplace -e '/^http {/a\
    include '"$NGINX_SITES_DIR"'/*.conf;' "$NGINX_CONF_DIR/nginx.conf" 2>/dev/null || \
                warn "无法自动修改 nginx.conf，请手动添加: include $NGINX_SITES_DIR/*.conf;"
            fi
        fi
    fi
elif ! $SKIP_FRONTEND; then
    echo ""
    warn "未检测到 nginx，无法部署前端页面。"
    prompt "是否跳过前端，仅安装后端？(Y/n) "
    read -r skip_frontend_input
    if [[ ! "${skip_frontend_input:-y}" =~ ^[Nn]([Oo])?$ ]]; then
        SKIP_FRONTEND=true
        warn "将跳过前端部署，仅安装后端"
        echo "  提示: 安装完成后可使用 VS Code 插件连接后端服务"
    else
        if $IS_MACOS; then
            error "请先安装 nginx: brew install nginx"
        else
            error "请先安装 nginx: sudo apt install nginx"
        fi
        exit 1
    fi
fi

# ============================================================================
# Step 2: 安装 broca Python 模块（虚拟环境感知）
# ============================================================================
step "Step 2/9: 安装 broca Python 模块..."

BROCA_VENV="$BROCA_HOME/venv"
cd "$PROJECT_ROOT"

# 检测是否已在虚拟环境中
IS_IN_VENV=false
if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    IS_IN_VENV=true
    info "检测到已激活的虚拟环境: $VIRTUAL_ENV"
elif $PYTHON -c "import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)" 2>/dev/null; then
    IS_IN_VENV=true
    info "检测到当前 Python 已在虚拟环境中"
fi

if $IS_IN_VENV; then
    # 已在虚拟环境中 — 从 venv 路径获取正确的 Python，而非 Step 1 检测的
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        BROCA_VENV="$VIRTUAL_ENV"
    else
        BROCA_VENV=$($PYTHON -c "import sys; print(sys.prefix)")
    fi
    BROCA_PYTHON="$BROCA_VENV/bin/python"
    BROCA_PIP="$BROCA_PYTHON -m pip"
    info "直接使用当前虚拟环境: $($BROCA_PYTHON --version)"
    info "虚拟环境路径: $BROCA_VENV"
elif [[ -f "$BROCA_VENV/bin/python" ]]; then
    # 已有 broca 专属虚拟环境 — 验证其有效性
    info "检测到已有的 broca 虚拟环境: $BROCA_VENV"
    VENV_VALID=true

    # 检查 1: Python 可执行
    if ! "$BROCA_VENV/bin/python" --version &>/dev/null; then
        warn "虚拟环境 Python 不可执行"
        VENV_VALID=false
    fi

    # 检查 2: pip 可用
    if $VENV_VALID && ! "$BROCA_VENV/bin/python" -m pip --version &>/dev/null; then
        warn "虚拟环境中 pip 不可用 (venv 可能不完整)"
        VENV_VALID=false
    fi

    if $VENV_VALID; then
        info "虚拟环境有效，复用: $BROCA_VENV"
        BROCA_PYTHON="$BROCA_VENV/bin/python"
        BROCA_PIP="$BROCA_PYTHON -m pip"
    else
        warn "虚拟环境不完整，将重新创建..."
        rm -rf "$BROCA_VENV"
        info "创建 broca 专属虚拟环境: $BROCA_VENV"
        $PYTHON -m venv "$BROCA_VENV" || {
            error "虚拟环境创建失败"
            exit 1
        }
        info "虚拟环境创建成功"
        BROCA_PYTHON="$BROCA_VENV/bin/python"
        BROCA_PIP="$BROCA_PYTHON -m pip"
        info "使用虚拟环境 Python: $($BROCA_PYTHON --version)"
    fi
else
    # 创建 broca 专属虚拟环境
    info "创建 broca 专属虚拟环境: $BROCA_VENV"
    $PYTHON -m venv "$BROCA_VENV" || {
        error "虚拟环境创建失败"
        exit 1
    }
    info "虚拟环境创建成功"
    BROCA_PYTHON="$BROCA_VENV/bin/python"
    BROCA_PIP="$BROCA_PYTHON -m pip"
    info "使用虚拟环境 Python: $($BROCA_PYTHON --version)"
fi

# 验证虚拟环境中 pip 可用；若缺失则用 ensurepip 补齐
# （某些 Linux 发行版若缺 python3-venv/python3-pip 包，python -m venv 创建的 venv 不含 pip）
if ! $BROCA_PIP --version &>/dev/null; then
    info "虚拟环境缺少 pip，尝试使用 ensurepip 补齐..."
    $BROCA_PYTHON -m ensurepip --upgrade 2>&1 || {
        error "虚拟环境 pip 创建失败"
        exit 1
    }
    if ! $BROCA_PIP --version &>/dev/null; then
        error "虚拟环境 pip 仍不可用"
        exit 1
    fi
    info "pip 已通过 ensurepip 补齐: $($BROCA_PIP --version | awk '{print $2}')"
fi

# 升级 pip
info "升级 pip..."
PIP_OUTPUT=$($BROCA_PIP install --upgrade pip setuptools wheel build 2>&1) || {
    error "pip 升级失败"
    echo "$PIP_OUTPUT"
    exit 1
}
echo "$PIP_OUTPUT" | { grep -v -E "^$|Requirement already" || true; }

# 安装 broca 模块
info "安装 broca 模块..."
PIP_OUTPUT=$($BROCA_PIP install "$PROJECT_ROOT" 2>&1) || {
    error "broca 模块安装失败"
    echo "$PIP_OUTPUT"
    exit 1
}
echo "$PIP_OUTPUT" | { grep -v -E "^$|Requirement already" || true; }

# 安装 supervisor (用于进程管理)
info "安装 supervisor..."
PIP_OUTPUT=$($BROCA_PIP install supervisor 2>&1) || {
    error "supervisor 安装失败"
    echo "$PIP_OUTPUT"
    exit 1
}
echo "$PIP_OUTPUT" | { grep -v -E "^$|Requirement already" || true; }

# 安装后端（broca-web/backend）依赖到虚拟环境
info "安装后端依赖..."
if PIP_OUTPUT=$($BROCA_PIP install "$PROJECT_ROOT/broca-web/backend" 2>&1); then
    echo "$PIP_OUTPUT" | { grep -v -E "^$|Requirement already|poetry.core" || true; }
    info "后端依赖安装完成"
else
    echo "$PIP_OUTPUT" | tail -10
    warn "后端依赖安装失败，可之后手动执行: $BROCA_PIP install $PROJECT_ROOT/broca-web/backend"
fi

# 将后续所有 $PYTHON 指向（虚拟环境的）Python
PYTHON="$BROCA_PYTHON"

# 安装 TUI（broca-tui）
if [[ -d "$PROJECT_ROOT/broca-tui" ]]; then
    info "安装 TUI 依赖..."
    if PIP_OUTPUT=$($BROCA_PIP install "$PROJECT_ROOT/broca-tui" 2>&1); then
        echo "$PIP_OUTPUT" | { grep -v -E "^$|Requirement already" || true; }
        info "TUI 依赖安装完成"
    else
        echo "$PIP_OUTPUT" | tail -10
        warn "TUI 依赖安装失败（broca-tui 目录存在但 pip install 出错）"
        warn "可之后手动执行: $BROCA_PIP install $PROJECT_ROOT/broca-tui"
    fi
else
    warn "broca-tui 目录不存在 (未找到 $PROJECT_ROOT/broca-tui)，跳过 TUI 安装"
    warn "如需使用 TUI，请确保 broca-tui 目录存在并手动执行:"
    warn "  $BROCA_PIP install $PROJECT_ROOT/broca-tui"
fi

info "broca 模块安装完成。"

# ============================================================================
# Step 3: 数据库迁移
# ============================================================================
step "Step 3/9: 数据库迁移..."

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
if ALEMBIC_OUTPUT=$(BROCA_DATABASE_DIR="$BROCA_DB_DIR" $PYTHON -m alembic -c broca/alembic.ini upgrade head 2>&1); then
    echo "$ALEMBIC_OUTPUT" | tail -5
    info "broca 主数据库迁移完成"
else
    echo "$ALEMBIC_OUTPUT" | tail -10
    warn "broca 主数据库迁移失败（可之后手动执行: alembic -c broca/alembic.ini upgrade head）"
fi

# ---- 迁移2: 后端数据库 ----
info "迁移后端数据库..."
cd "$PROJECT_ROOT/broca-web/backend"
if ALEMBIC_OUTPUT=$(SQLITE_DATABASE_PATH="sqlite:///${BACKEND_DB_PATH}" $PYTHON -m alembic upgrade head 2>&1); then
    echo "$ALEMBIC_OUTPUT" | tail -5
    info "后端数据库迁移完成"
else
    echo "$ALEMBIC_OUTPUT" | tail -10
    warn "后端数据库迁移失败（可之后手动执行: alembic upgrade head）"
fi

cd "$PROJECT_ROOT"

echo ""

# ============================================================================
# 配置 LLM
# ============================================================================
echo ""
echo "  配置文件"
echo "  ────────────────────────────────────────────"
echo "  configs.json   → $BROCA_HOME/configs/configs.json"
echo "  llm_config.json → $BROCA_HOME/configs/llm_config.json"
echo ""
echo "  首次安装会自动创建用户配置副本，之后你可安全地编辑它们。"
echo "  单个 LLM Key 也可通过环境变量覆盖:"
echo "    export BROCA_API_KEY_{PROVIDER}=\"your-key\""
echo "  ────────────────────────────────────────────"
echo ""

# ---- 复制 configs.json ----
mkdir -p "$BROCA_HOME/configs"
CONFIG_DST="$BROCA_HOME/configs/configs.json"
CONFIG_SRC="$PROJECT_ROOT/configs/configs.json"

if [[ ! -f "$CONFIG_DST" ]]; then
    if [[ -f "$CONFIG_SRC" ]]; then
        cp "$CONFIG_SRC" "$CONFIG_DST"
        # 将路径改为指向 ~/.broca/
        sed_inplace "s|\"database_dir\":.*|\"database_dir\": \"$BROCA_HOME/data\",|" "$CONFIG_DST"
        sed_inplace "s|\"llm_config_file\":.*|\"llm_config_file\": \"$BROCA_HOME/configs/llm_config.json\",|" "$CONFIG_DST"
        sed_inplace "s|\"log_file\":.*|\"log_file\": \"$BROCA_HOME/logs/agent.log\"|" "$CONFIG_DST"
        info "已创建用户配置: $CONFIG_DST"
    else
        warn "未找到默认配置: $CONFIG_SRC"
    fi
else
    info "用户配置已存在: ${CONFIG_DST}（跳过）"
fi

# ---- 复制 llm_config.json ----
LLM_DST="$BROCA_HOME/configs/llm_config_template.json"
LLM_CONFIG="$BROCA_HOME/configs/llm_config.json"
LLM_SRC="$PROJECT_ROOT/configs/llm_config_template.json"

cp "$LLM_SRC" "$LLM_DST"

if [[ ! -f "$LLM_CONFIG" ]]; then
    cp "$LLM_SRC" "$LLM_CONFIG"
    info "已创建用户 LLM 配置: $LLM_CONFIG"
else
    info "用户 LLM 配置已存在: ${LLM_CONFIG}（跳过）"
fi

# ---- 复制 Agent 配置 ----
AGENTS_SRC="$PROJECT_ROOT/configs/agents"
AGENTS_DST="$BROCA_HOME/configs/agents"

if [[ -d "$AGENTS_SRC" ]]; then
    mkdir -p "$AGENTS_DST"
    cp -r "$AGENTS_SRC/"* "$AGENTS_DST/" 2>/dev/null
    info "Agent 配置已更新: $AGENTS_DST"
else
    warn "未找到 Agent 配置目录: $AGENTS_SRC"
fi

# ---- 复制 tool_permission_config.json ----
PERM_DST="$BROCA_HOME/configs/tool_permission_config.json"
PERM_SRC="$PROJECT_ROOT/configs/tool_permission_config.json"

if [[ -f "$PERM_SRC" ]]; then
    cp "$PERM_SRC" "$PERM_DST"
    info "已创建工具权限配置: $PERM_DST"
else
    warn "未找到默认工具权限配置: $PERM_SRC"
fi

# ---- 复制 Skills ----
SKILLS_DST="$BROCA_HOME/skills"
SKILLS_SRC="$PROJECT_ROOT/skills"

if [[ -d "$SKILLS_SRC" ]]; then
    mkdir -p "$SKILLS_DST"
    rsync -a --delete "$SKILLS_SRC/" "$SKILLS_DST/" 2>/dev/null || cp -r "$SKILLS_SRC"/* "$SKILLS_DST/"
    info "Skills 已部署: $SKILLS_DST"
else
    warn "未找到 Skills 目录: $SKILLS_SRC"
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
# Step 5: 配置文件上传存储 (交互式)
# ============================================================================
if $SKIP_FRONTEND; then
    info "跳过前端配置（未部署 nginx）"
    echo ""
else
step "Step 4/9: 配置文件上传存储..."

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
                    sed_inplace -e '/^VITE_SUPABASE_URL=/d; /^VITE_SUPABASE_S3_ACCESS_KEY_ID=/d; /^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=/d; /^VITE_SUPABASE_BUCKET=/d; /^VITE_CLOUDFLARE_/d' "$ENV_FILE"
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
                    sed_inplace -e '/^VITE_CLOUDFLARE_/d; /^VITE_SUPABASE_URL=/d; /^VITE_SUPABASE_S3_ACCESS_KEY_ID=/d; /^VITE_SUPABASE_S3_SECRET_ACCESS_KEY=/d; /^VITE_SUPABASE_BUCKET=/d' "$ENV_FILE"
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
sed_inplace -e '/^VITE_API_BASE_URL=/d' "$ENV_FILE"
echo "# VITE_API_BASE_URL=" >> "$ENV_FILE"
sed_inplace -e '/^VITE_BROCA_SOCKET_SERVER_URL=/d' "$ENV_FILE"
echo "# VITE_BROCA_SOCKET_SERVER_URL=" >> "$ENV_FILE"

echo ""
fi  # SKIP_FRONTEND

# ============================================================================
# Step 6: 安装前端依赖并构建
# ============================================================================
if $SKIP_FRONTEND; then
    info "跳过前端构建（未部署 nginx）"
else
step "Step 5/9: 安装前端依赖并构建..."

if [[ ! -d "$FRONTEND_DIR" ]]; then
    error "前端目录不存在: $FRONTEND_DIR"
    exit 1
fi

cd "$FRONTEND_DIR"

if $USE_PNPM; then
    info "使用 pnpm v$PNPM_MAJOR_VERSION 安装前端依赖..."
    # 根据 pnpm 版本写入对应的 build 权限配置
    write_pnpm_build_config "$FRONTEND_DIR" "$PNPM_MAJOR_VERSION"
    # 删除旧锁文件，确保 pnpm 重新解析并应用 build 权限配置
    rm -f pnpm-lock.yaml
    if ! BUILD_OUTPUT=$(pnpm install 2>&1); then
        error "pnpm install 失败"
        echo "$BUILD_OUTPUT"
        exit 1
    fi
    echo "$BUILD_OUTPUT" | tail -5
else
    # 尝试安装 pnpm（项目使用 pnpm-lock.yaml，npm 可能无法正确解析依赖树）
    info "正在安装 pnpm (项目依赖 pnpm 管理)..."
    if BUILD_OUTPUT=$(npm install -g pnpm 2>&1); then
        USE_PNPM=true
        PNPM_MAJOR_VERSION=$(pnpm --version | cut -d. -f1)
        info "pnpm v$PNPM_MAJOR_VERSION 安装成功，使用 pnpm 安装前端依赖..."
        # 根据 pnpm 版本写入对应的 build 权限配置
        write_pnpm_build_config "$FRONTEND_DIR" "$PNPM_MAJOR_VERSION"
        # 删除旧锁文件，确保 pnpm 重新解析并应用 build 权限配置
        rm -f pnpm-lock.yaml
        if ! BUILD_OUTPUT=$(pnpm install 2>&1); then
            error "pnpm install 失败"
            echo "$BUILD_OUTPUT"
            exit 1
        fi
        echo "$BUILD_OUTPUT" | tail -5
    else
        warn "pnpm 安装失败，回退到 npm (使用 --legacy-peer-deps)..."
        echo "$BUILD_OUTPUT" | tail -3
        if ! BUILD_OUTPUT=$(npm install --legacy-peer-deps 2>&1); then
            error "npm install 失败"
            echo "$BUILD_OUTPUT"
            exit 1
        fi
        echo "$BUILD_OUTPUT" | tail -5
    fi
fi

info "构建前端 (production mode, 加载 .env.production)..."
if ! BUILD_OUTPUT=$(npx vite build 2>&1); then
    error "前端构建失败"
    echo "$BUILD_OUTPUT"
    exit 1
fi
echo "$BUILD_OUTPUT" | tail -10
info "前端构建完成: $FRONTEND_DIR/dist"
fi  # SKIP_FRONTEND

# ============================================================================
# Step 7: 打包 VS Code 插件（需要 Node.js）
# ============================================================================
if $HAS_NODE; then
step "Step 6/9: 打包 VS Code 插件..."

VSCODE_DIR="$PROJECT_ROOT/broca-vscode"
if [[ -d "$VSCODE_DIR" ]]; then
    cd "$VSCODE_DIR"
    info "使用 npm 安装 VS Code 插件依赖..."
    if ! BUILD_OUTPUT=$(npm install 2>&1); then
        warn "npm install 失败: $BUILD_OUTPUT"
    else
        info "打包 VS Code 插件..."
        if ! BUILD_OUTPUT=$(npm run package 2>&1); then
            warn "VS Code 插件打包失败: $BUILD_OUTPUT"
        else
            VSIX_FILE=$(ls -t "$VSCODE_DIR"/*.vsix 2>/dev/null | head -1 || true)
            if [[ -n "$VSIX_FILE" ]]; then
                info "VS Code 插件已打包: $VSIX_FILE"
            else
                warn "未找到生成的 .vsix 文件"
            fi
        fi
    fi
else
    warn "未找到 VS Code 插件目录: $VSCODE_DIR"
fi

else
    warn "跳过 VS Code 插件打包（未检测到 Node.js）"
fi

# ============================================================================
# Step 8: 部署前端
# ============================================================================
if $SKIP_FRONTEND; then
    if $HAS_NODE; then
        info "跳过前端部署（未安装 nginx）"
    else
        info "跳过前端部署和 VS Code 插件打包（未检测到 Node.js）"
    fi
    echo "  提示: 可使用 VS Code 插件连接后端服务"
    echo "  后端服务端口: 9000"
else
step "Step 7/9: 配置前端部署方式..."

mkdir -p "$BROCA_HOME"

info "配置 nginx 站点..."

if $IS_MACOS; then
    # macOS: Homebrew nginx 以 _www 用户运行，家目录默认不可读
    # 需要设置权限让 nginx 能访问前端静态文件
    NGINX_DIST_DIR="$BROCA_HOME/frontend-dist"
    mkdir -p "$NGINX_DIST_DIR"
    cp -r "$FRONTEND_DIR/dist/"* "$NGINX_DIST_DIR/"
    # 让 _www 用户可以读取前端文件（o+x 可遍历目录，o+r 可读文件）
    chmod o+x "$HOME"
    chmod o+x "$BROCA_HOME" 2>/dev/null || true
    chmod -R o+rX "$NGINX_DIST_DIR"
    info "前端静态文件已部署到: $NGINX_DIST_DIR"
else
    # Linux: nginx 以 www-data 运行，家目录不可读，放到系统路径
    NGINX_DIST_DIR="/var/www/broca/frontend"
    echo ""
    echo "  注意：nginx 以 $NGINX_USER 用户运行，不能读取 ~/.broca/ 下的文件。"
    echo "  静态文件将部署到 $NGINX_DIST_DIR"
    echo ""

    if command -v sudo &>/dev/null; then
        sudo mkdir -p "$NGINX_DIST_DIR"
        sudo cp -r "$FRONTEND_DIR/dist/"* "$NGINX_DIST_DIR/"
        sudo chown -R "${NGINX_USER}:${NGINX_USER}" "$NGINX_DIST_DIR" 2>/dev/null || true
        info "前端静态文件已部署到: $NGINX_DIST_DIR"
    else
        warn "未找到 sudo，请手动复制前端文件:"
        echo "    sudo mkdir -p $NGINX_DIST_DIR"
        echo "    sudo cp -r $FRONTEND_DIR/dist/* $NGINX_DIST_DIR/"
        echo "    sudo chown -R ${NGINX_USER}:${NGINX_USER} $NGINX_DIST_DIR"
        # 回退到 ~/.broca/
        NGINX_DIST_DIR="$BROCA_HOME/frontend-dist"
        mkdir -p "$NGINX_DIST_DIR"
        cp -r "$FRONTEND_DIR/dist/"* "$NGINX_DIST_DIR/"
        warn "已回退部署到 $NGINX_DIST_DIR"
        echo "  如遇权限错误，运行: chmod o+x ~ ~/.broca $NGINX_DIST_DIR"
    fi
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

    # 验证 nginx 配置语法（使用 sudo -n 避免非交互环境挂起）
    info "验证 nginx 配置语法..."
    if sudo -n nginx -t 2>&1; then
        info "nginx 配置语法正确"
    elif sudo nginx -t 2>&1; then
        info "nginx 配置语法正确"
    else
        warn "nginx 配置语法有误，请检查: sudo nginx -t"
    fi

    # 仅生成配置，不启用站点（用户通过 broca service start 启用）
    info "nginx 前端配置就绪（未启用，执行 broca service start 后启用）"
    echo ""
    echo "  可用命令:"
    echo "    broca service start      # 创建 symlink + reload nginx，启用前端"
    echo "    broca service stop       # 删除 symlink + reload nginx，停用前端"
fi  # SKIP_FRONTEND

# ============================================================================
# Step 9: 创建 supervisor 配置
# ============================================================================
step "Step 8/9: 创建 supervisor 进程管理配置..."

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
command=$BROCA_VENV/bin/uvicorn app.main:app --host $BACKEND_HOST --port 9000 --log-level info
directory=$BROCA_WEB_DIR/backend
user=$USER
autostart=true
autorestart=true
startretries=3
stderr_logfile=$LOG_DIR/backend.err.log
stdout_logfile=$LOG_DIR/backend.out.log
stdout_logfile_maxbytes=20MB
stderr_logfile_maxbytes=20MB
environment=PYTHONPATH="$BROCA_WEB_DIR/backend",BROCA_CONFIG="$BROCA_HOME/configs/configs.json",BROCA_DATABASE_DIR="$BROCA_HOME/data",BROCA_LLM_CONFIG="$BROCA_HOME/configs/llm_config.json",BROCA_AGENTS_CONFIG_DIR="$BROCA_HOME/configs/agents",BROCA_LOG_DIR="$BROCA_HOME/logs",SQLITE_DATABASE_PATH="sqlite:///${BROCA_HOME}/data/backend.db"
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
# Step 10: 配置持久化 & 收尾
# ============================================================================
step "Step 9/9: 完成安装..."

# 保存安装信息到 broca home
cat > "$BROCA_HOME/install.json" << JSONEOF
{
  "version": "0.1.0",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "python": "$($PYTHON --version 2>&1)",
  "python_path": "$BROCA_PYTHON",
  "venv_path": "$BROCA_VENV",
  "project_root": "$PROJECT_ROOT",
  "has_node": $HAS_NODE,
  "frontend_mode": $([ "$SKIP_FRONTEND" = true ] && echo '"none"' || echo '"nginx"'),
  "frontend_dist": "$FRONTEND_DIR/dist",
  "nginx_dist_dir": "$NGINX_DIST_DIR",
  "storage_configured": $([ -f "$ENV_FILE" ] && grep -qE '^VITE_(CLOUDFLARE_ACCOUNT_ID|SUPABASE_URL)=' "$ENV_FILE" && echo "true" || echo "false"),
  "backend_port": 9000,
  "frontend_port": $([ "$SKIP_FRONTEND" = true ] && echo 'null' || echo '5166'),
  "skip_frontend": $SKIP_FRONTEND
}
JSONEOF

# 创建 broca 命令软链接到 PATH 中的目录
BROCA_BIN="$BROCA_VENV/bin/broca"
BROCA_LINK_CREATED=false

# 优先选择可写入且已在 PATH 中的目录
for link_dir in "${HOME}/.local/bin" "${HOME}/bin"; do
    if [[ ":$PATH:" == *":$link_dir:"* ]] && [[ -d "$link_dir" ]]; then
        if ln -sf "$BROCA_BIN" "$link_dir/broca" 2>/dev/null; then
            info "broca 命令已链接到: $link_dir/broca"
            BROCA_LINK_CREATED=true
            break
        fi
    fi
done

# 如果 ~/.local/bin 不在 PATH 但 macOS 上常见 Homebrew 路径在 PATH 中
# 则创建 ~/.local/bin 并提示用户添加到 shell 配置
if ! $BROCA_LINK_CREATED; then
    LOCAL_BIN="${HOME}/.local/bin"
    mkdir -p "$LOCAL_BIN"
    if ln -sf "$BROCA_BIN" "$LOCAL_BIN/broca" 2>/dev/null; then
        if [[ ":$PATH:" == *":$LOCAL_BIN:"* ]]; then
            info "broca 命令已链接到: $LOCAL_BIN/broca"
            BROCA_LINK_CREATED=true
        else
            warn "broca 命令已安装到 $LOCAL_BIN/broca，但该目录不在 PATH 中"
            echo "  请将该目录添加到 PATH："
            if $IS_MACOS; then
                echo "    echo 'export PATH=\"\$PATH:$LOCAL_BIN\"' >> ~/.zshrc"
                echo "    source ~/.zshrc"
            else
                echo "    echo 'export PATH=\"\$PATH:$LOCAL_BIN\"' >> ~/.bashrc"
                echo "    source ~/.bashrc"
            fi
            echo ""
            echo "  或者直接使用完整路径运行: $BROCA_BIN"
            BROCA_LINK_CREATED=true  # 文件已创建，只是不在 PATH 中
        fi
    fi
fi

if ! $BROCA_LINK_CREATED; then
    warn "无法创建 broca 软链接，请手动添加到 PATH"
    echo "  请执行以下命令之一:"
    echo "    export PATH=\"\$PATH:$BROCA_VENV/bin\"    # 临时生效"
    if $IS_MACOS; then
        echo "    echo 'export PATH=\"\$PATH:$BROCA_VENV/bin\"' >> ~/.zshrc  # 永久生效"
    else
        echo "    echo 'export PATH=\"\$PATH:$BROCA_VENV/bin\"' >> ~/.bashrc  # 永久生效"
    fi
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Broca 安装完成！${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  虚拟环境:   $BROCA_VENV"
echo "  broca 命令: $BROCA_VENV/bin/broca"
echo "  日志目录:   $LOG_DIR"

if $SKIP_FRONTEND; then
    if $HAS_NODE; then
        echo "  前端:       未部署（未安装 nginx）"
        echo "  后端端口:   9000"
        echo ""
        echo "  快速开始:"
        echo "    broca service start      # 启动后端服务"
        echo "    broca service stop       # 停止后端服务"
        echo "    broca service status     # 查看服务状态"
        echo ""
        echo "  访问后端 API: http://localhost:9000"
        echo "  如需前端页面，请安装 VS Code 插件或重新安装 nginx 后运行:"
        echo "    sudo apt install nginx   # Ubuntu"
        echo "    brew install nginx       # macOS"
        echo "    broca service install    # 重新安装以启用前端"
    else
        echo "  前端:       未部署（未检测到 Node.js）"
        echo "  VS Code 插件: 未打包（需要 Node.js）"
        echo "  后端端口:   9000"
        echo ""
        echo "  快速开始:"
        echo "    broca service start      # 启动后端服务"
        echo "    broca service stop       # 停止后端服务"
        echo "    broca service status     # 查看服务状态"
        echo ""
        echo "  访问后端 API: http://localhost:9000"
        echo "  如需前端页面或 VS Code 插件，请安装 Node.js 后重新运行:"
        echo "    broca service install    # 重新安装"
    fi
else
    echo "  前端模式:   nginx"
    if [[ -f "$ENV_FILE" ]] && grep -qE '^VITE_(CLOUDFLARE_ACCOUNT_ID|SUPABASE_URL)=' "$ENV_FILE" 2>/dev/null; then
        echo "  文件存储:   ✅ 已配置"
    else
        echo -e "  文件存储:   ${YELLOW}⚠ 未配置${NC} (编辑 ${ENV_FILE} 后重新构建)"
    fi
    echo ""
    echo "  nginx 前端配置文件已就绪: $NGINX_SITE_CONF"
    echo ""
    echo "  快速开始:"
    echo "    broca service start      # 启动所有服务（后端 + 启用前端站点）"
    echo "    broca service stop       # 停止所有服务"
    echo "    broca service status     # 查看服务状态"
    echo "    broca web                # 启动开发模式 (前后端同时启动)"
    echo ""
    echo "  broca service start 后访问: http://localhost:5166"
fi

echo ""
echo "  如需手动激活虚拟环境:"
echo "    source $BROCA_VENV/bin/activate"
echo ""
