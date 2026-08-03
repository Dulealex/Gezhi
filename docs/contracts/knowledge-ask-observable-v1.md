# Knowledge Ask Observable v1 合同

状态：已冻结。本文只关闭 `knowledge ask` 尚未冻结的四个可观察边界：`RetrievalAuditV1` 的精确结构与 View 超限测量、command-owned supplemental diagnostics、Human 中文 presentation，以及 JSON/Human presentation failure 的公开结果边界；可观察投影不得反向成为领域事实源，见 [ADR 0122](../adr/0122-keep-knowledge-ask-observability-outside-the-domain-result.md)。既有 [Knowledge Answerer v1](./knowledge-answerer-v1.md)、[Knowledge Ask Result v1](./knowledge-ask-result-v1.md)、[Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md)、[CLI JSON v1](./cli-json-v1.md)、[CLI Diagnostics v1](./cli-diagnostics-v1.md) 与 [Answer Terminal v1](./answer-terminal-v1.md) 继续拥有正常路径、primary、result、Answer 终态与 terminal/recovery 行为。

本文不改变 pre-ID gate、`answer_id` cutover、Answer manifest 三元组、primary union、`result` presence、JSON normal exit、Codex child 分类、Retrieval View 语义、writer ownership 或原子提交点。若本文与上述权威来源冲突，停止 T06 分支，不得以本文重解释既有事实。

## 1. 模块边界与顺序

Knowledge adapter 只通过以下四个窄接口越过可观察 seam；名称描述概念合同，不冻结 Python 文件、class 或函数签名：

1. `build_retrieval_audit(retrieval_snapshot, measured_retrieval_view)`：消费同一冻结 SQLite snapshot、两路结果、最终选择，以及一次形成并已完整验证的 immutable `MeasuredRetrievalViewV1`；返回完整不可变的 `RetrievalAuditV1` value。`measured_retrieval_view` 必须绑定 exact `bytes` object、实际长度、SHA-256 与 cap verdict。
2. `build_knowledge_supplementals(recovery_facts, attempt_facts)`：只把本文批准的内部事实映射为 `READY_DIAGNOSTICS`，或返回 typed `DIAGNOSTIC_PROJECTION_UNREPRESENTABLE`；它不选择或改写 primary、outcome、result、commit 或 recovery。
3. `prepare_knowledge_human(final_command_state, terminal_answer_verdict)`：消费与 JSON 相同的 final command facts；只有 `succeeded` 且本次 Answer 已 committed 时才消费 terminal reader 返回的 typed、manifest-bound `answer.md` verdict。
4. `present_knowledge_human(prepared_human)`：只呈现已经完整形成、验证且有界的 Human candidate；不重读 Answer、Registry、staging、配置或 cancellation state。

`RetrievalAuditV1` 必须在 `retrieval_view.json` 是否可发布之前完整形成。Supplemental constructor 在 command-state seal 前运行。正常 JSON/Human candidate 与 `outcome/result/diagnostics` 在同一个 [ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md) generation 中共同锁存；若 typed pre-I/O projection/presentation failure 使完整公开 surface 不可形成，则同一 generation 改为锁存第 5 节的 no-output failure candidate。两种 candidate 都必须先完成全部适用 command-owned resource settle、cancellation zero-in-flight 与 source release；所选 cancellation profile 到达 `RELEASED` 后才允许 presentation 或 terminal fail-stop。

## 2. `RetrievalAuditV1`

### 2.1 顶层闭包

`retrieval_audit.json` 顶层必须且只能包含以下九个 required key，所有嵌套 object 同样 `additionalProperties=false`：

```json
{
  "algorithm_version": "gezhi.fts5_dual_rrf_k12.v1",
  "branch_results": {
    "trigram": [],
    "unicode61": []
  },
  "final_selection": [],
  "query_atoms": {
    "trigram": [],
    "unicode61": []
  },
  "question_asset_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "registry_snapshot_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "retrieval_query_asset_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "retrieval_view_measurement": {
    "byte_length": 109,
    "limit_bytes": 262144,
    "sha256": "51aebe839e0caa991344efe4c0a19518b93a1d59aaa9bccbd1c6220a367641ec",
    "status": "within_limit"
  },
  "schema_version": "gezhi.retrieval_audit.v1"
}
```

机器可验证的结构闭包见 [Retrieval Audit v1 Schema](./schemas/retrieval-audit-v1.schema.json)；跨数组身份、排序、RRF 算术与规范字节等语义不变量仍以本文为准，不能只做 JSON Schema validation。

`algorithm_version` 与 `schema_version` 是上述 exact ASCII 常量。三个 SHA-256 字段都使用 64 位小写十六进制：`question_asset_sha256` 和 `retrieval_query_asset_sha256` 分别覆盖已安装文件的完整 raw bytes，包含其唯一末尾 LF；`registry_snapshot_sha256` 按第 2.2 节计算。Audit 不内嵌 Question、SQL、数据库路径、原始 Registry 文件 bytes、未验证文本、异常或模型输入。

### 2.2 Registry snapshot identity

检索 transaction 中全部 `intake_status=active` 的 Candidate 使用同一 SQLite read snapshot 与一个 `ORDER BY candidate_id COLLATE BINARY ASC` cursor 流式读取。下列 object 是 identity 的**概念 CanonicalJson 值**，用于定义字段集合和最终 hash；production 不得把完整 `entries` array 或等价 O(N) object materialize 到内存：

```json
{
  "entries": [
    {
      "candidate_id": "cand_<24 lowercase hex>",
      "payload_sha256": "<64 lowercase hex>",
      "review_revision": 1,
      "search_projection_sha256": "<64 lowercase hex>"
    }
  ],
  "schema_version": "gezhi.registry_retrieval_snapshot_identity.v1"
}
```

该 object 不作为额外资产保存。Hasher 必须依次接收 exact ASCII prefix `{"entries":[`；随后对每个 cursor row 构造一个有界、单项 canonical entry bytes，首项前不加 comma、后续项前恰加一个 ASCII comma；最后接收 exact ASCII suffix `],"schema_version":"gezhi.registry_retrieval_snapshot_identity.v1"}`，**不追加 LF**。空 snapshot 因而直接 hash prefix+suffix。该 streaming byte sequence 必须逐 byte 等于把上述概念 object 交给 Python 3.11 `json.dumps(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))` 得到的 UTF-8 bytes；其 SHA-256 才是 `registry_snapshot_sha256`。

