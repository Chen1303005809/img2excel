#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
UVICORN_BIN="${PROJECT_ROOT}/.venv/bin/uvicorn"

if [[ ! -x "${PYTHON_BIN}" || ! -x "${UVICORN_BIN}" ]]; then
  echo "未找到 Python 虚拟环境，请先执行：./.venv/bin/python -m pip install -r requirements-app.txt" >&2
  exit 1
fi

if [[ ! -x "${PROJECT_ROOT}/frontend/node_modules/.bin/vite" ]]; then
  echo "未找到前端依赖，请先执行：cd frontend && npm install" >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

child_pids=()

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  for pid in "${child_pids[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
  for pid in "${child_pids[@]}"; do
    wait "${pid}" 2>/dev/null || true
  done

  exit "${exit_code}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "启动后端：http://127.0.0.1:8000"
"${UVICORN_BIN}" backend.app.main:app --host 127.0.0.1 --port 8000 &
child_pids+=("$!")

echo "启动 Worker"
"${PYTHON_BIN}" -m backend.worker &
child_pids+=("$!")

echo "启动前端：http://127.0.0.1:5173"
(
  cd "${PROJECT_ROOT}/frontend"
  exec npm run dev -- --host 127.0.0.1 --port 5173
) &
child_pids+=("$!")

echo "系统已启动，按 Ctrl-C 停止全部服务。"

# macOS 自带 Bash 不支持 wait -n，因此用轮询兼容 Bash 3.2。
while true; do
  for pid in "${child_pids[@]}"; do
    if ! kill -0 "${pid}" 2>/dev/null; then
      wait "${pid}" 2>/dev/null || true
      echo "进程 ${pid} 已退出，正在停止其他服务。" >&2
      exit 1
    fi
  done
  sleep 1
done
