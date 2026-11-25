# 11 · Excel 设计书：转成人和 AI 都能读的 Markdown

结论：**不要让 AI 直接读 .xlsx，也不要把 MCP 当主路径。** 用 [xlsx2ai.py](../templates/project/scripts/xlsx2ai.py) 在本地把设计书按 sheet 转成 Markdown：表格还原成 Markdown 表，地の文按缩进变成列表，用图形画的流程图以 Mermaid 嵌入。需要单元格位置时（写 `xlsx_patch.py` 的变更指示）再读同名的 JSON。转换不消耗模型 token，依据原本的 SHA-256 和生成文件清单决定是否重转。

现成的 Excel→Markdown 工具在日式“方眼纸”设计书上，不是膨胀就是丢字。实测下来最好的做法是两步：用 ExStruct 取出非空单元格及其行列号，再按版面规则（左端对齐的列、表头、缩进、标题行）还原结构。

## 1. 实测（2026-11-23）

样本：公开仓库 [presire/SoftwareDesignDocument](https://github.com/presire/SoftwareDesignDocument)（提交 `c6eb206`）。工具比较用其中 6 本（93 个 sheet，4,886 个不重复的单元格文本），采用的方法另在全部 14 本（202 个 sheet）上复测。样本只在本地测试，未收录进本仓库。

- token：离线的旧版 Claude 分词器估算，只用于相对比较。
- 文本保留率：不重复单元格文本（去空白后前 40 字）在输出中出现的比例；表中是 6 本里最差的一本。

| 方法 | 版本 | token（以 MarkItDown 为 100%） | 文本保留率（最差） | 观察 |
|---|---|---:|---:|---|
| MarkItDown | 0.1.9 | 990k（100%） | 99.8% | 整张表输出，方眼纸的空列全部展开 |
| Docling（docling-slim，无需 PyTorch） | 2.151.1 | 10.6M（1,072%） | 99.8% | 合并单元格的值按覆盖的格子数重复 |
| excel2md 标准 Markdown | 2.3.0 | 2.18M（220%） | **25.7%** | 大量文字丢失 |
| excel2md CSV-Markdown（默认） | 2.3.0 | 409k（41%） | 98.3% | CSV 放在代码块里，不是 Markdown 表 |
| [xlsx2md](https://github.com/igapyon/xlsx2md)（balanced） | tag20260411 | 203k（20%） | 96.8% | 按框线与值的分组找表，最接近目标；但合并单元格以 `[MERGED←]` 填充，节标题行变成表头，整页地の文变成一张宽表 |
| ExStruct light JSON（此前的方案） | 0.9.1 | 211k（21%） | 98.3% | 只有值与行列号，人难读 |
| **ExStruct + xlsx2ai 的结构还原（现方案）** | 0.9.1 | **146k（15%）** | **99.8%** | 表、标题、缩进列表 |

在全部 14 本上：Markdown 的 token 是 JSON 的 71%，文本保留率 100%，还原出 651 张表，没有一行会被渲染成代码块。另用其他作者的样本（ExStruct 自带的大量合并单元格的日文申请书、xlsx2md 的测试用工作簿）复核，没有丢字。

两条外部依据：ExStruct 自己的基准（n=12，gpt-4o）里，它在原始覆盖率与精度上最好，作者推荐“JSON → 由 LLM 重建 Markdown”；会后有一篇对比文章，标题是「方眼紙Excel→Markdown変換、結局LLMしか勝たん話」（Zenn，本环境网络受限未能读取正文）。两者都指向同一点：方眼纸的语义只能部分靠规则还原，最高质量要靠 LLM 加人工核对，见第 6 节。

## 2. 方案

```
specs/xxx.xlsx              原本（AI 不直接读；settings 里 deny Read(/**/*.xlsx)）
   │  python scripts/xlsx2ai.py        本地转换，增量
   ├─ specs-ai/index.md                全部设计书目次
   ├─ specs-ai/xxx/index.md            sheet 名、Markdown / JSON 链接、文字数、流程图、图片数
   ├─ specs-ai/xxx/sheets/<sheet>.md   先读这个：表、标题、缩进列表、Mermaid
   ├─ specs-ai/xxx/sheets/<sheet>.json ExStruct light：{"r": 行, "c": {列: 值}}，需要单元格位置时
   ├─ specs-ai/xxx/flows/<sheet>.mmd   有连接线的 sheet → Mermaid（excel2md），同时嵌入该 sheet 的 Markdown
   └─ specs-ai/xxx/media/              仅 --extract-media：贴图
```

AI 的读取顺序：`specs-ai/index.md` → 该书 `index.md` → grep 定位 → 只读 1～2 个 sheet 的 `.md`。规则写在模板的 AGENTS.md（Claude Code 与 Copilot 共用）与 CLAUDE.md。Markdown 也给人用：PR 里能看差分，GitHub 上能直接渲染表格和流程图。

```bash
pip install "exstruct==0.9.1" "excel2md==2.3.0"    # Python 3.11+
python scripts/xlsx2ai.py                          # specs → specs-ai，只转变化的
python scripts/xlsx2ai.py --check                  # CI：原本变更、删除或清单中的生成文件缺失时返回 1
python scripts/xlsx2ai.py specs specs-ai --extract-media
```

把 `specs-ai/` 用作生成文件的专用目录。提交生成物时一并提交 `.manifest.json`。旧版清单会在下次转换时更新。若总目次或清单里的 sheet、流程图、已提取图片丢失，`--check` 返回 `1`，运行转换命令即可补齐。完整性检查核对文件是否存在，生成文件的内容以重新转换为准。

写入前脚本会检查输出目录是否冲突。例如同时存在 `db.xlsx` 和 `db/a.xlsx` 时，两本书会共用一棵输出目录，需要先调整其中一本的名称。已有同名目录且没有清单记录时，可指定新的输出目录。以上冲突及转换失败均返回 `2`，正常完成返回 `0`。

输出目录名是原本去掉后缀的相对路径。`a.xlsx` 与 `a.xlsm` 并存（或文件名只差大小写）时，目录名改为 `a-xlsx` / `a-xlsm`，两本都会转换；目录名不保留 `.xlsx`，因为 settings 会 deny 读取它。

## 3. Markdown 的还原规则

只用标准库，规则写在 `xlsx2ai.py` 的 `sheet_markdown` 里：

- **表**：表头行加上它下面同一左端列开始、且所有值都落在表头列之内的行。允许两段表头，输出为 `上段/下段`：下段从右边开始的（如「イベント」下分「初期表示／操作時」），以及下段从同一列开始、上段每个表头下有多列的分组表头（如「基本情報」下分「氏名／年齢」）。允许合并单元格造成的最多 2 行空行。表头右侧多出的一个值（备注等）放进表头为空的列，不把表拆开；只有左端列一个值、其余都在右侧的行不算，这样下一张表的表头不会被并进来。只有一个值的行（编号、记号除外）结束表格，所以紧跟在表下的说明文字不会被吞进表里。
- **标题**：以编号（`5.2 `）或记号（■ □ ◆ ● 【 ≪ ＜ 〈 等）开头、只有一个值的行变成标题，层级按缩进的列决定；紧接在表格上方的一格标题变成粗体。以“。”结尾的是句子，不当标题。
- **地の文**：按左端列的缩进变成嵌套列表，每行最多深一级，所以不会出现被渲染成代码块的缩进；独立一格的「・」去掉，由列表符号代替。
- **转义**：单元格里的 `|` 转义，单元格内换行变成 `<br>`，形如 HTML 标签的 `<input>` 转义为 `\<input>`（`a < b` 不动）；整点的日期时间只保留日期。是否当标题按转义前的文字判断。
- **耗时**：从头到尾只扫一遍，时间与行数成正比（3000 行的 sheet 约 0.01 秒；改之前同样的数据要 27 秒）。

做不到的事：合并单元格的范围、单元格颜色与框线、批注、贴图里的文字都不在 Markdown 里；没有框线、列也没对齐的“表”会按列表输出。这些需要时看 JSON（行列号）或原本。

## 4. 画面试验的观点覆盖

画面试验框架的 `観点カバレッジ.md` 从 Markdown 设计书里收集画面一览、消息与“项番＋检查内容”的检查列表。此前只有 Excel 设计书的项目拿不到这项检查。现在把 `site.mjs` 的 `design` 指向 `specs-ai/<书>/sheets/<sheet>.md` 即可。

示例应用的端到端测试用 [tests/make_sample_design_xlsx.py](../tests/make_sample_design_xlsx.py) 把示例设计书做成方眼纸版式的 Excel（合并单元格、缩进的地の文、■ 节标题），经 `xlsx2ai.py` 转换后交给画面试验，得到与手写 Markdown 设计书相同的结果（3 项全部有用例）。这一步在开发中拦下过一个真实问题：表下方同列的说明文字曾被并进表里，句子被当成“消息”，覆盖项从 3 变成 6。

## 5. 需要人工处理的部分

- **分支标签**：Excel 连接线不带文字，「はい／いいえ」是独立文本框，会作为孤立节点出现在 Mermaid 里。对照原本挂到对应边上，作为单独维护的文件提交（不要改生成物）。
- **贴图流程图**：`--extract-media` 取出后由 AI 转成 Mermaid 一次，人工核对后单独提交；之后只读 Mermaid。
- **合并单元格的语义**：Markdown 与 light 模式的 JSON 都不含合并范围。需要时对个别 sheet 用 `exstruct -m standard`（图形与合并信息在 Windows + Excel COM 下最完整）。
- **是否提交 `specs-ai/`**：提交后 Copilot 等其他工具也能用、diff 可审；含客户信息的设计书按 AGENTS.md 的数据规则处理，必要时只在本地生成并加入 `.gitignore`。

## 6. 想把设计书改为以 Markdown 为正本时

规则还原适合“Excel 仍是正本、Markdown 跟着重新生成”。如果团队决定以后用 Markdown 写设计书，一次性迁移的质量上限在 LLM：

1. 以 `xlsx2ai.py` 生成的 Markdown 为底稿（文字齐全、表格已还原），交给 LLM 整理标题层级、把版面性的列表改成文章、给表补上意义；不要从原本截图或整本 JSON 开始。
2. 机械核对没有丢字也没有编造：对照底稿的表格行与原文，逐 sheet 检查迁移稿里出现了原本的全部单元格文本；对不上的逐条由人判断。
3. 迁移后删除原本或改为只读，避免两份正本。

本仓库没有为第 2 步提供脚本；需要时按第 1 节的保留率算法写即可（不重复单元格文本、去空白、在迁移稿中查找）。

修改 Excel 原本的做法见 [14 · 改修流程与画面试验](14-改修流程与画面试验.md#2-改-excelai-只写变更指示脚本负责写入和核对)：AI 写变更指示，`xlsx_patch.py` 写入并核对。

## 7. MCP 的定位

需要在对话中临时查询大表时再加：[ExStruct MCP](https://github.com/harumiWeb/exstruct)（`exstruct_read_json_chunk` 分块读取）、[jwadow/mcp-excel](https://github.com/jwadow/mcp-excel)（只取需要的数据）、[negokaz/excel-mcp-server](https://github.com/negokaz/excel-mcp-server)（`EXCEL_MCP_PAGING_CELLS_LIMIT` 分页）。每次调用都会重新解析，读设计书比预转换更费。

## 8. 验证边界

- 本仓库测试（`tests/test_xlsx2ai.py`）：合成 xlsx 上的 sheet 拆分、索引链接（含 `[]` 的书名）、流程图 6 条边并嵌入 Markdown、增量/删除/`--check`、输出格式变化后重新生成、锁文件 `~$*`、`--extract-media`、损坏文件不中断其他书；还原规则用合成的行数据单独测试（表、两段表头与分组表头、表右侧的备注、合并造成的空行、标题、列表深度、句子不当标题、转义、日期、长 sheet 的耗时）；替换输出失败时保留上次的输出；转换工具优先用当前 Python 里装的固定版本。
- 端到端：示例应用的 Excel 版设计书 → Markdown → 画面试验的观点覆盖。
- 实测数字来自第 1 节的公开样本，规则也是在这些样本上调出来的。你们的设计书版式可能不同：采用前用 2～3 本真实设计书复测保留率，并实际读几张 sheet 的 Markdown。

来源：[ExStruct](https://github.com/harumiWeb/exstruct)（含 benchmark/public/REPORT.md）、[elvezjp/excel2md](https://github.com/elvezjp/excel2md)、[igapyon/xlsx2md](https://github.com/igapyon/xlsx2md)、[microsoft/markitdown](https://github.com/microsoft/markitdown)、[docling-project/docling](https://github.com/docling-project/docling)、[MarkItDown 事例](https://dev.classmethod.jp/articles/markditdown-claude-code-excel-reformat/)、[OMN 設計書 Markdown 化](https://oproduct.ai/articles/6172205)。