每个 row 在 feed 前必须逐项验证 closed entry、规范 ID/hash、`candidate_id == "cand_" + payload_sha256[:24]`、`review_revision` 是 `1..9223372036854775807` 的 non-boolean integer，以及 projection hash 与同一 row 的实际 base projection 相等。Cursor 必须严格递增；只保存 previous `candidate_id` 即可拒绝乱序或重复。`payload_sha256` 的重复必然产生相同前 24 hex、进而产生相同 `candidate_id`，所以同一相邻检查同时证明两个字段各自唯一；不得为唯一性建立 O(N) set。实现除当前有界 row/entry bytes、incremental SHA-256 state、previous ID 与 checked scalar counters 外只允许 O(1) 额外内存。

`search_projection_sha256` 覆盖同一 transaction 中四个 FTS 字段共用的 `SearchProjectionBaseV1`。投影 object 必须且只能含 `candidate_statement`、`candidate_source_terms`、`descriptor_terms`、`work_title` 与 `schema_version=gezhi.candidate_search_projection.v1` 五项，前四项按以下唯一 source sequence 形成：

| field | source scalar sequence |
|---|---|
| `candidate_statement` | 只含 `candidate.payload.statement.text` |
| `candidate_source_terms` | `candidate.payload.statement.source_terms` 的既有 UTF-8 bytes canonical 顺序 |
| `descriptor_terms` | 按 `candidate.payload.descriptor_refs` 的既有 canonical 顺序遍历；每个 `method` 先取已验证 Descriptor payload 的 `value.text`，其他 kind 先取 `value.label`，随后取该 Descriptor `value.source_terms` 的既有 UTF-8 bytes canonical 顺序 |
| `work_title` | 由 `candidate.payload.work_id` 解析出的已验证 Work 书目 title（形成 View 时即 `CitationSnapshotV1.title`）；title 为 null 时为空 sequence，否则只含该 title |

每个 source scalar 必须**独立**执行 [Knowledge Answerer v1](./knowledge-answerer-v1.md) 的 SearchTextV1 基础规范化：CRLF/CR→LF、NFKC、Python 3.11 `str.casefold()`、control/separator→ASCII space、连续空白合并并 trim。规范化后为空的 fragment 丢弃；其余 fragment 按上述遍历顺序用且只用一个 ASCII space连接；全部 fragment 为空时结果是 empty string。禁止先连接 raw scalars 再整体规范化，因为这会改变边界语义。

Base projection object 以上述 canonical JSON 参数编码、不追加 LF并计算 `search_projection_sha256`。`trigram case_sensitive 0` 的四个实际索引字段直接使用这四个 base strings；`unicode61 remove_diacritics 2` 的四个实际索引字段分别从同一个 base string 纯函数派生，继续使用 Knowledge Answerer v1 已冻结的 Han 重叠二字窗口与非 Han token 规则。`algorithm_version` 与 base projection 唯一决定两路实际 FTS 输入；hash 直接覆盖的是 base projection canonical bytes，而不是未持久化的 unicode61 派生 bytes。不得从 FTS table bytes、rowid、SQLite page/WAL、查询时间或数据库文件 hash 形成 projection/snapshot identity。

同一 transaction snapshot 必须同时供 streaming snapshot identity、两路 FTS、最终选择与 View 物化使用。任一环节重开另一 snapshot、revision/payload/base projection/派生输入不一致或 Registry item identity 无法证明，返回既有 `failed: retrieval_materialization_failed`，不得发布近似 Audit。

### 2.3 Query atoms

`query_atoms.trigram` 与 `query_atoms.unicode61` 必须分别逐项等于已验证 `retrieval_query.json` 的 `trigram_atoms` 与 `unicode61_atoms`。每个 array 为 0–128 个 nonempty SearchTextV1 atom，按 UTF-8 bytes 严格升序、无重复；不得保存 FTS `MATCH` quoting、`OR` 拼接文本、SQL、绑定参数或原始 Question。两项都为空只可能形成正常零匹配，不是查询失败。

### 2.4 Branch results 与原始 BM25

`branch_results.trigram` 与 `.unicode61` 各为 0–48 项。每项必须且只能包含：

```json
{
  "bm25_float64_hex": "-0x1.0000000000000p+0",
  "candidate_id": "cand_<24 lowercase hex>",
  "payload_sha256": "<64 lowercase hex>",
  "rank": 1,
  "review_revision": 1,
  "search_projection_sha256": "<64 lowercase hex>"
}
```

`bm25_float64_hex` 是 SQLite/Python 接收的同一 finite binary64 值调用 Python 3.11 `float.hex()` 得到的 exact lowercase ASCII string；`NaN`、正负 infinity、无法 round-trip，或 `float.fromhex(value)` 后再次 `float.hex()` 不逐 byte 相等均失败。实现不能把分数四舍五入、转十进制字符串或 JSON float。每个 branch 内 `candidate_id` 唯一；数组必须按 `rank=1..N` 连续排列，并同时满足 `(numeric BM25 ASC, candidate_id ASCII ASC)`。

每项身份四元组必须存在于第 2.2 节同一 snapshot entry，且逐字段相等。某 Candidate 可以出现在两路；两路中的 payload/revision/projection 必须相同。某一路没有 query atom 时该 array 必须为空。

### 2.5 Final selection 与精确 RRF

`final_selection` 为 0–12 项，按 `final_rank=1..N` 连续排列。每项必须且只能包含：

```json
{
  "candidate_id": "cand_<24 lowercase hex>",
  "final_rank": 1,
  "payload_sha256": "<64 lowercase hex>",
  "review_revision": 1,
  "rrf_denominator": 13,
  "rrf_numerator": 2,
  "search_projection_sha256": "<64 lowercase hex>",
  "trigram_rank": 1,
  "unicode61_rank": 1
}
```

两个 branch rank 各为 `null` 或 `1..48` non-boolean integer，至少一个非 null，并逐项指向对应 branch 中同一 Candidate。身份字段与 branch/snapshot 完全相等。`rrf_numerator` 与 `rrf_denominator` 是 `Σ 1/(12+branch_rank)` 约分到最简项后的正整数；`gcd=1`，分母非零，checked arithmetic 不得溢出 signed 64-bit。数组必须按 exact fraction 降序，再按 `candidate_id` ASCII 升序；final selection 恰好是两路 union 的前 `min(12, union_count)`，不能删除、替换或重排 Candidate。

`RetrievalViewV1.items[*].rank` 与 Candidate 身份必须逐项等于 `final_selection`；零 selection 必须对应 `candidate_count=0,items=[]`。

### 2.6 View measurement 与超限分支

