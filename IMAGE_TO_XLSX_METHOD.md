# 图片转 Excel 的可复用本地路线

## 目标

输入可以是不同列数、不同表头、不同分区颜色的长截图或普通表格图片，不要求每张图片手工填写列线参数。结果允许有少量 OCR 错误，但要保留结构证据和质量信息，方便抽查。

## 默认流水线

```text
图片
  → OpenCV 自适应二值化和多尺度线段检测
  → 自动发现表格块、彩色标题带和局部网格
  → RapidOCR + ONNX Runtime CPU 分块识别文字
  → 根据每个表格自己的 x/y 线恢复单元格和合并关系
  → 无边框或断线时退回 OCR 行列聚类
  → JSON 中间格式
  → Python openpyxl 写出 XLSX
```

PP-StructureV3 和 img2table 不在默认主链中。它们可以作为独立 A/B 分支，但不能把生成的 HTML 或结构结果直接当成真值。

## 一条命令运行

需要 Python 3.12 或系统默认 Python 解释器：

```bash
python -m pip install -r requirements-image2xlsx.txt
python image2xlsx.py /path/to/input.png /path/to/output.xlsx --json-output /path/to/rows.json
```

也可以把输入改为目录，程序会扫描目录下的图片，并在输出目录中按原文件名生成
`.xlsx`（例如 `sales.png` 会生成 `sales.xlsx`）：

```bash
python image2xlsx.py /path/to/images /path/to/output
```

默认只扫描当前目录；加上 `--recursive` 会同时扫描子目录。批量模式下可用
`--json-output /path/to/json` 将每张图片的中间 JSON 以同名文件写入 JSON 目录。
同一批次中如果不同目录存在同名图片，程序会提前报错，避免结果互相覆盖。

Windows PowerShell 对应：

```powershell
python -m pip install -r requirements-image2xlsx.txt
python image2xlsx.py C:\path\input.png C:\path\output.xlsx --json-output C:\path\rows.json
```

不需要 Node，也不依赖 Mac 专用能力。`RapidOCR` 的模型随 Python 包安装到运行环境中，部署时应固定依赖版本并把模型包纳入离线安装包。

## 集成边界

- `image_to_rows.py` 是识别引擎，输出 `sections[].cells`、`merged_cells`、`ocr_boxes`、彩色说明框和 `metrics`。
- `sections[].cells` 和 `merged_cells[].value` 始终按识别原文字符串保存；百分号、千位分隔符等不会被自动转成数值。历史文档只有在同一单元格的 OCR 框明确包含 `%` 时才恢复百分号，避免把普通小数误判为百分数。
- `rows.json` 是稳定接口。Web API、桌面程序、批处理或消息队列都只需调用一次 `extract(image_path)`。
- `build_xlsx_portable.py` 只负责把 JSON 写成 Excel，不参与 OCR。以后替换 Excel 库时不需要改识别逻辑。

## 自动化策略

1. 有网格线：按当前图片自动发现水平线、垂直线和局部缺失边界，不使用固定列数。
2. 长图：按高度自动重叠切片 OCR，避免把整张长图缩得过小；重叠框会去重。
3. 彩色标题：检测到完整彩色分区时，优先用彩色带切分表格并保留带内多行说明；没有足够彩带时再回退到线段检测。黑白、蓝色、紫色或无标题带都可以进入主链。
4. 合并单元格：局部边界缺失时用相邻单元格连通关系恢复，遇到不规则噪声会放弃危险合并。
5. 无边框/断线：使用 OCR 文字框的行聚类和列起点聚类生成近似网格。
6. 低置信度或疑似 `%G`、问号等单元格：只对这些单元格做裁边二次识别，控制耗时。

## 结果检查

输出 Excel 默认包含：

- `识别结果`：按发现的表格块纵向排列，列数可变；彩色说明框和普通页脚追加在表格之后。
- `识别质量`：表格块数量、OCR 框、低分框、自动后备分支和二次修正记录。
- `OCR坐标`：原图坐标、所属行列和模型分数，可回查原图。

模型分数不是字符准确率。应优先抽查数字、百分号、红色标注、窄列、长合并表头和低分框。

## 已验证样本

- 原图 908 × 4141 像素。
- 自动发现 6 个表格块，不依赖固定紫色逻辑。
- 645 个 OCR 文字框，低于 0.75 的框为 0 个。
- 识别到 2 个疑似小百分号错误，并通过单元格裁边复识别修正。
- 额外用无彩色 4 列网格和无边框 4 列样本测试：分别走 `opencv_grid` 和 `ocr_layout_fallback`。

## 适用边界

规则表格、长截图、浅色线、局部合并单元格是当前重点。完全无文字线索的空表、严重透视变形、手写内容、复杂背景和不规则自由排版仍需要额外的透视矫正、专用模型或人工复核。
