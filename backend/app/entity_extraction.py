from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


class EntityExtractionError(RuntimeError):
    pass


def extract_import_entities(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run the same entity extraction functions used by the review UI."""
    project_root = Path(__file__).resolve().parents[2]
    frontend_dir = project_root / "frontend"
    script = frontend_dir / "auto_import_extract.cjs"
    node = shutil.which("node")
    if node is None or not script.is_file() or not (frontend_dir / "node_modules" / "typescript").is_dir():
        raise EntityExtractionError("自动导入实体解析器不可用，请安装 Node.js 与前端依赖")

    try:
        result = subprocess.run(
            [node, str(script)],
            input=json.dumps({"documents": documents}, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=frontend_dir,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise EntityExtractionError(f"自动导入实体解析失败：{error}") from error
    if result.returncode != 0:
        detail = result.stderr.strip() or f"实体解析器退出码 {result.returncode}"
        raise EntityExtractionError(f"自动导入实体解析失败：{detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise EntityExtractionError("自动导入实体解析器返回了无效结果") from error
    if not isinstance(payload, list) or len(payload) != len(documents):
        raise EntityExtractionError("自动导入实体解析器返回的来源数量不匹配")
    return payload
