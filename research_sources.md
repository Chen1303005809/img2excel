# 中文长截图表格离线转 XLSX：一手资料调研

> 调研日期：2026-09-15（Asia/Shanghai）
>
> 范围：只核对项目官方 GitHub 仓库的 README、源码、许可证和官方文档；未使用博客、测评文章或第三方教程。目标输入按用户给定的约 908×4141 像素、纵向多分区中文表格理解。

## 结论先行

对于这类长截图，最稳妥的轻量可复用路线是：

```text
原图
  -> OpenCV 灰度/二值化 + 水平/垂直线增强 + 连通区域/轮廓分析
  -> 找到各个表格分区，按分区裁剪（保留少量上下文和原始分辨率）
  -> 中文表格识别：PP-Structure 表格管线；或 RapidOCR + RapidTable 的 ONNX CPU 路线
  -> 用识别到的单元格/HTML结构写 XLSX
  -> 输出带置信度、坐标和人工复核标记的结果
```

> 用户补充的真实样本反馈：PP-StructureV3 在同类图片上会丢失单元格内容和文字；img2table 的效果更差且无法稳定跑通。以下内容因此只把它们作为对照或升级候选，不把它们当作默认主链。

关键判断：

- **PP-Structure** 是最直接的“表格图片 → 表格结构/HTML → XLSX”候选。官方表格实现明确组合了 DB 文本检测、CRNN 文本识别、SLANet 表格结构/单元格坐标预测，并在源码中把 HTML 交给 `tablepyxl` 写成 `.xlsx`。[PaddleOCR 表格 README](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/README.md)、[`ppstructure/table/predict_table.py`](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/predict_table.py)
- **RapidOCR** 更像轻量中文 OCR 前端/后端适配层：输出文字框、文本、分数，可选单词框；它本身不负责表格网格和 XLSX。配合官方同组织的 **RapidTable** 才形成“表格结构 → HTML”的组合。[RapidOCR README](https://github.com/RapidAI/RapidOCR/blob/main/README.md)、[RapidOCR 主流程源码](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/main.py)、[RapidTable README](https://github.com/RapidAI/RapidTable)
- **Tesseract** 能离线做中文行/词 OCR，并输出 TSV/hOCR 坐标和置信度，但不是表格结构识别器；适合作为裁剪后单元格/行的备用识别器或交叉校验器，不适合单独把多分区长图还原为 XLSX。[Tesseract README](https://github.com/tesseract-ocr/tesseract/blob/main/README.md)、[Tesseract 安装与运行文档](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)
- **OpenCV** 适合做确定性的几何预处理和分区，不识别中文语义，也不生成 XLSX。它应当处理“哪里是表格、哪里是线、哪里应裁剪”，而不是替代 OCR。[OpenCV Hough Line Transform](https://docs.opencv.org/4.x/d9/db0/tutorial_hough_lines.html)、[OpenCV Morphological Transformations](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html)、[OpenCV Structural Analysis](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html)
- **ONNX Runtime** 是模型推理运行时，不是 OCR 或表格算法。它最适合在 RapidOCR/RapidTable 的 ONNX CPU 路线上作为可替换后端；不能只安装它就得到中文识别能力。[ONNX Runtime README](https://github.com/microsoft/onnxruntime/blob/main/README.md)、[安装文档](https://onnxruntime.ai/docs/install/)、[Execution Providers](https://onnxruntime.ai/docs/execution-providers/)

## 1. 输入形态带来的硬约束

908×4141 的长宽比约为 4.56。不要把整张长截图直接当成一张“单表图片”交给表格结构模型：

1. PP-Structure 的官方表格示例按“一张表格图”运行，并按输入图片逐张生成 XLSX；源码的主循环对每个输入图调用一次表格系统、得到一个 HTML，再写一个同名 `.xlsx`。[`predict_table.py` 主流程](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/predict_table.py)
2. PP-StructureV3 官方参数将文本检测的 `text_det_limit_side_len` 默认写为 960，`max` 表示最长边不超过该值；长边 4141 会被大幅缩小，细小中文笔画可能丢失。[PP-StructureV3 参数文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md)
3. PP-Structure V2 表格快速开始文档公开了表格结构模型的 `table_max_len=488` 默认参数；这同样说明表格结构模型的输入是受控尺寸，而不是保真读取任意超长画布。[PP-Structure V2 Quick Start](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version2.x/ppstructure/quick_start.en.md)
4. RapidOCR 当前配置的全局 `max_side_len` 为 2000，中文检测模型配置的 `limit_side_len` 为 736；这不是文件格式限制，但对 4141 长边的整图输入意味着缩放或需要切片。[RapidOCR `config.yaml`](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)

因此，**切片不是可选的性能优化，而是保住中文小字分辨率和表格拓扑的核心步骤**。建议先按横向分隔线、明显留白、标题块和表格外框得到分区；对跨切片的横线或合并单元格保留 10–30 px 上下文，并用原图坐标回写结果。若一张分区本身仍很高，再按完整行边界切片，避免从单元格中间横切。

## 2. PaddleOCR / PP-Structure

### 实际能力

官方 PP-Structure 表格 README 将表格识别拆为三个模型/步骤：

- DB：单行文本检测；
- CRNN：单行文本识别；
- SLANet：表格结构和单元格坐标预测。

随后把 OCR 文本与结构/坐标匹配，构成 HTML 表格。官方示例明确提供中文、英文表格模型；源码返回 `cell_bbox` 和 `html`，并通过 `tablepyxl.document_to_xl()` 写入 XLSX。[表格管线 README](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/README.md)、[表格系统源码](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/predict_table.py)

PP-Structure 的版面分析还提供中文布局模型，能检测 `Table` 等区域；这使它可用于“长图先找表格区域、再逐区表格识别”的架构，但官方 XLSX 示例仍是按单张表图输出，多个分区的工作簿合并、命名和跨区去重需要自行编排。[中文布局 README](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/layout/README_ch.md)

### 安装与运行边界

- 当前 PaddleOCR 安装文档写明 `paddleocr` 包支持 Python 3.8+；包含 PP-StructureV3 的 `doc-parser` 可选依赖组要求 Python 3.9+。使用 Python 3.12 在版本声明上满足要求，但 PaddlePaddle 本体、操作系统、CPU/GPU/CUDA 仍要选择相匹配的官方 wheel。[安装文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/installation.en.md)
- 默认基础包与文档解析能力是分开的；仅安装 `paddleocr` 不等于已安装表格解析所需的全部可选依赖，表格/布局应安装对应 `doc-parser` 能力或按官方版本路径安装。
- 官方 V2 表格示例需要分别准备文本检测模型、中文文本识别模型、中文 SLANet 模型、字符字典和表格结构字典，并通过 `--*_model_dir` 指定路径。[V2 表格快速开始](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/README.md)
- 离线运行的边界是“安装包、模型、字典和依赖必须预先落盘”。文档中 `model_dir=None` 时会使用/下载官方模型；离线交付应固定版本、预下载模型、显式设置本地模型目录，并在无网络环境测试冷启动。

### 对 908×4141 多分区中文表格的适配判断

**理论能力完整，但本项目不作为默认主路线。** 它直接建模表格结构和单元格坐标，且官方源码已经包含 HTML→XLSX 的落地点；中文模型和表格结构字典也有明确入口。对有线表格、合并单元格、需要可编辑网格而非纯文本的目标，能力覆盖最完整。但用户对同类样本的实测反馈是单元格和文字会丢失，因此应先用当前样本做回归对照，不能只根据官方能力描述选型。

**需要规避的边界：** 不要整图一次性识别；不要把结构模型缩放后的低分辨率结果当成最终 OCR；不要默认多张表/多个分区会自动合并成一个正确工作簿。建议 OpenCV 先分区，PP-Structure 对每个分区单独推理，再在 XLSX 层面按分区排序、合并工作表或追加区块。

### 许可证注意点

PaddleOCR 仓库 LICENSE 为 Apache License 2.0。若再分发软件/镜像，应保留许可证、版权/归属声明，修改文件需有修改说明；商标权不由 Apache 许可证自动授予。[PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)

## 3. Tesseract 中文 OCR

### 实际能力

Tesseract 官方 README 说明其包含 OCR 引擎和命令行程序；Tesseract 4 起有基于 LSTM 的识别引擎，重点是行识别，同时保留旧引擎。官方支持 UTF-8 和 100+ 语言；`chi_sim` 是简体中文语言代码。[Tesseract README](https://github.com/tesseract-ocr/tesseract/blob/main/README.md)、[命令行手册](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)

对表格转换有用的输出是：

- TSV：每个识别词一行，含框坐标、置信度和文本；
- hOCR：HTML 形式，含词框和置信度；
- 另有普通文本、PDF、ALTO、PAGE 等输出。

这些是 OCR 结果，不是表格的行列拓扑、合并单元格或 XLSX。要做表格，必须另写几何聚类/单元格映射层。

### 安装与运行边界

- 官方安装文档强调有两个独立部分：引擎本体和各语言的 `.traineddata`。简体中文语言包通常命名为 `tesseract-ocr-chi-sim`，也可手动把 `chi_sim.traineddata` 放进 `tessdata`。[Tesseract Installation](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)
- 运行形式为 `tesseract image outputbase -l lang -psm pagesegmode`；可以对裁剪后的行/单元格使用合适的页面分割模式，并用 `tsv` 或 `hocr` 获得坐标。[Tesseract Installation](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)、[Tesseract 命令行手册](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)
- 本体和语言数据都要预先部署；运行时不需要云服务。语言数据版本应与引擎版本一起固定，避免“引擎已安装但 `chi_sim` 找不到/不兼容”的交付问题。

### 对 908×4141 多分区中文表格的适配判断

**不适合作为唯一主路线，适合作为后备 OCR。** 对整张长截图，它既不负责分区也不负责表格拓扑；即便得到 TSV，仍要从词框重建行列。对 OpenCV 已裁出的单元格、表格行，或对 PP-Structure/RapidOCR 的低置信度结果做复核，Tesseract 的本地 CLI、TSV 和 `chi_sim` 支持有实用价值。若截图字体规整、单元格已被准确裁剪，它可以很轻；若存在密集中文、合并单元格、窄列和多种字号，单独依赖它会把主要工作转移到自研布局算法。

### 许可证注意点

Tesseract 本体 LICENSE 为 Apache License 2.0；官方 `tessdata` 仓库也带 Apache License 2.0。实际打包仍应把本体和所用语言数据的许可证/归属一并保留，不要只查看 Python 调用库的许可证。[Tesseract LICENSE](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE)、[tessdata LICENSE](https://github.com/tesseract-ocr/tessdata/blob/main/LICENSE)

## 4. OpenCV 线段与表格预处理

### 实际能力

官方文档给出的可复用积木是：

- **形态学开运算**：腐蚀后膨胀，用于去除噪声；
- **形态学闭运算**：膨胀后腐蚀，用于填补前景内部的小孔/小黑点；
- **HoughLines/HoughLinesP**：检测直线；官方示例建议先做边缘检测，概率 Hough 直接返回线段；
- **findContours**：在二值图中查找轮廓。

对本任务的具体用法是：灰度化后做自适应阈值或二值化；用宽而矮的核提取水平线、用高而窄的核提取垂直线；以线段连续性、外框和空白带候选分区；再以轮廓/投影统计确定表格块和单元格边界。线条掩膜用于几何判断，中文 OCR 最好仍使用未擦除线条的原始或轻度增强裁剪图，避免笔画被形态学操作误删。最后一句是针对该输入的工程推断，不是 OpenCV 对 OCR 的保证。[形态学文档](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html)、[Hough 文档](https://docs.opencv.org/4.x/d9/db0/tutorial_hough_lines.html)、[轮廓文档](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html)

### 安装与运行边界

官方 `opencv-python` 仓库提供 CPU-only Python wheel，并明确要求四种包（主模块、contrib、headless 主模块、headless contrib）只选一种，因为都占用 `cv2` 命名空间；无 GUI 的离线转换工具可选 `opencv-python-headless`。不兼容 wheel 时 pip 可能回退到源码构建，因此离线交付应预先准备匹配平台/架构的 wheel。[opencv-python README](https://github.com/opencv/opencv-python/blob/4.x/README.md)

OpenCV 不会下载 OCR 模型，也不要求网络；它的边界是图像几何处理。它不能识别中文、判断“这一格属于哪一列”、处理语义合并单元格，也不会直接写 XLSX。

### 对 908×4141 多分区中文表格的适配判断

**非常适合作为前置分区层。** 908 像素宽使水平/垂直投影和线段检测的计算量很小；4141 像素高则适合逐行扫描和分区处理。对有清晰表格线的截图，OpenCV 可以减少后续 OCR 的有效画布，避免整图缩放导致中文变小；对无线表格、断线、阴影、背景渐变或倾斜较大图片，线段法会退化，应保留“留白/文本框聚类”或 OCR 版面检测的后备分支。

### 许可证注意点

OpenCV 主仓库 LICENSE 为 Apache License 2.0；`opencv-python` 是官方打包仓库，仓库页标注 MIT，但 wheel 内还涉及打包/第三方组件清单。发布时应随采用的发行包检查其许可证文件，而不是只记录 `opencv` 主仓库许可证。[OpenCV LICENSE](https://github.com/opencv/opencv/blob/4.x/LICENSE)、[opencv-python README](https://github.com/opencv/opencv-python/blob/4.x/README.md)、[opencv-python 第三方许可证清单](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt)

## 5. ONNX Runtime 与 RapidOCR

### RapidOCR 的实际能力

RapidOCR 官方 README 将其定位为基于 ONNX Runtime、OpenVINO、MNN、PaddlePaddle、TensorRT、PyTorch 等推理引擎的 OCR 工具箱；Python 快速开始是 `pip install rapidocr onnxruntime`，然后 `RapidOCR()` 返回 OCR 结果并可视化。[RapidOCR README](https://github.com/RapidAI/RapidOCR/blob/main/README.md)

当前源码/配置可核对到的默认边界：

- 全局有 `use_det`、`use_cls`、`use_rec`，即检测、方向分类、识别三个阶段；
- 返回结果包括检测框、识别文本和分数；`return_word_box` 可开启词级框；
- 全局 `max_side_len=2000`；中文检测配置 `limit_side_len=736`、`limit_type=min`，并配置了 PP-OCR 中文模型族；
- RapidOCR 上游配置默认 `use_cuda=false`；本项目通过 `IMAGE_TABLE_OCR_DEVICE` 覆盖该值，当前默认使用 CUDA，也可显式切回 CPU。[RapidOCR 配置](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)、[RapidOCR 主流程源码](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/main.py)

RapidOCR 本身的输出是 OCR 几何和文字，不是表格结构。RapidTable README 明确描述了“表格图片 + RapidOCR”经有线/无线表格识别后输出 HTML，并列出 `ppstructure_zh` 等 ONNX Runtime 表格模型；这是一条比直接手写网格重建更完整的 RapidAI 组合路线，但它增加了一个独立的表格包、模型和版本配对约束。[RapidTable README](https://github.com/RapidAI/RapidTable)

### ONNX Runtime 的实际能力和安装边界

ONNX Runtime 官方 README 将其定义为跨平台的机器学习推理/训练加速器，负责加载并运行 ONNX 模型，不提供中文字符字典、文本检测模型或表格拓扑。CPU Python 包的官方安装命令是 `pip install onnxruntime`；GPU、DirectML、CUDA/TensorRT 等是不同包或需要匹配驱动/运行库的执行提供程序。[ONNX Runtime README](https://github.com/microsoft/onnxruntime/blob/main/README.md)、[安装文档](https://onnxruntime.ai/docs/install/)

官方 Execution Providers 文档说明：可以按优先级配置执行提供程序，例如 CUDA 不可用时回退 CPU；但组合多个 EP 时，所有依赖库都必须存在。本项目固定 ONNX Runtime 版本，使用 `IMAGE_TABLE_OCR_DEVICE` 选择 CUDA/CPU，并用 `IMAGE_TABLE_OCR_MODEL_ROOT_DIR` 将模型缓存放在工作目录下。[Execution Providers](https://onnxruntime.ai/docs/execution-providers/)

### 对 908×4141 多分区中文表格的适配判断

- **RapidOCR + RapidTable：适合轻量 CPU 主路线的候选。** RapidOCR 包含小型 OCR 模型的快速使用路径，ONNX Runtime CPU 依赖清晰，OCR 结果可带框和分数；RapidTable 负责把表格结构变成 HTML。仍应先按分区/完整行切片，因为 RapidOCR 的默认尺寸参数并不鼓励把 4141 长边原样作为单次检测输入。
- **RapidOCR 单独使用：适合“文字框 → 自己重建网格”的路线，不适合直接产 XLSX。** 这条路线代码可控、依赖相对轻，但需要自行解决列边界、合并单元格、跨切片坐标和 Excel 写入。
- **ONNX Runtime 单独使用：不适合。** 它只是执行引擎；只有在已有 ONNX OCR/表格模型时才有意义。

### 许可证注意点

RapidOCR 源码和工程组件官方 README 标明 Apache License 2.0；同一 README 还特别说明，打包/托管的 OCR 模型源自官方 PaddleOCR，模型权利归属与源码许可证应分开核对，转换后的模型文件按其说明处理。[RapidOCR LICENSE 说明](https://github.com/RapidAI/RapidOCR/blob/main/README.md)、[RapidOCR LICENSE](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE)

ONNX Runtime 主仓库 LICENSE 为 MIT，要求保留版权和许可声明；这不替代所加载模型、字典和 RapidTable/PaddleOCR 组件各自的许可证义务。[ONNX Runtime LICENSE](https://github.com/microsoft/onnxruntime/blob/main/LICENSE)

## 6. 组件取舍表

| 组件 | 直接产出 | 对中文 | 表格结构/合并单元格 | 908×4141 适配 | 离线交付重点 |
|---|---|---|---|---|---|
| PP-Structure 表格管线 | HTML、单元格框；官方源码可写 XLSX | 有中文检测/识别/表格模型 | 有，SLANet 等 | **主路线**，但必须先分区/裁剪 | PaddleOCR 包、PaddlePaddle、3 个模型、字典、版本匹配 |
| Tesseract + chi_sim | 文本、TSV/hOCR 框和置信度 | 有 `chi_sim` | 无 | **后备/复核**；单独重建表格成本高 | 引擎与 `chi_sim.traineddata` 分开部署 |
| OpenCV | 线段、掩膜、轮廓、几何候选 | 无 | 只能几何辅助 | **强前置**，尤其适合有线多分区图 | 预装匹配 wheel；只选一种 `cv2` wheel |
| RapidOCR | 中文 OCR 框、文本、分数 | 有中文模型配置 | 无（需 RapidTable 或自研） | **轻量 OCR 候选**；仍要切片 | `rapidocr`、ONNX 模型、`onnxruntime` CPU wheel |
| RapidTable | 表格 HTML、逻辑点/单元格结果 | 依赖 RapidOCR | 有线/无线表格路线 | **RapidAI 组合路线** | RapidOCR/RapidTable/模型版本和许可证一起固定 |
| ONNX Runtime | ONNX 模型推理 | 无 | 无 | **后端**，不是独立方案 | CPU/GPU EP 与模型/驱动匹配；默认 CPU 最简单 |

## 7. 推荐的最小可复用技术路线

### A. 对照路线：结构模型优先

1. OpenCV 在原图上生成线段/轮廓辅助图，定位每个表格分区；同时保留原图像素，不把擦线后的图直接作为唯一 OCR 输入。
2. 按分区裁剪；高分辨率分区再按完整表格行切片，保留重叠和原图坐标偏移。
3. 每个分区单独调用 PP-Structure 中文表格模型，固定 `det/rec/table` 模型目录和中文字典。
4. 从 `html`/`cell_bbox` 生成每个分区的 XLSX；最终按纵向顺序写入一个工作簿的多个 sheet，或按业务需要合并成一个 sheet。跨分区合并单元格不要自动猜，标记为人工复核。
5. 同时保存识别分数、单元格坐标和可视化 HTML/框图，以便只复核低置信度区域。

### B. 当前样本首选：OpenCV + RapidOCR + 自研网格重建

1. 同样先用 OpenCV 分区；这一步与识别后端解耦。
2. RapidOCR 采用 ONNX Runtime，设备由 `IMAGE_TABLE_OCR_DEVICE` 决定，模型目录由 `IMAGE_TABLE_OCR_MODEL_ROOT_DIR` 决定。本次样本实测分区识别得到 645 个文字框，整图直接识别得到 585 个文字框。
3. 用水平/垂直线的局部存在性恢复跨行、跨列单元格；不要把全页统一的行列模板硬套到所有分区。
4. 把每个单元格值、原图坐标、原始 OCR 分数和必要的二次复识别结果一起输出到 XLSX，低置信度和疑似数字错误留给人工复核。
5. RapidTable 可作为独立对照分支，但在用户已反馈结构模型丢失内容的情况下，不应绕过坐标证据直接把 HTML 当成真值。

### C. 只在局部使用 Tesseract

对 PP-Structure/RapidOCR 低分单元格重新裁剪，使用 `chi_sim` 输出 TSV 或 hOCR；以坐标和置信度做差异提示。不要让 Tesseract 的纯文本输出直接决定列结构。

## 8. 需要在真实样本上验证的项目

官方资料确认的是组件能力和参数边界，不等于对当前截图的准确率承诺。对真实 908×4141 样本应至少测：

- 分区是否把标题、脚注、相邻表格误并；
- 中文小字号在整区缩放、行切片后的识别差异；
- 有线/无线表格、断线、合并单元格、跨行文本；
- 数字、日期、括号、百分号、空白单元格和全角/半角符号；
- 切片重叠造成的重复行，以及原图坐标映射误差；
- XLSX 中的行列数、合并单元格、文本可编辑性和异常字符；
- 无网络冷启动是否仍能运行，以及模型/字典/许可证文件是否完整。

### 一手来源索引

- [PaddleOCR README](https://github.com/PaddlePaddle/PaddleOCR)
- [PP-Structure 表格 README](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/README.md)
- [PP-Structure 表格源码 `predict_table.py`](https://github.com/PaddlePaddle/PaddleOCR/blob/main/ppstructure/table/predict_table.py)
- [PP-StructureV3 参数文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/PP-StructureV3.en.md)
- [PaddleOCR 安装文档](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/installation.en.md)
- [PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)
- [Tesseract README](https://github.com/tesseract-ocr/tesseract/blob/main/README.md)
- [Tesseract 安装文档](https://github.com/tesseract-ocr/tessdoc/blob/main/Installation.md)
- [Tesseract 命令行手册](https://github.com/tesseract-ocr/tesseract/blob/main/doc/tesseract.1.asc)
- [Tesseract LICENSE](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE)
- [tessdata LICENSE](https://github.com/tesseract-ocr/tessdata/blob/main/LICENSE)
- [OpenCV Hough Line Transform](https://docs.opencv.org/4.x/d9/db0/tutorial_hough_lines.html)
- [OpenCV Morphological Transformations](https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html)
- [OpenCV Structural Analysis](https://docs.opencv.org/4.x/d3/dc0/group__imgproc__shape.html)
- [OpenCV LICENSE](https://github.com/opencv/opencv/blob/4.x/LICENSE)
- [opencv-python README](https://github.com/opencv/opencv-python/blob/4.x/README.md)
- [RapidOCR README](https://github.com/RapidAI/RapidOCR/blob/main/README.md)
- [RapidOCR `config.yaml`](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/config.yaml)
- [RapidOCR 主流程源码](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/main.py)
- [RapidOCR LICENSE](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE)
- [RapidTable README](https://github.com/RapidAI/RapidTable)
- [ONNX Runtime README](https://github.com/microsoft/onnxruntime/blob/main/README.md)
- [ONNX Runtime 安装文档](https://onnxruntime.ai/docs/install/)
- [ONNX Runtime Execution Providers](https://onnxruntime.ai/docs/execution-providers/)
- [ONNX Runtime LICENSE](https://github.com/microsoft/onnxruntime/blob/main/LICENSE)