View materializer 必须先完成全部 `RetrievalViewV1` Schema、identity、排序、材料与跨字段验证，再对该完整 value **恰好一次**执行 canonical JSON serialization 并追加一个 LF，得到单一 immutable `bytes` object。`MeasuredRetrievalViewV1` 只绑定该 object identity、`len(buffer)`、覆盖同一 buffer 全部 bytes 的 SHA-256 与下列 cap verdict；后续不得重新序列化“等值”View、替换 bytes object、只 hash prefix 或从临时文件反推 measurement。

`retrieval_view_measurement` 必须且只能含：

| field | rule |
|---|---|
| `byte_length` | measured buffer 的实际长度，`0..9223372036854775807` non-boolean integer |
| `limit_bytes` | exact integer `262144` |
| `sha256` | measured buffer 的 SHA-256，64 位小写十六进制 |
| `status` | exact closed enum：`within_limit` 或 `too_large` |

Measured buffer 无 BOM、raw CR 或第二个 value。`status=within_limit` 当且仅当 `byte_length <= 262144`；`status=too_large` 当且仅当 `byte_length > 262144`。262144 合法，262145 必须超限。Hash 总是覆盖包含 LF 的完整 buffer。

`within_limit` 时，Audit 必须先使用该 measurement 完整形成并安装为 P3；随后 View asset installer 只能接收并写出 **同一 `MeasuredRetrievalViewV1.buffer` object**，不得接受重新编码、内容相等的副本或从文件回读构造的替代值。`retrieval_view.json` manifest asset 的 `byte_length` 与 `sha256` 必须逐值等于 Audit measurement，实际文件 bytes 必须逐 byte 等于该 buffer。Writer readback、terminal validator 与 orphan recovery 都必须交叉验证以下四者完全相等：Audit measurement、View manifest asset pair、View 实际 length/hash、View canonical bytes；任一不等整体拒绝。View 形成、写入、关闭、安装、hash/readback、manifest binding 或交叉复验失败时，撤销未完成 View、保持最后合法 P3，并使用既有 `failed: retrieval_materialization_failed`，不能改写 measurement 为 `too_large`。

`too_large` 时必须同时成立：

- `final_selection` 已完整冻结，Audit 自身完整合法；
- terminal Answer 为 committed `status=blocked,error.code=retrieval_view_too_large,error.stage=retrieval`，根级资产只到 P3；
- `retrieval_view.json`、Codex prompt/schema、attempt 与正式结果对全部缺席；
- primary 仍精确为 `{"code":"knowledge.ask.retrieval_view_too_large.v1","context":{}}`，实测长度与 hash 不进入 diagnostic/result/Human；
- measured View buffer 只可在内存或 writer-private 临时位置存在，绝不交给 View asset installer；terminal manifest 前必须释放/撤销，不能截断、压缩、删 Candidate/Descriptor/Evidence、换模型或改成 audit 输入。

### 2.7 Audit bytes、零 View witness 与超限 fixture

完整 Audit 使用 Python 3.11 canonical JSON 参数，UTF-8 bytes 后恰好追加一个 LF；无 BOM、raw CR、pretty print、NaN/Infinity 或额外 value。实际文件必须不超过 [Answer Terminal v1](./answer-terminal-v1.md) 的 `2,097,152` bytes inclusive cap；超限、serialization、写入或复验失败使用既有 `retrieval_materialization_failed`，不能省略 branch item 或 query atom来抢救。

第 2.1 节示例中的 measurement 是可执行零 View witness，精确对应以下完整 bytes：

```text
{"answer_kind":"candidate_backed","candidate_count":0,"items":[],"schema_version":"gezhi.retrieval_view.v1"}\n
```

其中 code fence 中的 `\n` 表示一个 raw `0x0A`，不是两个可见字符；完整长度必须为 `109`，SHA-256 必须为 `51aebe839e0caa991344efe4c0a19518b93a1d59aaa9bccbd1c6220a367641ec`。

下面只说明 `too_large` Audit 的字段形状；因为没有附带产生 measurement 的完整 would-be View bytes，它**不是**完整合法 witness，placeholder hash 也不得作为验收证据：

```json
{
  "algorithm_version": "gezhi.fts5_dual_rrf_k12.v1",
  "branch_results": {
    "trigram": [],
    "unicode61": []
  },
  "final_selection": [],
  "query_atoms": {
    "trigram": [],
    "unicode61": []
  },
  "question_asset_sha256": "<actual question asset sha256>",
  "registry_snapshot_sha256": "<actual registry snapshot sha256>",
  "retrieval_query_asset_sha256": "<actual retrieval query asset sha256>",
  "retrieval_view_measurement": {
    "byte_length": 262145,
    "limit_bytes": 262144,
    "sha256": "<actual measured View sha256>",
    "status": "too_large"
  },
  "schema_version": "gezhi.retrieval_audit.v1"
}
```

可执行 boundary fixture builder 必须从一个固定、完整、Schema-valid 的 View fixture 开始：恰有 12 个 item，每个 item 恰有 42 个合法且不同的 `evidence_snapshots`，每个 `excerpt` 初始为一个 ASCII `x`，其他字段使用固定的最小合法值。Builder 按 `items.rank`、再按 `evidence_snapshots` canonical 顺序遍历 `excerpt`，只追加 ASCII `x` 并保持各字段在已批准的 `1..800` code-point 范围内；每次追加恰增加一个 raw byte。它必须先断言初始长度不超过目标且剩余合法 padding 容量足以越过目标，在计算每次 measurement 前重新执行完整 View validator，并确定性地产生 canonical byte length 恰为 `262143`、`262144` 与 `262145` 的三个 value。测试对每个 value 恰好序列化一次、从实际 buffer 计算 SHA-256并要求 Audit measurement 相等；前两者安装同一 buffer，最后一者绝不调用 View installer。不得用脱离上述合法 fixture 的手写 buffer、单独重复字符 blob 或 placeholder hash 代替实际 bytes/hash equality 证明。

## 3. Supplemental diagnostics

### 3.1 Closed union

除共享 module 保留的 `cli.diagnostics_omitted.v1` 外，`knowledge.ask` V1 只新增以下五个 supplemental code；它们永远不能成为 primary、不能改变 outcome/result/commit，也不能写入 Answer manifest 或其他持久资产：

