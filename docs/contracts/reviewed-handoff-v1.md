# Reviewed Handoff v1 合同

状态：已冻结。本合同冻结 Candidate Review 的 append-only authority，以及 Literature 向 Knowledge 交付的两文件 Reviewed Handoff bytes。它实现 [ADR 0136](../adr/0136-submit-candidate-review-through-one-deep-module.md)，并与 [Literature Commands v1](./literature-commands-v1.md)、[Candidate Knowledge v1](./candidate-knowledge-v1.md)、[Literature Reader v1](./literature-reader-v1.md)、[ADR 0019](../adr/0019-use-append-only-candidate-review-decisions.md)、[ADR 0020](../adr/0020-use-a-minimal-self-contained-reviewed-handoff.md) 和 [ADR 0025](../adr/0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md) 共同构成 Review → Handoff seam。

## 1. Canonical bytes 与稳定身份

本合同中的 JSON object 都是 closed object，禁止额外字段、float、NaN、Infinity、重复 key 与未知枚举。JSON payload、JSON file 和 JSONL record 使用 [Candidate Knowledge v1](./candidate-knowledge-v1.md) 的 CanonicalJsonV1：UTF-8、`ensure_ascii=False`、`allow_nan=False`、`sort_keys=True`、紧凑分隔符，无 BOM、无 CR。身份前像是不带尾随 LF 的 CanonicalJsonV1 bytes；正式 `.json` 与每条 `.jsonl` record 在相同 bytes 后追加一个 LF。文件 SHA-256 对包含最终 LF 的完整实际 bytes 计算。

稳定值只接受：

- Work ID：`wrk_<lowercase UUIDv4>`；
- Source ID：`src_<24 lowercase hex>`，并与完整 `source_sha256` 前 24 位一致；
- Candidate ID：`cand_<24 lowercase hex>`，并与完整 `payload_sha256` 前 24 位一致；
- Handoff ID：`hnd_<24 lowercase hex>`；
- SHA-256：64 位小写十六进制；
- Review revision：`1..9223372036854775807` 的 JSON integer，boolean 非法。

## 2. Review authority

单入口接收 closed in-process value `ReviewCandidateCommandV1(candidate_id, action)`；该值不携带 reviewer、note、路径、payload或写权限，也不持久化为领域资产。它的 production caller 只有完整 public `literature review CANDIDATE_ID (--accept|--reject|--defer)` grammar。Action 到 Review Status 的映射唯一为 `accept→accepted`、`reject→rejected`、`defer→deferred`；`pending` 只表示没有 Decision，不能写入。Reviewer 恒由 module 写为 `local_human_cli`。Human-only 由 public grammar、固定 reviewer kind，以及 Reader 与运行时 Codex 不具有 Literature 写能力共同保证；V1 不接收或保存 note、Windows account、SID、email、Codex identity或自由 reviewer string。

Raw Candidate ID 先执行 Literature Commands v1 的 exact grammar。格式有效后，Candidate 必须从当前或历史完整有效的 T15 materialization successor 中唯一解析；实现重验 Candidate envelope、完整 payload hash、CanonicalJsonV1 payload bytes、Work/Source/Canonical/Reader/materialization provenance、Descriptor Reference/Payload、Evidence Pointer 成员资格与历史碰撞。Staging、坏 manifest、坏 current、仅有 SQLite row 或 identity collision 都不是可审核 Candidate。

### 2.1 ReviewDecisionV1

Decision 位于：

```text
works/<work_id>/reviews/<candidate_id>/<review_revision>.json
```

文件是以下 closed object 的 canonical JSON file bytes：

```json
{
  "candidate_id": "cand_<24hex>",
  "decided_at": "2026-08-29T12:34:56.789Z",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "review_status": "accepted|rejected|deferred",
  "reviewer_kind": "local_human_cli",
  "schema_version": "gezhi.review_decision.v1",
  "work_id": "wrk_<uuidv4>"
}
```

