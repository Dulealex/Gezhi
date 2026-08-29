# Literature Reader v1 合同

状态：已冻结。实现与验收必须遵守本合同；任何影响语义或持久 payload 的变更都需要新的角色或 Schema 版本。

## 职责

`literature_reader_v1` 从一个 Canonical Reading Asset 生成一个 Reading Result 与一组 Candidate Draft。它们在一次逻辑 semantic read 中由相同的 `input.jsonl`、提示词与 Schema 产生，经 Python 完成 closed Schema、Evidence、locator 与预算验证后作为同一个不可变 Reader bundle 发布；任何合同或证据错误都不得部分发布。T14 不把 Draft 转换成正式 Candidate Knowledge；规范化、内容身份与 Review Queue 物化属于 T15 的确定性 successor publication。只有 T13 terminal evidence 已机械证明的超时可以触发有限 attempt；它仍是同一次逻辑 read 的传输重试，不是第二次语义阅读。

相关决策：[ADR 0015](../adr/0015-normalize-reading-input-into-a-canonical-asset-bundle.md)、[ADR 0016](../adr/0016-combine-semantic-reading-and-candidate-drafting.md)、[ADR 0033](../adr/0033-use-two-isolated-codex-runtime-roles.md)、[ADR 0034](../adr/0034-version-and-snapshot-codex-prompts-and-schemas.md)、[ADR 0130](../adr/0130-publish-reader-drafts-before-candidate-materialization.md)、[ADR 0132](../adr/0132-bound-literature-reader-attempt-captures.md)、[ADR 0133](../adr/0133-keep-t14-reader-bundles-inside-the-read-stage.md)、[ADR 0134](../adr/0134-prove-only-the-data-root-consumed-by-a-codex-role.md)。正式 Candidate 的共同合同见 [Candidate Knowledge v1](./candidate-knowledge-v1.md)。

## 输入边界

首个可执行切片只接收当前 Work、Source、Canonical run 的身份与哈希及其 Canonical Reading Asset，不接收 Research Interest。它不得读取原始 PDF、MinerU vendor 产物、Knowledge Registry、仓库源码、用户 `AGENTS.md`、skills、个人配置或网络内容；Reader workspace/child 也不得 physical open、probe 或冻结 Knowledge Data Root identity。

Research Interest 的领域位置与未来输入位置保留，但只有在其权威存储、管理入口和用户交互被单独设计后才能启用；启用时必须升级 Codex 角色版本。

相关决策：[ADR 0040](../adr/0040-defer-research-interest-and-relevance-from-the-first-slice.md)。

## ReaderInputV1

Python 从 Canonical Reading Asset 中的文本 Evidence Block 确定性生成唯一 `input.jsonl`，Codex 不同时读取 `document.md` 或原始 `blocks.jsonl`。文件第一行且仅第一行为 metadata record，所有字段必须出现且禁止额外字段：

```json
{
  "arxiv_id": null,
  "authors": [],
  "canonical_content_sha256": "<64 位小写十六进制>",
  "canonical_run_id": "<Canonical run ID>",
  "doi": null,
  "record_type": "metadata",
  "schema_version": "gezhi.reader_input.v1",
  "source_id": "src_<source_sha256 前24位>",
  "source_sha256": "<64 位小写十六进制>",
  "title": null,
  "work_id": "wrk_<lowercase UUIDv4>",
  "year": null
}
```

`title` 为规范字符串或 null；`doi` 与 `arxiv_id` 只能是下一节定义的规范裸标识符或 null；`year` 为 1000–9999 的整数或 null，未知作者固定为 `[]`。`authors` 的每一项都是非空规范字符串，作者保持书目顺序而不排序。`source_sha256` 是 Source 原始内容的完整 SHA-256，`source_id` 必须与其前 24 位一致。`canonical_content_sha256` 使用 [Candidate Knowledge v1](./candidate-knowledge-v1.md) 冻结的内容身份算法，不使用包含 run ID 或时间的 manifest 文件哈希。

