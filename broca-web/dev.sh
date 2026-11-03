#!/usr/bin/env bash
# Broca Web 一键开发启动脚本
# 启动前端 (vite, :5177) + 后端 (uvicorn, :9001)
# Ctrl+C 停止所有服务
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"

# 确保能 import broca 包（worktree 场景下 venv 可能指向主目录）
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"

# 跳过 litellm 远程 model cost map 拉取（避免启动时 5s SSL 超时）
export LITELLM_LOCAL_MODEL_COST_MAP=true

# 获取端口（从 .env 读取，有默认值）
BACKEND_PORT=$(grep -m1 '^PORT=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "9001")
FRONTEND_PORT=$(grep -m1 '^VITE_DEV_PORT=' "$FRONTEND_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "5177")

echo "=========================================="
echo "  Broca Web Dev Server"
echo "  前端:  https://localhost:$FRONTEND_PORT"
echo "  后端:  http://localhost:$BACKEND_PORT"
echo "  SocketIO: http://localhost:$(grep -m1 '^BROCA_SOCKETIO_PORT=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "6666")"
echo "=========================================="
echo ""

# === 数据目录隔离检查 ===
# dev 实例绝不能读写 ~/.broca/data 下的生产数据库（sessions.db）。
# 隔离靠 BROCA_CONFIG 指向 configs.dev.json 实现，这里做启动前校验。
echo "[preflight] 检查数据目录隔离..."
# stderr 丢弃：dev 配置是 log_level=DEBUG，broca 初始化日志会污染输出
PREFLIGHT=$(cd "$BACKEND_DIR" && python - <<'PY' 2>/dev/null
from app.core.config import settings, check_data_dir_isolation
from broca.configs import get_configs

cfg = get_configs()
print("CONFIG_PATH=%s" % settings.broca_config_path)
print("DATABASE_DIR=%s" % cfg.database_dir)
print("LOG_DIR=%s" % cfg.log_dir)
print("SNAPSHOT_HOME=%s" % cfg.snapshot_home)
print("LEAKS=%s" % ", ".join(check_data_dir_isolation()))
PY
) || PREFLIGHT="PREFLIGHT_FAILED=1"

if grep -q '^PREFLIGHT_FAILED=1' <<<"$PREFLIGHT"; then
    echo "[preflight] ⚠ 无法解析配置，跳过隔离检查"
    echo "            手动排查: cd backend && python -c 'from app.core.config import settings; print(settings.broca_config_path)'"
else
    echo "$PREFLIGHT" | sed 's/^/           /'
    LEAKS=$(grep '^LEAKS=' <<<"$PREFLIGHT" | cut -d= -f2- || true)
    if [[ -n "$LEAKS" && "${BROCA_ALLOW_PROD_DATA:-0}" != "1" ]]; then
        echo ""
        echo "[preflight] ✗ 危险：dev 实例指向生产数据目录 —— $LEAKS"
        echo "            BROCA_CONFIG 应指向 ./configs.dev.json（见 backend/.env.example）"
        echo "            确认要共用生产数据时，用 BROCA_ALLOW_PROD_DATA=1 重新运行。"
        exit 1
    elif [[ -n "$LEAKS" ]]; then
        echo "[preflight] ⚠ 已允许共用生产数据目录：$LEAKS"
    else
        echo "[preflight] ✓ 数据目录已隔离"
    fi
fi
echo ""

# === 数据库迁移（幂等）===
# dev.sh 历史上从不迁移：迁移只在 scripts/install.sh 里做，而那只覆盖生产库
# (~/.broca/data/sessions.db)。dev 用 configs.dev.json 把数据目录隔离到
# backend/.local-data —— 全新目录下 sessions.db 不存在，SQLAlchemy 一连接就会
# 创建「0 表空文件」，随后启动时 restore_active_sessions() 直接报
#   sqlite3.OperationalError: no such table: session_runner
# 所以这里在启动前补一次迁移（已在 head 时是 no-op）。
#
# 目标库必须用 `-x db_url=` 显式传：broca/configs.py 与 app/core/config.py
# 都是纯文件驱动（不读 os.environ），环境变量在迁移期会被静默忽略；
# 裸 `alembic upgrade head` 会回退到仓库 configs/configs.json → 迁到生产库。
echo "[migrate] 检查数据库表结构..."
MIGRATE_TARGETS=$(cd "$BACKEND_DIR" && python - <<'PY' 2>/dev/null
from pathlib import Path

from app.core.config import settings
from broca.configs import get_configs

# sessions.db：与运行时同源（broca 的 database_dir）
cfg = get_configs()
sessions_db = (Path(cfg.database_dir).expanduser() / "sessions.db").resolve()

# backend.db：与运行时同源（settings.sqlite_database_path）。
# 相对路径以 backend/ 为基准 —— uvicorn 就是在 backend/ 下启动的。
raw = settings.sqlite_database_path
for prefix in ("sqlite:///", "sqlite://"):
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
        break
backend_db = Path(raw).expanduser()
if not backend_db.is_absolute():
    backend_db = (Path.cwd() / backend_db).resolve()

print(f"SESSIONS_DB={sessions_db}")
print(f"BACKEND_DB={backend_db}")
PY
) || MIGRATE_TARGETS=""

if [[ -z "$MIGRATE_TARGETS" ]]; then
    echo "[migrate] ⚠ 无法解析数据库路径，跳过迁移"
    echo "          若启动报 'no such table'，手动执行:"
    echo "          cd backend && python -m alembic -x \"db_url=sqlite:///\$PWD/dev.db\" upgrade head"
else
    SESSIONS_DB=$(grep '^SESSIONS_DB=' <<<"$MIGRATE_TARGETS" | cut -d= -f2- || true)
    BACKEND_DB=$(grep '^BACKEND_DB=' <<<"$MIGRATE_TARGETS" | cut -d= -f2- || true)
    echo "[migrate] sessions.db -> $SESSIONS_DB"
    echo "[migrate] backend.db  -> $BACKEND_DB"

    # 双保险：dev 实例不能把仓库里的新迁移静默应用到生产库
    if [[ "$SESSIONS_DB" == "$HOME/.broca/"* && "${BROCA_ALLOW_PROD_DATA:-0}" != "1" ]]; then
        echo "[migrate] ⚠ 目标库在生产目录下，跳过 sessions.db 迁移"
    else
        mkdir -p "$(dirname "$SESSIONS_DB")"
        if MIGRATE_OUT=$(python -m alembic -c "$PROJECT_ROOT/broca/alembic.ini" \
                -x "db_url=sqlite:///$SESSIONS_DB" upgrade head 2>&1); then
            tail -n 3 <<<"$MIGRATE_OUT" | sed 's/^/           /'
        else
            echo "$MIGRATE_OUT" | tail -n 10 | sed 's/^/           /'
            echo ""
            echo "[migrate] ✗ sessions.db 迁移失败（目标: $SESSIONS_DB）"
            echo "          没有表就无法使用 Web 会话功能。"
            exit 1
        fi
    fi

    mkdir -p "$(dirname "$BACKEND_DB")"
    if MIGRATE_OUT=$(cd "$BACKEND_DIR" && python -m alembic \
            -x "db_url=sqlite:///$BACKEND_DB" upgrade head 2>&1); then
        tail -n 3 <<<"$MIGRATE_OUT" | sed 's/^/           /'
    else
        echo "$MIGRATE_OUT" | tail -n 10 | sed 's/^/           /'
        echo ""
        echo "[migrate] ✗ backend.db 迁移失败（目标: $BACKEND_DB）"
        echo "          没有表就无法登录。"
        exit 1
    fi
    echo "[migrate] ✓ 表结构已就绪"
fi
echo ""

BACKEND_PID=""

# === 启动前清理：杀掉占用端口的旧进程 ===
# 注意：所有 kill/pkill 都带 `|| true`。脚本开了 `set -e`，而 kill 对
# 「已经退出的进程」返回 1 —— 旧后端收到 SIGTERM 后先退出，紧接着的
# `kill -9` 就会失败并让脚本**静默中止**（现象：日志停在"杀掉旧后端 PID"，
# 既不起后端也不报错）。
echo "[cleanup] 检查并清理旧进程..."
# 杀占用后端端口的进程
OLD_BACKEND=$(lsof -ti :"$BACKEND_PORT" 2>/dev/null || true)
if [[ -n "$OLD_BACKEND" ]]; then
    echo "[cleanup] 杀掉旧后端 PID: $OLD_BACKEND"
    kill $OLD_BACKEND 2>/dev/null || true
    sleep 1
    kill -9 $OLD_BACKEND 2>/dev/null || true
fi
# 杀占用前端端口的进程（vite 残留）
OLD_FRONTEND=$(lsof -ti :"$FRONTEND_PORT" 2>/dev/null || true)
if [[ -n "$OLD_FRONTEND" ]]; then
    echo "[cleanup] 杀掉旧前端 PID: $OLD_FRONTEND"
    kill $OLD_FRONTEND 2>/dev/null || true
    sleep 1
    kill -9 $OLD_FRONTEND 2>/dev/null || true
fi
# 杀 SocketIO 端口的残留
SOCKETIO_PORT=$(grep -m1 '^BROCA_SOCKETIO_PORT=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "6868")
OLD_SIO=$(lsof -ti :"$SOCKETIO_PORT" 2>/dev/null || true)
if [[ -n "$OLD_SIO" ]]; then
    echo "[cleanup] 杀掉旧 SocketIO PID: $OLD_SIO"
    kill $OLD_SIO 2>/dev/null || true
    sleep 1
    kill -9 $OLD_SIO 2>/dev/null || true
fi
# 杀本 worktree 的 runner 子进程（按 workspace 路径匹配，避免误杀其他项目的 runner）
OLD_RUNNERS=$(ps aux | grep "session_runner.runner" | grep "$PROJECT_ROOT" | awk '{print $2}' || true)
if [[ -n "$OLD_RUNNERS" ]]; then
    echo "[cleanup] 杀掉旧 runner: $OLD_RUNNERS"
    pkill -TERM -f "session_runner.runner.*$PROJECT_ROOT" 2>/dev/null || true
    sleep 2
    pkill -KILL -f "session_runner.runner.*$PROJECT_ROOT" 2>/dev/null || true
fi
echo "[cleanup] 完成"
echo ""

cleanup() {
    trap - SIGINT SIGTERM  # 防止递归
    echo ""
    echo "正在停止服务..."

    # 停止前端：先杀子进程（vite 是 pnpm/npm 的子进程），再杀 pnpm/npm 本身
    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        pkill -TERM -P "$FRONTEND_PID" 2>/dev/null || true
        kill -TERM "$FRONTEND_PID" 2>/dev/null || true
        # 等待最多 3 秒
        for i in {1..6}; do
            kill -0 "$FRONTEND_PID" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$FRONTEND_PID" 2>/dev/null; then
            pkill -KILL -P "$FRONTEND_PID" 2>/dev/null || true
            kill -KILL "$FRONTEND_PID" 2>/dev/null || true
        fi
    fi

    # 停止后端：先 SIGTERM 给进程及其子进程，再 SIGKILL 兜底
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        # 杀掉后端的所有子进程（session_runner 等）
        pkill -TERM -P "$BACKEND_PID" 2>/dev/null || true
        kill -TERM "$BACKEND_PID" 2>/dev/null || true
        # 等待最多 3 秒
        for i in {1..6}; do
            kill -0 "$BACKEND_PID" 2>/dev/null || break
            sleep 0.5
        done
        # 如果还活着，强制杀
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            pkill -KILL -P "$BACKEND_PID" 2>/dev/null || true
            kill -KILL "$BACKEND_PID" 2>/dev/null || true
        fi
    fi

    wait 2>/dev/null
    echo "已停止。"
    exit 0
}

trap cleanup SIGINT SIGTERM

# 启动后端
echo "[backend] 启动 uvicorn :$BACKEND_PORT ..."
cd "$BACKEND_DIR"
python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" --log-level info &
BACKEND_PID=$!
echo "[backend] PID=$BACKEND_PID"
echo ""

# 启动前端
echo "[frontend] 启动 vite :$FRONTEND_PORT ..."
cd "$FRONTEND_DIR"
pnpm dev 2>/dev/null || npm run dev &
FRONTEND_PID=$!
echo "[frontend] PID=$FRONTEND_PID"
echo ""

# 等待子进程（前台运行，Ctrl+C 触发 cleanup）
wait