`decided_at` 是 UTC、恰好 millisecond 精度的 `YYYY-MM-DDTHH:MM:SS.mmmZ`，只记录首次创建该 revision 的墙钟时间；时间不参与 Candidate 或 Handoff identity。`work_id` 必须等于 Candidate payload 的同名值，Candidate ID、payload hash 与重新编码后的 Candidate payload 必须互相成立。

首个 Decision 的 revision 为 1。已有 current Decision 与同一 Candidate payload、同一 Review Status 时返回 `unchanged`，不得创建新 leaf、改写 `decided_at` 或替换 current，但仍继续验证或补齐该 revision 的 no-action/Handoff/import。Review Status 不同时创建 `current.review_revision+1`；达到 int64 上限后禁止 wrap、复用或覆盖。新的 Candidate payload 具有新的内容身份，不能继承旧 Decision。

### 2.2 CurrentReviewDecisionV1

每个有 Decision 的 Candidate 恰有一个：

```text
works/<work_id>/reviews/<candidate_id>/current.json
```

其 canonical JSON file 是以下 closed pointer：

```json
{
  "candidate_id": "cand_<24hex>",
  "decision_sha256": "<对应 revision JSON 文件完整 bytes 的 SHA-256>",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "schema_version": "gezhi.review_decision_current.v1",
  "work_id": "wrk_<uuidv4>"
}
```

实现先以 non-replacing publication 提交并 readback immutable Decision leaf，再以同卷 replacement evidence 原子替换 current。Decision、current replacement、no-action、import attempt 与 import receipt 的临时文件只能位于 `works/<work_id>/reviews/.staging/.files/`；`reviews/<candidate_id>/` 及其 `no_actions/`、`import_attempts/`、`imports/` closed authority namespace 不得出现 `.tmp` 或其他 staging entry。Private staging evidence 不属于 authority，确定失败或 completion 不确定后可以留待诊断，且不得使下一次 authority snapshot 误判为 foreign entry。Current 不复制 Review Status、reviewer 或 timestamp；这些只从它按 hash 指向的 leaf读取。Directory leaf 已明确提交而 current 缺失时，下次 invocation 可以在完整 history 唯一证明后只补 current；坏 hash、revision gap、多个未被 current 指向的 next revision leaf、foreign entry或 replace completion不确定不能猜测 current。

### 2.3 ReviewNoActionReceiptV1

Rejected/deferred revision 只有在完整历史证明从未有成功 Knowledge import receipt、且没有未解决的 import commit uncertainty 时才是 no-action。Receipt 位于：

```text
works/<work_id>/reviews/<candidate_id>/no_actions/<review_revision>.json
```

文件是以下 closed canonical JSON file：

```json
{
  "candidate_id": "cand_<24hex>",
  "payload_sha256": "<64hex>",
  "reason": "never_imported",
  "review_revision": 1,
  "review_status": "rejected|deferred",
  "schema_version": "gezhi.review_no_action_receipt.v1",
  "work_id": "wrk_<uuidv4>"
}
```

Receipt 必须逐项等于对应 immutable Decision；相同 bytes 幂等复用，不得覆盖冲突 target。它属于 Literature Review authority，不是 Reviewed Handoff，不能生成 Handoff ID、交给 `KnowledgeIntake`、创建 Registry row 或被解释成 withdrawal。旧 accepted Decision/Handoff 尚未成功导入就被更高 non-accepted Decision supersede 时，旧 accept 不得再导入，新 revision 使用本 receipt。成功 no-action 对 command result 表示为 `handoff_action=none`、`handoff_id=null`、Handoff/import `not_required`、`intake_status=null`；Decision 已提交但本 receipt 的确定性提交失败表示为 `handoff_action=none`、`handoff_id=null`、`handoff_status=pending`、`import_status=not_required`、`intake_status=null`，并选择 non-null `handoff_failed`，不得伪装成 Decision 未提交。