### DOI 与 arXiv 规范值

非 null `doi` 必须是裸 DOI name，不得包含 `doi:` 标签、resolver URL 或外部空白修正。Python 以首个 U+002F `/` 分成 prefix 与非空 suffix；prefix 必须完整匹配 ASCII `10\.[0-9]+(?:\.[0-9]+)*`。suffix 的每个 Unicode scalar 必须属于 General_Category 的 Letter、Mark、Number、Punctuation、Symbol 或 Space_Separator（即类别首字母 `L/M/N/P/S` 或精确类别 `Zs`）；控制字符、format、surrogate、private-use、unassigned、line separator 与 paragraph separator 均非法。suffix 可以包含额外 `/`，它们属于 suffix 内容。

DOI 的 code point 序列与 ASCII 大小写必须原样保存；不得 NFC/NFKC、case-fold、lowercase、trim、删除尾标点、解读已有 `%HH`、使用宽松搜索正则或从 URL 字符串直接截取后未经验证写入。DOI 官方没有通用长度上限；首版依靠 Reader Input 与 Retrieval View 的既有总 byte budget 约束资源使用，不增加会拒绝合法 DOI 的任意长度阈值。

非 null `arxiv_id` 必须是没有 `arXiv:` 标签、URL、方括号分类或日期的裸 preferred external identifier，并完整匹配以下一种形式；可选版本后缀只能是 `v[1-9][0-9]*`：

- 新格式的 `YYMM.number`：`MM` 必须为 `01..12`；`0704..1412` 的 `number` 恰为 4 位且不全为零，`1501..9912` 恰为 5 位且不全为零；
- 旧格式的 `archive/YYMMNNN`：`archive` 完整匹配小写 ASCII `[a-z]+(?:-[a-z]+)*`，`MM` 为 `01..12`，日期范围为 `9107..9912` 或 `0001..0703`，三位序号不全为零；preferred external form 不保留旧的 `.subject-class`。

首版不提前接受六位新格式序号；arXiv 以后正式扩展时必须升级 Reader/Citation Schema。arXiv ID 保持 ASCII 大小写与版本号，不补 `v1`，不移除版本，也不依据当前日期、分类或 URL 推断。任何非 null DOI/arXiv 未满足本节时返回 `failed: reader_input_invalid`，不创建 Reader Codex attempt；`null` 是正常缺失值。

相关决策：[ADR 0048](../adr/0048-use-only-validated-urls-as-bibliographic-link-targets.md)。

### Evidence Block records

后续每行是一个 block record，所有字段必须出现且禁止额外字段：

```json
{
  "block_id": "<大小写敏感且文件内唯一的 Evidence Block ID>",
  "heading_path": [],
  "kind": "paragraph",
  "order": 0,
  "page_index": 0,
  "record_type": "block",
  "text": "<非空文本>"
}
```

`kind` 只允许 `heading`、`paragraph`、`list_item`、`table`、`figure_caption`、`figure_text`、`equation` 或 `other_text`。Reader 按 Canonical block order 升序投影文本块，并把投影后的 `order` 重编号为从 0 开始且连续；原始 order 重复、`block_id` 重复或零个文本块都属于 `failed: reader_input_invalid`。`heading_path` 是从最外层到最内层的字符串数组，根层为 `[]`；heading block 只列祖先标题，不包含自己的 `text`。`page_index` 是 0-based 最早页索引，无法可靠定位时为 null。

Reader 不重新解析、拆分、合并或改写 Evidence Block。`table.text` 直接投影 Canonical 阶段已经生成的规范文本；图题和已提取图中文字分别保持 `figure_caption` 与 `figure_text` 及各自 `block_id`。Reader 不读取 `images/`，不输出图片路径、bbox、尺寸或二进制内容，也不为纯视觉资产合成文字；若结论没有文本 Evidence Block，Reader 不得生成对应 Reading Statement 或 Candidate。

## ReaderInputV1 字节编码

