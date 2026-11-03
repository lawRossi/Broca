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

BACKEND_PID=""

# === 启动前清理：杀掉占用端口的旧进程 ===
echo "[cleanup] 检查并清理旧进程..."
# 杀占用后端端口的进程
OLD_BACKEND=$(lsof -ti :"$BACKEND_PORT" 2>/dev/null || true)
if [[ -n "$OLD_BACKEND" ]]; then
    echo "[cleanup] 杀掉旧后端 PID: $OLD_BACKEND"
    kill $OLD_BACKEND 2>/dev/null
    sleep 1
    kill -9 $OLD_BACKEND 2>/dev/null
fi
# 杀占用前端端口的进程（vite 残留）
OLD_FRONTEND=$(lsof -ti :"$FRONTEND_PORT" 2>/dev/null || true)
if [[ -n "$OLD_FRONTEND" ]]; then
    echo "[cleanup] 杀掉旧前端 PID: $OLD_FRONTEND"
    kill $OLD_FRONTEND 2>/dev/null
    sleep 1
    kill -9 $OLD_FRONTEND 2>/dev/null
fi
# 杀 SocketIO 端口的残留
SOCKETIO_PORT=$(grep -m1 '^BROCA_SOCKETIO_PORT=' "$BACKEND_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "6868")
OLD_SIO=$(lsof -ti :"$SOCKETIO_PORT" 2>/dev/null || true)
if [[ -n "$OLD_SIO" ]]; then
    echo "[cleanup] 杀掉旧 SocketIO PID: $OLD_SIO"
    kill $OLD_SIO 2>/dev/null
    sleep 1
    kill -9 $OLD_SIO 2>/dev/null
fi
# 杀本 worktree 的 runner 子进程（按 workspace 路径匹配，避免误杀其他项目的 runner）
OLD_RUNNERS=$(ps aux | grep "session_runner.runner" | grep "$PROJECT_ROOT" | awk '{print $2}' || true)
if [[ -n "$OLD_RUNNERS" ]]; then
    echo "[cleanup] 杀掉旧 runner: $OLD_RUNNERS"
    pkill -TERM -f "session_runner.runner.*$PROJECT_ROOT" 2>/dev/null
    sleep 2
    pkill -KILL -f "session_runner.runner.*$PROJECT_ROOT" 2>/dev/null
fi
echo "[cleanup] 完成"
echo ""

cleanup() {
    trap - SIGINT SIGTERM  # 防止递归
    echo ""
    echo "正在停止服务..."

    # 停止前端：先杀子进程（vite 是 pnpm/npm 的子进程），再杀 pnpm/npm 本身
    if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        pkill -TERM -P "$FRONTEND_PID" 2>/dev/null
        kill -TERM "$FRONTEND_PID" 2>/dev/null
        # 等待最多 3 秒
        for i in {1..6}; do
            kill -0 "$FRONTEND_PID" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$FRONTEND_PID" 2>/dev/null; then
            pkill -KILL -P "$FRONTEND_PID" 2>/dev/null
            kill -KILL "$FRONTEND_PID" 2>/dev/null
        fi
    fi

    # 停止后端：先 SIGTERM 给进程及其子进程，再 SIGKILL 兜底
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        # 杀掉后端的所有子进程（session_runner 等）
        pkill -TERM -P "$BACKEND_PID" 2>/dev/null
        kill -TERM "$BACKEND_PID" 2>/dev/null
        # 等待最多 3 秒
        for i in {1..6}; do
            kill -0 "$BACKEND_PID" 2>/dev/null || break
            sleep 0.5
        done
        # 如果还活着，强制杀
        if kill -0 "$BACKEND_PID" 2>/dev/null; then
            pkill -KILL -P "$BACKEND_PID" 2>/dev/null
            kill -KILL "$BACKEND_PID" 2>/dev/null
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
