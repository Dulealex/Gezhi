# Knowledge Read v1 合同

状态：已冻结。本合同为 [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) 与 [T05 / Issue #6](https://github.com/Dulealex/Gezhi/issues/6) 绑定 `knowledge search`、`knowledge show` 的 V1 可观察语义；后续实现票据不得以 SQLite 表结构、旧 PaperBot 行为或临时 CLI 输出覆盖这里的约定。

相关权威边界包括 [Candidate Knowledge v1](./candidate-knowledge-v1.md)、[Knowledge Answerer v1](./knowledge-answerer-v1.md)、[CLI Command v1](./cli-command-v1.md)、[CLI JSON v1](./cli-json-v1.md)、[CLI Diagnostics v1](./cli-diagnostics-v1.md)、[Configuration v1](./configuration-v1.md)、[ADR 0010](../adr/0010-use-one-authoritative-store-per-context.md)、[ADR 0021](../adr/0021-use-deterministic-sqlite-retrieval-before-codex-synthesis.md)、[ADR 0022](../adr/0022-defer-promotion-and-label-candidate-backed-answers.md)、[ADR 0025](../adr/0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md)、[ADR 0031](../adr/0031-use-a-flat-auditable-knowledge-asset-tree.md)、[ADR 0032](../adr/0032-use-static-composition-and-context-deep-modules.md) 与 [ADR 0044](../adr/0044-separate-semantic-retrieval-view-from-ranking-audit.md)。Concrete diagnostic、Human 中文、process exit 与 executable acceptance 由 [Knowledge Read Diagnostics v1](./knowledge-read-diagnostics-v1.md) 闭合。

## 1. 职责与深模块边界

本合同冻结两个只读 operation：

- `KnowledgeReads.search(SearchQueryV1) -> KnowledgeSearchResultV1`：从当前 active Candidate 中做确定性发现；
- `KnowledgeReads.show(CandidateIdV1) -> KnowledgeShowResultV1`：按一个完整 Candidate ID 查看当前治理状态与可核验交接证据。

CLI adapter 只接收 [CLI Command v1](./cli-command-v1.md) 已识别的 raw `str`、选择 Human 或 JSON renderer，并把命令报告交给共享 presentation seam。Knowledge 深模块独占输入领域校验、Registry snapshot、确定性选择、Candidate/交接证据物化和结果 Schema；CLI 不拼 SQL、不读取 `imports/`、不选择 diagnostic，也不从 JSON stdout 反解析 Human 结果。

`search` 与 `knowledge ask` 可以复用 Knowledge 内部同一个确定性 Candidate selector，但该 selector 是私有深模块，不是第三个公开命令或通用 Repository port。`show` 使用单 Candidate detail materializer，不先做 search。未来 Context 通过 ADR 0032 的静态 composition 显式增加自己的 adapter；本合同不建立动态 Bot registry、entry-point discovery、Command Bus、万能 ReadResult 基类或尚无领域定义的空扩展层。

## 2. 固定入口顺序

只有 project-wide raw argv preflight、typed bootstrap checks、完整 grammar 与 route selection 已成功，且 ADR 0119 已只加载 selected Knowledge adapter 后，才进入本合同。两个命令分别按下列 fail-fast 顺序运行；第一项失败停止后续 gate，不并行 collect-all：

1. 校验 raw Query 或 Candidate ID；
2. 按 Configuration v1 解析并校验配置；
3. 只 safe-open `knowledge.data_root`，完成 namespace、reparse、final-path、父链与 File ID 证明；
4. 从同一已证明的 root anchor 只读打开固定 `registry.sqlite3`，验证 Registry generation 与本 operation 所需能力；
5. 在一个 SQLite read transaction 中取得一致 logical snapshot；
6. 执行 search selection 或 show lookup/materialization；`show` 只按 Registry 已绑定的 import identity 只读核验相应 `imports/<handoff_id>/manifest.json` 与 `candidates.jsonl`；
7. 验证 command result、形成 Human/JSON presentation candidate，再关闭 read transaction 与 handles；
8. 输出完整 receipt 并按 outcome 返回。

配置的两个 Context root 字符串仍共同参加纯词法交叉验证，但 physical gate 不得探测 `literature.data_root` 或未来 Context root。`show` 核验 Knowledge 自己保留的 Reviewed Handoff，不回开 Literature Data Root。`search` 不读取 `imports/`、`answers/` 或任何 Literature 资产。

## 3. SearchQueryV1

Parser 已冻结为 `knowledge search QUERY [--json]`，其中 QUERY 恰好是一个 raw positional token；引号只由调用 shell 形成一个 argv 元素，Gezhi 不做二次拆词、glob、环境变量、`~` 或 response-file 展开。

Query 领域校验必须按以下顺序执行：

1. 拒绝 NUL 与非配对 surrogate；
2. CRLF 与 CR 转为 LF，再做 Unicode NFC；
3. 在 `str.strip()` 前拒绝除 U+0009 TAB 与 U+000A LF 外的全部 Unicode General_Category `Cc`；
4. 使用 Python 3.11 `str.strip()`；空值为 `invalid_query`；
5. 规范 Query 必须同时不超过 2000 Unicode code point 与 8192 UTF-8 bytes；边界值合法，超限为 `query_too_large`；
6. 从该值形成与 Knowledge Answerer 完全相同的 `SearchTextV1`：CRLF/CR→LF、NFKC、Python 3.11 `casefold()`、control/separator→ASCII space、合并连续空白并去除首尾空白；
7. 技术词内部只保留 `+`、`#`、`.`、`_`、`/`、`-`，其他标点只作分隔；SearchText 为空、纯符号或只含一个 Han 字符为 `invalid_query`；
8. 按 Knowledge Answerer 的相同规则形成 `unicode61_atoms` 与 `trigram_atoms`；每路按 UTF-8 bytes 去重升序，任一路超过 128 项为 `query_too_complex`，不得截断。

上述任一输入失败都发生在配置、Data Root 与 Registry 之前。原始 Query 不直接进入 FTS `MATCH`，不得注入 `AND`、`OR`、`NOT`、列过滤或其他 FTS 语法。成功 result 的 `query` 字段是第 6 步得到的 `SearchTextV1.normalized_text`，不是 raw argv 回显；Query 不写入文件或数据库。

## 4. CandidateIdV1

Parser 已冻结为 `knowledge show CANDIDATE_ID [--json]`。V1 selector 必须完整匹配小写 ASCII `cand_[0-9a-f]{24}`，总长恰好 29 bytes；不 trim、不 case-fold、不接受前缀匹配、完整 payload hash、Work ID、Source ID、数组序号、别名或“最近一次”隐式状态。

格式不合法为 `invalid_candidate_id`，发生在配置与 I/O 前。格式合法但当前 Registry snapshot 没有该 ID 为 `candidate_not_found`。Candidate 当前为 withdrawn 不是 missing 或错误：`show` 必须成功返回历史内容和当前 withdrawn 治理状态；`search` 与 `ask` 则必须排除它。

## 5. 只读 Registry snapshot 与持久化禁令

`registry.sqlite3` 是 Knowledge 治理事实源，已校验的 `imports/<handoff_id>/` 是不可变跨 Context 导入证据。读取必须使用只读 SQLite connection、`query_only` 约束与单一 read transaction；临时查询状态只可在内存中形成。实现不得自动创建缺失 Data Root/Registry，不得迁移未知 Schema，不得用空数据库、旧 PaperBot 数据库、内存数据库、JSON 扫描或单路 FTS 作为 fallback。

一次 command 的所有 status、rank、Candidate bytes 与 import provenance 必须来自同一 logical Registry snapshot。`show` 对 content/status import 的实际 bytes 使用 Registry 中已经绑定的 Handoff ID 与文件 SHA-256，从同一 root anchor safe-open 并重新核验；核验期间 identity、hash 或 root proof 漂移必须失败，不能返回混合 revision。数据库内部表名、索引拆分和 row shape 仍由 Knowledge module 隐藏，不进入公共 result。

两个命令都不得：

- 执行 DML/DDL、checkpoint、migration 或 vacuum，或写 Registry logical state、main database pages、`imports/`、`answers/`、Literature 资产、日志、receipt 文件、marker、sidecar、cache 或 `current` 指针；已存在 WAL/SHM 中仅服务 read snapshot 的 SQLite lock/read-coordination metadata 不构成业务状态写入；
- 创建 Answer ID、Question/Query/Audit/View 文件、staging 目录或 writer mutex；
- 调用 Codex、OCR、embedding、向量数据库、模型 rerank、网络或任何子进程；
- 安装、同步、升级或替换依赖，或探测不被本 operation 消费的 capability。

成功 `result` 是本次一致读取的 process-level read receipt，不是 commit acknowledgment，也不承诺 transaction 关闭后 Candidate 仍保持同一状态。`search` 的每项携带 Candidate 内容 hash；`show` 还携带内容与当前状态所绑定的 import hashes。二者都不把本地 path、SQLite rowid、wall-clock、PID 或随机值写入 receipt。

## 6. 确定性 search selection

`search` 只允许 `review_status=accepted`、`intake_status=active`、`promotion_status=not_promoted` 的 Candidate 进入两路 FTS。可检索文本恰好是 Candidate 规范陈述、Candidate `source_terms`、已验证 Descriptor snapshot 的名称/来源术语与 Work 标题；证据摘录、Candidate 类型、年份、Review Risk Flag、审核时间、Handoff revision 和导入时间不加权。

两路规则与 Knowledge Answerer v1 完全相同：

- `unicode61 remove_diacritics 2`，连续 Han 字符形成去重重叠二字窗口；
- `trigram case_sensitive 0`，连续 Han 字符形成去重重叠三字窗口，非 Han 技术词至少 3 个 code point 才进入；
- 某一路没有合法 atom 时，该路成功返回空集合；FTS/tokenizer 不可用不是空集合；
- 四个字段权重全部为 `1.0`；每路先过滤 active，再按 `bm25 ASC, candidate_id ASCII ASC` 取最多 48 条，branch rank 从 1 连续递增；
- Python 按 Candidate 合并两路，以整数或 `fractions.Fraction` 精确比较 `Σ 1 / (12 + branch_rank)`；不得用 float 决定 RRF 并列；
- 最终按 `rrf_score DESC, candidate_id ASCII ASC` 取最多 12 条，rank 从 1 连续递增。

两路都必须成功；任一路执行失败都不得用另一支兜底。参与 branch rank/RRF 的 row 必须先通过 Candidate identity、active governance 与 FTS 关联一致性验证；任一已选 Candidate 再完整验证 `CandidateKnowledgeV1` 与 payload hash。不得静默丢弃损坏 Candidate 后补位、改变 rank 或缩减结果。两路成功且零匹配是正常成功空结果。

## 7. KnowledgeSearchResultV1

成功 `knowledge.search` result 必须且只能包含：

```json
{
  "candidate_count": 0,
  "items": [],
  "query": "normalized search text",
  "result_kind": "candidate_backed",
  "schema_version": "gezhi.knowledge_search_result.v1"
}
```

`candidate_count` 是 `0..12` 的 integer 且逐值等于 `items` 长度；空结果固定为 `candidate_count=0`、`items=[]`，仍使用 `result_kind=candidate_backed`。Items 按 rank 升序，每项必须且只能包含：

```json
{
  "candidate": {},
  "governance": {
    "intake_status": "active",
    "promotion_status": "not_promoted",
    "review_status": "accepted"
  },
  "rank": 1
}
```

示意中的 `candidate` 必须是完整、无额外字段且重新验 hash 的 `CandidateKnowledgeV1`，不是合法空 object；同一结果中 `candidate_id` 与 `payload_sha256` 都不得重复。由于 Candidate statement 本身包含完整 `EvidencePointerV1`，search result 保留可追溯指针，但不附 Citation snapshot、Descriptor 正文、证据摘录/page、Handoff/import receipt、query atoms、BM25、branch rank、RRF、Registry revision/hash 或未入选 Candidate。

`result_kind=candidate_backed` 是固定治理披露：结果不是 Promoted Knowledge、已验证事实或自动蕴含证明。Rank 只是本次确定性发现顺序，不是置信度、证据强度或 Promotion 分数。

## 8. KnowledgeShowResultV1

成功 `knowledge.show` result 必须且只能包含：

```json
{
  "candidate": {},
  "citation": {},
  "content_import": {},
  "descriptor_snapshots": [],
  "evidence_snapshots": [],
  "governance": {
    "intake_status": "active|withdrawn",
    "promotion_status": "not_promoted",
    "review_status": "accepted|rejected|deferred"
  },
  "result_kind": "candidate_backed",
  "schema_version": "gezhi.knowledge_show_result.v1",
  "status_import": {}
}
```

`candidate` 是完整 `CandidateKnowledgeV1`。`citation`、`descriptor_snapshots` 与 `evidence_snapshots` 必须逐项满足 Knowledge Answerer v1 已冻结的 `CitationSnapshotV1`、`DescriptorSnapshotV1` 与 `EvidenceSnapshotV1`：Descriptor 数量为 0–6 且与 Candidate references 完全同序；Evidence 数量为 1–42，恰好覆盖 Candidate statement 与全部 Descriptor payload 的 Evidence Pointer 去重并集，并按 `(canonical_content_sha256 ASCII ASC, block_id UTF-8 bytes ASC)` 排序。所有对象禁止额外字段；标题、作者、DOI/arXiv、excerpt 与 page 规则不因 show 放宽。

`content_import` 与 `status_import` 都是以下关闭 object：

```json
{
  "action": "accept|withdraw",
  "candidates_sha256": "<64 位小写十六进制>",
  "handoff_id": "hnd_<24 位小写十六进制>",
  "manifest_sha256": "<64 位小写十六进制>",
  "review_revision": 1
}
```

`handoff_id` 必须与 T04 Reviewed Handoff identity 完全相同：恰好 28 个 ASCII byte，并完整匹配 `hnd_[0-9a-f]{24}`；不得接受其他 safe component、大小写变体、完整 SHA-256 或前缀。`review_revision` 是 `1..9223372036854775807` 的 integer，boolean 非法。两个 SHA-256 分别绑定该 Handoff 实际 `manifest.json` 与 `candidates.jsonl` 的完整 bytes。

`content_import.action` 固定为 `accept`，指向提供当前 Candidate/Citation/Descriptor/Evidence 内容的最近合法 accepted revision。`status_import` 指向当前 Registry 状态的 revision：

- active 时，`review_status=accepted`、`status_import.action=accept`，且两个 import object 逐字段相等；
- withdrawn 时，`review_status` 只能为 `rejected|deferred`、`status_import.action=withdraw`、其 revision 严格大于 `content_import.review_revision`；正文仍来自最后 accepted content import，仅供历史审计；
- `pending` 表示该 Candidate payload 尚无 Review Decision，因而没有 Reviewed Handoff 可供 Knowledge Intake 应用；它不创建或更新 Candidate Registry 状态，也永远不能作为 `review_status` 出现在 `KnowledgeShowResultV1`。从未 accepted 的 pending Candidate 即使已有 Literature-side Candidate ID，该 ID 也不在 Knowledge Registry，`knowledge show` 返回 `candidate_not_found`。既有 accepted Candidate 若没有更晚的 Reviewed Handoff，其 Registry row、active 状态、`review_status=accepted` 以及逐字段相等的 content/status import 全部保持不变；若 Literature 产生不同 payload，则它具有不同 Candidate ID，不能借 pending 状态改写或重标记既有 ID。只有后续显式 `rejected|deferred` Decision 形成的合法 withdraw Handoff 才能撤回已导入 Candidate；
- `promotion_status` 在 V1 始终为 `not_promoted`。

每个 Pointer 必须在 content import 中恰好解析到一个已校验 Evidence snapshot。Knowledge 不因 show 回开 Literature Data Root；这里的可解析性是对 Knowledge 持有的不可变 Reviewed Handoff 证据与 Registry provenance 的验证，不伪称已重新读取 PDF、Canonical Asset 或完整 Reading Result。私有审核备注、reviewer identity、文件路径与未绑定原始内容不得进入 result。

## 9. 普通 search、show 与 Retrieval View 的边界

普通 `search` 只输出 Candidate、固定治理三态与 final rank；它不是 `RetrievalViewV1`，也不创建 `retrieval_query.json`、`retrieval_audit.json` 或 `retrieval_view.json`。普通 `show` 是 Candidate ID 直读详情，不做 FTS、RRF 或 Answer selection，也不是模型上下文。

`knowledge ask` 必须从自己的规范 Question 和当次 Registry snapshot 重新调用私有 selector，再独立冻结 Ranking Audit 与 Retrieval View。它不得把以前的 search output、rank 或 show detail 当作缓存 View。Retrieval View 继续独占模型可见的完整 Citation/Descriptor/Evidence materialization；Ranking Audit 继续独占 query atoms、BM25、branch rank、RRF 与 Registry provenance。Codex 永远不参与本合同两个命令的召回、过滤、重排、展示或诊断。

## 10. JSON binding、result cap 与稳定字节

`knowledge search --json` 与 `knowledge show --json` 使用共享 `CliResultEnvelopeV1`，`command` 分别精确为 `knowledge.search` 与 `knowledge.show`。跨字段矩阵固定为：

| outcome | result | diagnostics |
|---|---|---|
| `succeeded` | 对应完整 `KnowledgeSearchResultV1` 或 `KnowledgeShowResultV1` | `[]` |
| `blocked` | `null` | 恰好一个 [Knowledge Read Diagnostics v1](./knowledge-read-diagnostics-v1.md) blocked primary |
| `failed` | `null` | 恰好一个 [Knowledge Read Diagnostics v1](./knowledge-read-diagnostics-v1.md) failed primary |
| `interrupted` | 非法 | 非法 |

两个只读 binding 不建立 Knowledge Ask 的 handled cancellation bridge、Answer identity 或应用级 `interrupted/130`。外部/default Ctrl+C 或强制终止可能没有完整 receipt，不能由 top-level fallback 改写成 `interrupted` envelope。

完整 success envelope 必须先在内存中通过所有 Schema 与交叉验证，再按 CLI JSON v1 的 Python 3.11 canonical serializer 形成唯一 immutable UTF-8 buffer并追加一个 LF。两个命令的完整 envelope inclusive cap 都是 1,048,576 bytes；边界值合法，多 1 byte 固定改为 `blocked: result_too_large`、`result=null`，不得截断字符串、证据、Candidate 或结果尾项。该小型 blocked envelope 也必须在首次 stdout I/O 前完整形成并验证。

JSON stdout 恰好是 canonical object 加 LF，无 BOM、ANSI、raw CR、pretty print、第二个值或 stderr 副本。该 binding 显式采用 Windows binary fd1 同步 writer：首次 I/O 前一次 `msvcrt.setmode(1, os.O_BINARY)`，随后对同一 immutable buffer 用 direct blocking `os.write` 循环；单次请求最多 65,536 bytes，short write 只推进实际正整数 count。Setup、zero/越界 count、I/O 或 broken-pipe failure 后停止写入、不得输出 fallback，按 presentation failure 返回 `1`；可能观察到空输出或 exact buffer prefix。该规则不修改 `knowledge.ask` 的 65,536-byte cap 与 whole-remaining-suffix writer。

相同已验证 logical Registry snapshot 与相同 raw Query 必须产生逐 byte 相同的完整 search JSON；SQLite rowid、查询计划、wall-clock、物理 path、并发枚举顺序或 Python hash seed 不得影响 bytes。相同 Registry snapshot、相同 import bytes 与相同 Candidate ID 对 show 适用同一规则。JSON key 由 canonical serializer 排序；有领域顺序的 array 只能使用本合同规定的 rank、Candidate、Pointer、Descriptor 或书目顺序。