| code | required context | source fact |
|---|---|---|
| `knowledge.ask.capture_overflow.v1` | 恰为 `{"channels":["events"]}`、`{"channels":["events","final_message"]}` 或 `{"channels":["final_message"]}` | 当前 committed failed Answer 的最后一个 Codex attempt 已确认一个或两个 capture overflow latch |
| `knowledge.ask.orphan_quarantined.v1` | `{"count":N}` | 历史 staging candidate 在 rename 资格前因 basename/safety/terminal validation/cap 失败而原地逻辑隔离 |
| `knowledge.ask.orphan_recovered.v1` | `{"count":N}` | 历史完整 orphan 的 non-replacing rename 明确成功 |
| `knowledge.ask.orphan_recovery_failed.v1` | `{"count":N}` | 已具备 rename 资格，但 rename 明确返回非 target-exists 的其他确定 candidate-local failure |
| `knowledge.ask.orphan_target_conflict.v1` | `{"count":N}` | 完整有效 staging 的 expected target 在检查时已存在，或 rename 明确返回 target-exists |

`count` 必须是 `1..9223372036854775807` non-boolean integer。每种事实用 checked addition 聚合。若真实 scan operation 已独立证明 `.staging/` 无法安全枚举，或 invocation-wide scan protocol 无法建立/完成，才可按既有领域合同选择 no-commit primary `knowledge.ask.orphan_scan_failed.v1`；该事实必须先于 supplemental projection 且不由 count 推导。

Scan 已成功完成后，某一 supplemental count 的数学值无法表示在上述范围内，只表示公开诊断投影不可表示。`build_knowledge_supplementals` 必须返回 typed `DIAGNOSTIC_PROJECTION_UNREPRESENTABLE`，不得截断、饱和、发 omission item、改写为 orphan scan failure，或改变已经确定的 primary、outcome、result、commit、manifest 与 recovery facts。该 verdict 阻止 JSON/Human 的完整 error surface，随后只可进入第 5 节共同的 pre-I/O no-output failure seam。

`channels` 必须是按 ASCII bytes 严格升序、无重复的非空 subset：`["events"]`、`["events","final_message"]` 或 `["final_message"]`。它不携带 observed bytes、tail、path、attempt ordinal、Win32 code、provider text或 capture 内容。

### 3.2 Orphan 的 one-hot 分类

每个被安全枚举的 staging direct child 最多贡献一个 supplemental fact：

1. basename、路径、安全、terminal validation 或任一 cap 未通过：`orphan_quarantined`；不派生不安全 target。
2. Candidate 完整有效但 expected target 已存在，或唯一 rename 返回 target-exists：`orphan_target_conflict`。
3. Candidate 完整有效、target 缺席且唯一 rename 返回其他确定 candidate-local failure：`orphan_recovery_failed`。
4. 唯一 rename 明确成功：`orphan_recovered`。

Uncertain rename completion 不属于任何 supplemental；它按 Answer Terminal v1 立即停止且不形成正常 outcome。Invocation-wide enumeration/root/ownership failure使用既有 primary，不伪装成 candidate-local count。相同 candidate 不能同时计入 quarantined 与 target conflict；分类只依据本次持锁完整检查和唯一 rename observation，不复用历史日志、mtime、PID 或旧 validator 结果。

Orphan supplementals 只允许出现在：任意 non-null committed result 的四种 outcome，或 `result=null` 且 outcome 为 `failed` 或 `interrupted`。`result=null,outcome=blocked` 在 writer scan 前已经停止，禁止 orphan supplemental。

### 3.3 Capture overflow binding

`capture_overflow` 只允许与以下 exact cross-field matrix 同时出现：

- `outcome=failed` 且 `result` 为本次 committed Answer receipt；
- primary 为 `knowledge.ask.codex_process_failed.v1`；
- terminal manifest 为 `status=failed,error.code=codex_process_failed,error.stage=synthesis`；
- 最后一个 attempt 的 `failure_class=process_error`，且本文 channels 与内部两个 confirmed monotonic overflow latch 一一对应；
- overflow attempt 后没有 retry、backoff、validation 或新 commitment。

普通 process/lifecycle/event-structure failure 没有 confirmed overflow latch时不得发该 item。Exact-cap clean EOF 不是 overflow。Prefix/tail bytes、内部 Job stop DWORD 与 provider exit 都不进入 context。

### 3.4 Role、排序与 maintenance absence

Command adapter 先构造合法 primary，再聚合本文 supplementals；共享 `DiagnosticSetV1` 按 code ASCII bytes 排序、执行同码唯一、16-item/16,384-byte caps并在需要时生成最后一项 `cli.diagnostics_omitted.v1`。本文五项不得按发现时间、candidate ID、严重度或线程完成顺序重排。

V1 的 Answer maintenance mutating action set 仍为空。没有 `maintenance_required`、`cleanup_available`、`orphan_deleted`、`quarantine_moved` 或通用 warning code；`status` 与 `doctor` 都只观察，不移动、删除、修补、恢复或重写 Answer，且 `doctor` 只检查 Operations v1 冻结的七项环境能力。缺少显式 maintenance interface 本身不是 diagnostic。

## 4. Human presentation

### 4.1 Authoritative candidate、channel 与 cap

Human mode 与 JSON mode 消费相同的 final `outcome/result/diagnostics` facts；只有完整 diagnostics 可表示时才形成正常 candidate。它不构造 JSON envelope，也不受 65,536-byte JSON cap；它为每个 coherent generation 恰好形成一个不可变 UTF-8 semantic buffer，最大 `532480` bytes inclusive（512 KiB `answer.md` cap + 8 KiB fixed Human envelope）。532480 合法，532481 只能成为第 5.2 节 typed cap verdict。正常 buffer 无 BOM、raw CR、NUL、行尾空白或第二个 payload；物理换行只用 LF并恰好一个末尾 LF。

Human candidate 必须在 command-state seal 前完整形成并验证；presentation 开始前不得向 stdout/stderr 写任何 progress、spinner、log、traceback、prompt 或 partial result。完整 handled Human presentation只写 stdout，stderr 必须为空。Interactive Rich 最多为可信 label 增加 ANSI style/box decoration；不得折叠、截断、重排、改写语义行或 `answer.md` 内容。Redirected/non-color subprocess 的规范 bytes 是下节精确格式且无 ANSI。

`succeeded` 时 adapter 必须调用 Answer Terminal 的窄 typed reader，且只接受 `TERMINAL_ANSWER_BYTES_READY`：其中 exact `answer.md` bytes 已通过 terminal validator，并与本次 committed proof、manifest length/hash 和正式 asset identity 一致。`TERMINAL_ANSWER_BYTES_REJECTED` 不改变 committed Answer 或业务 outcome，只进入第 5.2 节 Human-only no-output kind；renderer 不得把 reader 抛出的异常捕获成该 verdict。不得从 `result.answer_output` 重新渲染、读取 staging/其他历史 Answer、改用 raw Codex output或发布 Markdown 近似副本。其他 outcome 按 Answer 合同没有 `answer.md`，Human candidate 禁止读取或显示残留输出。

