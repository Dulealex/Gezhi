# Gezhi Operations Contract v1

## 1. Status and authority

This document freezes the public observable contract for `gezhi doctor` and `gezhi status [WORK_ID]` under [Parent Spec #1](https://github.com/Dulealex/Gezhi/issues/1) and [T03 / Issue #4](https://github.com/Dulealex/Gezhi/issues/4). It refines, without replacing, [CLI Command v1](./cli-command-v1.md), [CLI JSON v1](./cli-json-v1.md), [CLI Diagnostics v1](./cli-diagnostics-v1.md), [Configuration v1](./configuration-v1.md), and [ADR 0120](../adr/0120-keep-operations-read-only-and-report-partial-state-conservatively.md).

The two commands are owned by one deep `OperationsV1` module. Its external interface contains only the conceptual behaviours `doctor()` and `status(work_id?)`; these names do not freeze a Python module, class, function signature, exception type, or return type. The module hides check ordering, Context projection adapters, conservative aggregation, diagnostic arbitration, remediation selection, bounded serialization, and Human rendering behind that interface. CLI code only supplies the already parsed raw optional `WORK_ID`, selected mode, and immutable configuration-source snapshot, then presents the validated report.

Operations is product infrastructure, not a third domain Context. It reads Literature and Knowledge through repository-owned, read-only projection seams. Those seams are internal to the implementation and are not a public plugin, Command Bus, dynamic registry, generic repository, or permission for Operations to interpret private domain assets independently. A future Context must first define its language and state ownership, then explicitly extend the static projection and this versioned contract; V1 does not reserve arbitrary result keys or invent future business metrics.

## 2. Shared invariants

Both commands are strictly observational:

- they never create, rewrite, migrate, normalize, install, upgrade, authenticate, download, repair, resume, retry, quarantine, restore, delete, rename, lock for writing, or publish anything;
- they never run `uv`, `pip`, `npm`, `npm ci`, a package manager, an installer, an updater, a model download, OCR inference, or a Codex semantic request;
- they do not change configuration, environment variables, Data Root contents, SQLite, manifests, current pointers, staging entries, orphan entries, quarantined entries, caches, credentials, logs, telemetry, or persistent diagnostics;
- they may safe-open handles, read metadata/files/databases, run a no-bytecode isolated importability probe, and run only the approved read-only Codex identity/login probes described in Section 3; every opened handle and child is settled before presentation, and any probe that would require a project, Data Root, credential, cache, or package-state write is reported unavailable instead of being run;
- a missing or invalid capability is reported. It is never substituted with Conda, WSL, Docker, Ollama, a global or desktop Codex, another OCR path, another model, another Data Root, or stale cached success;
- `status` never advances a stage, completes an orphan, rewrites a projection, repairs a pointer, or changes a legacy `running` state. It reports the evidence exactly and proposes an external next action;
- a valid terminal manifest and its required hashes are the only authority for `succeeded`. File or directory existence, a SQLite projection, a current pointer, staging content, a partial file set, or quarantined content cannot independently prove success.

Configuration discovery starts only after the valid leaf and mode are selected. `doctor` is the one explicit command allowed to inspect both configured Context roots. `status` consumes both roots because its approved purpose is a cross-Context projection, but Section 6 permits a partial report when one Context remains independently readable. Other commands do not inherit either exception.

Neither command has a handled `interrupted` result in V1. Before the final report is sealed, external termination and Ctrl+C retain their actual OS/runtime semantics and do not generate a fallback envelope or Human receipt. After the report is sealed, presentation follows Section 9.

## 3. `doctor` check set

### 3.1 Fixed checks and order

`DoctorReportV1.checks` contains exactly seven items in this order:

| `id` | Ready proof | Blocked/not-checked boundary |
|---|---|---|
| `configuration` | every active Configuration v1 source validates and the final two-root lexical/cross-field snapshot is valid | invalid, unreadable, missing required default, incompatible, unknown, or final-invalid configuration is `blocked` |
| `core_python` | running interpreter is CPython `3.11.15` | a mismatch is normally rejected by the earlier typed bootstrap probe; if the handled check observes a coherent mismatch, it is `blocked` |
| `core_dependencies` | the nine direct runtime distributions in the Environment Contract have the exact frozen versions and their canonical top-level imports complete | any missing, mismatched, broken, or incompatible direct runtime distribution is `blocked` |
| `literature_data_root` | resolved Literature root passes the full local Windows namespace, existence, directory, access, no-hidden-alias, final-path, parent-chain, File ID, project-boundary, and physical-isolation proof | unsafe facts are `blocked`; unavailable/identity-unprovable facts are `blocked`; configuration failure makes this `not_checked` |
| `knowledge_data_root` | same proof for the Knowledge root | same rules; configuration failure makes this `not_checked` |
| `ocr_runtime` | OCR CPython, frozen direct package identities, MinerU configuration/model files, offline policy, CUDA PyTorch build, CUDA availability, and approved GPU identity all match the Environment Contract | any absent, drifted, unreadable, non-offline, non-CUDA, or wrong-device fact is `blocked`; doctor does not load a PDF or run inference |
| `codex_runtime` | project npm lock/package/native identity resolves uniquely to the pinned Windows x64 CLI, its read-only version probe reports the frozen version, and its read-only login-status probe reports usable ChatGPT authentication | absent, ambiguous, drifted, unsupported, not logged in, or probe-completed-unavailable is `blocked`; doctor does not run `codex exec` or a semantic request |

The `core_dependencies` direct set is exactly Feedparser `6.0.14`, HTTPX `0.28.1`, Pydantic `2.13.4`, Pydantic Settings `2.14.2`, PyPDF `6.14.2`, RapidFuzz `3.14.5`, Rich `15.0.0`, Tenacity `9.1.4`, and Typer `0.27.0`. Root-project `gezhi` installation metadata and transitive lock consistency are implementation invariants, not additional public check IDs. OCR and Codex facts are grouped deliberately: callers learn whether the capability can be consumed, while package-by-package and file-by-file detail stays behind the module.

The native Ctrl+C build toolchain is build/test-only, not a daily runtime capability, and is not an eighth doctor check. A project-owned bridge artifact is checked by the consuming Knowledge lifecycle contract when that artifact exists; its absence may select the already approved no-source cancellation profile and therefore is not reported as a false global environment failure here.

### 3.2 Independence and ordering

Configuration is checked first. Core Python/dependencies, OCR, and Codex checks remain independent and still run after configuration is blocked. The two Data Root checks run only after configuration is ready; neither root check is allowed to borrow proof from the other. Within the two root checks, Literature is observed before Knowledge only to make tests deterministic; both results are reported.

An expected absence, mismatch, unsafe fact, login-unavailable result, or read-only probe's approved unavailable verdict is `blocked`, not an implementation failure. An unexpected exception, malformed internal descriptor, impossible result, or inability to complete the inspection algorithm itself makes the affected check `failed`. A failed check does not authorize a fallback check or repair.

### 3.3 Doctor result schema

`DoctorReportV1` is governed by the repository JSON Schema [doctor-result-v1.schema.json](./schemas/doctor-result-v1.schema.json) plus the cross-field rules in this section. It is a closed object:

~~~json
{
  "schema_version": "gezhi.doctor_result.v1",
  "overall_status": "ready",
  "checks": [
    {"id": "configuration", "status": "ready"},
    {"id": "core_python", "status": "ready"},
    {"id": "core_dependencies", "status": "ready"},
    {"id": "literature_data_root", "status": "ready"},
    {"id": "knowledge_data_root", "status": "ready"},
    {"id": "ocr_runtime", "status": "ready"},
    {"id": "codex_runtime", "status": "ready"}
  ]
}
~~~

The root has exactly `schema_version`, `overall_status`, and `checks`; every check item has exactly `id` and `status`; all objects use `additionalProperties=false`.

- `schema_version` is exactly `gezhi.doctor_result.v1`.
- `id` is the seven-value enum and fixed order above; every value appears exactly once.
- check `status` is `ready`, `blocked`, `failed`, or `not_checked`.
- `not_checked` is legal only for the two Data Root checks when `configuration` is not `ready`.
- `overall_status=failed` iff at least one check is `failed`; otherwise it is `blocked` iff at least one check is `blocked` or `not_checked`; otherwise it is `ready`.

## 4. Doctor diagnostics, outcome, and exit

### 4.1 Closed diagnostic union

All arrays below are nonempty, unique, and sorted in the listed enum order. They contain no raw path, package name supplied at runtime, version observed at runtime, credential fact, exception text, or command output.

| Code | Closed context | Allowed role |
|---|---|---|
| `operations.doctor.configuration_invalid.v1` | `{}` | `blocked` primary or `failed` supplemental |
| `operations.doctor.core_environment_unavailable.v1` | `{"checks":[...]}` where values are `core_python`, `core_dependencies` | `blocked` primary/supplemental or `failed` supplemental |
| `operations.doctor.data_root_unsafe.v1` | `{"contexts":[...]}` where values are `literature`, `knowledge` | `blocked` primary/supplemental or `failed` supplemental |
| `operations.doctor.data_root_unavailable.v1` | same context enum | `blocked` primary/supplemental or `failed` supplemental |
| `operations.doctor.ocr_environment_unavailable.v1` | `{}` | `blocked` primary/supplemental or `failed` supplemental |
| `operations.doctor.codex_environment_unavailable.v1` | `{}` | `blocked` primary/supplemental or `failed` supplemental |
| `operations.doctor.inspection_failed.v1` | `{"checks":[...]}` where values are any of the seven check IDs | `failed` primary only |

All legal items remain under the shared 1,024-byte cap. One code is emitted at most once; repeated facts aggregate into its array.

If any check failed, `inspection_failed` is primary. All independently proved blocked facts may follow as supplemental diagnostics. Otherwise a blocked primary is chosen by this static priority: configuration invalid, unsafe Data Root, unavailable Data Root, core environment, OCR environment, Codex environment. Other proved blocked facts are supplemental and shared `DiagnosticSetV1` sorts them by code. A ready report has `diagnostics=[]`.

### 4.2 Cross-field matrix

| `overall_status` | outer `command` | outer `outcome` | `result` | Normal exit |
|---|---|---|---|---:|
| `ready` | `doctor` | `succeeded` | full `DoctorReportV1` | `0` |
| `blocked` | `doctor` | `blocked` | full `DoctorReportV1` | `2` |
| `failed` | `doctor` | `failed` | full `DoctorReportV1` | `1` |

The public command identity is exactly `command="doctor"`. Doctor always returns its bounded report for a handled outcome, including partial check completion. `result=null` and `outcome=interrupted` are invalid doctor bindings.

## 5. `status` scope and vocabulary

### 5.1 Input

Absent `WORK_ID` selects `scope="overall"`. One present raw value is validated without normalization only after Configuration v1 succeeds. A valid Work ID is exactly `wrk_` followed by a lowercase canonical hyphenated UUIDv4 (`8-4-4-4-12` hexadecimal digits, version nibble `4`, RFC variant nibble `8`, `9`, `a`, or `b`). Whitespace, uppercase, braces, compact UUIDs, other versions, aliases, paths, and values that would require normalization are rejected; the raw value is never echoed.

An invalid validly-parsed operand is a handled `operations.status.invalid_work_id.v1` result, not a CLI grammar failure. A syntactically valid but absent Work is `operations.status.work_not_found.v1`.

### 5.2 Operational status vocabulary

`OperationalStatusV1` is distinct from Literature `Review Status`, Knowledge `Intake Status`, Knowledge `Answer Status`, ADR 0027 stage status, and CLI outer `outcome`:

| Value | Meaning |
|---|---|
| `empty` | the requested overall projection has no Work and no attributable governed/Answer/recovery fact |
| `pending` | a known workflow has not begun its next required stage or waits for a normal user governance action |
| `running` | an authoritative current invocation owns a live stage; existence of an old `running` value alone is not enough |
| `succeeded` | every required fact for the requested scope is backed by valid committed authority and no recovery/integrity fact is present |
| `blocked` | the authoritative workflow state is blocked on a recoverable prerequisite |
| `failed` | the authoritative workflow state reached a deterministic operational failure |
| `interrupted` | the authoritative workflow state records interruption and is not currently live |
| `partial` | a coherent report exists, but at least one requested Context projection is locally unavailable or only a strict validated subset can be attributed |
| `staging` | at least one uncommitted staging entry is in scope; it is never success authority |
| `orphaned` | at least one fully committed but unattached/recovery-pending object is in scope; it is never current success authority |
| `quarantined` | at least one isolated invalid or unsafe recovery object is in scope; it is never success authority |
| `inconsistent` | validated authorities contradict, required authority is corrupt, or identity/integrity cannot be reconciled conservatively |

When one summary value is required, integrity/recovery observations win in this order: `inconsistent > quarantined > orphaned > staging`. Next comes `partial`, then authoritative workflow urgency `failed > blocked > interrupted > running > pending > succeeded > empty`. This is a presentation aggregation rule only; it never changes the underlying Context state.

ADR 0027 stage items retain exactly `pending`, `running`, `succeeded`, `blocked`, `failed`, or `interrupted`. The four recovery/integrity words and `partial` may not be written back as stage state.

## 6. Status observation and local blocking

`status` first resolves Configuration v1. Configuration invalidity produces no report. With valid configuration, each required root is independently safe-opened and passed to its owning read-only projection.

- Overall scope may return a `partial` report when exactly one Context projection is coherent and the other root/projection is unavailable or unsafe. If neither Context can produce a coherent projection, the command is `blocked` with `result=null`.
- Work scope requires a coherent Literature projection to prove Work identity. If Literature cannot be read safely, the command is `blocked` with `result=null`. Knowledge may be unavailable; the result then remains a coherent Literature-backed `partial` report.
- A corrupt local item that can be isolated without guessing produces an `inconsistent` status, recovery count, and supplemental diagnostic while preserving the rest of the report. If corruption prevents the requested scope from being identified or bounded, no report is emitted and the command is `failed`.
- SQLite is authoritative only where the Context ADR says it is. A Literature SQLite projection cannot override immutable assets, and a file-system copy cannot override the Knowledge Candidate Registry. Current pointers and indexes are observations, not independent success authority.
- Overall and Work scope use the same Context projection and aggregation rules. Work scope is a filter over stable Work/source/Candidate attribution, not a second implementation.

An Answer is related to a Work only when a valid committed Answer's Retrieval View contains at least one Candidate whose validated source snapshot names that exact `work_id`. Any safely observed and attributable direct entry at literal `answers/.staging/<answer_id>/` contributes only to `RecoverySummaryV1.staging_count`: because this read-only command does not hold writer ownership, it leaves the entry unclassified and must not use a manifest, timestamp or age, PID or mutex observation, apparent file stability, target presence/conflict, or content validity to increment `orphaned_count` or `quarantined_count`. An invalid or unattributable formal target may contribute only to the recovery/integrity fact that the owning Knowledge projection can prove under Answer Terminal v1; it is never a related Answer.

## 7. Status result schema

The structural wire schema is [status-result-v1.schema.json](./schemas/status-result-v1.schema.json). JSON Schema validation is necessary but not sufficient: this section additionally freezes ordering, zero omission, aggregation, availability, authority, and next-action cross-field rules that are not delegated to a generic schema validator.

### 7.1 Shared closed shapes

Every count is a JSON integer in `0..9223372036854775807` and not a boolean.

`RecoverySummaryV1` has exactly:

~~~json
{"staging_count":0,"orphaned_count":0,"quarantined_count":0,"inconsistent_count":0}
~~~

Counts include only entries within the requested scope and proven owned by that Context. An untrusted entry that cannot be attributed safely increments `inconsistent_count` only in overall scope.

`StageItemV1` has exactly `stage` and `status`. Work scope contains exactly seven items, in order: `ingest`, `ocr`, `canonicalize`, `read`, `review`, `handoff`, `knowledge_import`. Status uses only the six ADR 0027 values.

`StatusCountV1` has exactly `status` and `count`. Lists omit zero-count values, contain unique statuses, and use the `OperationalStatusV1` order from Section 5.2. An empty list is `[]`. `empty` is legal only as the top-level status of an overall report; an existing Work and every `work_status_counts` item must use one of the other eleven values.

An availability-only Context summary is exactly `{"availability":"unavailable"}` or `{"availability":"unsafe"}`. A populated summary uses `availability="ready"` or `availability="partial"` and the fields below. No summary may combine unavailable/unsafe with counts.

### 7.2 Overall report

`OverallStatusReportV1` has exactly these keys:

~~~json
{
  "schema_version":"gezhi.status_result.v1",
  "scope":"overall",
  "status":"pending",
  "literature":{
    "availability":"ready",
    "work_count":1,
    "work_status_counts":[{"status":"pending","count":1}],
    "pending_review_count":0,
    "pending_handoff_count":0
  },
  "knowledge":{
    "availability":"ready",
    "active_candidate_count":0,
    "withdrawn_candidate_count":0,
    "answer_status_counts":[]
  },
  "recovery":{"staging_count":0,"orphaned_count":0,"quarantined_count":0,"inconsistent_count":0},
  "next_action":"inspect_work"
}
~~~

The populated Literature object has exactly `availability`, `work_count`, `work_status_counts`, `pending_review_count`, and `pending_handoff_count`. Starting from zero and following the listed order, checked addition of every `work_status_counts[*].count` must complete without exceeding `9223372036854775807` and must equal `work_count` exactly; therefore `work_count=0` iff `work_status_counts=[]`, and every counted Work contributes to exactly one status item. Overflow or any unequal sum makes the report invalid and selects `operations.status.observation_failed.v1` with outer `outcome=failed` and `result=null`; the implementation must not truncate, omit, saturate, or normalize counts to obtain equality. The populated Knowledge object has exactly `availability`, `active_candidate_count`, `withdrawn_candidate_count`, and `answer_status_counts`. Answer counts use only terminal operational values `succeeded`, `blocked`, `failed`, and `interrupted`, in that order when nonzero; Answer semantic `answered`/`insufficient_evidence` is deliberately absent.

### 7.3 Work report

`WorkStatusReportV1` has exactly these keys:

~~~json
{
  "schema_version":"gezhi.status_result.v1",
  "scope":"work",
  "work_id":"wrk_123e4567-e89b-42d3-a456-426614174000",
  "status":"pending",
  "literature":{
    "availability":"ready",
    "stages":[
      {"stage":"ingest","status":"succeeded"},
      {"stage":"ocr","status":"pending"},
      {"stage":"canonicalize","status":"pending"},
      {"stage":"read","status":"pending"},
      {"stage":"review","status":"pending"},
      {"stage":"handoff","status":"pending"},
      {"stage":"knowledge_import","status":"pending"}
    ],
    "review_counts":{"pending":0,"accepted":0,"rejected":0,"deferred":0},
    "handoff_status":"none"
  },
  "knowledge":{
    "availability":"ready",
    "candidate_counts":{"active":0,"withdrawn":0},
    "related_answer_status_counts":[]
  },
  "recovery":{"staging_count":0,"orphaned_count":0,"quarantined_count":0,"inconsistent_count":0},
  "next_action":"resume_work"
}
~~~

The populated Literature object has exactly `availability`, `stages`, `review_counts`, and `handoff_status`. `review_counts` always has exactly the four Review Status keys shown. It summarizes the latest valid Review Decision for each Candidate; history is not double-counted. `handoff_status` is `none`, `pending`, `available`, `blocked`, `failed`, or `inconsistent`; it is an Operations projection and does not replace a Handoff manifest status.

The populated Knowledge object has exactly `availability`, `candidate_counts`, and `related_answer_status_counts`. `candidate_counts` always has exactly `active` and `withdrawn`, derived from authoritative Intake Status. Related Answer counts follow the terminal operational order above and never use Answer Status.

### 7.4 Next action

`next_action` is exactly one of:

| Value | Stable Human recommendation |
|---|---|
| `none` | no action is currently required; a live `running` Work also uses this value to avoid unsafe duplicate resume |
| `add_work` | run `gezhi literature add <pdf_path>` |
| `inspect_work` | run `gezhi status <work_id>` for an affected Work |
| `resume_work` | run `gezhi literature resume <work_id>` after the reported prerequisite is ready |
| `review_candidate` | use a Candidate ID from the Review Queue with `gezhi literature review` |
| `repair_data_root` | restore or secure the named Context Data Root externally; do not ask Gezhi to create it |
| `inspect_recovery` | stop writes for the affected scope, preserve the evidence, and obtain maintenance review; do not delete or rename it manually |

Selection is deterministic: integrity/recovery selects `inspect_recovery`; a required unavailable/unsafe Context selects `repair_data_root`; a live `running` Work selects `none`; pending Candidate Review selects `review_candidate`; another resumable incomplete Work selects `resume_work`; empty overall selects `add_work`; an overall report needing a Work choice selects `inspect_work`; a clean terminal report selects `none`. Configuration/environment actions occur only on no-result diagnostic branches and therefore do not appear inside a status result.

## 8. Status diagnostics, outcome, and exit

### 8.1 Closed diagnostic union

| Code | Closed context | Allowed role |
|---|---|---|
| `operations.status.configuration_invalid.v1` | `{}` | `blocked` primary only |
| `operations.status.invalid_work_id.v1` | `{}` | `blocked` primary only |
| `operations.status.work_not_found.v1` | `{"work_id":"wrk_<lowercase UUIDv4>"}` | `blocked` primary only |
| `operations.status.data_root_unsafe.v1` | `{"contexts":[...]}` with nonempty unique `literature`, `knowledge` in that order | `blocked` primary or `succeeded`/`failed` supplemental |
| `operations.status.data_root_unavailable.v1` | same context shape | `blocked` primary or `succeeded`/`failed` supplemental |
| `operations.status.integrity_attention.v1` | `{"kinds":[...],"count":N}`; kinds are nonempty unique `staging`, `orphaned`, `quarantined`, `inconsistent` in that order; `N` is their checked sum in `1..9223372036854775807`; an unrepresentable sum makes the report invalid and selects observation failure | `succeeded` supplemental only |
| `operations.status.projection_incomplete.v1` | `{"contexts":[...]}` using the Context enum above | `succeeded` supplemental only |
| `operations.status.observation_failed.v1` | `{}` | `failed` primary only |

All legal items remain within 1,024 bytes. No path, raw invalid ID, title, Candidate text, Question, exception, SQLite detail, filename, manifest field, credential, or provider output appears in diagnostic context.

Configuration invalidity wins before Work ID validation because the handled Operations module consumes the immutable configuration snapshot before opening domain state. After valid configuration, invalid Work ID wins before Data Root access. In Work scope, a valid absent Work is selected only after the Literature root and minimum projection are safely readable.

When no coherent result can be produced, blocked primary priority is configuration invalid, invalid Work ID, unsafe required Data Root, unavailable required Data Root, then Work not found. `observation_failed` is the only failed primary. A coherent report always has outer `outcome=succeeded`; root/projection/integrity findings are supplemental and cannot change that invocation outcome.

### 8.2 Cross-field matrix

| Branch | outer `command` | outer `outcome` | `result` | Diagnostics | Normal exit |
|---|---|---|---|---|---:|
| coherent overall or Work report, including historical blocked/failed/interrupted state | `status` | `succeeded` | one report union | zero or supplemental only | `0` |
| invalid configuration/Work ID, Work absent, or minimum required projection unavailable/unsafe | `status` | `blocked` | `null` | one primary, optional supplemental | `2` |
| observation algorithm cannot form a bounded coherent report | `status` | `failed` | `null` | `observation_failed` primary, optional supplemental | `1` |

The public identity is exactly `command="status"`. A report whose own `status` is `blocked`, `failed`, `interrupted`, `partial`, `staging`, `orphaned`, `quarantined`, or `inconsistent` still has outer `outcome=succeeded`: the read-only invocation successfully reported historical/current facts. `outcome=interrupted` is invalid for V1 status.

## 9. JSON and Human presentation

### 9.1 Canonical receipt

Operations explicitly adopts the CLI JSON v1 canonical serialization. A complete `doctor --json` or `status --json` receipt is exactly one validated five-field envelope, encoded as UTF-8 canonical JSON plus one LF, with empty stderr. The complete buffer including LF is capped independently at 65,536 bytes inclusive; 65,536 is valid and 65,537 is a controlled presentation failure. This numerical cap is an Operations decision and does not inherit Knowledge Answer payload assumptions.

After every check/projection handle and read-only child is settled, Operations forms one immutable buffer and explicitly adopts ADR 0109's synchronous Windows binary fd1 setup and remaining-suffix short-write loop for this buffer. It does not adopt the Knowledge cancellation seal, Answer commit semantics, or manifest parity. Serialization/cap/setup/invalid-count/write failure after a validated outcome produces no fallback JSON, no Human text, no diagnostic, and no stderr; with no pending Operations-owned I/O it terminates via `os._exit(1)`. Empty or partial stdout is not a receipt and exit `1` alone cannot distinguish a business `failed` envelope from presentation failure.

### 9.2 Human wire format

Human mode renders the same validated report/diagnostic set, never parses JSON stdout, and uses one bounded UTF-8 buffer with LF line endings, no BOM, ANSI, raw CR, table-width dependence, spinner, progress line, prompt, traceback, raw path, or exception text. Stderr is empty on every complete handled Human receipt. The buffer is capped at 65,536 bytes and uses the same settled-resource fd1 writer/failure rule above. Rich may construct the fixed text internally, but V1 wire bytes remain the plain lines below so console launcher and `python -m gezhi` are identical when captured by a subprocess.

Doctor report lines are:

~~~text
格致 doctor：<就绪|受阻|检查失败>
配置：<就绪|受阻|检查失败>
核心 Python：<就绪|受阻|检查失败>
核心依赖：<就绪|受阻|检查失败>
Literature Data Root：<就绪|受阻|检查失败|未检查>
Knowledge Data Root：<就绪|受阻|检查失败|未检查>
OCR 运行时：<就绪|受阻|检查失败>
Codex 运行时：<就绪|受阻|检查失败>
<zero or more diagnostic problem/recommendation pairs>
~~~

Ready doctor adds `下一步：冻结环境已就绪。`; other branches append one pair for each diagnostic in array order, using Section 9.3. Every output ends with exactly one LF.

Overall status lines are:

~~~text
格致状态：<Section 9.3 mapping>
范围：全部
Literature：<可用性>；Work=<N>；状态=[<status=count list>]；待审核=<N>；待交接=<N>
Knowledge：<可用性>；active=<N>；withdrawn=<N>；Answer=[<terminal-status=count list>]
恢复风险：暂存=<N>；待恢复=<N>；已隔离=<N>；不一致=<N>
下一步：<next_action mapping>
<zero or more diagnostic problem/recommendation pairs>
~~~

Work status lines are:

~~~text
格致状态：<Section 9.3 mapping>
范围：Work <validated work_id>
Literature：<可用性>
阶段：ingest=<状态>；ocr=<状态>；canonicalize=<状态>；read=<状态>；review=<状态>；handoff=<状态>；knowledge_import=<状态>
审核：待审核=<N>；已接受=<N>；已拒绝=<N>；已暂缓=<N>
交接：<handoff_status>
Knowledge：<可用性>；active=<N>；withdrawn=<N>；相关 Answer=[<terminal-status=count list>]
恢复风险：暂存=<N>；待恢复=<N>；已隔离=<N>；不一致=<N>
下一步：<next_action mapping>
<zero or more diagnostic problem/recommendation pairs>
~~~

Status-count lists use the JSON list order, map each status to its Chinese label from Section 9.3, place ASCII `=` between label/count, use ASCII comma with no following space between items, and use empty brackets `[]` when no item exists. If an overall Context summary is unavailable/unsafe, its populated line is replaced exactly by `Literature：<不可用|不安全>` or `Knowledge：<不可用|不安全>`.

If Work Knowledge is unavailable/unsafe its populated line becomes exactly `Knowledge：<不可用|不安全>` and has no counts. Work Literature is required for a result and therefore always emits the Stage/Review/Handoff lines.

A no-result branch has exactly:

~~~text
格致状态：<受阻|读取失败>
<diagnostic problem/recommendation pairs>
~~~

### 9.3 Chinese mappings

Operational status maps to: `empty=空`、`pending=待处理`、`running=运行中`、`succeeded=完成`、`blocked=受阻`、`failed=失败`、`interrupted=已中断`、`partial=部分可用`、`staging=存在暂存结果`、`orphaned=存在待恢复结果`、`quarantined=存在隔离结果`、`inconsistent=状态不一致`. Stage status uses the same Chinese words for its six-value subset. Availability maps `ready=就绪`、`partial=部分可用`、`unavailable=不可用`、`unsafe=不安全`. Handoff status maps `none=无`、`pending=待处理`、`available=可用`、`blocked=受阻`、`failed=失败`、`inconsistent=不一致`.

Each diagnostic appends exactly two lines:

| Code | `问题：...` | `建议：...` |
|---|---|---|
| `operations.doctor.configuration_invalid.v1` / `operations.status.configuration_invalid.v1` | `问题：格致配置无效。` | `建议：检查版本化配置后重试；本命令不会修改配置。` |
| `operations.doctor.core_environment_unavailable.v1` | `问题：核心 Python 环境或依赖与冻结基线不一致。` | `建议：使用已批准的冻结环境恢复流程；不要在 doctor 中安装或升级。` |
| doctor/status `data_root_unsafe` | `问题：一个或多个 Data Root 不满足 Windows 安全边界。` | `建议：停止写入并在外部修复路径边界；本命令不会移动或创建目录。` |
| doctor/status `data_root_unavailable` | `问题：一个或多个 Data Root 不可用。` | `建议：在外部恢复已配置目录及访问权限后重试；本命令不会创建目录。` |
| `operations.doctor.ocr_environment_unavailable.v1` | `问题：OCR 运行时与冻结基线不一致或不可用。` | `建议：使用已批准的 OCR 环境恢复流程；不要切换 CPU、在线模型或其他 OCR。` |
| `operations.doctor.codex_environment_unavailable.v1` | `问题：项目锁定的 Codex CLI 不可用。` | `建议：检查项目锁、原生 CLI 与登录状态；不要切换全局、桌面或其他模型。` |
| `operations.doctor.inspection_failed.v1` | `问题：doctor 无法完成只读检查。` | `建议：保留现场并检查格致实现或运行环境；不要让 doctor 自动修复。` |
| `operations.status.invalid_work_id.v1` | `问题：Work ID 无效。` | `建议：使用完整的小写 wrk_ UUIDv4。` |
| `operations.status.work_not_found.v1` | `问题：找不到指定 Work。` | `建议：核对 Work ID，或运行 gezhi status 查看整体状态。` |
| `operations.status.integrity_attention.v1` | `问题：状态范围内存在恢复或完整性风险。` | `建议：停止相关写入、保留现场并进行维护检查；不要手工删除或改名。` |
| `operations.status.projection_incomplete.v1` | `问题：状态报告只覆盖了可验证的部分 Context。` | `建议：先恢复不可用的 Context，再运行相同 status 命令。` |
| `operations.status.observation_failed.v1` | `问题：无法形成可信的状态报告。` | `建议：保留现场并检查权威资产、索引与读取环境；status 不会自动修复。` |

Next-action mappings are exactly: `none=当前无需操作。`、`add_work=运行 gezhi literature add <pdf_path> 添加 Work。`、`inspect_work=运行 gezhi status <work_id> 查看需要处理的 Work。`、`resume_work=前置条件就绪后运行 gezhi literature resume <work_id>。`、`review_candidate=使用 Review Queue 中的 Candidate ID 运行 gezhi literature review。`、`repair_data_root=在外部恢复或修复 Data Root 后重试。`、`inspect_recovery=停止相关写入、保留现场并进行维护检查。` Angle-bracket operands are literal guidance placeholders except that Work-scope `resume_work` substitutes the report's already validated `work_id`; no raw invalid operand is ever substituted.

## 10. Executable branch witnesses

The JSON below shows semantic values and does not claim member order; the writer applies Section 9.1 `sort_keys=True` canonicalization, and executable tests compare those canonical bytes.

### 10.1 Doctor witnesses

| Branch | Required witness |
|---|---|
| ready | all seven checks ready; `succeeded`, empty diagnostics, exit `0`, Human ready report |
| configuration blocked | roots `not_checked`, independent checks still observed; configuration primary, exit `2` |
| root unsafe/unavailable | affected root blocked, other checks retained; matching root primary/supplemental, exit `2` |
| core/OCR/Codex missing or drifted | only affected capability blocked; no installer/updater/process fallback; exit `2` |
| multiple blocked facts | static primary priority plus code-sorted supplemental items; every fact represented once |
| inspection failure | affected check failed, inspection primary, other proved blockers supplemental; exit `1` |

Ready JSON value:

~~~json
{"schema_version":"gezhi.cli_result.v1","command":"doctor","outcome":"succeeded","result":{"schema_version":"gezhi.doctor_result.v1","overall_status":"ready","checks":[{"id":"configuration","status":"ready"},{"id":"core_python","status":"ready"},{"id":"core_dependencies","status":"ready"},{"id":"literature_data_root","status":"ready"},{"id":"knowledge_data_root","status":"ready"},{"id":"ocr_runtime","status":"ready"},{"id":"codex_runtime","status":"ready"}]},"diagnostics":[]}
~~~

Configuration-blocked JSON value (independent capabilities still ready):

~~~json
{"schema_version":"gezhi.cli_result.v1","command":"doctor","outcome":"blocked","result":{"schema_version":"gezhi.doctor_result.v1","overall_status":"blocked","checks":[{"id":"configuration","status":"blocked"},{"id":"core_python","status":"ready"},{"id":"core_dependencies","status":"ready"},{"id":"literature_data_root","status":"not_checked"},{"id":"knowledge_data_root","status":"not_checked"},{"id":"ocr_runtime","status":"ready"},{"id":"codex_runtime","status":"ready"}]},"diagnostics":[{"code":"operations.doctor.configuration_invalid.v1","context":{}}]}
~~~

Its complete Human stdout is:

~~~text
格致 doctor：受阻
配置：受阻
核心 Python：就绪
核心依赖：就绪
Literature Data Root：未检查
Knowledge Data Root：未检查
OCR 运行时：就绪
Codex 运行时：就绪
问题：格致配置无效。
建议：检查版本化配置后重试；本命令不会修改配置。
~~~

Stderr is empty and normal exit is `2`.

### 10.2 Status witnesses

| Branch | Required witness |
|---|---|
| empty overall | coherent empty projections; report `status=empty`, outer succeeded, exit `0`, next action add Work |
| complete overall/work | only valid authority contributes success; outer succeeded, exit `0` |
| historical pending/running/blocked/failed/interrupted | report carries that operational value while outer remains succeeded, exit `0` |
| one Context unavailable/unsafe | coherent other projection produces `partial`, matching supplemental plus projection-incomplete, exit `0` |
| staging/orphan/quarantine/inconsistency | never `succeeded`; recovery count plus integrity supplemental, exit `0` if bounded |
| Answer staging seen by `status` | only `staging_count` increments; manifest, age, stability, target presence/conflict, and content validity never upgrade it to orphaned/quarantined |
| Work count mismatch/overflow | result null, observation-failed primary, exit `1`; no truncation, omission, saturation, or normalization |
| invalid Work ID | result null, blocked primary, exit `2`; raw invalid value absent from output |
| Work absent | result null, work-not-found primary with validated ID, exit `2` |
| invalid configuration or no minimum projection | result null, blocked primary, exit `2` |
| unbounded observation failure | result null, failed primary, exit `1` |

Partial Work JSON value:

~~~json
{"schema_version":"gezhi.cli_result.v1","command":"status","outcome":"succeeded","result":{"schema_version":"gezhi.status_result.v1","scope":"work","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000","status":"partial","literature":{"availability":"ready","stages":[{"stage":"ingest","status":"succeeded"},{"stage":"ocr","status":"succeeded"},{"stage":"canonicalize","status":"pending"},{"stage":"read","status":"pending"},{"stage":"review","status":"pending"},{"stage":"handoff","status":"pending"},{"stage":"knowledge_import","status":"pending"}],"review_counts":{"pending":0,"accepted":0,"rejected":0,"deferred":0},"handoff_status":"none"},"knowledge":{"availability":"unavailable"},"recovery":{"staging_count":0,"orphaned_count":0,"quarantined_count":0,"inconsistent_count":0},"next_action":"repair_data_root"},"diagnostics":[{"code":"operations.status.data_root_unavailable.v1","context":{"contexts":["knowledge"]}},{"code":"operations.status.projection_incomplete.v1","context":{"contexts":["knowledge"]}}]}
~~~

Its complete Human stdout is:

~~~text
格致状态：部分可用
范围：Work wrk_123e4567-e89b-42d3-a456-426614174000
Literature：就绪
阶段：ingest=完成；ocr=完成；canonicalize=待处理；read=待处理；review=待处理；handoff=待处理；knowledge_import=待处理
审核：待审核=0；已接受=0；已拒绝=0；已暂缓=0
交接：无
Knowledge：不可用
恢复风险：暂存=0；待恢复=0；已隔离=0；不一致=0
下一步：在外部恢复或修复 Data Root 后重试。
问题：一个或多个 Data Root 不可用。
建议：在外部恢复已配置目录及访问权限后重试；本命令不会创建目录。
问题：状态报告只覆盖了可验证的部分 Context。
建议：先恢复不可用的 Context，再运行相同 status 命令。
~~~

Stderr is empty and normal exit is `0`.

Invalid Work ID JSON value:

~~~json
{"schema_version":"gezhi.cli_result.v1","command":"status","outcome":"blocked","result":null,"diagnostics":[{"code":"operations.status.invalid_work_id.v1","context":{}}]}
~~~

Observation-failed JSON value:

~~~json
{"schema_version":"gezhi.cli_result.v1","command":"status","outcome":"failed","result":null,"diagnostics":[{"code":"operations.status.observation_failed.v1","context":{}}]}
~~~

### 10.3 Highest-seam acceptance

Every witness runs through both public launchers in a fresh Windows subprocess. Tests compare complete stdout bytes, complete stderr bytes, normal exit, and a before/after snapshot proving no project-owned mutation. Fixtures inject frozen read-only observations through private composition seams; tests never uninstall, install, upgrade, authenticate, create a production root, modify user credentials, or damage real data.

Public acceptance additionally proves:

- no `uv`, package manager, installer, updater, OCR inference, semantic Codex request, WSL process, or fallback executable starts;
- configuration invalidity does not stop independent doctor capability checks, but prevents root probing;
- a non-consumed/unavailable Context only narrows the status report allowed by Section 6;
- staging, partial, orphaned, quarantined, and inconsistent fixtures never produce `status=succeeded` or a Human completion heading;
- Answer staging fixtures that differ only by manifest, age, apparent stability, target presence/conflict, or content validity produce the same staging-only recovery classification without writer ownership;
- `work_status_counts` covers zero/equal totals, unequal totals, and checked-add overflow; only the exact representable equality produces a report;
- a historical Answer `failed`/`blocked` state does not make the read invocation fail;
- JSON exact bytes, Human exact lines, stderr isolation, exit mapping, two-launcher parity, and 65,536/65,537 presentation boundaries hold;
- complete stdout is the only Operations receipt. Empty/partial stdout, even with a familiar exit value, is not interpreted as a handled report.

## 11. Change rule and non-goals

Changing the seven doctor check IDs/order, Work ID grammar, operational vocabulary, result shapes, diagnostic union/context, primary priority, Human lines, normal exits, cap, or read-only guarantee requires a new Operations contract generation or explicit replacing decision. A new Context extends static composition and must define its own projection facts before a later contract adds it; no V1 arbitrary map is reserved for that purpose.

This contract does not implement T09 or T24, add a command, add a dependency, change a lock, define a maintenance command, persist a health receipt, internationalize Human messages, expose package/path/credential detail, create a background monitor, or authorize deployment. PaperBot/WSL behaviour remains a read-only historical reference and none of its command names, status files, storage layout, fallback paths, or code is a compatibility target.