### 2.4 ReviewImportAttemptV1 与 ReviewImportReceiptV1

Literature 只有在正式 Handoff 已完整验证、真实 `KnowledgeIntake` adapter 已装配且即将调用 `apply` 时，才先以 non-replacing publication 提交 deterministic launch commitment：

```text
works/<work_id>/reviews/<candidate_id>/import_attempts/<review_revision>.json
```

文件是以下 closed canonical JSON file：

```json
{
  "action": "accept|withdraw",
  "candidate_id": "cand_<24hex>",
  "candidates_sha256": "<完整 candidates.jsonl bytes 的 64hex>",
  "handoff_id": "hnd_<24hex>",
  "manifest_sha256": "<完整 manifest.json bytes 的 64hex>",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "schema_version": "gezhi.review_import_attempt.v1",
  "work_id": "wrk_<uuidv4>"
}
```

`KnowledgeIntake.apply` 明确返回合法 `IntakeAppliedV1` 后，Literature 才以相同路径规则提交 acknowledgement：

```text
works/<work_id>/reviews/<candidate_id>/imports/<review_revision>.json
```

Receipt 逐项等于对应 attempt，另加 `"intake_status":"active|withdrawn"` 并把 Schema 改为 `gezhi.review_import_receipt.v1`；accept 只能是 active，withdraw 只能是 withdrawn。Adapter 的 `disposition=applied|unchanged` 必须在运行时闭合验证但不持久化，使首次 apply 与 crash 后幂等重放得到相同 receipt bytes。

Attempt 与 Receipt 必须绑定现存 Decision leaf、由该 Decision 重算的 action/Handoff ID、正式 Handoff 恰好两个权威 bytes及其 hash。Receipt 必须有同 revision exact attempt；no-action 与 attempt/import 在同 revision 互斥；withdraw receipt 必须有更早的完整有效 accept receipt。任一 foreign entry、超出 Decision history 的 revision、字段/bytes/hash/action/status冲突或不安全目录使 Review authority invalid。

Attempt 无 matching Receipt 时是唯一 unresolved import。它必须属于最新 Decision，且同 Candidate 最多一个；在相同 Handoff bytes 被 adapter 幂等重放并形成 Receipt 前，不得追加更高 Decision、生成 no-action或把 Candidate解释为从未导入。未装配 adapter时返回该 unresolved Decision 的 non-null `import_blocked`；装配后先续行该 attempt，成功后才处理本次新的人工 action。T16 public path未装配T18 adapter，因此只提交 Handoff并返回 pending，不创建 attempt 或 Receipt。

## 3. Review Status 到 Handoff action

| 当前 Review Status | 已有成功 Knowledge import receipt | 本 revision obligation |
|---|---:|---|
| `accepted` | 任意 | `accept` Handoff |
| `rejected` | 否 | no-action receipt |
| `deferred` | 否 | no-action receipt |
| `rejected` | 是 | `withdraw` Handoff |
| `deferred` | 是 | `withdraw` Handoff |

“曾导入”只由第2.4节完整验证通过的成功 Knowledge import receipt证明；任意历史有效 accept Receipt 足以触发后续 withdraw。Handoff存在、import pending、unresolved attempt、Registry探测失败、stdout或 SQLite-looking 文件都不够。Withdraw不删除历史 accept Handoff、attempt、Receipt或 Candidate内容。已 withdrawn 后的更高 rejected/deferred仍发布更高 revision的 withdraw；更高 accepted可以重新发布 accept并恢复 active。

## 4. Handoff identity 与 namespace

每个需要 Handoff 的 review revision 恰有一个 identity payload：

```json
{
  "action": "accept|withdraw",
  "candidate_id": "cand_<24hex>",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "schema_version": "gezhi.reviewed_handoff_identity.v1"
}
```