### 4.2 Exact semantic layout

首行只由 outer outcome 决定：

| outcome | exact first line |
|---|---|
| `succeeded` | `Knowledge ask：完成` |
| `blocked` | `Knowledge ask：已阻塞` |
| `failed` | `Knowledge ask：失败` |
| `interrupted` | `Knowledge ask：已中断` |

随后严格按以下顺序：

1. `result` 非 null时一行 `Answer ID：<answer_id>`；`result=null` 时整行缺席。
2. 非 succeeded 的唯一 primary 映射一行 `原因：<第 4.3 节正文>`；succeeded 无原因行。
3. 每个 supplemental 按 diagnostics array 顺序各映射一行 `提示：<第 4.4 节正文>`；primary不重复为提示。
4. 一行 `下一步：<正文>`。非 succeeded 使用 primary catalog；succeeded 若含 `cli.diagnostics_omitted.v1` 或任一 quarantined/recovery_failed/target_conflict，固定为 `运行 gezhi status 观察历史 Answer 异常；status 不会修复、移动、删除或恢复 Answer 目录`，否则为 `无需操作`。
5. succeeded 再输出一个空行，然后逐 byte追加 exact committed `answer.md`；其他 outcome 在“下一步”行末尾 LF后立即结束。

ID、count 与 channel 只能来自 sealed result/diagnostic。Integer 使用无正号、无前导零 ASCII 十进制；不本地化。不得显示 path、Question 原始 argv、配置、异常、provider文本、PID、Win32 code、模型 session、raw capture、Audit 实测长度或 hash。

### 4.3 Primary Human catalog

机器 code 不变；下表只冻结 Human 原因与下一步。所有正文不含句末句号，renderer不得同义改写。

下表中的 `gezhi status` 只观察历史/当前 Work、Registry、Answer 与 recovery 风险，绝不修复、移动、删除、恢复或重写资产。`gezhi doctor` 只检查 Operations v1 的七项能力：configuration、core Python、core dependencies、Literature Data Root、Knowledge Data Root、OCR runtime 与 Codex runtime；它不检查或修复某个历史 Answer、Registry row、commit、staging 或 recovery 结果。

| primary code | exact 原因正文 | exact 下一步正文 |
|---|---|---|
| `knowledge.ask.fts5_unavailable.v1` | SQLite FTS5 双路检索能力不可用 | 在外部恢复项目 Python 的 SQLite FTS5 双路能力后重新提问 |
| `knowledge.ask.retrieval_view_too_large.v1` | 检索视图超过 262144 字节上限 | 使用更具体的问题重新提问；保留 Answer ID 作为本次超限审计 |
| `knowledge.ask.retrieval_query_failed.v1` | Candidate Registry 检索查询失败 | 运行 gezhi status 观察 Knowledge 状态（status 不会修复），保留 Answer ID 并在外部修复后重新提问 |
| `knowledge.ask.retrieval_materialization_failed.v1` | 检索审计或候选材料未能完整验证 | 运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）；保留 Answer ID 且不要手动修补 Answer |
| `knowledge.ask.codex_runtime_unavailable.v1` | 冻结的 Codex CLI 运行能力不可用 | 运行 gezhi doctor 检查项目 Codex CLI 与登录能力，恢复后重新提问 |
| `knowledge.ask.codex_timeout_exhausted.v1` | Codex 回答尝试已耗尽超时预算 | 稍后重新提问；若持续发生，运行 gezhi doctor 检查 Codex 环境能力 |
| `knowledge.ask.codex_network_exhausted.v1` | Codex 回答尝试因网络问题耗尽 | 恢复网络后重新提问 |
| `knowledge.ask.codex_rate_limit_exhausted.v1` | Codex 回答尝试因速率限制耗尽 | 稍后重新提问 |
| `knowledge.ask.codex_server_error_exhausted.v1` | Codex 回答尝试因服务端错误耗尽 | 稍后重新提问 |
| `knowledge.ask.codex_transient_exhausted.v1` | Codex 回答尝试因多种瞬时问题耗尽 | 稍后重新提问；若持续发生，运行 gezhi doctor 检查 Codex 环境能力 |
| `knowledge.ask.synthesis_input_invalid.v1` | Codex 回答输入包未通过本地验证 | 运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复），保留 Answer ID 并检查本地输入形成 |
| `knowledge.ask.codex_process_failed.v1` | Codex 子进程或捕获链失败 | 先运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）；必要时运行 gezhi doctor 检查 Codex 环境能力 |
| `knowledge.ask.answer_output_invalid.v1` | Codex 回答未通过结构、引用或状态校验 | 重新表述问题后提问；若持续发生，运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复） |
| `knowledge.ask.citation_link_construction_failed.v1` | 来源标识符无法形成安全引用链接 | 运行 gezhi status 观察整体 Work 与 Knowledge 状态（status 不会修复），在外部修正 DOI 或 arXiv 身份后重新提问 |
| `knowledge.ask.answer_rendering_failed.v1` | 可读 Answer 未能确定性渲染 | 运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复），保留 Answer ID 并检查确定性渲染 |
| `knowledge.ask.user_interrupted.v1` | 用户中断了已经建立身份的本次回答 | 如仍需要答案，请重新运行 knowledge ask |
| `knowledge.ask.invalid_question.v1` | 问题为空、语义不足或包含不支持的控制字符 | 输入一个单轮、自包含且可读的问题后重试 |
| `knowledge.ask.question_too_large.v1` | 问题超过 2000 个 Unicode code point 或 8192 个 UTF-8 字节 | 缩短问题后重试 |
| `knowledge.ask.question_too_complex.v1` | 问题产生的安全检索原子超过上限 | 减少并列术语或拆成更具体的单轮问题后重试 |
| `knowledge.ask.configuration_invalid.v1` | 格致配置的格式、版本或字段无效 | 运行 gezhi doctor 检查配置能力，并在外部修正版本化配置后重试 |
| `knowledge.ask.configuration_incompatible.v1` | 格致配置与冻结的运行角色不兼容 | 恢复与当前版本匹配的冻结配置后重试 |
| `knowledge.ask.provenance_unavailable.v1` | 无法形成本次运行所需的仓库 provenance | 在外部恢复可验证的 Git provenance 后重试 |
| `knowledge.ask.data_root_unavailable.v1` | Knowledge 数据目录不存在、不可访问或不是普通本机目录 | 运行 gezhi doctor 检查 Knowledge Data Root 能力，并在外部恢复已配置目录后重试 |
| `knowledge.ask.data_root_unsafe.v1` | Knowledge 数据目录违反本机路径或隔离安全边界 | 运行 gezhi doctor 检查 Knowledge Data Root 能力，并在外部改用安全且隔离的本机目录 |
| `knowledge.ask.data_root_identity_unavailable.v1` | 无法取得 Knowledge 数据目录的稳定物理身份 | 运行 gezhi doctor 检查 Knowledge Data Root 能力，并改用支持稳定文件身份的本机文件系统 |
| `knowledge.ask.answer_writer_busy.v1` | 另一个 knowledge ask 正在写入同一 Knowledge 数据目录 | 等待另一个回答完成后重试 |
| `knowledge.ask.answer_writer_coordination_unavailable.v1` | 无法建立 Knowledge Answer 单写者协调 | 运行 gezhi status 观察 Knowledge 状态（status 不会修复），在外部恢复 Windows 单写者协调后重试 |
| `knowledge.ask.pre_answer_formation_failed.v1` | Answer 身份建立前的本地审计对象形成失败 | 运行 gezhi status 观察整体状态（status 不会修复），保留现场并检查本地对象形成 |
| `knowledge.ask.data_root_integrity_lost.v1` | Knowledge 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi status 观察完整性风险（status 不会修复）；必要时运行 gezhi doctor 检查当前 Data Root 能力 |
| `knowledge.ask.orphan_scan_failed.v1` | 历史 Answer staging 无法安全完成扫描 | 运行 gezhi status 观察 staging 风险（status 不会修复）；不要手动移动、删除或修补 staging |
| `knowledge.ask.answer_staging_failed.v1` | 本次 Answer staging 或非终态资产形成失败 | 运行 gezhi status 观察 staging 风险（status 不会修复），保留现场后检查存储与权限 |
| `knowledge.ask.answer_manifest_failed.v1` | 本次 Answer terminal manifest 形成或复验失败 | 保留 staging 并运行 gezhi status 观察 staging 与 Answer 整体状态（status 不会复验或修复 manifest）；不要手动补写 manifest |
| `knowledge.ask.answer_target_conflict.v1` | 本次 Answer 的同身份正式 target 已存在 | 运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会判定或修复该冲突）；不要覆盖、删除或合并现有 Answer |
| `knowledge.ask.answer_commit_failed.v1` | 本次 Answer 的原子目录提交确定失败 | 保留 staging 并运行 gezhi status 观察 staging 与 Answer 整体状态（status 不会判定或修复该提交），再在外部检查存储 |
| `knowledge.ask.user_interrupted_before_answer.v1` | 用户在 Answer 身份建立前中断了本次请求 | 如仍需要答案，请重新运行 knowledge ask |

