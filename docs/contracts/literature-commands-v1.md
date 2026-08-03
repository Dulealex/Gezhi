# Literature Commands v1 合同

状态：已冻结。本合同关闭 Windows V1 的 `literature add`、`literature resume` 与 `literature review` 三个公开命令从成功 grammar handoff 到完整 Human/JSON presentation 之前的领域结果；token、arity、option scope 与 parser failure 继续由 [CLI Command v1](./cli-command-v1.md) 唯一拥有。

本合同实现 [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) 与 [T04 / Issue #5](https://github.com/Dulealex/Gezhi/issues/5)，并保持以下既有决定：

- [ADR 0011](../adr/0011-model-literature-as-work-source-and-assets.md)、[ADR 0012](../adr/0012-use-stable-internal-identities-and-external-aliases.md)：`Work → Source → Assets`、稳定内部身份与内容寻址 Source。
- [ADR 0013](../adr/0013-preserve-immutable-stage-runs-and-atomic-current-pointers.md)、[ADR 0027](../adr/0027-use-a-fixed-seven-stage-asset-driven-workflow.md)：不可变 run、原子 current pointer 与固定七阶段。
- [ADR 0019](../adr/0019-use-append-only-candidate-review-decisions.md)、[ADR 0025](../adr/0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md)、[ADR 0026](../adr/0026-continue-review-through-handoff-and-knowledge-import.md)：追加式审核、accept/withdraw 与审核后的可恢复续行。
- [ADR 0030](../adr/0030-structure-literature-assets-by-work-source-and-run.md)、[ADR 0032](../adr/0032-use-static-composition-and-context-deep-modules.md)：Literature 权威资产树、静态装配与深 module。
- [ADR 0117](../adr/0117-freeze-context-scoped-data-root-cli-overrides.md)、[ADR 0118](../adr/0118-limit-v1-candidate-review-to-one-candidate-and-action.md)、[ADR 0119](../adr/0119-lazy-load-only-the-selected-context-command-adapter.md)：Context-scoped root、一次一个 Candidate/一个 action，以及 valid route 后才加载 Literature adapter。
- [Candidate Knowledge v1](./candidate-knowledge-v1.md)、[Literature Reader v1](./literature-reader-v1.md)、[CLI JSON v1](./cli-json-v1.md)、[CLI Diagnostics v1](./cli-diagnostics-v1.md) 与 [Configuration v1](./configuration-v1.md)。

## 1. 范围与三个深 module seam

公开 CLI adapter 在 grammar 成功后只能调用三个概念行为：

1. `add_local_pdf(request)`：安全读取一个显式本地 PDF，解析 Work/Source 身份，发布不可变 Source Asset，并把该 Source 明确选为唯一 Active Source。
2. `resume_work(work_id)`：从权威资产重新计算 Continuation Point，复用已验证成功，恢复可确定的提交间隙，并推进所有当前可自动推进的工作。
3. `review_candidate(candidate_id, action)`：保存一个显式人类 Review Decision，并为该 decision 唯一需要的 Handoff 与 Knowledge import 继续执行或恢复。

这些名称冻结行为 interface，不冻结 Python module、class、函数签名或 exception。CLI adapter 不得逐步调用“算 hash”“写 manifest”“改 current”“写 review”“生成 handoff”或“直接改 Registry”等浅接口，也不得自己解释资产状态。三者分别把路径安全/身份、七阶段恢复、审核/交接一致性隐藏在 Literature-owned deep module 内；唯一跨 Context 写入仍是 `KnowledgeIntake.apply(reviewed_handoff)`。

运行端 Codex、OCR child、renderer、`status`、reader 与未来 Context 都不能获得 `review_candidate` 的写能力。模型输出最多形成 Candidate Knowledge 与 pending Review Queue；只有从完整 public `literature review CANDIDATE_ID (--accept|--reject|--defer)` grammar 创建的不可伪造、invocation-local human-review capability 才能提交 Review Decision。

## 2. 共同 gate、身份与资源所有权

### 2.1 入口顺序

三个命令共同遵守以下顺序，前一 gate 未通过时不得触碰后一 gate：

1. CLI Command v1 的 raw argv preflight、typed bootstrap checks 与完整 grammar；
2. 只加载 Literature command adapter；
3. Configuration v1 形成一次 immutable configuration snapshot；
4. 只对当前操作实际消费的 Context Data Root 执行 physical gate；
5. 校验 command-owned raw domain values；
6. 取得与 frozen Literature root physical identity 绑定的 writer ownership；
7. safe-open、恢复、领域变更与原子发布；
8. 冻结一个 command outcome，再由 Human 或 JSON adapter 呈现。

`add` 只消费 Literature Data Root，不探测 Knowledge、OCR 或 Codex。`resume` 只有到达 OCR、read 或 knowledge_import 才分别探测 OCR、Codex 或 Knowledge Data Root/Registry。`review` 保存决定和 Handoff 时只消费 Literature Data Root，只有实际需要 import 时才探测 Knowledge Data Root/Registry；它永不探测 OCR 或 Codex。Configuration resolver 仍验证两个 root raw strings 的共享 lexical invariant；“不消费”只表示不对另一个 Context root 做 physical open/probe。

### 2.2 稳定 ID

本合同只接受以下大小写精确的稳定 ID：

- Work：`wrk_<lowercase UUIDv4>`；UUID version nibble 为 `4`，variant 为 RFC 4122 variant。
- Source：`src_<24 位小写十六进制>`，并等于 Source 原始完整 bytes SHA-256 前 24 位。
- Candidate：`cand_<24 位小写十六进制>`，并与完整 `payload_sha256` 及 Candidate Knowledge v1 payload 一致。
- Handoff：`hnd_<24 位小写十六进制>`，算法见第 6.3 节。

Parser 不验证或修复这些值；空字符串、前后空白、大写、非规范 UUID、别名、路径或“当前项”标记均由所属 command 的 handled domain gate 拒绝。

### 2.3 Writer ownership

每个 Work 同时最多一个写 invocation。Ownership 必须绑定当前线程、depth one、Literature root physical identity 与目标 `work_id`；它不是 lock-file 名称、PID、时间戳或 caller 可构造的 boolean。`add` 在尚未决定 Work 时取得 root-level identity-intake ownership，解析出 Work 后转入该 Work ownership；不得同时持有两个 Work writer ownership。

另一个 writer 已拥有相同作用域时返回受控 `blocked`，不无限等待、不 steal lock、不按 PID/时间猜测 owner 已死亡。Crash 后的新 invocation 只有在重新取得 ownership 并从当前 namespace/bytes 重验后才能恢复；旧进程内证据全部失效。

## 3. 七阶段词汇与权威状态

阶段顺序固定为：

```text
ingest → ocr → canonicalize → read → review → handoff → knowledge_import
```

阶段状态只允许 `pending`、`running`、`succeeded`、`blocked`、`failed`、`interrupted`：

- `running` 只是活跃 writer 的投影，不是成功证据。新 owner 看到遗留 `running` 必须先形成 `interrupted` terminal record，不能继续旧进程状态。
- `succeeded` 只能由完整有效的已提交 manifest/assets 与匹配 current pointer 证明；SQLite row、日志、stdout、mtime、目录名或 staging 都不够。
- `blocked` 是当前输入下可由环境、用户或后续显式 `resume` 改变的前置条件；它不是部分成功。
- `failed` 是确定性本地、合同、完整性或 commit failure；它不能更新 success current。
- `interrupted` 只在用户取消先胜出、全部 child/handle/write 安全停止且 terminal record 可完整提交时形成；否则只留 staging，不伪造 handled receipt。

Blocked、failed 与 interrupted run 可以作为不可变审计资产提交，但绝不替换 success current。相同完整 input fingerprint 的有效 success 必须复用；旧 success 与当前上游指纹不符时保留历史，但不满足当前阶段。

| stage | 唯一输入 authority | success authority | 谁可以推进 |
|---|---|---|---|
| `ingest` | 显式 PDF bytes、身份别名和既有 Work/Source assets | Source manifest、原始 Source Asset 与唯一 Active Source pointer | `add_local_pdf`；`resume` 只验证/修复确定提交间隙 |
| `ocr` | 当前 Active Source 完整身份 | 与 Source/config/tool identity 绑定的 OCR run/current | `resume_work` OCR adapter |
| `canonicalize` | 当前有效 OCR success | Canonical Reading Asset run/current 与 content hash | `resume_work` canonicalizer |
| `read` | 当前 Canonical asset 与固定 Reader inputs | Literature Reader v1 完整 semantic result/current | `resume_work` Reader adapter |
| `review` | 完整有效 Candidate payload | append-only Review Decision/current；无 Candidate 时为 no-op | 仅显式 `review_candidate`；`resume` 只观察 |
| `handoff` | 已提交 Review Decision 与 Handoff history | matching accept/withdraw Handoff 或 no-action receipt | review；resume 只续行已授权 revision |
| `knowledge_import` | 有效 Handoff/no-action receipt | Registry transaction/no-action receipt | 仅 `KnowledgeIntake.apply`，由 review/resume 编排 |

阶段顺序是 authority dependency，不是“必须一次审核完所有 Candidate”的 batch barrier。一个 Candidate 的显式 decision 可以立即续行自己的 Handoff/Import；其他 Candidate 仍 pending 时，Work 的 Continuation Point 仍是 `review`，`resume` 不会替它们作决定。

## 4. `literature add`

### 4.1 Raw input

CLI adapter 原样交付 `PDF_PATH`、可选 `WORK_ID`、`DOI`、`ARXIV_ID` 与 `CITATION`；不得 trim path、做环境/`~`/glob 展开或二次 shell splitting。

`WORK_ID` 若出现，必须是第 2.2 节格式且指向已存在、可完整验证的 Work。DOI/arXiv 使用 Literature Reader v1 的裸标识符 grammar 与“不修复”规则。`CITATION` 若出现，按 CRLF/CR→LF、Unicode NFC、Python 3.11 `str.strip()` 规范化，拒绝 NUL、非配对 surrogate 与除 TAB/LF 外的 `Cc`，并同时要求 1–4,096 code points、最终 UTF-8 不超过 16,384 bytes。空的已提供 value 无效；缺席与空字符串不同。

Citation 是弱书目别名，不参与稳定 ID，也不能单独触发自动 merge。实现可以用它发现需人工判断的相似 Work，但不得用 fuzzy score、标题近似或作者重合自动选择 Work。

### 4.2 PDF path 与稳定读取

`PDF_PATH` 只接受 Windows 本机 drive-absolute 或 local extended-DOS absolute path。相对、UNC、WSL UNC、remote drive、device/Volume GUID、ADS、目录、reparse point 或 final physical identity 无法证明的路径都拒绝。路径大小写、分隔符和扩展名不参与 Source identity。

Intake 通过 no-follow safe-open 取得本机普通文件 handle，锁存 volume/file identity，禁止本次打开期间的 write/delete sharing，并从该 handle 一次流式复制到 Literature root 同卷私有 staging，同时计算准确 byte length 与 SHA-256。不得先按一个 handle hash、再按 path 重开另一个文件复制；完成后复验同一 handle identity、EOF、staging length/hash。

V1 最小 PDF 内容 gate 要求非空，最前五个 raw bytes 精确为 ASCII `%PDF-`。不根据 `.pdf` 后缀接受伪装内容，也不在 add 中解析页面、运行 PyPDF、OCR 或修复损坏。T04 不新增 PDF 总 byte cap；实现必须流式处理，持久 `byte_length` 只允许 `0..9223372036854775807` non-boolean integer，溢出失败且不截断/分卷/降级。

### 4.3 Work/Source 解析

`source_sha256` 是原始完整 bytes SHA-256，`source_id=src_<前24位>`。解析顺序固定为：

1. 先检查同一完整 hash/bytes 的全局既有 Source；同短 ID 不同完整 hash、或同完整 hash 不同 bytes 是 collision，绝不覆盖。
2. 显式 `--work-id` 是用户对目标既有 Work 的明确选择；同一 Source 已属于其他 Work，或 DOI/arXiv exact alias 已由其他 Work 拥有时，返回 identity conflict，不移动/复制 Source、不改 alias。
3. 无 `--work-id` 时，相同 Source 幂等解析到其 Work；否则 DOI/arXiv exact alias 可以解析 Work。所有强事实必须指向同一 Work；分别指向不同 Work、同一强 alias 出现在多个 Work，或强 alias 与相同 Source 的 Work 冲突时，需要 Identity Review，不能猜测。
4. 没有强事实解析到 Work 时创建新的 `wrk_<UUIDv4>`。Citation/弱相似性不自动 merge；若观察到不能安全忽略的弱冲突，只能返回 Identity Review required。

新 Work ID 只在全部 pre-ID gates 通过后生成。Uncertain commit 后不得在同一 invocation 换 UUID 重试；后续 invocation 从 Source hash、已提交 assets 与 namespace 重判。相同 Source/Work/alias 的重复 add 为 `reused_source`，不复制原始 bytes、不创建第二 Source、不改写 immutable manifest；新增 alias 只能追加 Work-owned identity revision。

### 4.4 Active Source、提交与 result

完整成功的 add 明确表示“把 supplied Source 选为该 Work 的唯一 Active Source”：新 Work 首 Source自动 active；既有 Work 新 Source或 inactive Source原子切换；already-active duplicate无变化。Result 通过 `active_source_changed` 明示。切换只使旧 downstream success 与当前 input fingerprint不匹配，不删除/覆盖历史 run、Review、Handoff 或 Registry history。

Source bundle 在同卷 staging 完整写入、关闭、hash/manifest readback后，以 non-replacing directory rename提交；Active Source pointer只在完整 Source提交后原子替换。`catalog.sqlite3` 是可重建投影：资产/pointer成功但 SQLite transaction失败时不回滚，command失败，下次相同 add补投影而不复制内容。Rename/replace completion不确定时 stop-new-work、无正常 result、不换 ID重试；后续 invocation从 namespace/hash重验。V1不承诺 power-loss durability。

成功 outer 使用 `command="literature.add"`、`outcome="succeeded"`、`diagnostics=[]`，result恰好为：

```json
{
  "active_source_changed": true,
  "disposition": "created_work",
  "schema_version": "gezhi.literature_add_result.v1",
  "source_id": "src_<24hex>",
  "source_sha256": "<64hex>",
  "work_id": "wrk_<uuidv4>"
}
```

`disposition` 只允许 `created_work|added_source|reused_source`。三个值都可能 `active_source_changed=true`；只有 already-active reused Source 为 false。Add 的 blocked/failed/interrupted 固定 `result=null`；较早提交点可能已存在，但 null 不表示回滚或成功 receipt。

## 5. `literature resume`

### 5.1 重入算法

`resume` 恰好接收一个显式 Work ID，没有 implicit current/last Work。Work/ownership通过后必须：

1. 从文件权威 manifest/assets/current 与 Review/Handoff/Registry receipts重建七阶段 snapshot；SQLite不能覆盖文件事实。
2. 对 directory commit已存在但 current缺失/陈旧的完整 success，验证 fingerprint/hash/namespace后只补 pointer，不重跑。
3. 对 prior owner不存在的遗留 running/staging分类；只有完整有效 terminal success且只差已批准 rename/pointer的 orphan可补交，partial/unsafe/invalid原地 quarantine，不修补成 success。
4. 跳过全部匹配当前上游 fingerprint的 success，从最早未满足 obligation开始。
5. 串行推进自动阶段，直到 complete、首个 blocked/failed/interrupted、uncertain commit，或只剩没有显式 Review Decision的 Candidate。

一次 resume 可以连续完成多个自动阶段，但每阶段有独立 run/manifest/commit point；后阶段只能读前阶段 committed success。过去 blocked/failed/interrupted run 不永久禁止显式 resume；修复前置条件后可创建新 run，但不得修改旧 run、复用失败 partial或换 provider。相同 success禁止重算，V1无 `--force`。

### 5.2 人工 gate 与 backlog

`resume` 永不创建 Review Decision、把 pending/deferred改 accepted、选择 action、伪造 reviewer或调用模型审核。没有 decision 的 Candidate 保持 pending；deferred是已发生的人类 decision，不等同 pending，也不进入 accept Handoff。

在返回 `awaiting_review` 前，resume必须先补齐已由历史显式 decision授权而未完成的 Handoff/Import backlog，按 `(candidate_id ASCII bytes, review_revision)` 升序执行；这只续行已提交决定。Backlog处理完仍有 pending Candidate时，Continuation Point为 review且 outer blocked。零 Candidate或全部 Candidate有 accepted/rejected/deferred decision时，review obligation可满足并继续。

聚合 success 条件：review要求当前 semantic result每个 Candidate都有绑定同一 payload hash的 current decision（零 Candidate自动满足）；handoff要求每个 decision有 matching accept/withdraw Handoff或“从未 accept且当前 non-accepted”的 no-action receipt；knowledge_import要求每个 required Handoff有 Registry receipt、每个 no-action有同一 deterministic receipt。

### 5.3 Resume result

Work、Active Source 与 root trust完整验证后，command可以形成以下 closed snapshot；在此之前失败为 `result=null`：

```json
{
  "active_source_id": "src_<24hex>",
  "advanced_stages": ["ocr", "canonicalize"],
  "pending_candidate_ids": ["cand_<24hex>"],
  "pipeline_complete": false,
  "schema_version": "gezhi.literature_resume_result.v1",
  "start_stage": "ocr",
  "stop_stage": "review",
  "work_id": "wrk_<uuidv4>"
}
```

`start_stage`/`stop_stage` 各为七阶段值或 `complete`，分别是 invocation初始/呈现前的 Continuation Point。`advanced_stages` 是本 invocation明确发布 success或只修复 success pointer/receipt的阶段，无重复且按阶段顺序；既有 skip不列入。`pending_candidate_ids` 最多12项，按 Candidate Knowledge v1顺序，只列无 decision 的当前 Candidate；deferred不列入。

`pipeline_complete=true` iff `stop_stage=complete`、pending为空且七阶段当前 obligations全可验证；already-complete调用使用 start/stop=`complete`、advanced=[]。受控 stage blocked/failed/interrupted若仍能证明 snapshot可保留 non-null result；root/Work/Active Source identity无法证明、snapshot不唯一或 commit outcome uncertain时不得构造近似 result。

## 6. `literature review`

### 6.1 Candidate、action 与 decision

Candidate ID必须解析到完整有效、Literature-owned Candidate Knowledge，并复验 ID/hash/canonical bytes/provenance/Evidence Pointer。Candidate可来自当前或历史有效 semantic run，以便显式撤回历史已导入 Candidate；staging、collision、坏资产或仅有 SQLite row不可审核。

Action映射唯一为 `--accept→accepted`、`--reject→rejected`、`--defer→deferred`。`pending`表示无 decision，不能由 action写入。V1 note恒 absent。Reviewer固定为 repository-owned actor kind `local_human_cli`；不读取/保存 Windows account、SID、email、Codex identity或自由 reviewer string。

首 decision `review_revision=1`。不同于 current action的新 decision使用 revision+1，并不可变写入 `works/<work_id>/reviews/<candidate_id>/<revision>.json`；decision绑定 Candidate ID与完整 payload hash，current-decision pointer只在 leaf完整验证后切换。相同 payload/action重复是幂等 `unchanged`：不追加 revision、不改 timestamp/current，但继续补该 revision未完成的 Handoff/Import。不同 action为 `created`。新 payload identity绝不继承旧 decision。

Decision明确提交后不因 Handoff、Knowledge root、Registry或 presentation failure回滚。Decision publish不确定时无正常 receipt；后续相同 review从实际 history/current重判 created/unchanged。

### 6.2 Review Status → Handoff → Registry

| Review Status | Knowledge import receipt 证明曾导入 | 本 revision Handoff | apply 后 Intake Status |
|---|---:|---|---|
| `accepted` | 任意 | `accept`，完整 self-contained Candidate payload | `active` |
| `rejected` | 否 | no action；无空 Handoff/Registry row | 不存在 |
| `deferred` | 否 | no action；无空 Handoff/Registry row | 不存在 |
| `rejected` | 是 | 最小 `withdraw` tombstone | `withdrawn` |
| `deferred` | 是 | 最小 `withdraw` tombstone | `withdrawn` |

同 action复用同一 identity。只有至少一个先前 accept 已有成功 Knowledge import receipt 时，accepted→non-accepted…51 tokens truncated…无该 Candidate。Non-accepted→accepted发布新 accept；已 withdrawn后的更高 non-accepted revision仍发布更高 withdraw，保存最新 review revision。Pending从不产生 Handoff。

每个 public review revision最多一个 single-record Reviewed Handoff；`candidates.jsonl`恰好一条 accept/withdraw。Handoff ID是以下 CanonicalJsonV1 bytes SHA-256前24位加 `hnd_`：

```json
{
  "action": "accept",
  "candidate_id": "cand_<24hex>",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "schema_version": "gezhi.reviewed_handoff_identity.v1"
}
```

No-action不生成 Handoff ID；Literature用绑定 candidate/payload/revision/status的 deterministic no-action receipt满足幂等，但它不是 Handoff，不能交给 Knowledge。

Knowledge apply只处理当前 Review Decision仍授权的 Handoff，以及为撤回一个已有成功 import receipt所必需的后续 withdraw；已经被更高 decision supersede且从未导入的旧 accept不得补导入。待应用 Handoff按同一 Candidate review revision升序；revision严格递增但不要求连续，因为 no-action decision会形成合法 gap。Handoff已提交、Registry失败时不删除或回滚；review/resume用同一 bytes/ID重试。相同 revision/bytes幂等；同 revision不同 bytes、倒序、hash/payload冲突 failed，不能 last-write-wins。Accepted/active仍是 Candidate Knowledge；不写 Promotion Gate或 Promoted Knowledge。

### 6.3 Review result

Decision明确提交或 unchanged完整验证后，result恰好为：

```json
{
  "candidate_id": "cand_<24hex>",
  "decision_disposition": "created",
  "handoff_action": "accept",
  "handoff_id": "hnd_<24hex>",
  "handoff_status": "committed",
  "import_status": "applied",
  "intake_status": "active",
  "payload_sha256": "<64hex>",
  "review_revision": 1,
  "review_status": "accepted",
  "schema_version": "gezhi.literature_review_result.v1",
  "work_id": "wrk_<uuidv4>"
}
```

值域：`decision_disposition=created|unchanged`；`handoff_action=accept|withdraw|none`；`handoff_status=committed|not_required|pending`；`import_status=applied|not_required|pending`；`intake_status=active|withdrawn|null`；revision为 `1..9223372036854775807` non-boolean integer。

Action=none必须配 handoff_id=null、handoff/import=not_required、intake=null。Accept/withdraw必须配 deterministic Handoff ID；Handoff未提交时 handoff/import=pending、intake=null；Handoff committed但 import未完成时 committed/pending/null；import applied时 accept→active、withdraw→withdrawn。

Decision前 blocked/failed/interrupted固定 result=null。Decision后的 Handoff/Import blocked、failed或安全 interruption保留 non-null partial receipt，只陈述已完成提交点；完整成功要求 required continuation applied或 no-action成立。

## 7. Primary diagnostics、outcome 与 exit

T04 V1不定义 supplemental Literature diagnostic。成功 `diagnostics=[]`；blocked/failed/interrupted恰好一个 primary。除表中 context外均为 `{}`，全部服从 CLI Diagnostics v1。

### 7.1 Add union

| code | outcome | context |
|---|---|---|
| `literature.add.configuration_invalid.v1` | blocked | `{}` |
| `literature.add.data_root_unavailable.v1` | blocked | `{}` |
| `literature.add.input_invalid.v1` | blocked | `{"field":"pdf_path|pdf_content|work_id|doi|arxiv_id|citation"}` |
| `literature.add.pdf_unavailable.v1` | blocked | `{}` |
| `literature.add.work_not_found.v1` | blocked | `{}` |
| `literature.add.identity_review_required.v1` | blocked | `{}` |
| `literature.add.identity_conflict.v1` | blocked | `{}` |
| `literature.add.work_busy.v1` | blocked | `{}` |
| `literature.add.data_root_integrity_lost.v1` | failed | `{}` |
| `literature.add.source_changed.v1` | failed | `{}` |
| `literature.add.content_identity_collision.v1` | failed | `{}` |
| `literature.add.commit_failed.v1` | failed | `{}` |
| `literature.add.catalog_projection_failed.v1` | failed | `{}` |
| `literature.add.user_interrupted.v1` | interrupted | `{}` |

### 7.2 Resume union

| code | outcome | context |
|---|---|---|
| `literature.resume.configuration_invalid.v1` | blocked | `{}` |
| `literature.resume.data_root_unavailable.v1` | blocked | `{}` |
| `literature.resume.work_invalid.v1` | blocked | `{}` |
| `literature.resume.work_not_found.v1` | blocked | `{}` |
| `literature.resume.work_busy.v1` | blocked | `{}` |
| `literature.resume.active_source_unavailable.v1` | blocked | `{}` |
| `literature.resume.stage_blocked.v1` | blocked | `{"reason":"<closed>","stage":"<stage>"}` |
| `literature.resume.data_root_integrity_lost.v1` | failed | `{}` |
| `literature.resume.stage_failed.v1` | failed | `{"reason":"<closed>","stage":"<stage>"}` |
| `literature.resume.recovery_failed.v1` | failed | `{}` |
| `literature.resume.user_interrupted.v1` | interrupted | `{"stage":"<stage>"}` |

`stage_blocked` closed matrix：

| stage | allowed reason |
|---|---|
| `ingest` | `identity_review_required`, `source_unavailable` |
| `ocr` | `ocr_runtime_unavailable`, `ocr_transient_exhausted` |
| `canonicalize` | `canonical_prerequisite_unavailable` |
| `read` | `reader_input_too_large`, `model_context_limit`, `codex_runtime_unavailable`, `codex_timeout_exhausted`, `codex_network_exhausted`, `codex_rate_limit_exhausted`, `codex_server_error_exhausted`, `codex_transient_exhausted` |
| `review` | `awaiting_review` |
| `handoff` | `handoff_blocked` |
| `knowledge_import` | `import_blocked`, `registry_unavailable`, `registry_busy` |

`stage_failed` closed matrix：

| stage | allowed reason |
|---|---|
| `ingest` | `source_asset_invalid`, `identity_conflict`, `commit_failed` |
| `ocr` | `ocr_failed`, `asset_integrity_lost`, `commit_failed` |
| `canonicalize` | `canonicalization_failed`, `asset_integrity_lost`, `commit_failed` |
| `read` | `reader_input_invalid`, `codex_process_failed`, `reader_output_invalid`, `candidate_validation_failed`, `asset_integrity_lost`, `commit_failed` |
| `review` | `review_state_invalid`, `asset_integrity_lost`, `commit_failed` |
| `handoff` | `handoff_failed`, `revision_conflict`, `asset_integrity_lost`, `commit_failed` |
| `knowledge_import` | `import_failed`, `revision_conflict`, `registry_conflict`, `commit_failed` |

Stage/reason必须来自表中 ASCII enum，不能拼内部 error/provider/exception。

### 7.3 Review union

| code | outcome | context | result |
|---|---|---|---|
| `literature.review.configuration_invalid.v1` | blocked | `{}` | null |
| `literature.review.data_root_unavailable.v1` | blocked | `{"data_root":"literature|knowledge"}` | decision前null；Knowledge gate时non-null |
| `literature.review.candidate_invalid.v1` | blocked | `{}` | null |
| `literature.review.candidate_not_found.v1` | blocked | `{}` | null |
| `literature.review.work_busy.v1` | blocked | `{}` | null |
| `literature.review.handoff_blocked.v1` | blocked | `{}` | non-null |
| `literature.review.import_blocked.v1` | blocked | `{}` | non-null |
| `literature.review.data_root_integrity_lost.v1` | failed | `{"data_root":"literature|knowledge"}` | 按已提交事实 |
| `literature.review.review_state_invalid.v1` | failed | `{}` | null |
| `literature.review.review_commit_failed.v1` | failed | `{}` | null |
| `literature.review.handoff_failed.v1` | failed | `{}` | non-null |
| `literature.review.import_failed.v1` | failed | `{}` | non-null |
| `literature.review.user_interrupted.v1` | interrupted | `{"stage":"review|handoff|knowledge_import"}` | decision前null；之后non-null |

### 7.4 Normal exit

完整 Human或JSON presentation后的 normal exit：succeeded→`0`、blocked→`2`、failed→`1`、interrupted→`130`。这些数字只属于完整 handled receipt；raw argv/bootstrap/grammar/unexpected exception/external termination/uncertain commit/presentation failure不能因数字相同被重分类。

## 8. JSON 与 Human presentation

JSON outer command分别为 `literature.add|literature.resume|literature.review`。Envelope先通过本合同全部规则，再按 CLI JSON v1恰好整体序列化一次；唯一末尾 LF在内的完整 buffer上限为 `32,768` raw UTF-8 bytes inclusive。32,769或无法形成唯一 buffer时不输出 fallback、不改领域事实、不换 Human；该 presentation failure不属于 normal exit。完整成功 stdout只有 buffer、stderr空，不混入 Rich/progress/prompt/log/child/path。空/partial stdout不是 receipt。该 32 KiB profile独立冻结，不默默继承 knowledge.ask 的 cap或 cancellation bridge。Presentation开始前必须 seal immutable outcome/buffer，停止并释放 command-owned child、write、handle与 writer ownership；随后共享 CLI writer对 fd1恰好一次切换 Windows binary mode，并用 blocking write loop从 offset 0写同一 buffer直到完整 completion。Short write只推进实际正整数 count；zero/negative/bool/超请求 count、setup/write exception或无法证明 completion都停止输出、禁止 fallback，并且不使用第7.4节 normal outcome exit。

Human renderer消费同一 sealed outcome/result/diagnostic，不重读资产。完整 presentation使用 UTF-8 stdout、stderr空，首行固定：

| command/outcome | first line |
|---|---|
| add succeeded / blocked / failed / interrupted | `Literature add：完成` / `Literature add：已阻塞` / `Literature add：失败` / `Literature add：已中断` |
| resume succeeded / blocked / failed / interrupted | `Literature resume：完成` / `Literature resume：已阻塞` / `Literature resume：失败` / `Literature resume：已中断` |
| review succeeded / blocked / failed / interrupted | `Literature review：完成` / `Literature review：已阻塞` / `Literature review：失败` / `Literature review：已中断` |

存在 result时显示稳定 ID、disposition/阶段或 Review→Handoff→Import状态；不得显示 PDF path、citation、文档内容、异常/provider文本。Resume pending Candidate逐个显示完整 ID，并给出显式 `gezhi literature review <candidate_id> --accept|--reject|--defer` 下一步；不能 prompt、默认、倒计时接受或把回车当批准。Primary code/context映射为固定中文原因/下一步。颜色/box drawing/terminal width不冻结；redirected non-color subprocess必须保留首行、稳定字段顺序、单末尾 LF、同 exit且无 ANSI。


完整 Human body 顺序固定为：首行；若 result非 null则按该 result Schema 的 canonical key顺序逐行显示 `字段：值`（array逐项缩进）；primary的 `原因：...`；最后是 `下一步：...`。下表正文不含句末句号，renderer不得改写、拼异常或回显输入：

### 8.1 Add Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.add.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 add |
| `literature.add.data_root_unavailable.v1` | Literature 数据目录不可用 | 运行 gezhi doctor 并修复 Literature 数据目录 |
| `literature.add.input_invalid.v1` | 输入字段无效（`<field>`） | 修正该输入字段后重新运行 add |
| `literature.add.pdf_unavailable.v1` | PDF 当前不可稳定读取 | 确认文件存在、可读且未被修改后重试 |
| `literature.add.work_not_found.v1` | 指定 Work 不存在 | 核对 Work ID 后重试 |
| `literature.add.identity_review_required.v1` | Work 身份需要人工确认 | 核对 DOI、arXiv ID 与目标 Work 后显式重试 |
| `literature.add.identity_conflict.v1` | Work、Source 或身份别名互相冲突 | 修正冲突的身份输入，不要覆盖既有资产 |
| `literature.add.work_busy.v1` | 该 Work 正由另一个写流程处理 | 等待该流程结束后重试 |
| `literature.add.data_root_integrity_lost.v1` | Literature 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi doctor |
| `literature.add.source_changed.v1` | PDF 在读取过程中发生变化 | 固定文件内容后重新运行 add |
| `literature.add.content_identity_collision.v1` | Source 内容身份发生冲突 | 保留现有资产并报告冲突，不要覆盖 |
| `literature.add.commit_failed.v1` | Source 或 Active Source 提交失败 | 保持相同输入重新运行 add 以恢复 |
| `literature.add.catalog_projection_failed.v1` | Literature 索引投影未完成 | 保持相同输入重新运行 add 以重建投影 |
| `literature.add.user_interrupted.v1` | 用户中断了 add | 确认现有资产状态后按需要重试 |

### 8.2 Resume Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.resume.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 resume |
| `literature.resume.data_root_unavailable.v1` | Literature 数据目录不可用 | 运行 gezhi doctor 并修复 Literature 数据目录 |
| `literature.resume.work_invalid.v1` | Work ID 格式无效 | 使用完整规范 Work ID 重试 |
| `literature.resume.work_not_found.v1` | 指定 Work 不存在 | 核对 Work ID 后重试 |
| `literature.resume.work_busy.v1` | 该 Work 正由另一个写流程处理 | 等待该流程结束后重试 |
| `literature.resume.active_source_unavailable.v1` | Active Source 不可用 | 先用 literature add 明确选择可用 Source |
| `literature.resume.stage_blocked.v1` | `<stage>` 阶段已阻塞（`<reason>`） | 修复该前置条件后重新运行 resume；awaiting_review 时对列出的 Candidate 显式 review |
| `literature.resume.data_root_integrity_lost.v1` | Literature 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi doctor |
| `literature.resume.stage_failed.v1` | `<stage>` 阶段失败（`<reason>`） | 保留现有资产，修复该阶段后重新运行 resume |
| `literature.resume.recovery_failed.v1` | Literature 恢复检查失败 | 保留 staging 与历史资产并运行 gezhi doctor |
| `literature.resume.user_interrupted.v1` | 用户在 `<stage>` 阶段中断了 resume | 确认现有资产状态后重新运行 resume |

### 8.3 Review Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.review.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 review |
| `literature.review.data_root_unavailable.v1` | `<data_root>` 数据目录不可用 | 修复该 Context 数据目录后用相同 action 重试 |
| `literature.review.candidate_invalid.v1` | Candidate 资产无效 | 核对 Candidate 来源与完整性 |
| `literature.review.candidate_not_found.v1` | 指定 Candidate 不存在 | 核对 Candidate ID 后重试 |
| `literature.review.work_busy.v1` | Candidate 所属 Work 正由另一个写流程处理 | 等待该流程结束后重试 |
| `literature.review.handoff_blocked.v1` | Review Decision 已保存，但 Handoff 尚未完成 | 用相同 action 重试或运行 literature resume |
| `literature.review.import_blocked.v1` | Review Decision 与 Handoff 已保存，但 Knowledge import 尚未完成 | 修复 Knowledge 前置条件后用相同 action 重试或运行 literature resume |
| `literature.review.data_root_integrity_lost.v1` | `<data_root>` 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi doctor |
| `literature.review.review_state_invalid.v1` | Candidate Review 历史无效 | 保留审核资产并检查 revision 与 payload identity |
| `literature.review.review_commit_failed.v1` | Review Decision 提交失败 | 保持相同 Candidate 与 action 重试 |
| `literature.review.handoff_failed.v1` | Review Decision 已保存，但 Handoff 失败 | 保留 Decision 并用相同 action 重试 |
| `literature.review.import_failed.v1` | Review Decision 与 Handoff 已保存，但 Knowledge import 失败 | 保留前置事实并修复 Registry 冲突 |
| `literature.review.user_interrupted.v1` | 用户在 `<stage>` 阶段中断了 review | 用相同 Candidate 与 action 重试以继续未完成步骤 |


## 9. Crash、重入与持久断言

- Success result只能在其全部 authority提交点明确完成后形成；presentation failure不回滚 Work、Source、Decision、Handoff或 Registry。
- Staging、partial manifest、坏 hash、孤立 pointer、SQLite row或旧 stdout不能成为 success。Reader/status只接受完整 authority。
- Directory commit成功但 pointer/projection/import未完成时，下次相同 add/review/resume只补剩余步骤；不新建 Source、Decision revision或 Handoff ID。
- Target conflict永不 overwrite/merge/delete-then-retry/换 ID。确定 failure同 invocation不重试；uncertain立即停止，下一 invocation从零复验。
- Resume不清理历史。Quarantine是原路径逻辑拒绝；V1无 archive/purge/repair/force/resume-staging或隐藏 maintenance alias。
- `catalog.sqlite3` 从有效 assets重建。Knowledge Registry仍是 Knowledge事实源；Literature不直接写表，只调用 intake interface。
- 单个 Candidate invalid/quarantine只阻塞其 review/handoff，不污染其他 Work、Registry、Literature只读资产或未来 Context。

## 10. Public subprocess 验收

两种 launcher均覆盖：

### Add

- 新 PDF创建 Work/Source/asset并 active；显式 Work新增 Source并切换；duplicate不复制；inactive duplicate只切换 pointer。
- Source/alias跨 Work冲突、identity ambiguity、hash collision、relative/UNC/WSL/reparse/ADS/directory/missing/changing/bad-magic、invalid IDs/aliases均按表拒绝且无 success pointer。
- 在 Source commit、Active pointer、catalog transaction、presentation之间注入失败，重试只补未完成提交。
- Add不探测 OCR/Codex/Knowledge、不调用 WSL、不安装依赖。

### Resume

- 七阶段每个 valid success跳过；directory committed/pointer missing只补 pointer；从 ingest自动推进到 pending review并返回 IDs，不写 Decision。
- Zero Candidate完成 no-op；全部有 decision时补 Handoff/Import；有已授权 backlog和其他 pending时先补 backlog再 awaiting_review。
- 每阶段 blocked/failed/interrupted、遗留 running、partial/invalid orphan、target conflict、uncertain均无 partial success/overwrite。
- OCR缺失只在 ocr阻塞；Codex缺失只在 read；Knowledge root只在 import；已完成阶段仍可读。

### Review

- 三 action、首 revision、同 action幂等、不同 action追加；accepted→active；never-accepted nonaccepted→no action；accepted后 nonaccepted→withdrawn；之后 accepted→active。
- 新 payload不继承旧 decision；坏 Evidence/hash/collision拒绝。
- Decision/Handoff/Registry/presentation逐点失败保留前置事实，retry同 identity续行。
- Codex/resume/status/reader不能写 Decision；无 default accept、batch、note、Promotion或Research Interest。

### Presentation

- 每 command/outcome覆盖 Human/JSON；完整 canonical bytes、32 KiB inclusive cap、单 LF、channel/exit匹配。
- Result presence符合第4.4、5.3、6.3、7.3节；earlier commit不自动使 outer succeeded。
- Redirected Human无 ANSI，首行/稳定字段/next action可断言；Human/JSON来自同一 outcome。

## 11. 非目标与演进

本合同不增加 command/option、batch/interactive review、Identity Review专用命令、自动搜索/下载、网络 acquisition、多 Source评分、force rerun、维护命令、GUI/daemon、动态插件、Promotion Gate、Promoted Knowledge、Research Interest或 Relevance Candidate。它不冻结 OCR/Canonical/Reader内部 schema、Registry表、Human样式或 child transport实现；这些由各实施 ticket/既有合同拥有。

未来 Context先定义业务语言、状态所有权与 versioned handoff，再由 static composition加入；不得复用 human-review capability、直接写 Literature assets或把七阶段扩成通用 DAG。

修改 result字段/值域、primary code/context、阶段推进权限、Review→Handoff→Intake矩阵、Active Source语义或 normal exit，必须升级 nested schema/code或使用 replacing decision。只改未冻结 Rich样式或内部 module拆分不改变本合同。