`handoff_id` 是该 object 的 CanonicalJsonV1 identity bytes 的 SHA-256 前 24 位加 `hnd_`。Identity 不包含 timestamp、run path、Citation、Descriptor、Evidence excerpt、manifest hash或import状态；因此同一 identity 下任何两文件 bytes差异都是冲突，不能 last-write-wins。

正式 namespace 为：

```text
works/<work_id>/handoffs/
├── .staging/
│   ├── .files/
│   └── <handoff_id>/
└── <handoff_id>/
    ├── candidates.jsonl
    └── manifest.json
```

正式 `<handoff_id>/` 必须是普通本机目录且恰含上述两个普通文件。实现先把文件发布临时证据写入同卷 private `.staging/.files/`，再在 `.staging/<handoff_id>/` readback `candidates.jsonl`、最后写入并验证 `manifest.json`，然后以 non-replacing directory rename 提交。正式 Handoff immutable，无 `current.json`、空 action file、第三个 sidecar、PDF、Canonical正文、完整 Reading Result、模型输出或私人审核备注。相同 ID 与相同两文件 bytes幂等复用；target conflict、partial/foreign entry、reparse、坏 hash或歧义明确失败，rename completion不确定时保留证据并停止 normal handled receipt。

## 5. ReviewedCandidateActionV1

`candidates.jsonl` 恰好一条 CanonicalJsonV1 record并以一个 LF结束；空文件、多行、空行或额外 record非法。Record只能是以下两个 closed variant。

### 5.1 Accept

下例中的 `candidate={}` 与三个 snapshot 空数组只用于展示 closed key set；正式 accept 必须安装完整 Candidate，并满足本节及第 6 节的实际数量规则，尤其 `evidence_snapshots` 必须有 1–42 项。

```json
{
  "action": "accept",
  "candidate": {},
  "citation": {
    "arxiv_id": null,
    "author_count": null,
    "doi": null,
    "primary_authors": [],
    "source_id": "src_<24hex>",
    "source_sha256": "<64hex>",
    "title": null,
    "work_id": "wrk_<uuidv4>",
    "year": null
  },
  "descriptor_snapshots": [],
  "evidence_snapshots": [],
  "review_receipt": {
    "review_revision": 1,
    "review_status": "accepted",
    "reviewer_kind": "local_human_cli"
  },
  "schema_version": "gezhi.reviewed_candidate_action.v1"
}
```

`candidate` 必须是完整 closed `CandidateKnowledgeV1`，而不是引用、摘要或字段投影；其 ID、完整 hash 与 payload bytes必须重新验算成立。`review_receipt` 逐项等于对应 Decision，但不复制 `decided_at`、note或Windows/Codex identity。

### 5.2 Withdraw

```json
{
  "action": "withdraw",
  "candidate_id": "cand_<24hex>",
  "payload_sha256": "<64hex>",
  "review_receipt": {
    "review_revision": 2,
    "review_status": "rejected|deferred",
    "reviewer_kind": "local_human_cli"
  },
  "schema_version": "gezhi.reviewed_candidate_action.v1"
}
```

Withdraw 的 Candidate ID、payload hash与 Work-owned import history 中最后导入的同一 Candidate内容身份相等；revision 必须严格大于已应用的 status revision。Withdraw 不复制 Candidate、Citation、Descriptor、Evidence、全文或自由 reason；`review_status` 已完整表达 rejected/deferred治理原因。

## 6. Accept self-contained snapshots

### 6.1 CitationSnapshotV1

Citation object 恰含 `arxiv_id、author_count、doi、primary_authors、source_id、source_sha256、title、work_id、year`。Work/Source三个身份字段逐项等于 Candidate payload。其余字段来自该 Candidate provenance所绑定的 Reader input metadata record，不从当前 Identity Alias、正文、文件名、模型输出或网络推断：

