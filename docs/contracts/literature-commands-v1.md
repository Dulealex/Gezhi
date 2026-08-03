# Literature Commands v1 合同

状态：已冻结。本合同关闭 Windows V1 的 `literature add`、`literature resume` 与 `literature review` 三个公开命令从成功 grammar handoff 到完整 Human/JSON presentation 之前的领域结果；token、arity、option scope 与 parser failure 继续由 [CLI Command v1](./cli-command-v1.md) 唯一拥有。

本合同实现 [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) 与 [T04 / Issue #5](https://github.com/Dulealex/Gezhi/issues/5)，并保持以下既有决定：

- [ADR 0011](../adr/0011-model-literature-as-work-source-and-assets.md)、[ADR 0012](../adr/0012-use-stable-internal-identities-and-external-aliases.md)：`Work → Source → Assets`、稳定内部身份与内容寻址 Source。
- [ADR 0013](../adr/0013-preserve-immutable-stage-runs-and-atomic-current-pointers.md)、[ADR 0027](../adr/0027-use-a-fixed-seven-stage-asset-driven-workflow.md)：不可变 run、原子 current pointer 与固定七阶段。
- [ADR 0019](../adr/0019-use-append-only-candidate-review-decisions.md)、[ADR 0025](../adr/0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md)、[ADR 0026](../adr/0026-continue-review-through-handoff-and-knowledge-import.md) 与 [ADR 0121](../adr/0121-classify-continuation-failures-by-recoverability-and-certainty.md)：追加式审核、accept/withdraw、审核后的可恢复续行，以及 blocked/failed/uncertain 分类。
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

每个实际消费的 Context Data Root 在初始 physical gate 使用闭合分类：相对、UNC/WSL UNC、remote mapping、device/Volume GUID/ADS、reparse/8.3/SUBST/volume mount 或其他已证明的 hidden alias/physical overlap 是 `data_root_unsafe`；目录缺失、不可访问、不是目录，或在没有正面 unsafe 证据时无法完成 identity proof 是 `data_root_unavailable`。初始 gate 通过后，同一 frozen physical identity 在执行中漂移或失去可信性只能是 `data_root_integrity_lost`，不得降格为 unsafe/unavailable。`add` 只可能为 Literature root 产生这些分类；`resume` 的三个 root code 都使用第 7.2 节 exact context object：`literature` variant 属于初始 Literature authority gate或其后 identity proof并阻止 result seal，`knowledge` variant 只在到达 `knowledge_import` 后实际消费 Knowledge root时出现且不要求 Literature root 同时失去可信性；`review` 用第 7.3 节 exact context object 区分两个 root 及 Decision 前后 result presence。

### 2.2 稳定 ID

本合同只接受以下大小写精确的稳定 ID：

- Work：`wrk_<lowercase UUIDv4>`；UUID version nibble 为 `4`，variant 为 RFC 4122 variant。
- Source：`src_<24 位小写十六进制>`，并等于 Source 原始完整 bytes SHA-256 前 24 位。
- Candidate：`cand_<24 位小写十六进制>`，并与完整 `payload_sha256` 及 Candidate Knowledge v1 payload 一致。
- Handoff：`hnd_<24 位小写十六进制>`，算法见第 6.3 节。

Parser 不验证或修复这些值；空字符串、前后空白、大写、非规范 UUID、别名、路径或“当前项”标记均由所属 command 的 handled domain gate 拒绝。

### 2.3 Writer ownership

每个 Work 同时最多一个写 invocation。Ownership 必须绑定当前线程、depth one、Literature root physical identity 与目标 `work_id`；它不是 lock-file 名称、PID、时间戳或 caller 可构造的 boolean。`add` 在尚未决定 Work 时取得 root-level identity-intake ownership，解析出 Work 后转入该 Work ownership；不得同时持有两个 Work writer ownership。

另一个 writer 已拥有相同作用域时返回受控 `blocked`，不无限等待、不 steal lock、不按 PID/时间猜测 owner 已死亡。`add` 尚未解析出 Work 时，root-level identity-intake 争用只能是 `literature.add.identity_intake_busy.v1`；Work 一旦唯一解析，root-level scope 必须先转交/释放，此后同 Work 争用只能是 `literature.add.work_busy.v1`。`work_busy` 不得用于尚未解析 Work 的 root scope。Crash 后的新 invocation 只有在重新取得 ownership 并从当前 namespace/bytes 重验后才能恢复；旧进程内证据全部失效。

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
- `interrupted` 只用于后续 owner 在重新取得 ownership、确认 prior owner 已不存在并安全收尾遗留 `running` attempt 后写入的不可变阶段审计；它不是本次 CLI outer outcome。T04 不批准用户取消来源或 handled interruption receipt。

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

`disposition` 只允许 `created_work|added_source|reused_source`。三个值都可能 `active_source_changed=true`；只有 already-active reused Source 为 false。Add 的 blocked/failed 固定 `result=null`；较早提交点可能已存在，但 null 不表示回滚或成功 receipt。

## 5. `literature resume`

### 5.1 重入算法

`resume` 恰好接收一个显式 Work ID，没有 implicit current/last Work。Work/ownership通过后必须：

1. 从文件权威 manifest/assets/current 与 Review/Handoff/Registry receipts重建七阶段 snapshot；SQLite不能覆盖文件事实。
2. 对 directory commit已存在但 current缺失/陈旧的完整 success，验证 fingerprint/hash/namespace后只补 pointer，不重跑。
3. 对 prior owner不存在的遗留 running/staging分类；只有完整有效 terminal success且只差已批准 rename/pointer的 orphan可补交，partial/unsafe/invalid原地 quarantine，不修补成 success。
4. 跳过全部匹配当前上游 fingerprint的 success，从最早未满足 obligation开始。
5. 串行推进自动阶段，直到 complete、首个本次 blocked/failed、uncertain commit，或只剩没有显式 Review Decision的 Candidate。历史 `interrupted` run 是关闭的审计事实，不单独阻止新 invocation 从权威资产重算 Continuation Point。

一次 resume 可以连续完成多个自动阶段，但每阶段有独立 run/manifest/commit point；后阶段只能读前阶段 committed success。过去 blocked/failed/interrupted run 不永久禁止显式 resume；修复前置条件后可创建新 run，但不得修改旧 run、复用失败 partial或换 provider。相同 success禁止重算，V1无 `--force`。

### 5.2 人工 gate 与 backlog

`resume` 永不创建 Review Decision、把 pending/deferred改 accepted、选择 action、伪造 reviewer或调用模型审核。没有 decision 的 Candidate 保持 pending；deferred是已发生的人类 decision，不等同 pending，也不进入 accept Handoff。

在返回 `awaiting_review` 前，resume必须先补齐已由历史显式 decision授权而未完成的 Handoff/Import backlog，按 `(candidate_id ASCII bytes, review_revision)` 升序执行；这只续行已提交决定。若 backlog 在 `handoff` 或 `knowledge_import` 形成 handled blocked/failed，本 invocation 立即停在该实际 stage，`stop_stage` 与 primary context 的 stage 相同；即使其他 Candidate 仍 pending、`pending_candidate_ids` 非空且 Work 的全局 Continuation Point 仍是 `review`，也不得把这次停止改写为 `awaiting_review`。只有 backlog 全部成功结清后才能呈现 `awaiting_review`；此时若仍有 pending Candidate，实际 `stop_stage=review`、Continuation Point 为 `review` 且 outer blocked。零 Candidate或全部 Candidate有 accepted/rejected/deferred decision时，review obligation可满足并继续。

聚合 success 条件：review要求当前 semantic result每个 Candidate都有绑定同一 payload hash的 current decision（零 Candidate自动满足）；handoff要求每个 decision有 matching accept/withdraw Handoff或“从未 accept且当前 non-accepted”的 no-action receipt；knowledge_import要求每个 required Handoff有 Registry receipt、每个 no-action有同一 deterministic receipt。

### 5.3 Resume result

`ResumeResultV1` 的 presence 由唯一 `resume result seal` 决定。进入该 seal 前发生的任何 handled failure 都是 `result=null`。Seal 必须同时证明：Literature root、Work 与 Active Source identity 完整有效；invocation 初始 Continuation Point 唯一；每个列入 `advanced_stages` 的 success run、pointer 或 receipt 已明确提交并 readback；所有已启动的 stage/child/handle 已 settle；根据本 invocation 已确认的停止事实与当前 authority 重建的实际 `stop_stage`、pending Candidate 序列及其他字段完整、有界且互相一致。满足这些事实后 result 恰好为以下 closed snapshot：

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

`start_stage`/`stop_stage` 各为七阶段值或 `complete`。`start_stage` 始终是 invocation 初始 Continuation Point；`stop_stage` 是本 invocation 在完成允许的自动推进或已授权 backlog 续行后实际停止的 Literature Stage，完整完成时才是 `complete`，它不表示呈现时 Work 的全局 Continuation Point。因 pending Candidate 使初始 Continuation Point 为 `review`、但 invocation 先续行已授权 backlog 时，`start_stage` 仍为 `review`。`advanced_stages` 是本 invocation明确发布 success或只修复 success pointer/receipt的阶段，无重复且按阶段顺序；既有 skip不列入。`pending_candidate_ids` 最多12项，按 Candidate Knowledge v1顺序，只列无 decision 的当前 Candidate；deferred不列入。

`pipeline_complete=true` iff `stop_stage=complete`、pending为空且七阶段当前 obligations全可验证；already-complete调用使用 start/stop=`complete`、advanced=[]。每个合法 `stage_blocked` 或 `stage_failed` stage/reason pair 只能在 `resume result seal` 完成后选择，因此其 result 一律 non-null，`stop_stage` 等于 primary context 的 stage。`pending_candidate_ids` 非空不推出 `stop_stage=review`：backlog blocked/failed 时可分别为 `handoff` 或 `knowledge_import`，同时 Work 的全局 Continuation Point 仍为 `review`；只有 backlog 成功结清后仍有 pending Candidate 的 `awaiting_review` 分支才要求 `stop_stage=review`。`commit_failed` 只表示当前 stage 没有达到 success commit point：该 stage 不得进入 `advanced_stages`，已经明确提交的较早阶段仍保留。

Active Source gate 位于 seal 前：缺失、当前不可稳定读取或没有正面 invalid 证据而无法完成 identity proof 选择 blocked `active_source_unavailable`；Source asset 存在但 manifest、ID、hash 或 bytes 确定矛盾选择 failed `active_source_invalid`。两者都固定 `result=null`，不得伪装成 `ingest` stage pair。

`configuration_invalid`、`work_invalid`、`work_not_found`、`work_busy`、`active_source_unavailable`、`active_source_invalid` 与 `recovery_failed` 七个 code 在所有 context 下固定 `result=null`。三个 Resume root code 按 context variant 决定 presence：`{"data_root":"literature"}` 的 unsafe、unavailable、integrity-lost 三个 variant 都阻止 seal并为 null，因此总计仍有十个 null variants；`{"data_root":"knowledge"}` 的三个 variant 只在到达 `knowledge_import` 后选择，全部为 non-null。Knowledge variant 必须先 settle Knowledge-owned child/handle/write，再仅从仍可信的 Literature authority 重建并 seal snapshot；`pipeline_complete=false`、`stop_stage=knowledge_import`，`advanced_stages`、`pending_candidate_ids` 与其他字段保留本 invocation 已明确提交的进度，未成功的 `knowledge_import` 不得进入 `advanced_stages`。Knowledge root故障不暗示或要求 Literature root失信，三个 root code也不得折叠为 `stage_blocked`/`stage_failed` pair。

历史 `interrupted` 只作为 snapshot 内的阶段审计事实，不能产生 outer `interrupted`。Snapshot 不唯一、Literature authority 漂移或 commit outcome uncertain 时不得构造近似 result；uncertain commit 仍位于正常 handled 矩阵外。

## 6. `literature review`

### 6.1 Candidate、action 与 decision

Raw Candidate selector 先按第 2.2 节 grammar 原样校验；格式、大小写或规范性无效只选择 blocked `candidate_invalid`，格式有效但没有对应 Candidate只选择 blocked `candidate_not_found`，两者都为 `result=null`。一旦 canonical ID 已解析到现存 Literature-owned Candidate，就复验 ID/hash/canonical bytes/provenance/Evidence Pointer、payload identity、collision 与 asset完整性；任一确定失败只能选择 failed `candidate_integrity_lost` 且 `result=null`，不得退回 `candidate_invalid`。Candidate可来自当前或历史有效 semantic run，以便显式撤回历史已导入 Candidate；staging、collision、坏资产或仅有 SQLite row不可审核。

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

同 action复用同一 identity。只有至少一个先前 accept 已有成功 Knowledge import receipt 时，accepted→non-accepted 才发布 withdraw。若旧 accepted Decision/Handoff 尚无成功 import receipt 就被更高 rejected/deferred revision supersede，旧 accept 不得再补导入，新 revision 也不得发布空 withdraw，Registry 继续没有该 Candidate。Non-accepted→accepted发布新 accept；已 withdrawn后的更高 non-accepted revision仍发布更高 withdraw，保存最新 review revision。Pending从不产生 Handoff。

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

[ADR 0121](../adr/0121-classify-continuation-failures-by-recoverability-and-certainty.md) 部分取代 ADR 0026 的笼统 blocked 映射：实际消费 root 的 physical gate先选择 context-specific Data Root code；Resume 的 Registry unavailable/busy、revision/Registry conflict、asset integrity与 commit failure再优先选择互斥的 specific stage reason。只有 Handoff 或 `KnowledgeIntake` interface 返回的其余已批准 typed recoverable prerequisite 才使用 generic blocked，其余已批准 deterministic typed interface failure 才使用 generic failed；unknown、untyped 与 commit-uncertain 均在正常 handled 矩阵外。任何此前已明确提交的 Decision、Handoff 或 Registry fact 都不回滚，后续 invocation 复用相同 Candidate、payload、revision 与 Handoff identity。

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

Decision前 blocked/failed固定 result=null。Decision后先应用 ADR 0121 的 specific-before-generic 互斥映射；generic blocked/failed 只接受 Handoff 或 `KnowledgeIntake` interface 的其余已批准 typed verdict，两者都保留 non-null partial receipt且只陈述已完成提交点。Unknown、untyped 或 commit-uncertain 不形成 handled receipt；完整成功要求 required continuation applied或 no-action成立。

## 7. Primary diagnostics、outcome 与 exit

T04 V1不定义 supplemental Literature diagnostic。成功 `diagnostics=[]`；blocked/failed恰好一个 primary。除表中 context外均为 `{}`，全部服从 CLI Diagnostics v1。

### 7.1 Add union

| code | outcome | context |
|---|---|---|
| `literature.add.configuration_invalid.v1` | blocked | `{}` |
| `literature.add.data_root_unsafe.v1` | blocked | `{}` |
| `literature.add.data_root_unavailable.v1` | blocked | `{}` |
| `literature.add.input_invalid.v1` | blocked | 第 7.1 节下方的 closed field object |
| `literature.add.identity_intake_busy.v1` | blocked | `{}` |
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

`literature.add.input_invalid.v1` 的 context 是以下六个 exact object 的 closed one-of：`{"field":"pdf_path"}`、`{"field":"work_id"}`、`{"field":"doi"}`、`{"field":"arxiv_id"}`、`{"field":"citation"}`、`{"field":"pdf_content"}`。不得出现其他 value、key 或 additional property。`identity_intake_busy` 只证明尚未解析 Work 时的 root-level identity-intake scope 正忙；`work_busy` 只在 Work 已唯一解析后证明该 Work scope 正忙。

### 7.2 Resume union

| code | outcome | context | result |
|---|---|---|---|
| `literature.resume.configuration_invalid.v1` | blocked | `{}` | null |
| `literature.resume.data_root_unsafe.v1` | blocked | 第 7.2 节下方的 closed Data Root object | Literature variant 为 null；Knowledge variant 为 non-null |
| `literature.resume.data_root_unavailable.v1` | blocked | 第 7.2 节下方的 closed Data Root object | Literature variant 为 null；Knowledge variant 为 non-null |
| `literature.resume.work_invalid.v1` | blocked | `{}` | null |
| `literature.resume.work_not_found.v1` | blocked | `{}` | null |
| `literature.resume.work_busy.v1` | blocked | `{}` | null |
| `literature.resume.active_source_unavailable.v1` | blocked | `{}` | null |
| `literature.resume.stage_blocked.v1` | blocked | `{"reason":"<closed>","stage":"<stage>"}` | non-null |
| `literature.resume.data_root_integrity_lost.v1` | failed | 第 7.2 节下方的 closed Data Root object | Literature variant 为 null；Knowledge variant 为 non-null |
| `literature.resume.active_source_invalid.v1` | failed | `{}` | null |
| `literature.resume.stage_failed.v1` | failed | `{"reason":"<closed>","stage":"<stage>"}` | non-null |
| `literature.resume.recovery_failed.v1` | failed | `{}` | null |

三个 Resume Data Root primary 的 context 都是且只能是 `{"data_root":"literature"}` 或 `{"data_root":"knowledge"}` 两个 exact object 的 closed one-of；不得出现合并字符串、其他 value、其他 key 或 additional property。三个 `literature` variant 均阻止 result seal 并返回 null；三个 `knowledge` variant 只在到达 `knowledge_import` 后出现，均返回第 5.3 节冻结的 non-null sealed result，`stop_stage=knowledge_import`，且不属于下方 42 个 stage/reason pair。Knowledge root fault 不暗示 Literature root 同时失去可信性。

`stage_blocked` closed matrix：

| stage | allowed reason | pair count |
|---|---|---:|
| `ingest` | `identity_review_required` | 1 |
| `ocr` | `ocr_runtime_unavailable`, `ocr_transient_exhausted` | 2 |
| `canonicalize` | `canonical_prerequisite_unavailable` | 1 |
| `read` | `reader_input_too_large`, `model_context_limit`, `codex_runtime_unavailable`, `codex_timeout_exhausted`, `codex_network_exhausted`, `codex_rate_limit_exhausted`, `codex_server_error_exhausted`, `codex_transient_exhausted` | 8 |
| `review` | `awaiting_review` | 1 |
| `handoff` | `handoff_blocked` | 1 |
| `knowledge_import` | `registry_unavailable`, `registry_busy`, `import_blocked` | 3 |

`stage_failed` closed matrix：

| stage | allowed reason | pair count |
|---|---|---:|
| `ingest` | `identity_conflict`, `commit_failed` | 2 |
| `ocr` | `ocr_failed`, `asset_integrity_lost`, `commit_failed` | 3 |
| `canonicalize` | `canonicalization_failed`, `asset_integrity_lost`, `commit_failed` | 3 |
| `read` | `reader_input_invalid`, `codex_process_failed`, `reader_output_invalid`, `candidate_validation_failed`, `asset_integrity_lost`, `commit_failed` | 6 |
| `review` | `review_state_invalid`, `asset_integrity_lost`, `commit_failed` | 3 |
| `handoff` | `revision_conflict`, `asset_integrity_lost`, `commit_failed`, `handoff_failed` | 4 |
| `knowledge_import` | `revision_conflict`, `registry_conflict`, `commit_failed`, `import_failed` | 4 |

Stage/reason 必须来自表中 ASCII enum，不能拼内部 error/provider/exception。两张表精确展开为 17 个 blocked pair 与 25 个 failed pair，共 42 个 retained pair；没有隐含组合。每个 retained pair 都必须有独立可达见证：先通过 Literature root、Work、Active Source 与唯一初始 Continuation Point 的 result-presence 前置条件，再把执行推进到表中 stage 并注入该 reason，最终形成 non-null sealed result，且 `stop_stage` 精确等于该 stage。`ingest` 的三个 retained pair 只覆盖一个已验证 Active Source 的 ingest identity/current repair：可恢复 identity ambiguity 是 blocked，确定 identity conflict 或 repair commit failure 是 failed。Active Source 本身缺失/不可证明与确定 invalid 分别提前映射到 `active_source_unavailable` 与 `active_source_invalid`，不得出现在这 42 个 pair 中。

ADR 0121 的映射按闭合层级执行：实际消费 Data Root 的 physical gate 先选择 context-specific root primary，不能改写为 stage pair；Resume 的 Registry unavailable/busy 分别只选择 `knowledge_import/registry_unavailable` 或 `knowledge_import/registry_busy`，与 `import_blocked` 互斥；Handoff 的 revision conflict、asset integrity lost、commit failure，以及 Knowledge import 的 revision conflict、Registry conflict、commit failure，分别只选择对应 specific `stage_failed` reason，并与 generic failed reason 互斥。Specific reason 一律优先；`handoff_blocked`/`import_blocked` 只接收 Handoff/`KnowledgeIntake` interface 的其余已批准 typed recoverable prerequisite，`handoff_failed`/`import_failed` 只接收其余已批准 deterministic typed interface failure。Unknown、untyped、commit-uncertain 不得选择任一 pair。

### 7.3 Review union

| code | outcome | context | result |
|---|---|---|---|
| `literature.review.configuration_invalid.v1` | blocked | `{}` | null |
| `literature.review.data_root_unsafe.v1` | blocked | 第 7.3 节下方的 closed Data Root object | Literature gate 时 null；Knowledge gate 时 non-null |
| `literature.review.data_root_unavailable.v1` | blocked | 第 7.3 节下方的 closed Data Root object | Literature gate 时 null；Knowledge gate 时 non-null |
| `literature.review.candidate_invalid.v1` | blocked | `{}` | null |
| `literature.review.candidate_not_found.v1` | blocked | `{}` | null |
| `literature.review.work_busy.v1` | blocked | `{}` | null |
| `literature.review.handoff_blocked.v1` | blocked | `{}` | non-null |
| `literature.review.import_blocked.v1` | blocked | `{}` | non-null |
| `literature.review.data_root_integrity_lost.v1` | failed | 第 7.3 节下方的 closed Data Root object | Decision 未提交时 null；已提交时 non-null |
| `literature.review.candidate_integrity_lost.v1` | failed | `{}` | null |
| `literature.review.review_state_invalid.v1` | failed | `{}` | null |
| `literature.review.review_commit_failed.v1` | failed | `{}` | null |
| `literature.review.handoff_failed.v1` | failed | `{}` | non-null |
| `literature.review.import_failed.v1` | failed | `{}` | non-null |

三个 Review Data Root primary 的 context 都是且只能是 `{"data_root":"literature"}` 或 `{"data_root":"knowledge"}` 两个 exact object 的 closed one-of；不得出现合并字符串、其他 value、其他 key 或 additional property。Unsafe/unavailable 的 `literature` variant 只可能来自 Decision 前的初始 Literature gate，因此 result 为 null；`knowledge` variant 只可能在 Decision 已明确提交或 unchanged 验证、且实际需要 import 后到达，因此 result 为 non-null。Integrity-lost 的 `literature` variant 以 Decision 是否已明确提交决定 result presence；`knowledge` variant 必然在 Decision 后且 result 为 non-null。

`candidate_invalid` 只表示 raw selector 的格式、大小写或规范性无效；一旦规范 Candidate ID 已解析到现存 Candidate，任何 ID/hash/canonical bytes/provenance/Evidence/payload/collision/asset 完整性失败都只选择 `candidate_integrity_lost`。实际消费 root 的 physical gate 先选择 Data Root primary；`handoff_blocked`/`import_blocked` 只接受已知缺失且可恢复的 typed interface prerequisite，确定性的其余已批准 Handoff/KnowledgeIntake 完整性、协议、revision、commit 或 Registry failure 分别选择 `handoff_failed`/`import_failed`。Continuation outcome 保留已提交 Decision 的 non-null receipt；unknown、untyped 与 uncertain commit 位于本 union 外。

### 7.4 Primary 仲裁与同 gate fail-fast

Gate 仍按第 2.1 节严格串行；首个 handled fault 立即 stop-new-work，未到达的 gate 不得再探测。已经启动的同 gate operation 在 settle 时可能再形成 primary candidate；success candidate 只在没有任何 primary candidate 时成立。若 candidate 多于一个，`failed` 总是优先于 `blocked`，同一 outcome 再按下表从左到右选择第一个。观察时间、线程/child 完成顺序、异常类型、容器顺序和旧日志均不得参与仲裁：

| command | `failed` priority | `blocked` priority |
|---|---|---|
| add | `data_root_integrity_lost` > `source_changed` > `content_identity_collision` > `commit_failed` > `catalog_projection_failed` | `configuration_invalid` > `data_root_unsafe` > `data_root_unavailable` > `input_invalid` > `identity_intake_busy` > `pdf_unavailable` > `work_not_found` > `identity_review_required` > `identity_conflict` > `work_busy` |
| resume | `data_root_integrity_lost` > `active_source_invalid` > `stage_failed` > `recovery_failed` | `configuration_invalid` > `data_root_unsafe` > `data_root_unavailable` > `work_invalid` > `work_not_found` > `work_busy` > `active_source_unavailable` > `stage_blocked` |
| review | `data_root_integrity_lost` > `candidate_integrity_lost` > `review_state_invalid` > `review_commit_failed` > `handoff_failed` > `import_failed` | `configuration_invalid` > `data_root_unsafe` > `data_root_unavailable` > `candidate_invalid` > `candidate_not_found` > `work_busy` > `handoff_blocked` > `import_blocked` |

表中 suffix 自动带所属 `literature.<command>.` prefix 与 `.v1`。同一个 code 有多个合法 context candidate 时，add 的 `input_invalid.field` 顺序固定为 `pdf_path`、`work_id`、`doi`、`arxiv_id`、`citation`、`pdf_content`；这些 raw fields 全部通过后才允许稳定读取选择较晚的 `pdf_content`。Resume 与 review 的 Data Root context 都使用 `literature`、`knowledge` 顺序；Resume 的 stage context 先按第 3 节七阶段顺序，再按第 7.2 节对应 stage 行内 reason 顺序。受 ADR 0121 约束的三行必须保持 specific-before-generic：`knowledge_import` blocked 为 `registry_unavailable`、`registry_busy`、`import_blocked`，`handoff` failed 为 `revision_conflict`、`asset_integrity_lost`、`commit_failed`、`handoff_failed`，`knowledge_import` failed 为 `revision_conflict`、`registry_conflict`、`commit_failed`、`import_failed`；generic reason 固定在行末，不得按字母或实现枚举重排。Add 的 unresolved root scope 与 resolved Work scope 互斥，因此 `identity_intake_busy` 与 `work_busy` 不得作为同一 ownership snapshot 的两个候选。Resume 只有一个 `work_id`；review 先结束 raw Candidate selector gate，解析到现存 Candidate 后才进入完整性 gate，且只有一个 `candidate_id`；action 冲突已在 grammar gate 结束。单一 field 内的多个缺陷映射到同一 code/context，不产生第二 primary。

仲裁后恰好发出胜出 code 的一个 primary item及其唯一 closed context；T04 没有 supplemental，其他 candidate 不输出、不聚合也不改 result。Uncertain commit、外部 termination、未批准 cancellation 与 presentation failure继续位于该仲裁和正常 envelope之外。

### 7.5 Normal exit

完整 Human或JSON presentation后的 normal exit：succeeded→`0`、blocked→`2`、failed→`1`。这些数字只属于完整 handled receipt；raw argv/bootstrap/grammar/unexpected exception/external termination/uncertain commit/presentation failure不能因数字相同被重分类。

T04 不为三个 Literature 命令冻结用户取消 source、latch、checkpoint、child stop/drain 或 release profile，因此不允许 `user_interrupted` primary、outer `interrupted` 或 normal exit `130`。Console control、external termination、`KeyboardInterrupt` 或取消期间无法安全形成完整 envelope 都保持在本合同正常矩阵外；实现不得捕获 `KeyboardInterrupt` 临时合成 handled outcome。未来只有在完整采用或取代既有 Windows cancellation bridge 合同并冻结全部 ownership/teardown 边界后，才能版本化增加该分支。

## 8. JSON 与 Human presentation

JSON outer command分别为 `literature.add|literature.resume|literature.review`。Envelope先通过本合同全部规则，再按 CLI JSON v1恰好整体序列化一次；唯一末尾 LF在内的完整 buffer上限为 `32,768` raw UTF-8 bytes inclusive。32,769或无法形成唯一 buffer时不输出 fallback、不改领域事实、不换 Human；该 presentation failure不属于 normal exit。完整成功 stdout只有 buffer、stderr空，不混入 Rich/progress/prompt/log/child/path。空/partial stdout不是 receipt。该 32 KiB profile独立冻结，不默默继承 knowledge.ask 的 cap或 cancellation bridge。Presentation开始前必须 seal immutable outcome/buffer，停止并释放 command-owned child、write、handle与 writer ownership；随后共享 CLI writer对 fd1恰好一次切换 Windows binary mode，并用 blocking write loop从 offset 0写同一 buffer直到完整 completion。Short write只推进实际正整数 count；zero/negative/bool/超请求 count、setup/write exception或无法证明 completion都停止输出、禁止 fallback，并且不使用第7.5节 normal outcome exit。

Human renderer消费同一 sealed outcome/result/diagnostic，不重读资产。完整 presentation使用 UTF-8 stdout、stderr空，首行固定：

| command/outcome | first line |
|---|---|
| add succeeded / blocked / failed | `Literature add：完成` / `Literature add：已阻塞` / `Literature add：失败` |
| resume succeeded / blocked / failed | `Literature resume：完成` / `Literature resume：已阻塞` / `Literature resume：失败` |
| review succeeded / blocked / failed | `Literature review：完成` / `Literature review：已阻塞` / `Literature review：失败` |

存在 result时显示稳定 ID、disposition/阶段或 Review→Handoff→Import状态；不得显示 PDF path、citation、文档内容、异常/provider文本。Resume pending Candidate先在 result array逐个显示完整 ID；仅 awaiting-review blocked分支再按每个 Candidate 分别给出 `--accept`、`--reject`、`--defer` 三条完整可复制命令，action 顺序固定后才进入下一个 Candidate，不能输出带 raw `|` 的缩写命令。这些行不使用 `下一步` 标签。Renderer不能 prompt、默认、倒计时接受或把回车当批准。Primary code/context映射为固定中文原因/下一步。颜色/box drawing/terminal width不冻结；redirected non-color subprocess必须保留首行、稳定字段顺序、单末尾 LF、同 exit且无 ANSI。


完整 Human body 的语义行顺序固定为：首行；若 `result` 非 `null`，按下列映射表自上而下输出全部字段；仅对第 8 节随后冻结的 resume `stage=review/reason=awaiting_review` pair 输出逐 Candidate 审核命令行；若有 primary，输出 `原因：<catalog 原因正文>`；最后输出恰好一行 `下一步：<正文>`。成功没有 `原因` 行；blocked/failed 的原因与下一步必须逐字来自第 8.1–8.3 节，并只按各 catalog 明确批准的 placeholder 来源替换字面 `<...>`。Renderer 不得改写、拼异常或回显输入。

| command | result key | exact Human label |
|---|---|---|
| add | `active_source_changed` | `Active Source 已切换` |
| add | `disposition` | `处理结果` |
| add | `schema_version` | `Schema` |
| add | `source_id` | `Source ID` |
| add | `source_sha256` | `Source SHA-256` |
| add | `work_id` | `Work ID` |
| resume | `active_source_id` | `Active Source ID` |
| resume | `advanced_stages` | `本次推进阶段` |
| resume | `pending_candidate_ids` | `待审核 Candidate` |
| resume | `pipeline_complete` | `管线已完成` |
| resume | `schema_version` | `Schema` |
| resume | `start_stage` | `开始阶段` |
| resume | `stop_stage` | `停止阶段` |
| resume | `work_id` | `Work ID` |
| review | `candidate_id` | `Candidate ID` |
| review | `decision_disposition` | `Decision 处理结果` |
| review | `handoff_action` | `Handoff 动作` |
| review | `handoff_id` | `Handoff ID` |
| review | `handoff_status` | `Handoff 状态` |
| review | `import_status` | `Import 状态` |
| review | `intake_status` | `Intake 状态` |
| review | `payload_sha256` | `Payload SHA-256` |
| review | `review_revision` | `Review revision` |
| review | `review_status` | `Review 状态` |
| review | `schema_version` | `Schema` |
| review | `work_id` | `Work ID` |

String/enum/ID/hash/schema value 逐字输出且不加引号；boolean 只输出 `是` / `否`；`null` 只输出 `无`；integer 使用无正号、无前导零的 ASCII 十进制。空 array 恰好一行 `标签：[]`。非空 array 先输出 `标签：`，随后每项一行、恰好两个 ASCII space 加 `- ` 再加逐字 item；不得逗号连接、编号、截断或省略。所有语义行使用上述全角 `：`，无行尾空白，以单个 LF 分隔并恰好一个末尾 LF。Interactive Rich 最多增加 ANSI/box decoration，不得改变语义行文本或顺序；redirected subprocess 必须输出下列无 ANSI UTF-8 bytes。

当且仅当 primary 为 `literature.resume.stage_blocked.v1`、context 恰好 `{"reason":"awaiting_review","stage":"review"}` 且 sealed result 非 null 时，`pending_candidate_ids` 必须有 1–12 项。Renderer 仍先按上面的非空 array 规则完整输出 `待审核 Candidate`；在最后一个 mapped result 字段 `Work ID` 之后、`原因` 之前，对数组中的每个 Candidate 相邻输出以下三行，先按 `accept`、`reject`、`defer` action 顺序，再进入下一个 Candidate：

```text
审核命令：gezhi literature review <candidate_id> --accept
审核命令：gezhi literature review <candidate_id> --reject
审核命令：gezhi literature review <candidate_id> --defer
```

`<candidate_id>` 逐字取 sealed array 当前项，不加引号或 shell escape。每项恰好三条审核命令，因此 N 个 Candidate 恰好输出 `3N` 条，最大 12 项时为 36 条；命令中不得出现 raw `|`。这些 action hint 不替代、不截断数组，也不使用 `下一步` 标签；整个 receipt 仍只有最后那一行 `下一步`。其他 primary、成功 resume 与空 pending array 都不得输出审核命令行。

Awaiting-review Human 的 32 KiB 证明冻结如下：规范 Candidate ID 为 29 raw UTF-8 bytes，其 array item 连 LF 为 34 bytes；三条命令连 LF 分别为 78、78、77 bytes，所以每项 Candidate 总增量恰好 267 bytes。实现测试必须枚举所有冻结的非 Candidate 字段、catalog 替换与边界值，并证明其最长固定部分不超过 2,048 bytes；于是 12 项上界为 `2,048 + 12 × 267 = 5,252` bytes，严格小于 32,768。JSON 不包含 Human action hint，pending ID 增量更小，仍单独服从同一全 buffer cap。V1 的 Candidate 上限因此保持 12；提高上限必须同时修订本证明与验收。

成功的 `下一步` 唯一为：add 与 review 使用 `运行 gezhi literature resume <work_id>`，其中 ID 取 sealed result；resume succeeded 必须 `pipeline_complete=true`，并使用 `无需操作`。若 resume 尚未 complete，则必须由 closed blocked/failed primary 呈现，不能用 succeeded 配其他下一步。

Add succeeded 完整 stdout witness（stderr empty，最后一行后还有一个 LF）：

```text
Literature add：完成
Active Source 已切换：是
处理结果：created_work
Schema：gezhi.literature_add_result.v1
Source ID：src_0123456789abcdef01234567
Source SHA-256：0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
Work ID：wrk_123e4567-e89b-42d3-a456-426614174000
下一步：运行 gezhi literature resume wrk_123e4567-e89b-42d3-a456-426614174000
```

Resume succeeded 完整 stdout witness：

```text
Literature resume：完成
Active Source ID：src_0123456789abcdef01234567
本次推进阶段：
  - ocr
  - canonicalize
  - read
  - review
  - handoff
  - knowledge_import
待审核 Candidate：[]
管线已完成：是
Schema：gezhi.literature_resume_result.v1
开始阶段：ocr
停止阶段：complete
Work ID：wrk_123e4567-e89b-42d3-a456-426614174000
下一步：无需操作
```

Resume awaiting-review blocked 完整 stdout witness：

```text
Literature resume：已阻塞
Active Source ID：src_0123456789abcdef01234567
本次推进阶段：
  - ocr
  - canonicalize
  - read
待审核 Candidate：
  - cand_aaaaaaaaaaaaaaaaaaaaaaaa
  - cand_cccccccccccccccccccccccc
管线已完成：否
Schema：gezhi.literature_resume_result.v1
开始阶段：ocr
停止阶段：review
Work ID：wrk_123e4567-e89b-42d3-a456-426614174000
审核命令：gezhi literature review cand_aaaaaaaaaaaaaaaaaaaaaaaa --accept
审核命令：gezhi literature review cand_aaaaaaaaaaaaaaaaaaaaaaaa --reject
审核命令：gezhi literature review cand_aaaaaaaaaaaaaaaaaaaaaaaa --defer
审核命令：gezhi literature review cand_cccccccccccccccccccccccc --accept
审核命令：gezhi literature review cand_cccccccccccccccccccccccc --reject
审核命令：gezhi literature review cand_cccccccccccccccccccccccc --defer
原因：review 阶段已阻塞（awaiting_review）
下一步：修复该前置条件后重新运行 resume；awaiting_review 时对列出的 Candidate 显式 review
```

Review succeeded 完整 stdout witness：

```text
Literature review：完成
Candidate ID：cand_aaaaaaaaaaaaaaaaaaaaaaaa
Decision 处理结果：created
Handoff 动作：accept
Handoff ID：hnd_6516df7f17eab620795d28ee
Handoff 状态：committed
Import 状态：applied
Intake 状态：active
Payload SHA-256：aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Review revision：1
Review 状态：accepted
Schema：gezhi.literature_review_result.v1
Work ID：wrk_123e4567-e89b-42d3-a456-426614174000
下一步：运行 gezhi literature resume wrk_123e4567-e89b-42d3-a456-426614174000
```

### 8.1 Add Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.add.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 add |
| `literature.add.data_root_unsafe.v1` | Literature 数据目录不安全 | 运行 gezhi doctor 并移除不受支持的 namespace 或路径别名 |
| `literature.add.data_root_unavailable.v1` | Literature 数据目录不可用 | 运行 gezhi doctor 并修复 Literature 数据目录 |
| `literature.add.input_invalid.v1` | 输入字段无效（`<field>`） | 修正该输入字段后重新运行 add |
| `literature.add.identity_intake_busy.v1` | Literature 身份接收正由另一个写流程处理 | 等待该 root-level 身份接收流程结束后重试 |
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


### 8.2 Resume Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.resume.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 resume |
| `literature.resume.data_root_unsafe.v1` | `<data_root>` 数据目录不安全 | 运行 gezhi doctor 并移除 `<data_root>` 数据目录不受支持的 namespace 或路径别名 |
| `literature.resume.data_root_unavailable.v1` | `<data_root>` 数据目录不可用 | 运行 gezhi doctor 并修复 `<data_root>` 数据目录 |
| `literature.resume.work_invalid.v1` | Work ID 格式无效 | 使用完整规范 Work ID 重试 |
| `literature.resume.work_not_found.v1` | 指定 Work 不存在 | 核对 Work ID 后重试 |
| `literature.resume.work_busy.v1` | 该 Work 正由另一个写流程处理 | 等待该流程结束后重试 |
| `literature.resume.active_source_unavailable.v1` | Active Source 不可用 | 先用 literature add 明确选择可用 Source |
| `literature.resume.stage_blocked.v1` | `<stage>` 阶段已阻塞（`<reason>`） | 修复该前置条件后重新运行 resume；awaiting_review 时对列出的 Candidate 显式 review |
| `literature.resume.data_root_integrity_lost.v1` | `<data_root>` 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi doctor 检查 `<data_root>` 数据目录身份 |
| `literature.resume.active_source_invalid.v1` | Active Source 资产无效 | 保留现有资产并检查 Source manifest、ID、hash 与 bytes |
| `literature.resume.stage_failed.v1` | `<stage>` 阶段失败（`<reason>`） | 保留现有资产，修复该阶段后重新运行 resume |
| `literature.resume.recovery_failed.v1` | Literature 恢复检查失败 | 停止相关写入并保留 staging 与恢复证据；运行 gezhi status，按 Operations 的 inspect_recovery 指引进行维护检查；不要手工删除或改名 |

Resume catalog 的 `<data_root>` 逐字取胜出 root primary context 中的 `data_root`，只能是 `literature` 或 `knowledge`；`<stage>` 与 `<reason>` 逐字取胜出 stage context。不得从异常、路径或其他资产补值。


### 8.3 Review Human primary catalog

| code | 原因正文 | 下一步正文 |
|---|---|---|
| `literature.review.configuration_invalid.v1` | 配置无效 | 修正格致配置后重新运行 review |
| `literature.review.data_root_unsafe.v1` | `<data_root>` 数据目录不安全 | 移除不受支持的 namespace 或路径别名后用相同 action 重试 |
| `literature.review.data_root_unavailable.v1` | `<data_root>` 数据目录不可用 | 修复该 Context 数据目录后用相同 action 重试 |
| `literature.review.candidate_invalid.v1` | Candidate ID 格式无效 | 使用完整规范 Candidate ID 重试 |
| `literature.review.candidate_not_found.v1` | 指定 Candidate 不存在 | 核对 Candidate ID 后重试 |
| `literature.review.work_busy.v1` | Candidate 所属 Work 正由另一个写流程处理 | 等待该流程结束后重试 |
| `literature.review.handoff_blocked.v1` | Review Decision 已保存，但 Handoff 尚未完成 | 用相同 action 重试或运行 literature resume |
| `literature.review.import_blocked.v1` | Review Decision 与 Handoff 已保存，但 Knowledge import 尚未完成 | 修复 Knowledge 前置条件后用相同 action 重试或运行 literature resume |
| `literature.review.data_root_integrity_lost.v1` | `<data_root>` 数据目录身份在执行中失去可信性 | 停止写入并运行 gezhi doctor |
| `literature.review.candidate_integrity_lost.v1` | Candidate 资产完整性失效 | 保留 Candidate 与 Evidence 资产，运行 gezhi status 并检查 ID、hash、canonical bytes、provenance、Evidence、payload、collision 与 asset 完整性 |
| `literature.review.review_state_invalid.v1` | Candidate Review 历史无效 | 保留审核资产并检查 revision 与 payload identity |
| `literature.review.review_commit_failed.v1` | Review Decision 提交失败 | 保持相同 Candidate 与 action 重试 |
| `literature.review.handoff_failed.v1` | Review Decision 已保存，但 Handoff 失败 | 保留 Decision 与 Handoff 资产，运行 gezhi status 检查 Handoff 完整性、协议、revision 与提交状态；修复确定原因后以同一 identity 续行 |
| `literature.review.import_failed.v1` | Review Decision 与 Handoff 已保存，但 Knowledge import 失败 | 保留 Decision、Handoff 与 Registry 前置事实，运行 gezhi status 检查 KnowledgeIntake/Registry 完整性、协议、revision、commit 与 conflict；修复确定原因后以同一 identity 续行 |

Review catalog 的 `<data_root>` 逐字取胜出 root primary context 中的 `data_root`，只能是 `literature` 或 `knowledge`；不得从路径或异常补值。



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
- Source/alias跨 Work冲突、identity ambiguity、hash collision、invalid IDs/aliases与 PDF path/content 缺陷均按表拒绝且无 success pointer。
- 初始 Literature root 的 relative/UNC/WSL/device/ADS/reparse/8.3/SUBST/hidden alias 等正面不安全证据选择 `data_root_unsafe`；missing/inaccessible/non-directory/identity-unprovable 选择 `data_root_unavailable`；gate 通过后的 physical identity drift 选择 `data_root_integrity_lost`。
- Unresolved Work 的 root-level ownership contention 只选择 `identity_intake_busy`；Work 唯一解析后的 contention 只选择 `work_busy`，两者不得跨 scope。
- 在 Source commit、Active pointer、catalog transaction、presentation之间注入失败，重试只补未完成提交。
- Add不探测 OCR/Codex/Knowledge、不调用 WSL、不安装依赖。

### Resume

- 七阶段每个 valid success跳过；directory committed/pointer missing只补 pointer；从 ingest自动推进到 pending review并返回 IDs，不写 Decision。
- Zero Candidate完成 no-op；全部有 decision时补 Handoff/Import；有已授权 backlog和其他 pending时先补 backlog再 awaiting_review。对 `handoff` 与 `knowledge_import` 的每个 retained blocked/failed reason 都必须有 backlog+pending 见证：`start_stage=review`，`pending_candidate_ids` 非空且 Work 全局 Continuation Point 仍为 `review`，但 `stop_stage` 精确等于该 blocked/failed primary context 的 stage；backlog 全部成功后才允许以 `stop_stage=review`、`awaiting_review` 呈现。
- Resume result seal逐 variant覆盖：17 个 `stage_blocked` pair 与 25 个 `stage_failed` pair 逐项具有可达见证并返回 non-null，42 个 stage pair 的可达性与计数不变；三条 ADR 0121 相关 reason 列表逐字验证 specific 在前、generic 在末，并证明第 7.4 节同 stage 仲裁优先选择 specific。七个固定 null code 加三个 Literature root variant 恰好形成十个 null variants，三个 Knowledge root variant 均形成 non-null sealed result、`stop_stage=knowledge_import` 并保留已明确提交的进度。Active Source 的缺失/identity-unprovable 与确定 invalidity 分别由 seal 前的 `active_source_unavailable` 与 `active_source_invalid` 闭合，不进入 ingest matrix；`commit_failed` 不把当前 stage列入 `advanced_stages`，uncertain commit不形成 handled receipt。
- Awaiting-review redirected Human完整匹配 witness：N 项 Candidate array 按外层 Candidate 顺序、内层 accept/reject/defer 顺序输出恰好 `3N` 条完整命令，最多 36 条且命令不含 raw `|`；命令位于 `Work ID` 后、`原因` 前，全 receipt 恰好一个最终 `下一步` 行。
- 每阶段 blocked/failed、历史 interrupted、遗留 running、partial/invalid orphan、target conflict、uncertain均无 partial success/overwrite。
- OCR缺失只在 ocr阻塞；Codex缺失只在 read；Knowledge root只在 import；已完成阶段仍可读。
- Resume 三个 root code 各覆盖 `literature`、`knowledge` 两个 exact context，合计六个 context variants：Literature variant 为 null，Knowledge variant 为 non-null 且不属于 42 个 stage pair；Knowledge root fault 不要求 Literature root 同时失信。Active Source unavailable/invalid 分别覆盖 blocked/failed 且都在 seal 前返回 null。

### Review

- 三 action、首 revision、同 action幂等、不同 action追加；accepted→active；never-accepted nonaccepted→no action；accepted后 nonaccepted→withdrawn；之后 accepted→active。
- Raw Candidate selector 的格式、大小写或规范性无效只选择 blocked `candidate_invalid`；一旦规范 ID 解析到现存 Candidate，ID/hash/canonical bytes/provenance/Evidence/payload/collision/asset 任一确定失败只选择 failed `candidate_integrity_lost`，两者都为 null。
- Decision/Handoff/Registry/presentation逐点失败保留前置事实，retry 同 identity 续行；`handoff_failed`/`import_failed` 的 Human 指引覆盖完整性、协议、revision、commit 与 Registry consistency 检查，不把 deterministic failure 简化为自动原样重试。
- Review 对 Literature/Knowledge root 的 unsafe/unavailable 使用两个 exact context object；Literature 初始 gate 位于 Decision 前且 result 为 null，Knowledge import gate 位于 Decision 后且 result 为 non-null，通过 gate 后 drift 使用 context-matched `data_root_integrity_lost`。
- ADR 0121 分类逐项覆盖：root physical gate 先选择 root primary；Resume 的 Registry unavailable/busy、revision conflict、Registry conflict、asset integrity 与 commit failure 优先选择 mutually exclusive specific stage reason；只有其余已批准 typed interface verdict 使用 generic blocked/failed，unknown、untyped 与 uncertain commit 位于 handled matrix 外；先前提交事实不回滚且续行 identity 不变。
- Codex/resume/status/reader不能写 Decision；无 default accept、batch、note、Promotion或Research Interest。

### Presentation

- 每 command 的 succeeded/blocked/failed覆盖 Human/JSON；完整 canonical bytes、32 KiB inclusive cap、单 LF、channel/exit匹配。
- Awaiting-review 最大 witness 使用 12 个 Candidate、36 条审核命令，并验证固定部分不超过 2,048 bytes、总上界为 5,252 bytes；Candidate 上限变化必须同步修订证明。
- Result presence符合第4.4、5.3、6.3、7.2–7.3节；earlier commit不自动使 outer succeeded。
- 每个 command注入同 gate多字段/多 code故障和已启动 operation的并发故障，以固定 field/context顺序与静态 priority恰好选择一个 primary；losing candidate不输出。
- Redirected Human无 ANSI，首行/稳定字段/next action可断言；Human/JSON来自同一 outcome。

## 11. 非目标与演进

本合同不增加 command/option、batch/interactive review、Identity Review专用命令、自动搜索/下载、网络 acquisition、多 Source评分、force rerun、维护命令、GUI/daemon、动态插件、Promotion Gate、Promoted Knowledge、Research Interest或 Relevance Candidate。它不冻结 OCR/Canonical/Reader内部 schema、Registry表、可选 interactive Rich decoration或 child transport实现；第 8 节的 Human 语义行与 redirected bytes 已冻结。

未来 Context先定义业务语言、状态所有权与 versioned handoff，再由 static composition加入；不得复用 human-review capability、直接写 Literature assets或把七阶段扩成通用 DAG。

修改 result字段/值域、primary code/context、阶段推进权限、Review→Handoff→Intake矩阵、Active Source语义或 normal exit，必须升级 nested schema/code或使用 replacing decision。只改未冻结 Rich样式或内部 module拆分不改变本合同。
