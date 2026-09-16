#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

backend_host_was_set="${IMAGE_TABLE_BACKEND_HOST+x}"
backend_host_from_env="${IMAGE_TABLE_BACKEND_HOST-}"
backend_port_was_set="${IMAGE_TABLE_BACKEND_PORT+x}"
backend_port_from_env="${IMAGE_TABLE_BACKEND_PORT-}"
frontend_host_was_set="${IMAGE_TABLE_FRONTEND_HOST+x}"
frontend_host_from_env="${IMAGE_TABLE_FRONTEND_HOST-}"
frontend_port_was_set="${IMAGE_TABLE_FRONTEND_PORT+x}"
frontend_port_from_env="${IMAGE_TABLE_FRONTEND_PORT-}"

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${PROJECT_ROOT}/.env"
  set +a
fi

if [[ -n "${backend_host_was_set}" ]]; then IMAGE_TABLE_BACKEND_HOST="${backend_host_from_env}"; fi
if [[ -n "${backend_port_was_set}" ]]; then IMAGE_TABLE_BACKEND_PORT="${backend_port_from_env}"; fi
if [[ -n "${frontend_host_was_set}" ]]; then IMAGE_TABLE_FRONTEND_HOST="${frontend_host_from_env}"; fi
if [[ -n "${frontend_port_was_set}" ]]; then IMAGE_TABLE_FRONTEND_PORT="${frontend_port_from_env}"; fi

export IMAGE_TABLE_BACKEND_HOST="${IMAGE_TABLE_BACKEND_HOST:-127.0.0.1}"
export IMAGE_TABLE_BACKEND_PORT="${IMAGE_TABLE_BACKEND_PORT:-8000}"
export IMAGE_TABLE_FRONTEND_HOST="${IMAGE_TABLE_FRONTEND_HOST:-127.0.0.1}"
export IMAGE_TABLE_FRONTEND_PORT="${IMAGE_TABLE_FRONTEND_PORT:-5173}"

if ! command -v python >/dev/null 2>&1 || ! python -c 'import uvicorn' >/dev/null 2>&1; then
  echo "未找到默认 Python 解释器或 uvicorn，请先执行：python -m pip install -r requirements-app.txt" >&2
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

echo "启动后端：http://${IMAGE_TABLE_BACKEND_HOST}:${IMAGE_TABLE_BACKEND_PORT}"
python -m uvicorn backend.app.main:app --host "${IMAGE_TABLE_BACKEND_HOST}" --port "${IMAGE_TABLE_BACKEND_PORT}" &
child_pids+=("$!")

echo "启动 Worker"
python -m backend.worker &
child_pids+=("$!")

echo "启动前端：http://${IMAGE_TABLE_FRONTEND_HOST}:${IMAGE_TABLE_FRONTEND_PORT}"
(
  cd "${PROJECT_ROOT}/frontend"
  exec npm run dev
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