- `title` 是原书目标题或 null；
- 完整作者表可用时，`author_count` 是非负总人数，`primary_authors` 保持原顺序并恰为前 `min(3, author_count)` 项；作者信息完全缺失时为 `author_count=null、primary_authors=[]`；
- `year` 是 `1000..9999` integer或 null；
- `doi` 与 `arxiv_id` 是 Literature Reader v1 定义的规范裸标识符或 null；
- 非 null title和每位作者保持 metadata原 code point，并重新拒绝除 TAB/LF 外全部 Unicode `Cc`，不得修复、替换或降级为 null。

Citation 不进入 Candidate或Handoff identity；一旦 Handoff提交，后续 Identity Alias revision不得改写它。

### 6.2 DescriptorSnapshotV1

`descriptor_snapshots` 有 0–6 项，与 `candidate.payload.descriptor_refs` 数量、顺序和逐字段值完全相同且无重复。每项恰含：

```json
{
  "payload": {},
  "reference": {
    "descriptor_id": "desc_<24hex>",
    "kind": "method|object|dataset|experiment|metric",
    "payload_sha256": "<64hex>",
    "schema_version": "gezhi.descriptor_reference.v1"
  }
}
```

`payload` 是 T15 successor 中对应的完整 `DescriptorPayloadV1`；按 CanonicalJsonV1重算的 SHA-256、短 ID与kind必须和reference一致。禁止缺项、多项、模糊匹配、数组位置引用、只传名称或复制未引用 Descriptor。

### 6.3 EvidenceSnapshotV1

先取得 Candidate statement 与全部 Descriptor payload 的 `evidence_pointers`，按完整 pointer object去重，再按 `(canonical_content_sha256 ASCII bytes, block_id UTF-8 bytes)` 排序。`evidence_snapshots` 必须与该并集逐项一一对应、无缺失、无多项、无重复，并有 1–42 项。每项恰含：

```json
{
  "excerpt": "<原语言直接摘录>",
  "page_index": null,
  "pointer": {
    "block_id": "<Evidence Block ID>",
    "canonical_content_sha256": "<64hex>",
    "schema_version": "gezhi.evidence_pointer.v1"
  }
}
```

Pointer必须是所绑定 Canonical内容中的真实 Evidence Block成员，且其内容 hash等于Candidate顶层 `canonical_content_sha256`。Excerpt 从该 Evidence Block的完整原语言 `text` 确定性形成：先把 CRLF/CR转为LF，再做Unicode NFC与Python 3.11 `str.strip()`；规范化后必须非空，随后取最前面的 `min(800, code_point_count)` 个Unicode code point，禁止按UTF-8 byte截断、翻译、释义、模型生成、加省略号或从其他block拼接。`page_index`逐项等于该block的0-based page index；无法可靠定位时为null。Snapshot不携带bbox、路径、Canonical run ID或完整block正文。

## 7. ReviewedHandoffManifestV1 与 provenance

`manifest.json` 是以下 exact closed object 的 canonical JSON file：

```json
{
  "candidates_sha256": "<candidates.jsonl 完整 bytes 的 SHA-256>",
  "canonical_content_sha256": "<64hex>",
  "canonical_run_id": "<Canonical run ID>",
  "handoff_id": "hnd_<24hex>",
  "provenance": {
    "canonical_run_id": "<Canonical run ID>",
    "semantic_run_id": "<Reader semantic run ID>"
  },
  "record_count": 1,
  "schema_version": "gezhi.reviewed_handoff_manifest.v1",
  "source_id": "src_<24hex>",
  "source_sha256": "<64hex>",
  "work_id": "wrk_<uuidv4>"
}
```