### 4.4 Supplemental Human catalog

| supplemental code/context | exact 提示正文 |
|---|---|
| `capture_overflow`, `channels=["events"]` | Codex 事件捕获超过 16777216 字节上限，已保留精确上限前缀 |
| `capture_overflow`, `channels=["final_message"]` | Codex 最终消息捕获超过 1048576 字节上限，已保留精确上限前缀 |
| `capture_overflow`, both | Codex 事件与最终消息捕获均超过各自上限，已保留精确上限前缀 |
| `orphan_quarantined` | 发现 `<count>` 个无法安全恢复的历史 Answer staging，已原地逻辑隔离 |
| `orphan_recovered` | 已恢复并提交 `<count>` 个完整历史 Answer |
| `orphan_recovery_failed` | 有 `<count>` 个历史 Answer 的确定性恢复提交失败，staging 已原地保留 |
| `orphan_target_conflict` | 有 `<count>` 个历史 Answer 因同身份 target 已存在而未恢复 |
| `cli.diagnostics_omitted.v1` | 另有 `<count>` 项运行提示因诊断容量上限未显示 |

### 4.5 Redirected exact witnesses

成功且 `answer_status=insufficient_evidence` 的完整 stdout witness（stderr empty；code fence 后不显示额外字节，实际最后一行后恰好一个 LF）：

```text
Knowledge ask：完成
Answer ID：ans_550e8400-e29b-41d4-a716-446655440000
下一步：无需操作

# 回答

> 治理说明：本结果为候选知识支持（Candidate-backed）；可用内容仅来自已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。

## 问题

哪些证据支持这个结论？

## 证据不足

本次检索未找到与该问题匹配、且当前可参与检索的已审核 Candidate Knowledge，因此无法形成候选知识支持的回答。
```

No-commit invalid Question：

```text
Knowledge ask：已阻塞
原因：问题为空、语义不足或包含不支持的控制字符
下一步：输入一个单轮、自包含且可读的问题后重试
```

Committed capture overflow failed：

```text
Knowledge ask：失败
Answer ID：ans_550e8400-e29b-41d4-a716-446655440000
原因：Codex 子进程或捕获链失败
提示：Codex 事件与最终消息捕获均超过各自上限，已保留精确上限前缀
下一步：先运行 gezhi status 观察 Knowledge 与 Answer 整体状态（status 不会修复）；必要时运行 gezhi doctor 检查 Codex 环境能力
```

No-commit handled interruption：

```text
Knowledge ask：已中断
原因：用户在 Answer 身份建立前中断了本次请求
下一步：如仍需要答案，请重新运行 knowledge ask
```

### 4.6 Human normal exit

只有完整 semantic output 已成功呈现且进程沿 handled normal-return 返回时使用：`succeeded=0`、`blocked=2`、`failed=1`、`interrupted=130`。Result 是否 non-null、supplemental 数量与 `answer_status` 不改变映射。Exit code 不是 Answer commit acknowledgment；Human 被截断、没有最后 LF或只有前缀时，不能据此推断 commit。

Raw argv resource failure、controlled bootstrap/argument failure继续使用 [CLI Command v1](./cli-command-v1.md) 的 pre-handled stderr 合同，不进入本文 Human renderer。外部终止、late/default Ctrl+C、pending I/O、seal/release proof failure或未分类 internal/entry fault不得捕获后伪装成上述四种正常结果。

## 5. Presentation failure 公开边界

### 5.1 共用 typed pre-I/O no-output union

`KnowledgeAskPreIoPresentationVerdictV1` 只允许正常 mode candidate，或 `NO_OUTPUT_OBSERVABLE_PRESENTATION_FAILURE`。后者的 internal kind 是以下封闭 union；kind 只在 invocation 内存中存在，不进入 JSON、Human、diagnostic、Answer、manifest、日志、trace、telemetry 或其他持久 surface：