metadata 中的 `title`、`authors` 与 block 中的 `heading_path`、`text` 先把 CRLF、CR 转为 LF，再做 Unicode NFC；除此之外不折叠空白、不做 NFKC、断词修复或翻译，并拒绝 NUL 与非配对 surrogate。完成上述规范化后，非 null `title` 与每个 `authors` item 还必须拒绝除 U+0009 CHARACTER TABULATION 与 U+000A LINE FEED 之外的全部 Unicode General_Category `Cc`；违反时返回 `failed: reader_input_invalid`，不创建 Reader Codex attempt，也不得删除、替换、Windows-1252 重映射或转成可见占位文本。该附加显示安全约束不改变 block `heading_path`、`text` 的既有供给合同。

`doi` 是标识符而不是人类可读文本，必须保持上一节已经验证的原 code point 序列，不做 Unicode normalization、大小写转换或 trim；`arxiv_id` 与所有内部身份、哈希和 run ID 都已经限定为 ASCII 规范值，也不得改写。每条记录使用 Python 3.11 下列等价编码，并追加一个 LF：

```python
json.dumps(
    record,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

`input.jsonl` 无 UTF-8 BOM、无空行，物理记录分隔符只能是 LF，最后一条记录后有且仅有一个 LF；必须二进制写入，禁止 Windows 文本模式换行转换。`input_sha256` 不写入文件自身，而对最终完整字节计算后写入 semantic manifest。字符串中的换行由 JSON 编码为 `\n`，不成为物理记录分隔符。

相关决策：[ADR 0041](../adr/0041-use-one-compact-text-reader-input-view.md)、[ADR 0049](../adr/0049-escape-untrusted-visible-text-with-one-pass-commonmark-tokens.md)。

## 输入大小与超限

确定性生成后的 `input.jsonl` 必须同时满足：最终实际文件大小不超过 524288 bytes（512 KiB），block record 不超过 4096 条；metadata record 不计入 block 数量。`actual_bytes=len(final_bytes)`，包含 metadata、JSON 转义、所有记录 LF 和末尾 LF；中文与 emoji 按实际 UTF-8 bytes 而不是字符数计算。524288 bytes 与 4096 blocks 合法，任一多 1 即超限。Python 在启动 Codex 前以同一份最终字节计算大小和 SHA-256，并记录两项实际值与限制值；任一超限都返回 `blocked: reader_input_too_large`，不创建 Codex attempt，也不重试。

首版禁止截断、删除尾部、只取摘要、自动分块、Map-Reduce、多次语义阅读、切换模型或降低阅读质量。Codex CLI `0.146.0` 不在 `exec --json` 中提供可机器判别的 context-window error；项目上限内发生的这类 attempted provider failure 与其他无结构化 discriminator 的 provider terminal 一样保守返回 `failed: codex_process_failed` 并保留原始事件，不解析错误 message。后续长文档能力必须以独立角色版本设计，调整上限或恢复专属 `model_context_limit` 都必须升级角色版本，但无需迁移既有资产。

相关决策：[ADR 0042](../adr/0042-block-oversized-reader-input-without-chunking-or-truncation.md)。

## Reading Result

Reading Result 只包含：

- 一段 `synopsis`；
- `research_problems`；
- `methods`；
- `findings`；
- `limitations`；
- `relevance`；
- `open_questions`；
- 由 Object、Dataset、Experiment、Metric 构成的 `study_descriptors`。

除描述符外的语义条目均使用 `EvidenceStatementV1`。没有来源支持的集合保持为空；首个可执行切片要求 `relevance` 恒为空，Codex 不得推测用户研究方向。不得输出逐章节摘要、阅读日记、重复报告或自由 sidecar。

相关决策：[ADR 0035](../adr/0035-use-a-minimal-evidence-bound-reading-result.md)、[ADR 0040](../adr/0040-defer-research-interest-and-relevance-from-the-first-slice.md)。

## EvidenceStatementV1

每条语义陈述包含：

- `text`：简体中文规范陈述；
- `source_terms`：能在所引原文证据中定位的精简来源术语；
- `evidence_block_ids`：至少一个、无重复且属于本次 Canonical Reading Asset 的 Evidence Block；
- `support_kind`：`direct`、`synthesized` 或 `interpretive`；
- `risk_flags`：只允许 `numeric_claim`、`comparative_claim`、`translation_sensitive`、`source_ambiguity`、`evidence_gap`。

Method、Claim、Limitation Candidate 不得使用 `interpretive`；Open Question Candidate 可以使用它，Relevance Candidate 的 interpretive 能力保留到未来启用。合同不包含模型自报百分比或高/中/低 confidence。

相关决策：[ADR 0036](../adr/0036-use-chinese-canonical-statements-with-source-language-evidence.md)、[ADR 0037](../adr/0037-model-evidence-support-instead-of-self-reported-confidence.md)。

## StudyDescriptorV1

每个 Study Descriptor 只包含：

- `kind`：`object`、`dataset`、`experiment` 或 `metric`；
- `label`：简短中文规范名称，专有名称可以保留来源写法；
- `source_terms`：来源中的名称、别名或缩写；
- `evidence_block_ids`：至少一个、无重复且属于本次 Canonical Reading Asset 的 Evidence Block。

Study Descriptor 不包含自由描述、标签、评分或 Candidate 语义，也不能脱离本次 Reading Result 创建。

## Descriptor 定位与发布

Codex 在 `CandidateDraftV1.descriptor_refs` 中只输出临时 `DescriptorLocatorV1`：

- `kind`：`method`、`object`、`dataset`、`experiment` 或 `metric`；
- `index`：对应 Reading Result 数组中的 0-based 位置。

T14 必须验证 kind、目标数组和 index，确保每个 locator 都能解析到同一 Reading Result 的完整 Method 或 Study Descriptor；未知 kind 或越界 index 使整个 Reader run 校验失败。T15 随后按照 [Candidate Knowledge v1](./candidate-knowledge-v1.md) 构造 `DescriptorPayloadV1`，计算完整 SHA-256 与 `desc_<前24位>`，检查短 ID 和完整 hash 碰撞，并把 Locator 替换为正式 `DescriptorReferenceV1`。正式 Candidate 不保存数组位置或复制 Descriptor 正文；重复描述符映射到同一内容身份，不同描述符不做模糊合并。

相关决策：[ADR 0039](../adr/0039-resolve-temporary-descriptor-locators-to-content-addressed-references.md)。

## CandidateDraftV1

每条 Candidate Draft 只包含：

- `candidate_type`：`method`、`claim`、`limitation`、`relevance` 或 `open_question`；
- `statement`：一个 `EvidenceStatementV1`；
- `descriptor_refs`：可为空，但每项必须解析到同一 Reading Result 中的 Method 或 Study Descriptor；
- `research_interest_id`：为未来 Relevance Candidate 保留，对其他类型禁止。

首个可执行切片禁止输出 `candidate_type=relevance`，也禁止任何 `research_interest_id`。Codex 不生成 `candidate_id`、Work/Source 身份、哈希、通用 subtype、自由结构 attributes、标题、推荐理由、重要性分数、自由标签或重复摘要。Comparison 使用 Claim 正文与 `comparative_claim` 风险标记表达。T14 只发布通过 Reader 合同与证据验证的 Draft；T15 才按 [Candidate Knowledge v1](./candidate-knowledge-v1.md) 生成正式 `EvidencePointerV1`、Candidate payload、完整 `payload_sha256` 与 `candidate_id`。

相关决策：[ADR 0017](../adr/0017-reduce-candidate-taxonomy-to-five-types.md)、[ADR 0018](../adr/0018-content-address-candidate-knowledge.md)、[ADR 0038](../adr/0038-use-a-minimal-typed-candidate-draft.md)、[ADR 0040](../adr/0040-defer-research-interest-and-relevance-from-the-first-slice.md)。

## 字段与集合上限

所有模型输出字符串先按 Candidate Knowledge v1 的文本规则规范化再验证长度；除顶层 `candidate_drafts` 的精确重复合并例外外，列表内部禁止完全重复项。任何超限或缺少必填项都使本次 semantic run 合同校验失败，Python 不静默截断。上限只用于约束输出膨胀，不构成填满要求；以后调整上限必须升级 Codex 角色版本，但不迁移既有资产。

| 字段或集合 | v1 限制 |
| --- | ---: |
| `synopsis.text` | 1–1200 字符 |
| 其他 `statement.text` | 1–600 字符 |
| Study Descriptor `label` | 1–160 字符 |
| 单个 `source_term` | 1–160 字符 |
| 每条陈述的 `source_terms` | 最多 12 |
| 每条陈述的 `evidence_block_ids` | 1–6 |
| 每个 Study Descriptor 的 `source_terms` | 最多 12 |
| 每个 Study Descriptor 的 `evidence_block_ids` | 1–6 |
| 每条陈述的 `risk_flags` | 最多 5 |
| Candidate 的 `descriptor_refs` | 最多 6 |
| `research_problems` | 最多 3 |
| `methods` | 最多 6 |
| `findings` | 最多 8 |
| `limitations` | 最多 6 |
| `relevance` | 首个切片固定 0 |
| `open_questions` | 最多 5 |
| 每类 Study Descriptor | 最多 8 |
| 全部 Study Descriptor 合计 | 最多 24 |

## Candidate 审核预算

每个 Work 最多生成 12 条 Candidate Draft，只有上限、没有最低配额：

| Candidate 类型 | 上限 |
| --- | ---: |
| `method` | 2 |
| `claim` | 4 |
| `limitation` | 3 |
| `relevance` | 首个切片为 0；未来最多 2，且每个 Research Interest 最多 1 |
| `open_question` | 2 |

候选必须优先保留证据更直接、可独立审核、可跨 Work 检索且不重复的内容。T14 对原始 `candidate_drafts` 执行 Schema、总数上限、Evidence 与 Descriptor locator 验证；超限使整个 Reader run 失败。T15 再规范化并构造正式 payload，只有完整 hash 与 CanonicalJsonV1 bytes 都相同的 Candidate 才在正式集合中确定性合并，然后对合并后的唯一集合执行逐类型预算；相似但 payload 不同的候选不得自动合并。完整顺序以 [Candidate Knowledge v1](./candidate-knowledge-v1.md) 为准。调整模型输出总数上限必须升级 Codex 角色版本；正式逐类型预算的演进由 Candidate Knowledge/T15 合同拥有。

## 原子发布与重建

每个 Source 的语义阶段固定使用以下边界：

```text
semantic/
├── current.json
├── .staging/<run_id>/
└── runs/<run_id>/
    ├── manifest.json
    ├── input.jsonl
    ├── prompt.txt
    ├── schema.json
    ├── attempts/<NN>/attempt.json
    ├── attempts/<NN>/events.jsonl
    ├── attempts/<NN>/final_message.txt
    └── result/
        ├── reading_result.json
        ├── candidate_drafts.json
        ├── candidate_knowledge.jsonl
        └── review_queue.json
