# 11 · Excel 设计书：省 token 的读取方案

结论：**不要让 AI 直接读 .xlsx，也不要把 MCP 当主路径。** 用 [xlsx2ai.py](../templates/project/scripts/xlsx2ai.py) 在本地把设计书一次性转成按 sheet 拆分的 JSON，图形画的流程图转成 Mermaid；AI 先读索引，再只打开需要的 sheet。转换不消耗模型 token，只重转 SHA-256 变化的文件。

## 1. 实测（2026-11）

样本：公开仓库 [presire/SoftwareDesignDocument](https://github.com/presire/SoftwareDesignDocument) 的 3 本设计书，以及一个用真实 DrawingML 图形 + 连接线绘制的流程图 xlsx（合成）。样本只在本地测试，未收录进本仓库。

- token：离线的旧版 Claude 分词器估算，只用于相对比较。
- 文本保留率：原表不重复单元格文本（前 40 字）在输出中出现的比例。

| 方法 | 機能概要書（21 sheet、合并单元格 4337） | テーブル定義書（13 sheet） | 解析フロー設計書（8 sheet） | 文本保留率 |
|---|---:|---:|---:|---|
| pandas 整本读（基线） | 146,329（100%） | 85,619（100%） | 70,987（100%） | 100% |
| MarkItDown | 124% | 157% | 155% | 81～99% |
| excel2md 标准 Markdown | 56% | 295% | 534% | 28～84% |
| excel2md CSV-Markdown（默认） | 63% | 53% | 59% | 99.9～100% |
| **ExStruct light（JSON）** | **31%** | **23%** | **25%** | **99.9～100%** |

- **按 sheet 拆分**：機能概要書 21 个 sheet，中位数 2,115 token，最大 5,430。只读一个 sheet 约为整本读的 1.5%。
- **图形 + 连接线画的流程图**：excel2md 的 `--mermaid-detect-mode shapes` 取到全部 6 条边，形状（起止、判断）也正确，Mermaid 只要 111 token；ExStruct 的图形提取在非 Windows 环境只有 libreoffice 模式可用，输出 690 token 的 JSON。
- **贴图的流程图**：两者都提取不了；`xl/media/` 里能拿到原图，一张约 0.7k～3k token（视尺寸）。
- MarkItDown 和 excel2md 标准 Markdown 在方眼纸上反而膨胀，不建议用于设计书。

## 2. 方案

```
specs/xxx.xlsx            原本（AI 不直接读；settings 里 deny Read(/**/*.xlsx)）
   │  python scripts/xlsx2ai.py        本地转换，增量
   ├─ specs-ai/index.md                全部设计书目次
   ├─ specs-ai/xxx/index.md            sheet 名、文字数、流程图、图片数
   ├─ specs-ai/xxx/sheets/<sheet>.json ExStruct light：{"r": 行, "c": {列: 值}}
   ├─ specs-ai/xxx/flows/<sheet>.mmd   有连接线的 sheet → Mermaid（excel2md）
   └─ specs-ai/xxx/media/              仅 --extract-media：贴图
```

AI 的读取顺序：`specs-ai/index.md` → 该书 `index.md` → grep 定位 → 只读 1～2 个 sheet JSON / `.mmd`。规则写在模板的 AGENTS.md（Claude Code 与 Copilot 共用）与 CLAUDE.md。

```bash
pip install "exstruct==0.9.0" "excel2md==2.3.0"    # Python 3.11+
python scripts/xlsx2ai.py                          # specs → specs-ai，只转变化的
python scripts/xlsx2ai.py --check                  # CI：有过期或多余输出则退出码 1
python scripts/xlsx2ai.py specs specs-ai --extract-media
```

退出码：`0` 正常；`1` `--check` 发现过期；`2` 参数/依赖错误或有书转换失败（其他书照常转换，失败的书保持过期）。

## 3. 需要人工处理的部分

- **分支标签**：Excel 连接线不带文字，「はい／いいえ」是独立文本框，会作为孤立节点出现在 `.mmd` 里。对照原本挂到对应边上，作为单独维护的文件提交（不要改生成物）。
- **贴图流程图**：`--extract-media` 取出后由 AI 转成 Mermaid 一次，人工核对后单独提交；之后只读 Mermaid。
- **合并单元格**：light 模式不输出合并范围，只保留带行列号的值。需要时对个别 sheet 用 `exstruct -m standard`（图形与合并信息在 Windows + Excel COM 下最完整）。
- **是否提交 `specs-ai/`**：提交后 Copilot 等其他工具也能用、diff 可审；含客户信息的设计书按 AGENTS.md 的数据规则处理，必要时只在本地生成并加入 `.gitignore`。

## 4. MCP 的定位

需要在对话中临时查询大表时再加：[ExStruct MCP](https://github.com/harumiWeb/exstruct)（`exstruct_read_json_chunk` 分块读取）、[jwadow/mcp-excel](https://github.com/jwadow/mcp-excel)（只取需要的数据）、[negokaz/excel-mcp-server](https://github.com/negokaz/excel-mcp-server)（`EXCEL_MCP_PAGING_CELLS_LIMIT` 分页）。每次调用都会重新解析，读设计书比预转换更费。

## 5. 验证边界

本仓库测试（`tests/test_xlsx2ai.py`）只用合成 xlsx：sheet 拆分、索引链接（含 `[]` 的书名）、流程图 6 条边、增量/删除/`--check`、锁文件 `~$*`、`--extract-media`、损坏文件不中断其他书。实测数字来自上述 3 本公开设计书；你们的设计书格式可能不同，采用前用 2～3 本真实设计书复测 token 与保留率。

来源：[ExStruct](https://github.com/harumiWeb/exstruct)、[elvezjp/excel2md](https://github.com/elvezjp/excel2md)、[xlsx2md 仕様](https://github.com/igapyon/xlsx2md/blob/devel/docs/xlsx2md-spec.md)、[MarkItDown 事例](https://dev.classmethod.jp/articles/markditdown-claude-code-excel-reformat/)、[OMN 設計書 Markdown 化](https://oproduct.ai/articles/6172205)。
