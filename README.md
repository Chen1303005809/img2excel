# 网址抓图、图片转表格与历史对比系统

这是一个单机单用户的前后端分离应用：保存网页来源后，由本地 Worker 使用 Crawl4AI 抓取正文图片，复用 `image_to_rows.py` 识别为通用结构化表格，再生成 JSON、XLSX 和可编辑的网页预览。每次运行均保存独立产物，并与同一来源最近一次成功运行的原始 OCR 结果比较。来源可以开启按自定义分钟间隔的定时抓取；定时运行下载图片后会先比较 SHA-256，图片未变化时跳过 OCR 并复用上次识别结果。

## 运行环境

- Python 3.12，使用系统默认解释器 `python`
- Node.js 20+
- Crawl4AI 所需的 Chromium 浏览器

首次安装依赖：

```bash
cp .env.example .env  # 首次运行时复制，并按需修改端口
python -m pip install -r requirements-app.txt
CRAWL4_AI_BASE_DIRECTORY="$PWD/data/.crawl4ai" crawl4ai-setup   # 如果本机还没有 Crawl4AI 浏览器
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
set -a
source .env
set +a
python -m uvicorn backend.app.main:app --host "$IMAGE_TABLE_BACKEND_HOST" --port "$IMAGE_TABLE_BACKEND_PORT" --reload
python -m backend.worker
cd frontend && npm run dev
```

浏览器访问 `http://${IMAGE_TABLE_FRONTEND_HOST}:${IMAGE_TABLE_FRONTEND_PORT}`。后端默认只绑定本机；应用第一次启动会通过 Alembic 建库并预置 804、805、970 三个 YAFCO 来源。数据库和运行产物默认写入 `data/`，可通过 `.env` 或 `IMAGE_TABLE_*` 环境变量调整。

关键配置：

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `IMAGE_TABLE_DATA_DIR` | `data` | SQLite 与运行产物目录 |
| `IMAGE_TABLE_BACKEND_HOST` | `127.0.0.1` | 后端监听地址 |
| `IMAGE_TABLE_BACKEND_PORT` | `8000` | 后端监听端口 |
| `IMAGE_TABLE_FRONTEND_HOST` | `127.0.0.1` | 前端监听地址 |
| `IMAGE_TABLE_FRONTEND_PORT` | `5173` | 前端监听端口 |
| `IMAGE_TABLE_FRONTEND_ORIGIN` | 自动按前端地址生成 | 后端 CORS 来源；跨域部署时可显式设置 |
| `IMAGE_TABLE_WORKER_CONCURRENCY` | `1` | Worker 同时处理的运行数 |
| `IMAGE_TABLE_CRAWL_CONCURRENCY` | Worker 并发数 | 抓取信号量 |
| `IMAGE_TABLE_OCR_CONCURRENCY` | `1` | OCR 信号量，默认串行 |
| `IMAGE_TABLE_OCR_DEVICE` | `cuda` | OCR 设备，可设为 `cuda` 或 `cpu` |
| `IMAGE_TABLE_OCR_MODEL_ROOT_DIR` | `./models` | RapidOCR 模型目录；相对路径按当前工作目录解析 |
| `IMAGE_TABLE_OCR_CUDA_DEVICE_ID` | `0` | CUDA GPU 编号 |
| `IMAGE_TABLE_LEASE_SECONDS` | `900` | Worker 租约超时恢复时间 |
| `IMAGE_TABLE_ALLOW_PRIVATE_HOSTS` | `false` | 是否允许抓取本机/私有地址 |
| `IMAGE_TABLE_ORACLE_DATABASE_URL` | 空 | Oracle 目标库 SQLAlchemy 连接串；只放在运行环境，不写入代码或导入产物 |
| `IMAGE_TABLE_ORACLE_CREATOR_ID` | 空 | 直接指定 `CREATOR` 业务用户 ID；与用户映射 SQL 二选一 |
| `IMAGE_TABLE_ORACLE_CREATOR_LOOKUP_SQL` | 空 | 使用绑定参数 `:session_user` 按 Oracle 当前登录用户查询业务用户 ID |
| `IMAGE_TABLE_ORACLE_APPLICATION_VERSION` | `V260123` | 写入模板头表的功能版本号 |
| `IMAGE_TABLE_ORACLE_IMPORT_TIMEOUT_SECONDS` | `30` | Oracle TCP 连接、调用和连接池超时 |