`record_count` 恒为1。Manifest顶层 `canonical_run_id` 必须等于 `provenance.canonical_run_id`；两个 run ID指向 Candidate实际来源的历史有效 Canonical/Reader success，不要求等于当前Active Source的current。Reader manifest必须绑定同一个Work/Source/Canonical内容，T15 materialization input/manifest必须绑定该Reader success；Candidate、Citation、Descriptor和Evidence全部来自这条已验证provenance链。Manifest中的Work/Source/Canonical字段逐项等于accept Candidate payload；withdraw则逐项等于其已导入Candidate内容身份。`candidates_sha256`必须匹配sole record完整文件bytes。

Validator从sole action record构造第4节identity payload并重算`handoff_id`；Manifest不保存自身SHA-256。Knowledge import receipt另行绑定`manifest.json`与`candidates.jsonl`各自完整bytes hash。禁止向manifest增加materialization path、review timestamp、import状态、Registry revision或其他字段；T15 materialization仍由Literature内部provenance验证，不扩张既有cross-context witness。

## 8. KnowledgeIntake bytes seam 与 T16 pending

唯一写Knowledge的owned cross-context interface概念上是：

```python
KnowledgeIntake.apply(
    ReviewedHandoffBytesV1(
        manifest_bytes=<最终 manifest.json bytes>,
        candidates_bytes=<最终 candidates.jsonl bytes>,
    )
)
```

值只携带两个已经readback并完整验证的immutable buffers，不携带Path、Literature Data Root、Review current、Candidate materialization locator、open handle或Registry connection。Knowledge adapter从bytes独立执行closed Schema、CanonicalJson、文件hash、Handoff identity、action/revision、Candidate/Descriptor/Evidence/Citation与provenance校验，并在自己的transaction中写Candidate Registry及原样保留`imports/<handoff_id>/`两文件；Literature不得直接写Registry。`apply` 对 exact Handoff identity/bytes 必须幂等，`applied|unchanged` 都确认同一目标 Intake Status；这是第2.4节 unresolved attempt 可以安全重放的前提。

T16尚未实现T18 Knowledge adapter时，不调用或伪造该interface。Required accept/withdraw Handoff提交成功后，public review返回blocked `literature.review.import_blocked.v1`和non-null result：`handoff_status=committed、import_status=pending、intake_status=null`。相同action重试复用同一Decision revision、Handoff ID和两文件bytes。只有未来真实`KnowledgeIntake.apply`返回合法 typed success并提交第2.4节 Receipt 后，结果才能成为`import_status=applied`及accept→active或withdraw→withdrawn。Apply 前已提交 attempt 而 Receipt 未定时，后续 invocation只可按同一 bytes续行；unknown、异常或本地 acknowledgement completion不确定不形成 normal handled receipt。No-action receipt不调用本seam。

## 9. Witness compatibility、幂等与非目标

[Knowledge Read Diagnostics v1](./knowledge-read-diagnostics-v1.md) 的四个 redirected fixture files是本合同的exact-byte conformance witness。Accept/withdraw `ReviewedCandidateActionV1`和两个manifest必须逐字段兼容；对应完整文件SHA-256保持：Accept candidates `9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507`、Accept manifest `8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930`、Withdraw candidates `0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e`、Withdraw manifest `a6c2da28a7e542197222fe646305023178606b1febff6954b3f09f8b9eec5f47`。

相同Candidate/revision/action和相同bytes幂等；相同revision不同bytes、同一Handoff ID不同bytes、倒序revision、Candidate/payload/hash冲突或unknown Schema明确失败。Decision、Handoff或Registry任一已经明确提交后都不因后续failure或presentation failure回滚；commit completion不确定时不形成handled receipt。

本合同不增加batch、interactive review、note、default accept、Promotion Gate、Promoted Knowledge、Research Interest、Relevance Candidate、全文传输、第三个Handoff文件、Registry Schema、Knowledge查询interface或动态plugin。修改Decision/current/no-action/import-attempt/import-receipt Schema、Handoff identity前像、两文件field set、snapshot算法、excerpt选择、provenance、attempt恢复规则或KnowledgeIntake bytes seam必须发布新的合同版本或明确replacing decision。