| internal kind | allowed mode | 唯一 typed source verdict |
|---|---|---|
| `diagnostic_projection_unrepresentable` | JSON、Human | `build_knowledge_supplementals` 的 `DIAGNOSTIC_PROJECTION_UNREPRESENTABLE` |
| `human_terminal_answer_bytes_rejected` | 仅 Human | Answer Terminal reader 的 `TERMINAL_ANSWER_BYTES_REJECTED` |
| `human_semantic_render_rejected` | 仅 Human | Human renderer 的 `HUMAN_SEMANTIC_TEXT_REJECTED` |
| `human_utf8_encode_failed` | 仅 Human | 第 5.2 节唯一 strict encode 直接抛出的 `UnicodeEncodeError` |
| `human_semantic_bytes_rejected` | 仅 Human | Human bytes validator 的 `HUMAN_SEMANTIC_BYTES_REJECTED` |
| `human_semantic_bytes_too_large` | 仅 Human | Human cap checker 的 `HUMAN_SEMANTIC_BYTES_TOO_LARGE` |

`diagnostic_projection_unrepresentable` 发生时，既有 primary、outcome、result、commit、manifest 与 recovery facts 保持原值，但完整 diagnostics/error surface 不存在，所以禁止 JSON envelope 与 Human receipt。它不能成为 `orphan_scan_failed`、第五种 outcome、第八项 no-commit failed、supplemental 或 omission item。Human-only kind 同样只阻止 presentation，不回滚或重分类已 committed Answer。

No-output candidate 必须绑定 fresh generation、mode、上述 exact kind、已冻结但不对外发布的 domain/command facts，以及 stdout/stderr 均未启动、无 presentation handle/buffer/pending I/O 的证明；不得用 `b""` 冒充 absent payload。它与正常 candidate 在同一 cancellation admission/seal 域竞争：callback 先赢则整个 candidate 作废并重新仲裁；candidate 先赢才进入 `SEALED_PASS_THROUGH`。随后必须完成全部适用 domain/command resource settle、profile-specific zero-in-flight 与 source release 并进入 `RELEASED`；任一 identity、seal、settle、release 或 ownership proof 无法成立时保持正常矩阵外，不能猜成该 union。

到达 `RELEASED` 后，no-output terminal seam 必须保持 stdout 与 stderr **恰好均为 empty bytes**，停止全部新 presentation，并恰好一次调用 `os._exit(1)`。不得普通 return、`sys.exit`、raise 后转换、运行 cleanup/finally/`atexit`/flush，或追加 fallback JSON、Human、diagnostic、traceback、日志与持久事实。这个 decimal `1` 不是业务 `outcome=failed`；空输出不能证明 Answer 是否 committed。

### 5.2 Human preparation 的 direct typed boundaries

Human candidate 必须在任何 stdout/stderr I/O 前按下列固定顺序形成；每个 typed producer 只返回列出的 verdict，不用 broad exception catch 把实现或 OS failure改写成 verdict：

1. Supplemental builder 先返回 `READY_DIAGNOSTICS`；否则只允许 common `diagnostic_projection_unrepresentable`。
2. 对 committed `succeeded`，Answer Terminal reader 直接返回 `TERMINAL_ANSWER_BYTES_READY` 或 `TERMINAL_ANSWER_BYTES_REJECTED`。Ready branch 同时携带 exact raw `answer.md` bytes、strict UTF-8 text 与 manifest/committed-proof binding；renderer 必须保证最终 semantic text 中的 Markdown suffix 重新编码后逐 byte 等于该 raw asset。其他 outcome 不调用 reader。
3. Human renderer 直接返回 `HUMAN_SEMANTIC_TEXT_READY` 或 `HUMAN_SEMANTIC_TEXT_REJECTED`。Rejection 只表示 renderer 明确验证的 closed layout/input verdict；renderer 调用抛出的异常不能被 relabel。Ready text 必须满足第 4 节 exact semantic layout，尚未声称 UTF-8 bytes 合法。
4. Ready text 只执行下面一条 strict encode 调用；`try` 只能包住该行，并且只能捕获它直接抛出的 `UnicodeEncodeError`：

```python
try:
    semantic_bytes = semantic_text.encode("utf-8", errors="strict")
except UnicodeEncodeError:
    return NO_OUTPUT_OBSERVABLE_PRESENTATION_FAILURE("human_utf8_encode_failed")
```

5. `HumanSemanticBytesValidatorV1` 直接返回 `HUMAN_SEMANTIC_BYTES_VALID` 或 `HUMAN_SEMANTIC_BYTES_REJECTED`；它复验无 BOM/raw CR/NUL/ANSI、无行尾空白、exact layout、succeeded Markdown suffix identity、仅 LF且恰好一个最终 LF，以及不存在第二 payload。它不抛异常来表示正常 rejection，caller 也不 broad-catch validator exception。
6. Cap checker 对同一 immutable bytes object 返回 `HUMAN_SEMANTIC_BYTES_WITHIN_LIMIT` 当且仅当 `len(bytes) <= 532480`，否则返回 `HUMAN_SEMANTIC_BYTES_TOO_LARGE`。Within-limit branch 把同一 object identity、长度与 fresh generation 绑定给正常 Human candidate；不得重编码或替换为内容相等副本。

除上述唯一 `UnicodeEncodeError` catch 外，`MemoryError`、`AssertionError`、`KeyboardInterrupt`、`SystemExit`、`OSError`、`TypeError`、其他 `ValueError`、其他 `Exception`/`BaseException`，以及未知 runtime/implementation fault 都不得 relabel 为 no-output kind、business outcome、diagnostic 或 exit `1`。Terminal reader、renderer、bytes validator 与 cap checker 的直接调用都不得位于 `except Exception`/`except BaseException` 或等价 broad catch 内。

### 5.3 JSON 既有边界保持不变

`knowledge ask --json` 在 `READY_DIAGNOSTICS` 后继续完整服从 ADR 0107–0109：完整 canonical envelope 与末尾 LF 最多 65536 bytes，stdout 只有该 buffer且 stderr为空。成功 seal/release 后的 canonical serialization/cap no-output failure、binary fd1 setup failure、invalid completed write、同步 I/O/broken pipe failure在 completion 可证明且无 pending writer时，停止新 write并恰好一次 `os._exit(1)`；不形成 fallback JSON/Human、primary/supplemental、日志或持久事实。本文不改变 ADR 0107 的 `READY_BYTES | NO_OUTPUT_PRESENTATION_FAILURE`、ADR 0108 的 closed completion proof或 ADR 0109 的 direct-call `OSError` 边界。