定时抓取在“来源管理”中按来源配置。勾选“自动”，输入抓取间隔（1–43,200 分钟）后失焦保存；Worker 会在下一次到期时自动创建运行记录。停用来源或取消“自动”后不会再创建定时任务，已排队的运行仍会正常处理。

## 业务流程

1. 来源页添加或停用网址，规范化后的 URL 保证同一来源不重复。
2. 点击“立即运行”，API 只创建 `queued` 记录；Worker 负责后续阶段。开启来源的定时抓取后，Worker 也会按来源配置自动创建 `queued` 记录。
3. Crawl4AI 按 `yafco_image` 页面配置等待 `.ya-con img`，从 `.ya-con img[src]` 提取候选图片。
4. 0 张图片会失败；1 张自动识别；多张进入候选选择，避免静默选错。
5. 识别结果保留 `image_to_rows` v2 文档，并封装为 `schema_version=1` 的运行文档；所有识别单元格按原文字符串保存（百分数不会转换成小数），生成表格时会把相邻的空白单元格合并为矩形结构。
6. 数据面板支持真实 `rowSpan`/`colSpan` 的表格预览、单元格编辑、识别分数颜色分级和显式保存修订；运行详情显示各颜色分数的识别框数量，原图按比例完整展开；单击起始单元格后按住 Shift 单击结束单元格，可手动合并或取消合并，再导出修订后的 JSON/XLSX。
7. 每次运行下载选中的正文图片并计算 SHA-256；如果与上一条成功运行的图片相同，则跳过 OCR，复用上一条原始识别文档，再生成本次运行的 JSON/XLSX。SHA 变化或没有可用识别基线时才会重新识别。
8. 修订写入 `revisions/`，原始识别 JSON/XLSX 永不覆盖。下一次运行默认比较上一条成功运行的原始 OCR 文档。
9. 识别到“异常交易监管阈值/交易限额”表时，数据面板会额外生成标准化的异常交易开仓总量表：直接从既有识别表格的“交易限额”单元格提取品种/合约和单日最大开仓量，再通过前端静态映射补全交易所与代码；原始识别表格仍可展开核对。原图未提供独立预警线，因此当前页面按最大开仓量的 80% 展示预警值。
10. 识别到“交易所期货/期权限仓”表时，数据面板会额外生成标准化的持仓限仓表：按交易所、品种/合约、持仓日期、总持仓量和固定/百分比限仓规则展开，并把无法映射的品种保留在提示中；原始识别表格仍可展开核对。
11. 在实体整理表点击“写入数据库”后，后端先校验运行状态、文档哈希、静态代码映射、日期哨兵、数值范围和目标 Oracle 权限；通过后再由用户确认创建草稿临时模板。头表、明细表和梯度表在同一个 Oracle 事务中写入，任一条失败全部回滚；本地 SQLite 保留导入批次和逐行错误审计。

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

`POST /api/sources` 和 `PATCH /api/sources/{source_id}` 支持 `schedule_enabled`、`schedule_interval_minutes`；来源响应会返回 `next_run_at`。例如：`{"schedule_enabled": true, "schedule_interval_minutes": 30}` 表示每 30 分钟自动抓取一次。

`DocumentExporter` 是扩展边界，当前注册 JSON 和 XLSX；未来可增加数据库写入适配器，而不改变抓取、OCR 和历史对比契约。

异常交易品种、交易所与代码的官方资料核对记录见 [`research_sources_static_mapping.md`](research_sources_static_mapping.md)；交易限额本身仍应以交易所最新公告为准。

## 测试

```bash
python -m pytest -q
cd frontend && npm run build
```

后端新增测试使用假的抓取器和识别器验证队列、候选选择、修订、差异和产物；根目录的 `test_image_to_rows.py` 继续作为真实 OCR 回归测试。