```

`final_message.txt` 只在该 attempt 实际产生最终输出时存在，并保持 Codex 提供的原始字节，无论它能否解析为有效 JSON；`result/` 只允许在完整成功时存在。运行先在同一卷的 `.staging/<run_id>/` 写入并关闭文件，再写 `manifest.json`；manifest 记录终态、角色/模型/reasoning、Codex CLI 与 Git revision、有效配置和输入哈希，并列出除自身外每个文件的相对路径、字节数、SHA-256 与 Schema identity 或 media type。随后目录原子改名为 `runs/<run_id>/`；只有 `status=succeeded` 且完整结果校验通过的 manifest 才有资格原子替换 `current.json`，指针只含 Schema 版本、run ID 与 manifest SHA-256。

若在目录发布后、指针替换前中断，`resume` 必须复用该有效成功 run 并只完成指针，不再次调用 Codex。blocked、failed 与 interrupted run 也以终态 manifest 保存 attempt 审计，但没有 `result/` 且不得更新 `current.json`；崩溃遗留的 staging 只有在输入、Schema、prompt、namespace 及已有 attempt/capture 都能完整证明时，才在恢复时标为 interrupted 后终态化，不能被当成成功资产。歧义、reparse、foreign entry、partial result 或已有 terminal manifest 一律保持原位并停止恢复。

Interrupted recovery 允许 `0..3` 个严格连续的 attempt：`0` 表示首次 commitment 前终止；非末次 attempt 只能是机械 `timeout`。每个 attempt 必须重读并验证 canonical `attempt.json`、必有且不超过 16,777,216 bytes 的 `events.jsonl`、条件存在且不超过 1,048,576 bytes 的 `final_message.txt`，并从原始 events 重算四项 token 与 `usage_unavailable`。`failure_class=null` 还必须同时证明 `exit_code=0`、final 存在且 events framing有效；timeout/process_error不要求 final，也不从 capture内容猜测更细故障。任一矩阵不成立都属于无法证明的 staging，保持原位并停止恢复。

T14 的 `reading_result.json`、`candidate_drafts.json`、精确零字节 `candidate_knowledge.jsonl` 与空 `review_queue.json` 是一个不可分割的成功 Reader 结果；前两者使用版本化 Gezhi wrapper，manifest 记录实际 `candidate_draft_count`，同时固定 `candidate_count=0`。空 Candidate/Queue 文件只是固定清单中的“尚未物化”证据，不表示 T15 完成，也不允许后续原地填充。T15 从完整有效 Reader bundle 发布 [ADR 0135](../adr/0135-publish-candidate-materialization-as-an-immutable-successor.md) 的 `semantic/materializations/` 不可变 successor，以 input/manifest 绑定 Reader 文件实际哈希，并在独立 result 中保存 Descriptor Payload、正式 Candidate 与 Review Queue v2。正式 Review Queue 仍只是待审核投影而不是审核权威状态；`catalog.sqlite3` 通过扫描有效 terminal authority、正式 Candidate、Work-owned Review 与 Handoff 重建，并忽略 staging、无效 manifest 和未提交结果。

这个“成功 Reader 结果”只描述 Reader 子模块的不可变 publication，不等于七阶段 `read` 已成功。只有绑定它的有效 Candidate materialization successor 已提交或只修复 success current 后，公开 Resume 才把 `read` 列入 `advanced_stages`。非零 Candidate 随后停在 `review/awaiting_review`；零 Candidate 的其余空集合义务自动满足并完成管线。后续调用验证并复用两层 bundle，不再次调用 Codex。

Gezhi 自有领域 payload JSON 顶层带 `schema_version`；Gezhi 自有 JSONL 由首条 header/metadata 或每条独立记录提供 Schema identity，标准 `schema.json` 使用 JSON Schema `$id` 标识版本。Codex `events.jsonl` 与 `final_message.txt` 保持提供方原始字节，`prompt.txt` 也不是 JSON；三者不注入 Gezhi 字段。所有文件的实际 SHA-256 统一由 manifest 记录，manifest 不保存自己的自哈希，其 SHA-256 由 `current.json`、Review 或 Handoff provenance 记录。

## 超时、重试与用量审计

每个 Literature Codex attempt 必须满足 [ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md)：commitment 前由项目 resolver 证明唯一 native CLI，随后用 no-console/no-process-group、三项 stdio handle allowlist 与 suspended→attempt-exclusive Job→resume 的唯一顺序直接创建该 root，不经 `tools/codex.ps1`、PowerShell、shell 或隐藏 `--version` child。Prompt 通过专用 stdin pipe，`--json` 原始 bytes 通过专用 stdout pipe 形成 `events.jsonl`，stderr 唯一导向 `NUL`，`--output-last-message` 仍形成本合同的 `final_message.txt`；timeout/interruption 只通过 Job-owned tree stop，child exit 不反向生成父 cancellation。

每个 Codex attempt 的 wall-clock 超时为 30 分钟；首次调用后只对 T13 terminal evidence 已机械证明的 `timeout` 最多重试两次，退避依次为 10 秒和 30 秒，因此最多 3 个 attempt，整个 read 阶段 wall-clock 安全上限为 95 分钟。第一次成功启动形成的absolute `shared_deadline_monotonic_ns`必须从terminal evidence逐字传入后续每个retry plan；不得为第二或第三次attempt重建95分钟窗口，退避时间也自然消耗同一窗口。每次 attempt 必须使用完全相同且已哈希的 `input.jsonl`、`prompt.txt` 与 `schema.json`，启动全新进程和临时目录；任何 attempt 的部分输出都不进入下一次。超时必须终止整个 Codex 子进程树并保留批准上限内已有的原始 JSONL bytes。

Reader 为每个 attempt 独立冻结 `events.jsonl` 16,777,216 bytes与`final_message.txt` 1,048,576 bytes的逐文件cap；两项cap都包含端点，恰好等于cap不是overflow。第cap+1个实际byte才单调锁存`overflow=true`，正式资产只保留exact-cap prefix；若此时Job仍非空，orchestrator只执行一次整棵Job stop。安全收敛后该attempt固定为不可重试`failure_class=process_error`，公开结果为`failed: codex_process_failed`。Reader没有实际final source时仍不创建`final_message.txt`；不能为了形成固定pair补零字节文件。manifest与attempt inventory记录这些有界资产的实际byte length与SHA-256。两项Reader常量虽与Knowledge现值相同，但所有权、测试与演进独立；改变数值、端点、prefix、stop、failure mapping或缺失final语义都必须升级`literature_reader_v1`角色/合同版本。

实际 timeout attempts 耗尽时返回 `blocked: codex_timeout_exhausted`，manifest 记录每次 `failure_class=timeout`。公开 Literature adapter 不安装 Knowledge Ask 的 Ctrl+C cancellation bridge；外部终止不承诺形成 handled CLI 结果，下次 `resume` 才把可完整证明的遗留 staging 终态化为 `interrupted` audit run，且不自动重试该旧 attempt。共享 child 的 mechanical `interrupted` 组合能力不因此成为 T14 产品路径。已安全收尾的其他 provider terminal、未知非零退出、capture overflow 或事件结构故障统一使用 `failure_class=process_error` 与 `failed: codex_process_failed`，不自动重试，也不得从 message、stderr 或退出码猜测 network、429、5xx、runtime 或 context-window 类别。Commitment 前由 project resolver、认证或 launch-plan preflight 明确确认的 CLI/模型/能力不可用仍返回 `blocked: codex_runtime_unavailable` 且不创建 attempt；Schema、证据、Descriptor、身份或预算错误返回 failed，均不自动重试。

该保守分类由 [ADR 0129](../adr/0129-retry-only-mechanically-classified-codex-timeouts.md) 冻结，外部终止恢复边界由 [ADR 0131](../adr/0131-recover-literature-termination-on-the-next-resume.md) 冻结，Reader capture边界由 [ADR 0132](../adr/0132-bound-literature-reader-attempt-captures.md) 冻结。V1 不再拥有 `model_context_limit`、`codex_network_exhausted`、`codex_rate_limit_exhausted`、`codex_server_error_exhausted` 或 `codex_transient_exhausted` 终态。

只有 Codex 正常退出、最终 JSON 存在且 Schema、Evidence Block、Descriptor 与 Candidate 校验全部通过，semantic run 才能发布成功结果；超时前即使产生看似完整的 JSON 也不得发布。每个 attempt 记录 `input_tokens`、`cached_input_tokens`、`output_tokens`、`reasoning_output_tokens`、`started_at`、`finished_at`、`elapsed_ms`、`exit_code` 与 `failure_class`，manifest 同时保存逐次值与总计。CLI 未提供的 token 字段记为 `null` 并设置 `usage_unavailable`，不得因此使有效结果失败；首版不估算金额，也不依据模型自报 token 数中途终止。