Common `diagnostic_projection_unrepresentable` 发生在完整 envelope/ADR 0107 candidate 形成之前，使用第 5.1 节 union；它不伪装成 `canonical_serialization_failed` 或 `stdout_cap_exceeded`。零字节或 partial JSON加 exit `1` 只表示没有完整 machine acknowledgment，不能推断 sealed outcome、result或 Answer commit。若调用方仍取得并验证 exact full envelope与末尾 LF，该 receipt 仍成立，即使进程随后 hard-exit `1`。External termination、pending/completion 不确定、seal/release proof failure与 ADR 0108 排除项保持正常矩阵外；数值偶合 `1` 或 `130` 不建立应用分类。

### 5.4 Human I/O 开始后的边界

Human presentation 开始后的 write/console failure不得重写前缀、切换 JSON、追加 stderr、补 LF、回滚 Answer或生成 failed diagnostic。它不属于第 5.1 节 pre-I/O union；只有 complete output可用第 4.6 节 normal exit，partial/zero output保持正常矩阵外。V1 不冻结 exotic/nonblocking/overlapped Human endpoint，也不把 JSON 的 fd1 primitive静默推广为共享 writer。

## 6. 验收断言

### Audit 与超限

- `RetrievalAuditV1` 顶层/嵌套 closed Schema、canonical bytes、末尾 LF、2 MiB cap、三个 asset/snapshot hash全部 exact。
- 两路 0/1/48 与 49、final 0/1/12 与 13、rank gap/duplicate、identity drift、非 finite/非 canonical float hex、错误最简分数均覆盖。
- Registry snapshot 只来自同一 transaction；withdrawn Candidate不进入 entries、branch或 final selection。测试用 materialized reference object 对比 exact prefix/entry/comma/suffix streaming hash，覆盖空/单项/多项、乱序、重复、identity mismatch，并用大 N fixture证明实现不建立 O(N) entries/object/set。
- 四个 base search field 逐一覆盖 exact source sequence、每个 scalar 独立 SearchTextV1、empty fragment 丢弃、ASCII-space join 与 all-empty；Descriptor method `value.text`、其他 kind `value.label`、各自 source terms、null Work title 与 canonical order均有反例。Trigram 输入逐值等于 base strings；unicode61 从同一 base按冻结二字/非 Han规则派生；algorithm version + base 必须唯一重建两路输入，hash只覆盖 base projection canonical bytes。
- 零 View 标准库复算必须得到 109 bytes 与 `51aebe839e0caa991344efe4c0a19518b93a1d59aaa9bccbd1c6220a367641ec`。Executable builder 产生 262143、262144 与 262145 exact buffers；前两者为 within，最后一者为 too_large；测量/hash都覆盖同一完整 buffer与 LF。
- Within-limit 分支断言 Audit measurement、同一 buffer object、View manifest pair 与实际 View bytes 四向相等；替换等值 bytes object、重序列化、manifest drift、readback drift 与 recovery drift全部拒绝为 `retrieval_materialization_failed`。Too-large 分支断言 View installer调用次数为零。
- too_large committed Answer恰到 P3，Audit在、View/C/attempt/O均不在，primary context仍为空；Audit自身失败不得冒充 too_large。

### Supplemental

- 每个 orphan分类至少一个 witness；同 candidate one-hot，count checked，uncertain rename不产 item。
- 五个 code只能 supplemental；同码聚合、ASCII排序、omission-last、16-item/16384-byte cap服从共享模块。
- 真实 invocation-wide scan protocol failure才可产生 `orphan_scan_failed`；scan 成功后的 count 表示溢出必须返回 `DIAGNOSTIC_PROJECTION_UNREPRESENTABLE`，保持 primary/outcome/result/commit不变，并令 JSON/Human都走 empty stdout/stderr hard-exit `1`，不生成 diagnostic、omission或 fallback。
- capture channels三种合法组合、空/重复/乱序/unknown非法；exact-cap clean EOF无 item；合法 item必须绑定 committed codex_process_failed矩阵。
- Result-null blocked禁止 orphan items；maintenance absence不产生通用 warning。

### Human 与 presentation

- 35 个 primary逐项断言 exact原因/下一步、first line、ID presence、stdout/stderr与 `0/2/1/130`。
- 五个 command-owned supplemental与 omission逐项断言 exact提示；succeeded next-action按第4.2节稳定选择。
- 每个 remediation 断言 `doctor` 只用于其七项环境能力，历史 Answer/Registry/commit/recovery只由 `gezhi status` 观察且文案明确 status 不修复；不得声称任一 Operations 命令会自动 repair/recover/move/delete。
- 成功 Human逐 byte包含 committed `answer.md`，不从 AnswerOutput重渲染；blocked/failed/interrupted绝不读或显示残留结果。
- Redirected witnesses、LF/CR/BOM/ANSI、532480/532481、zero/partial/full writer分支覆盖。
- JSON 既有 controlled failure无 fallback且 hard-exit1；六个 closed no-output kind（其中一个是 common diagnostic failure）逐项覆盖 mode legality、fresh generation、seal/release、empty stdout/stderr与恰好一次 hard-exit1。
- Human terminal reader/renderer/bytes validator逐项返回 typed accept/reject verdict；strict encode只捕获直接 `UnicodeEncodeError`。`MemoryError`、`AssertionError`、`KeyboardInterrupt`、`SystemExit`、`OSError`、`TypeError`、其他 `ValueError` 与未知 exception注入必须原样逃逸，不能进入 no-output kind、normal exit或 diagnostic。
- Human I/O 开始后的 zero/partial failure、external termination、pending/completion 不确定与 seal/release proof failure不得冒充业务 outcome或 pre-I/O hard fail。
- installed `gezhi` 与 `python -m gezhi` 对所有公开 witness完全一致。

## 7. 非目标与演进

本文不新增 command、option、配置、依赖、日志、telemetry、持久 diagnostic、maintenance mutation、Answer sidecar、模型调用、retry、view 压缩、Candidate删减、embedding/vector/rerank、GUI、daemon或国际化。它不改变 Answer/Capture cap、Codex Job stop、primary code、result Schema、manifest generation、SearchText/RRF算法或 Promotion Gate。

新增 supplemental variant必须使用新 versioned code并静态扩展 concrete union；改变 `RetrievalAuditV1` 字段、snapshot identity、float表示或 measurement语义必须升级 audit Schema。未来 maintenance必须先冻结独立 command/interface、ownership与动作集合，不能通过 Human 建议或 supplemental code偷偷获得写权限。未来 Context不得复用 Knowledge Audit、Human catalog或 presentation hard-fail语义，除非自己的 concrete contract显式采用并证明边界。
