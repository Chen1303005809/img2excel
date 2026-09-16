# 网址抓图、图片转表格与历史对比系统

这是一个单机单用户的前后端分离应用：保存网页来源后，由本地 Worker 使用 Crawl4AI 抓取正文图片，复用 `image_to_rows.py` 识别为通用结构化表格，再生成 JSON、XLSX 和可编辑的网页预览。每次运行均保存独立产物，并与同一来源最近一次成功运行的原始 OCR 结果比较。

## 运行环境

- Python 3.12，使用仓库内的 `.venv`
- Node.js 20+
- Crawl4AI 所需的 Chromium 浏览器

首次安装依赖：

```bash
./.venv/bin/python -m pip install -r requirements-app.txt
CRAWL4_AI_BASE_DIRECTORY="$PWD/data/.crawl4ai" ./.venv/bin/crawl4ai-setup   # 如果本机还没有 Crawl4AI 浏览器
cd frontend && npm install
```

已有可用的 Crawl4AI 环境无需重复安装。设置 `CRAWL4_AI_BASE_DIRECTORY` 是为了让 Crawl4AI 的缓存和本地数据库跟随本项目的 `data/` 目录。

## 启动

推荐使用根目录启动入口一次启动后端、Worker 和前端：

```bash
./start.sh
```

也可以在仓库根目录分别启动三个进程：

```bash
./.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
./.venv/bin/python -m backend.worker
cd frontend && npm run dev
```

浏览器访问 <http://127.0.0.1:5173>。后端默认只绑定本机；应用第一次启动会通过 Alembic 建库并预置 804、805、970 三个 YAFCO 来源。数据库和运行产物默认写入 `data/`，可通过 `.env` 或 `IMAGE_TABLE_*` 环境变量调整。

关键配置：

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `IMAGE_TABLE_DATA_DIR` | `data` | SQLite 与运行产物目录 |
| `IMAGE_TABLE_WORKER_CONCURRENCY` | `1` | Worker 同时处理的运行数 |
| `IMAGE_TABLE_CRAWL_CONCURRENCY` | Worker 并发数 | 抓取信号量 |
| `IMAGE_TABLE_OCR_CONCURRENCY` | `1` | OCR 信号量，默认串行 |
| `IMAGE_TABLE_LEASE_SECONDS` | `900` | Worker 租约超时恢复时间 |
| `IMAGE_TABLE_ALLOW_PRIVATE_HOSTS` | `false` | 是否允许抓取本机/私有地址 |

## 业务流程

1. 来源页添加或停用网址，规范化后的 URL 保证同一来源不重复。
2. 点击“立即运行”，API 只创建 `queued` 记录；Worker 负责后续阶段。
3. Crawl4AI 按 `yafco_image` 页面配置等待 `.ya-con img`，从 `.ya-con img[src]` 提取候选图片。
4. 0 张图片会失败；1 张自动识别；多张进入候选选择，避免静默选错。
5. 识别结果保留 `image_to_rows` v2 文档，并封装为 `schema_version=1` 的运行文档。
6. 数据面板支持真实 `rowSpan`/`colSpan` 的表格预览、单元格编辑、低置信度提示和显式保存修订。
7. 修订写入 `revisions/`，原始识别 JSON/XLSX 永不覆盖。下一次运行默认比较上一条成功运行的原始 OCR 文档。

运行产物结构：

```text
data/runs/<run_id>/
  crawl.json
  source.png
  recognized.json
  recognized.xlsx
  revisions/
    revision-001.json
    revision-001.xlsx
```

## API

后端 API 前缀为 `/api`，主要接口如下：

- `GET/POST /api/sources`、`PATCH /api/sources/{source_id}`
- `POST /api/sources/{source_id}/runs`
- `GET /api/runs`、`GET /api/runs/{run_id}`
- `POST /api/runs/{run_id}/image-selection`
- `GET /api/runs/{run_id}/document?view=recognized|revised`
- `PUT /api/runs/{run_id}/revision`
- `GET /api/runs/{run_id}/compare`
- `POST /api/runs/{run_id}/exports`
- `GET /api/artifacts/{artifact_id}/download`
- `GET /api/health`

`DocumentExporter` 是扩展边界，当前注册 JSON 和 XLSX；未来可增加数据库写入适配器，而不改变抓取、OCR 和历史对比契约。

## 测试

```bash
./.venv/bin/python -m pytest -q
cd frontend && npm run build
```

后端新增测试使用假的抓取器和识别器验证队列、候选选择、修订、差异和产物；根目录的 `test_image_to_rows.py` 继续作为真实 OCR 回归测试。
