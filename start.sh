#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'USAGE'
用法：./start.sh [--check]

  --check    只检查运行环境，不启动服务
USAGE
  exit 0
fi

if [[ "$#" -gt 0 && "${1}" != "--check" ]]; then
  echo "用法：$0 [--check]" >&2
  exit 2
fi

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

cd "${PROJECT_ROOT}"

if ! PYTHON_BIN="$(command -v python)" || [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "未找到当前环境的 Python 解释器。" >&2
  echo "请先激活已安装项目依赖的 Conda 环境。" >&2
  exit 1
fi

if ! NODE_BIN="$(command -v node)"; then
  echo "未找到 Node.js，请安装 Node.js 20+。" >&2
  exit 1
fi

if ! NPM_BIN="$(command -v npm)"; then
  echo "未找到 npm，请安装 Node.js 20+。" >&2
  exit 1
fi

if ! "${NODE_BIN}" -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 20 ? 0 : 1)'; then
  echo "Node.js 版本过低，需要 Node.js 20+：$(${NODE_BIN} --version)" >&2
  exit 1
fi

if [[ ! -x "${PROJECT_ROOT}/frontend/node_modules/.bin/vite" ]]; then
  echo "未找到前端依赖，请先执行：cd frontend && npm install" >&2
  exit 1
fi

echo "检查 Python/Crawl4AI/Chromium 运行环境。"
if ! "${PYTHON_BIN}" - <<'PY'
import asyncio
import importlib
import os
import sys
from pathlib import Path

from backend.app.config import Settings

settings = Settings()
data_dir = settings.resolved_data_dir
data_dir.mkdir(parents=True, exist_ok=True)
crawl_dir = data_dir / ".crawl4ai"
crawl_dir.mkdir(parents=True, exist_ok=True)
os.environ["CRAWL4_AI_BASE_DIRECTORY"] = str(crawl_dir)

required_modules = (
    "uvicorn",
    "fastapi",
    "sqlalchemy",
    "alembic",
    "crawl4ai",
    "playwright",
    "rapidocr",
)
missing = []
for module_name in required_modules:
    try:
        importlib.import_module(module_name)
    except Exception as error:
        missing.append(f"{module_name}: {error}")

if missing:
    print("Python 依赖检查失败：", file=sys.stderr)
    for item in missing:
        print(f"  - {item}", file=sys.stderr)
    raise SystemExit(1)

from playwright.async_api import async_playwright


async def check_browser() -> None:
    async with async_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        print(f"Python: {sys.executable}")
        print(f"Crawl4AI 数据目录: {crawl_dir}")
        print(f"Chromium: {executable}")
        if not executable.is_file():
            raise RuntimeError(
                "未找到 Playwright Chromium，请执行："
                " crawl4ai-setup"
            )


asyncio.run(check_browser())
print("Python/Crawl4AI/Chromium 检查通过。")
PY
then
  echo "运行环境检查失败。" >&2
  exit 1
fi

if [[ "${1:-}" == "--check" ]]; then
  echo "全部运行环境检查通过。"
  exit 0
fi

child_pids=()
child_names=()

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

start_service() {
  local service_name="$1"
  shift
  echo "启动 ${service_name}"
  "$@" &
  child_names+=("${service_name}")
  child_pids+=("$!")
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "后端地址：http://${IMAGE_TABLE_BACKEND_HOST}:${IMAGE_TABLE_BACKEND_PORT}"
start_service "后端" "${PYTHON_BIN}" -m uvicorn backend.app.main:app --host "${IMAGE_TABLE_BACKEND_HOST}" --port "${IMAGE_TABLE_BACKEND_PORT}"
start_service "Worker" "${PYTHON_BIN}" -m backend.worker
echo "前端地址：http://${IMAGE_TABLE_FRONTEND_HOST}:${IMAGE_TABLE_FRONTEND_PORT}"
(
  cd "${PROJECT_ROOT}/frontend"
  exec "${NPM_BIN}" run dev
) &
child_names+=("前端")
child_pids+=("$!")

echo "系统已启动，按 Ctrl-C 停止全部服务。"

# macOS 自带 Bash 不支持 wait -n，因此用轮询兼容 Bash 3.2。
while true; do
  for index in "${!child_pids[@]}"; do
    pid="${child_pids[${index}]}"
    if ! kill -0 "${pid}" 2>/dev/null; then
      if wait "${pid}"; then
        exit_code=0
      else
        exit_code=$?
      fi
      echo "服务 ${child_names[${index}]} (PID ${pid}) 已退出，退出码：${exit_code}。正在停止其他服务。" >&2
      exit "${exit_code:-1}"
    fi
  done
  sleep 1
done
