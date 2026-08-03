# Knowledge Ask Diagnostics v1 合同

状态：已冻结 committed Answer 的 15+1 primary 与 committed JSON normal-exit table；无 committed Answer 的 `blocked/failed/interrupted` 分类、`result=null` presence matrix、`succeeded` 禁令与正常 JSON `2/1/130` exit，以及 no-commit `blocked` 的 11 项、`failed` 的 7 项与 `interrupted` 的 1 项 primary/context union。Blocked 内部 fail-fast 仲裁、跨 outcome 静态优先级 `failed > interrupted > blocked`、单一 cancellation latch、固定 checkpoints、stop-new-work、原子 pre-ID identity barrier、`NoCommitSafeBoundaryV1`、`HandledCancellationWindowV1` 的完整 cutover、项目自有 native Win32 DLL bridge、interactive candidate 的 inherited-ignore normalization、只读 console/processed-input capability gate、capability-absent no-source profile、current-process debugger gate/no-source selection、orchestrator-owned Codex attempt root 的 no-console/no-process-group/stdio/handle/Job isolation、pre-seal immutable JSON candidate、65,536-byte inclusive stdout cap、closed controlled JSON presentation failure 的静默 `os._exit(1)`、exact Windows binary fd `1` writer、ADR 0110 的 project-wide `RawArgvPreflightV1` pre-Typer seam/职责、ADR 0111 的 PASS 后 lazy-import Typer/Rich/完整 command graph 强入口边界、[ADR 0113](../adr/0113-feed-one-immutable-argv-snapshot-to-preflight-and-typer.md) 的唯一 immutable snapshot/exact feed-through/禁用 Windows expansion 与 shell completion、[ADR 0114](../adr/0114-exclude-argv-zero-from-raw-argv-resource-measurement.md) 的 argv0 计量排除、[ADR 0115](../adr/0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 的三个 inclusive ceilings/`len(str)` 单位/精确 aggregate，以及 [ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 的无 payload resource verdict/fixed stderr/empty stdout/exit `2` 也已冻结；supplemental variants、Human 中文文案/exit、其余 parser/bootstrap/internal/argument exit 与 ADR 0108 排除的其他 presentation failure 仍待冻结。决策依据见 [ADR 0092](../adr/0092-map-committed-knowledge-ask-outcomes-to-primary-diagnostics-and-exit-codes.md)、[ADR 0093](../adr/0093-classify-uncommitted-knowledge-ask-outcomes-by-terminal-cause.md)、[ADR 0094](../adr/0094-freeze-uncommitted-blocked-knowledge-ask-primary-diagnostics.md)、[ADR 0095](../adr/0095-freeze-uncommitted-knowledge-ask-failed-primary-diagnostics.md)、[ADR 0096](../adr/0096-freeze-uncommitted-knowledge-ask-interrupted-primary-diagnostic.md)、[ADR 0097](../adr/0097-prioritize-uncommitted-knowledge-ask-outcomes-as-failed-interrupted-blocked.md)、[ADR 0098](../adr/0098-use-one-cancellation-latch-and-an-atomic-pre-id-barrier.md)、[ADR 0099](../adr/0099-prove-no-commit-safety-with-a-zero-live-resource-ledger.md)、[ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md)、[ADR 0101](../adr/0101-use-a-project-owned-native-win32-ctrl-c-bridge.md)、[ADR 0102](../adr/0102-normalize-inherited-ctrl-c-ignore-before-activation.md)、[ADR 0103](../adr/0103-require-a-read-only-conin-processed-input-capability-gate.md)、[ADR 0104](../adr/0104-continue-with-a-no-source-cancellation-profile-when-capability-is-absent.md)、[ADR 0105](../adr/0105-use-the-no-source-profile-when-the-current-process-is-being-debugged.md)、[ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md)、[ADR 0107](../adr/0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md)、[ADR 0108](../adr/0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md)、[ADR 0109](../adr/0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md)、[ADR 0110](../adr/0110-run-a-decoded-argv-resource-preflight-before-typer.md)、[ADR 0111](../adr/0111-lazy-import-the-cli-framework-and-command-graph-after-argv-preflight.md)、[ADR 0113](../adr/0113-feed-one-immutable-argv-snapshot-to-preflight-and-typer.md)、[ADR 0114](../adr/0114-exclude-argv-zero-from-raw-argv-resource-measurement.md)、[ADR 0115](../adr/0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 与 [ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md)；十五项 manifest 三元组来源见 [ADR 0060](../adr/0060-use-a-minimal-closed-answer-error-code-table.md) 与 [Knowledge Answerer v1](./knowledge-answerer-v1.md)，共享 item/集合规则见 [CLI Diagnostics v1](./cli-diagnostics-v1.md)，outer/result 分别见 [CLI JSON v1](./cli-json-v1.md) 与 [Knowledge Ask Result v1](./knowledge-ask-result-v1.md)。

## Committed Answer 矩阵

本次新 Answer 目录 commit 成功时，`result` 必须是 `KnowledgeAskResultV1` object，outer outcome、primary 与 process exit code 为：

| terminal manifest | outer `outcome` | primary | normal exit |
|---|---|---|---:|
| `status=succeeded`、`error=null` | `succeeded` | 不存在；所有 diagnostics 均为 supplemental | `0` |
| `status=blocked`、合法非空 `error` | `blocked` | index 0，按下表从 manifest error 静态选择 | `2` |
| `status=failed`、合法非空 `error` | `failed` | index 0，按下表从 manifest error 静态选择 | `1` |
| `status=interrupted`、`error=null` | `interrupted` | `knowledge.ask.user_interrupted.v1` | `130` |

`succeeded` 的 `answer_output` 是完整 `AnswerOutputV1`；其余三行的 `answer_output=null`。正常证据不足仍属于 `succeeded`，没有 primary error diagnostic。Supplemental items 若存在，不能改变本矩阵。

## Committed primary union

以下十六个 code 只允许作为 primary。每个 item 必须精确为 `{"code":"<table value>","context":{}}`；`context` 禁止任何 member。

| manifest `error.code` / cause | required outer outcome | required primary `code` |
|---|---|---|
| `fts5_unavailable` | `blocked` | `knowledge.ask.fts5_unavailable.v1` |
| `retrieval_view_too_large` | `blocked` | `knowledge.ask.retrieval_view_too_large.v1` |
| `retrieval_query_failed` | `failed` | `knowledge.ask.retrieval_query_failed.v1` |
| `retrieval_materialization_failed` | `failed` | `knowledge.ask.retrieval_materialization_failed.v1` |
| `codex_runtime_unavailable` | `blocked` | `knowledge.ask.codex_runtime_unavailable.v1` |
| `codex_timeout_exhausted` | `blocked` | `knowledge.ask.codex_timeout_exhausted.v1` |
| `codex_network_exhausted` | `blocked` | `knowledge.ask.codex_network_exhausted.v1` |
| `codex_rate_limit_exhausted` | `blocked` | `knowledge.ask.codex_rate_limit_exhausted.v1` |
| `codex_server_error_exhausted` | `blocked` | `knowledge.ask.codex_server_error_exhausted.v1` |
| `codex_transient_exhausted` | `blocked` | `knowledge.ask.codex_transient_exhausted.v1` |
| `synthesis_input_invalid` | `failed` | `knowledge.ask.synthesis_input_invalid.v1` |
| `codex_process_failed` | `failed` | `knowledge.ask.codex_process_failed.v1` |
| `answer_output_invalid` | `failed` | `knowledge.ask.answer_output_invalid.v1` |
| `citation_link_construction_failed` | `failed` | `knowledge.ask.citation_link_construction_failed.v1` |
| `answer_rendering_failed` | `failed` | `knowledge.ask.answer_rendering_failed.v1` |
| 用户中断，manifest `error=null` | `interrupted` | `knowledge.ask.user_interrupted.v1` |

前十五项必须通过静态 lookup 从已经完整验证的 `gezhi.answer_manifest.v1` manifest 三元组选择，禁止动态 prefix/concatenation、近似匹配或 unknown-code fallback。`user_interrupted` 只能来自已 committed 且验证通过的 `status=interrupted,error=null` manifest，不能只凭 Ctrl+C observation 或 attempt failure class 生成；它不是 Answer manifest error code，不得写入 manifest。所有 primary code 均符合 CLI Diagnostics v1 的 96-byte 上限，空 context 也满足单项 byte cap。

Primary item 不复制 manifest `status`、`stage`、裸 `error.code`、`answer_id`、commit flag、path 或 Human message。`answer_id` 已由 result receipt 唯一携带；stage 与 cause 已由 versioned primary code 静态判别。这组 `.v1` machine 语义绑定当前 `gezhi.answer_manifest.v1` error 表；未来 manifest generation 或 code 语义变化不能静默重解释。Confirmed capture overflow 的 primary 仍是 `knowledge.ask.codex_process_failed.v1`；任何未来 overflow detail 只能是另行批准的 supplemental variant。

## 无 committed Answer 的 outcome matrix

本次 invocation 没有成功提交自己的新 Answer 目录时：

| no-commit terminal-cause class | required `outcome` | required `result` | required primary | normal JSON exit |
|---|---|---|---|---:|
| 输入问题或可恢复前置条件 | `blocked` | `null` | 恰好一个；从下节十一项静态选择 | `2` |
| 本地 Answer 形成、验证或目录提交失败 | `failed` | `null` | 恰好一个；从下节七项静态选择 | `1` |
| 同一 cancellation latch 在原子 pre-ID barrier 先于本次新 `answer_id` cutover 线性化、完成安全收尾，且没有七项 failed candidate | `interrupted` | `null` | `knowledge.ask.user_interrupted_before_answer.v1` | `130` |
| 无 commit 的 `succeeded` | 禁止 | — | — | — |

旧 orphan 的 recovery rename 不是本次新 Answer commit，不能令 `result` 非 `null` 或选择 `succeeded`。未提交 staging 中的字面 `status` 也不能选择 outcome。`blocked`、`failed` 与 `interrupted` 必须由 command-owned no-commit terminal-cause classifier 选择，并分别使用下列静态 union。任何分支都不得用空 array、通用 fallback code、manifest error 或异常文本填补。

每次 one-shot CLI invocation 都先在 CPython 形成 `sys.argv` 后、Typer 解释任何 token 前经过 project-wide `RawArgvPreflightV1`；这层不属于 Knowledge adapter，只拥有静态 resource-ceiling 机械检查，不识别 command、literal `--json`、Human、help、version 或 known/unknown token。ADR 0113 已关闭 Typer shell completion，因此没有 environment-owned completion arguments 作为第二套输入；ADR 0114 已冻结全部资源计量只覆盖 snapshot suffix、完全排除 argv0；ADR 0115 已冻结三个 inclusive ceilings、`len(str)` 单位、精确 aggregate 与 raw-before-domain 顺序。ADR 0115 权威判定超限的 preflight resource failure 位于本合同外，不形成 handled result、outcome、diagnostic 或 cancellation；[ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 只让最小 bootstrap presenter 尝试 fixed stderr、保持 stdout empty 并返回 `2`。只有 seam 通过后，项目才 lazy-import Typer、Rich 与完整 command graph，随后 parser 才处理 grammar。`blocked` 覆盖进入 Knowledge adapter 后的 Question 领域输入问题与可恢复前置条件。Parser 只处理 command/subcommand/option grammar；unknown command/option、recognized option 完全缺少参数、重复或互斥规则违反仍是 argument failure。Recognized Question/configuration value 必须以 raw string representation 进入 handled adapter，类型/range/path existence/reparse 等领域校验不得在 parser 提前发生。Blocked 的具体 code 与 blocked 内部相对顺序由下一节冻结。`failed` 覆盖本次本地 Answer/staging/manifest 形成、验证或目录提交失败；若失败仍成功提交 terminal Answer，则改走 committed matrix。同一 one-shot cancellation latch 在原子 pre-ID barrier 前先线性化并达到相应安全收尾点时，只形成 provisional interruption；最终没有七项 failed candidate 时才选择 no-commit `interrupted`，并使用 ADR 0096 的独立 primary，不能复用 committed-only `knowledge.ask.user_interrupted.v1`。一旦 `answer_id` 已生成并锁存，安全取消必须尝试提交 `status=interrupted` Answer；提交成功走 committed matrix，terminalization/commit 失败走 no-commit `failed`，无法证明 `NoCommitSafeBoundaryV1` 则不进入正常矩阵。Crash、外部强杀、单独 Ctrl+C observation 或 attempt failure class 都不能自动构造 no-commit `interrupted` envelope。单个历史 orphan 的 validation failure、target conflict 或 recovery rename failure 只可成为 supplemental；staging 集合无法安全枚举、scan protocol 无法成立等全局基础设施故障不在该例外内，使用 no-commit `failed` 静态表。`Failed` 与 `interrupted` primary 已分别由 ADR 0095、ADR 0096 闭合，ADR 0097 已冻结同时存在的候选 cause 按 `failed > interrupted > blocked` 仲裁，ADR 0098 已冻结 cancellation observation/linearization、stop-new-work 与 pre-ID cutover，ADR 0099 已冻结 no-commit 完整 settle、typed resource cleanup 与安全后置条件。

## No-commit blocked primary union

V1 不把恶意或高权限本机进程并发替换目录组件纳入保证范围。实现仍须在 Data Root preflight、创建本次 staging 直接子目录之前，以及任何正式或 recovery directory rename 之前，复核冻结 root identity、handle-derived canonical root、目标父链与 reparse 状态；descendant path 只能从 frozen canonical root 派生，不能重新使用 raw configured path。发现漂移必须停止，但本合同不要求全程 handle-relative Win32/NT I/O，也不承诺消除最后一次复核与操作之间的 hostile TOCTOU。下文“Data Root handle/physical identity 复用于 ID 后路径”只表示 handle/identity 持续作为锚点且路径复用 frozen canonical root，不表示 descendant path 由 root handle 相对寻址。

初始 Data Root gate 成功是不可逆的 outcome-classification latch：只有该 gate 内可以选择本节三项 Data Root blocked primary。成功之后，持锁 recovery、staging 创建前或最终 rename 前的 checkpoint 若无法继续证明 root identity/canonical path/父链/reparse 状态仍安全且相同，一律选择 no-commit `failed`，不因 `answer_id` 尚未生成而退回 `blocked`。Root 已不可信时禁止尝试提交 terminal `status=failed` Answer；本次新 staging 若存在则留在原路径并继续被正式 reader 忽略，outer `result=null`。Candidate-local 的历史 orphan 无效或 target conflict 仍只是 supplemental；只有 invocation-wide root trust loss 才终止当前命令。该分支唯一 primary 为 `{"code":"knowledge.ask.data_root_integrity_lost.v1","context":{}}`，正常 JSON exit 为 `1`；明确漂移与无法重新建立 checkpoint 证明都使用同一码，且不得作为 blocked、committed 或 supplemental item。

`knowledge ask` 的 Data Root gate 只 safe-open 并验证本命令消费的 `knowledge.data_root`；`literature.data_root` 与 future Context roots 不得被执行 existence/access/handle/physical-identity probe，其状态不能阻塞本命令。允许的等价形式仅为 Windows 大小写、separator、`.` / `..` 归一和普通/local-extended DOS 前缀；safe-open 证明 8.3 short name、SUBST、额外 drive-letter、volume mount 或其他隐藏 filesystem alias 时，选择 `knowledge.ask.data_root_unsafe.v1`。若别名/最终路径判定无法完成但没有 unsafe 肯定证据，选择 `knowledge.ask.data_root_unavailable.v1`。

所有 Context Data Root 的规范化 Windows path namespace 必须两两不同且互不构成祖先/后代。任一 root 都不得等于或包含项目根 `E:\Gezhi`；项目内 root 必须是 `E:\Gezhi\data` 的严格后代而不能直接使用该共享容器，项目外本机 root 仍允许。Future Context 继续适用同一 pairwise isolation rule。全部 source 合并后，能够无文件系统 I/O 纯词法归一为本机 DOS 绝对路径的 final values 若已经相同、嵌套或侵犯项目边界，选择 Configuration primary `knowledge.ask.configuration_invalid.v1`；无法在这一层形成受支持本地绝对路径的 namespace 留给 Data Root gate。文本配置通过后，只有 safe open 的 reparse evidence、handle-derived final path 或 physical identity 才证明的隐藏别名、真实对象重合/嵌套或物理边界冲突，选择 Data Root primary `knowledge.ask.data_root_unsafe.v1`。

以下十一项只允许在 `result=null`、outer `outcome=blocked` 时作为 `diagnostics[0]` primary。每项必须精确为 `{"code":"<table value>","context":{}}`；`context` 禁止任何 member，也不得把这些 code 用作 supplemental。

| pre-Answer gate | closed cause | required primary `code` |
|---|---|---|
| Question | `invalid_question` | `knowledge.ask.invalid_question.v1` |
| Question | `question_too_large` | `knowledge.ask.question_too_large.v1` |
| Question | `question_too_complex` | `knowledge.ask.question_too_complex.v1` |
| Configuration | `configuration_invalid` | `knowledge.ask.configuration_invalid.v1` |
| Configuration | `configuration_incompatible` | `knowledge.ask.configuration_incompatible.v1` |
| Provenance | `provenance_unavailable` | `knowledge.ask.provenance_unavailable.v1` |
| Data Root | `data_root_unavailable` | `knowledge.ask.data_root_unavailable.v1` |
| Data Root | `data_root_unsafe` | `knowledge.ask.data_root_unsafe.v1` |
| Data Root | `data_root_identity_unavailable` | `knowledge.ask.data_root_identity_unavailable.v1` |
| Answer Writer | `answer_writer_busy` | `knowledge.ask.answer_writer_busy.v1` |
| Answer Writer | `answer_writer_coordination_unavailable` | `knowledge.ask.answer_writer_coordination_unavailable.v1` |

全局 blocked-only 顺序固定为 Question validation → configuration validation 与冻结部署配置/角色审计 bytes → provenance formation → Data Root safe open 与 physical identity → Answer Writer zero-wait ownership。每个 gate 只在前一个成功后运行；首个权威 blocked cause 停止后续 probe，禁止并行 collect-all 或按异常到达时间选择。Question 内部依次为基础可规范化性、规范值规模、最低语义有效性、查询原子复杂度：禁止 control/无法规范化/空先选 `invalid_question`，规模超限再选 `question_too_large`，规模合法的纯符号或单 Han 再选 `invalid_question`，最后才可选 `question_too_complex`。Configuration source 固定按 CLI → `GEZHI_*` → local TOML → default TOML → 程序安全默认值验证；内置默认值是完整基线，default 是必需的版本化 partial TOML，local 是可选的版本化 partial TOML，CLI/env 是无版本 partial raw patch。Active TOML 的 `config_version` 必须匹配 `gezhi.config.vN`，当前只支持 `gezhi.config.v1`，且 default/local generation 必须相同；CLI/env/defaults 不能设置该 metadata。Local 缺失跳过，default 缺失无效；第一个 active source 的错误停止后续 source。每个 patch 只验证 source-owned required key 与实际提供字段，全部通过后才合并并验证 final required/cross-field 规则。Merge 对 closed Schema 的每个 leaf 选择最高优先级第一个 present value；nested table 只覆盖 present leaf，scalar/array 原子替换，禁止 null/unset/tombstone，空字符串仍算 present。Final runtime leaf 只有 nonempty string `literature.data_root` 与 `knowledge.data_root`，默认分别为 `E:\Gezhi\data\literature` / `E:\Gezhi\data\knowledge`；unknown Context/table/leaf 无效。单一 source 内按读取/语法/结构/版本无效、合法但 unsupported/mismatched generation 与受支持 supplied-field 验证的顺序裁决。Model/reasoning/Codex version、timeout/backoff 及所有 role limits 都不是配置 field；提供时按 unknown field 选择 `configuration_invalid`，`effective_config.json` bytes 由 role descriptor 预先生成。Data Root 只接受本机 non-remote drive-absolute/local extended DOS namespace；项目外本地根允许，relative/UNC/WSL UNC/remote mapping/device/Volume GUID/ADS 等明确拒绝并选择 `data_root_unsafe`。Reparse evidence 也 unsafe；无该证据但缺失、非目录、拒绝访问或 resolved-path 核对失败选择 `data_root_unavailable`；safe open 后 FileId API/structure 失败或 FileId 全零选择 `data_root_identity_unavailable`，合法 FileId 配 `VolumeSerialNumber=0` 仍允许。成功的 deployment config、role audit bytes、provenance 与 Data Root handle/physical identity 必须冻结并复用于 ID 后路径，不能重算或从原始路径重开。完整边界、反例与安全理由见 ADR 0094。

`WAIT_TIMEOUT` 是 `answer_writer_busy` 的唯一依据；无法建立、打开或等待 ownership mechanism、`WAIT_FAILED` 及其他未批准返回值选择 `answer_writer_coordination_unavailable`。`WAIT_OBJECT_0` / `WAIT_ABANDONED` 表示 ownership 已取得，两者都进入持锁 orphan scan。历史单项 orphan 异常只可成为未来 supplemental；orphan scan 基础设施故障以及取得 ownership 后的 staging/manifest/commit 故障留给 no-commit `failed`。ADR 0097 已冻结 failed 压过 cancellation、cancellation 压过 provisional blocked；blocked cause 在最终安全 arbitration boundary 前仍只是 provisional，不能提前发布 envelope。ADR 0098 已冻结取消 latch、固定 observation checkpoints、stop-new-work 与原子 pre-ID barrier，ADR 0099 已冻结 ownership-aware drain、release/close 顺序与充分安全证明。

## No-commit failed primary union

完整 no-commit failed union 固定为以下七项；V1 不授权新增分支或任何 catch-all：

| closed failed cause | required primary `code` | required `context` |
|---|---|---|
| Caller-owned Question、Configuration 或 Git facts 已合法，但 `answer_id` 前无法机械构造/canonical-serialize `QuestionEnvelopeV1`、role audit bytes 或 provenance object | `knowledge.ask.pre_answer_formation_failed.v1` | `{}` |
| 初始 Data Root gate 成功后，任一强制 checkpoint 无法继续证明 root identity、canonical path、父链与 reparse 状态仍安全且相同 | `knowledge.ask.data_root_integrity_lost.v1` | `{}` |
| Writer ownership 已取得且 root trust 仍成立，且 cancellation 前已 commitment 的 scan operation 独立证明 `answers/.staging/` 无法安全枚举或 invocation-wide orphan scan protocol 无法建立/完成 | `knowledge.ask.orphan_scan_failed.v1` | `{}` |
| `answer_id` 已生成且 root trust 仍成立，但本次 staging direct child、任一 non-terminal asset 或私有 entry 无法形成、写完、验证、安装或撤销，因而不能达到封闭 terminal asset set | `knowledge.ask.answer_staging_failed.v1` | `{}` |
| 本次新 Answer 已进入 terminal manifest formation 且 root trust 仍成立，但 manifest canonical buffer/cap、形成、写入、关闭、readback 或完整复验失败 | `knowledge.ask.answer_manifest_failed.v1` | `{}` |
| 本次新 Answer 的 expected target 在 final checkpoint 已存在，或 non-replacing rename 明确返回 target-exists，且 root trust 仍成立 | `knowledge.ask.answer_target_conflict.v1` | `{}` |
| Final checkpoint 已通过、root trust 仍成立且 target 不存在；non-replacing same-volume rename 返回其他确定失败，且能够证明 staging 未提交、target 不是本次 commit、操作已安全停止 | `knowledge.ask.answer_commit_failed.v1` | `{}` |

七项都只允许 outer `outcome=failed`、`result=null`、正常 JSON exit `1`，且不得作为 blocked、committed 或 supplemental item。`pre_answer_formation_failed` 不披露异常、内部字段或序列化细节；`data_root_integrity_lost` 不披露 path、file identity、permission、Win32 code 或原始异常；`orphan_scan_failed` 不披露 staging 名称、数量、manifest 内容、目标或 filesystem 错误；`answer_staging_failed` 不披露 `answer_id`、资产路径、临时文件名、捕获内容或 I/O 错误；`answer_manifest_failed` 不披露 manifest bytes、validation detail、asset identity 或 I/O 错误；`answer_target_conflict` 不披露 `answer_id`、target path、现有 target 状态或比较结果；`answer_commit_failed` 不披露 `answer_id`、staging/target path、Win32 code 或 rename detail。ADR 0098 在安全有界单元之间 stop-new-work、不再启动下一 orphan candidate/recovery 或得到预期 cancellation completion 均不构成 `orphan_scan_failed`；只有取消线性化前已 commitment 的 scan operation 独立失败才可选择该 cause，无法区分时保持矩阵外。Scan 期间 root trust loss 优先于 orphan scan failure；Answer 生命周期内 root trust loss 优先于 staging/manifest/target/commit failure。Manifest formation 前的 non-terminal asset failure 选择 staging code，formation 开始后的 terminal manifest failure 选择 manifest code；target-exists 与其他 determinate rename error 必须分开。Rename 是否提交无法确定时在正常矩阵外。Candidate-local orphan 异常仍只作 supplemental。

## No-commit interrupted primary

当 no-commit terminal-cause classifier 最终选择 `interrupted` 时，`diagnostics[0]` 必须精确为 `{"code":"knowledge.ask.user_interrupted_before_answer.v1","context":{}}`；它只允许配 `outcome=interrupted`、`result=null` 与正常 JSON exit `130`，不得作为 committed、blocked、failed 或 supplemental item。该 code 不披露取消来源、时间、阶段、句柄或内部错误。

资格边界是：command-owned one-shot cancellation latch 的 cancellation transition 在原子 pre-ID barrier 先于规范 `answer_id` 的成功生成、验证与锁存线性化，并且 ADR 0099 的 `NoCommitSafeBoundaryV1` 已成立；满足这些条件只建立 provisional interruption，最终仍须确认没有七项 failed candidate。单独 Ctrl+C observation、attempt `failure_class=interrupted`、子进程退出、Windows 外部强杀或进程消失都不够；ID cutover 后取消必须尝试提交完整 interrupted Answer。ADR 0097 已冻结存在 failed cause 时 failed 获胜、否则 interruption 压过 provisional blocked；ADR 0098 冻结本段的 latch、checkpoint、stop-new-work 与 cutover，ADR 0099 冻结完整 settle 与安全收尾证明。

V1 唯一受支持的用户取消源是 ADR 0100 `HandledCancellationWindowV1` 内由 command-owned bridge 接受的 Ctrl+C；bridge callback 只可一次性锁存取消事实及首次 `observed_monotonic_ns`，不直接选择 outcome、写 diagnostic、抛异步业务异常、终止进程、释放 ownership、写文件或执行 cleanup。重复取消不能改写，Ctrl+Break、console close/logoff/shutdown、worker/Codex 状态、子进程退出、外部强杀或进程消失都不是 latch 写入者；同一 invocation 在 ID 前后复用这一个事实，consumer 的较晚运行时间不能冒充首次 observation，observation 不进入 diagnostic 或持久资产。

唯一 Knowledge 编排器在 handled adapter 入口、每个 pre-Answer gate 进入前和返回后、enumeration 与相邻 orphan candidate/recovery 等安全有界单元之间、final pre-ID barrier，以及任何 no-commit outcome 最终锁存前消费 latch。Cancellation transition 与下一 gate、candidate 或其他新业务工作的 commitment 必须由同一串行状态转换二选一，禁止 `read false -> start work`；取消先赢后只排空此前已经赢得 commitment 的 in-flight operation 并执行必要 cleanup。独立成立的七项 failed cause 继续按 ADR 0097 获胜；取消请求、响应取消的 stop request 或预期 cancellation completion 本身不能制造 failed。Final pre-ID snapshot 与 ID 的成功生成、验证、锁存也必须是同一转换，取消先赢则绝不安装 ID，预生成 UUID bytes 不算 `answer_id`；ID 先赢则 Answer 生命周期不可逆开始，即使 `started_at` 或 staging 尚未形成也必须尝试提交 interrupted Answer。全部 in-flight 必须按 ADR 0099 settle 并越过 `NoCommitSafeBoundaryV1` 后，最终 no-commit outcome 才在同一仲裁域原子锁存；barrier 内 UUID 生成/验证失败没有获准 V1 cause，不得冒充 `pre_answer_formation_failed`，保持正常矩阵外。

## Handled cancellation window 与 presentation cutover

Parser 成功识别 `knowledge ask`、完成 grammar 并保留 recognized raw values 后，唯一编排器必须在第一项领域 gate/probe 前选择并激活本 invocation 的 cancellation profile。两种 profile 都使用 `OUTSIDE -> ARMED_PASS_THROUGH -> ACCEPTING -> SEALED_PASS_THROUGH -> RELEASED`：`capability_absent` 直接选择 `NoInteractiveCancellationBridgeV1`；`interactive_candidate` 在 capability handle 关闭后先恰好调用一次 `IsDebuggerPresent`，nonzero 同样选择 no-source，zero 才允许随后证明 native registration/control block 与 normalization 并进入 interactive profile。Debugger gate 失败或后续 interactive setup 失败都不能降级。只有 profile-specific activation 已证明并进入 `ACCEPTING` 后，领域工作才可 commitment；profile identity、activation 或 ownership 无法证明时保持正常矩阵外。

Interactive profile 的 `ACCEPTING` callback admission 与 final command-state seal 使用 ADR 0098 的同一串行状态域。Callback 先赢时锁存一次 cancellation，重复 accepted Ctrl+C 不改写 timestamp；该 callback 对本次事件的 accepted/pass-through 决定固定，不能在返回时二次读取 phase 改判。No-source profile 不存在 callback/admission writer，只有唯一主编排线程可以执行逻辑 seal。两种 profile 都只有在领域执行、适用 safe-finalization、result/diagnostic 构造与验证全部完成后，才建立 mode-specific complete candidate；`knowledge.ask --json` 还必须按 ADR 0107 在每个 generation 中一次性形成 `READY_BYTES`，或对 canonical serialization/cap invariant failure 形成 buffer-absent `NO_OUTPUT_PRESENTATION_FAILURE`。单一 seal 转换同时锁存 exact immutable final `outcome/result/diagnostics`、presentation disposition 与完整 payload 并进入 `SEALED_PASS_THROUGH`；interactive callback 先赢则整项 candidate/token 作废并重新仲裁，seal 先赢则晚到 callback 只能 pass-through，不能修改任何领域或 presentation state。

Seal 后必须按所选 profile 证明 accepted-in-flight 为零并完成 source-specific release，才进入 `RELEASED`。Interactive profile 先排空全部在 seal 前已赢得 accepted admission 的 callback，再只撤销 Gezhi 自己的 matching registration；unregister 成功不替代 callback quiescence。No-source profile 的 drain 固定证明为 `source=none && accepted_in_flight=0`，release 固定证明为本 invocation 从未建立 Gezhi-owned registration，不执行 removal call。ADR 0101 已冻结 process-pinned native DLL、C-only handler、generation-checked conditional seal、主线程 Python exported-API adapter 与 matching routine-pointer removal；ADR 0102 已冻结 interactive candidate 的 inherited-ignore normalization，ADR 0103 已冻结只读 `CONIN$`/processed-input candidate gate，ADR 0104 已冻结 no-source lifecycle，ADR 0105 已冻结 debugger-present selection，ADR 0106 已冻结 orchestrator-owned Codex attempt root 的 no-console/no-process-group 与 Job-owned stop，ADR 0107 已冻结 `knowledge.ask --json` 的 exact prepared candidate、65,536-byte inclusive cap 与 same-buffer writer，ADR 0109 已冻结一次 direct binary `setmode` 与 direct blocking `os.write` whole-suffix loop。可能晚执行的 interactive pass-through routine/control block 不得访问 invocation-owned mutable state。JSON 与 Human presentation 都只能在 `RELEASED` 后开始；其中 `knowledge.ask --json` 的 `READY_BYTES` 才允许从 exact buffer 写出，`NO_OUTPUT_PRESENTATION_FAILURE` 恰好写零 bytes 并按 ADR 0108 `os._exit(1)`，Human 不使用该 union/cap 或 ADR 0109 primitive。此后的外部/default Ctrl+C 语义可以终止进程并留下 JSON zero/exact-prefix/full output 或截断 Human presentation，但不能重分类 sealed state、回滚 commit、触发新 cleanup 或由 Gezhi 选择应用级 normal-return `130`。Codex root/Job exit 也不得反向写 cancellation latch 或按数值制造 `interrupted/130`。Profile state、candidate identity、drain、release 或 ownership 无法证明时不发布正常 envelope，也不得伪装成 ADR 0108 failure。

Task Manager、父进程终止、`TerminateProcess`，以及实际由 prior/default/runtime 投递的 Ctrl+C、signal 或 `KeyboardInterrupt` 都不写 cancellation latch，也不得被 top-level `BaseException`/`KeyboardInterrupt` fallback 捕获并翻译成 `blocked`、`failed`、`interrupted`、diagnostic、fallback envelope 或 normal-return `130`；外部退出数值偶合 `130` 仍不是 Gezhi 的应用级 `130`。

`DBG_CONTROL_C` 导致 alertable wait 返回或终止不是 cancellation fact；只能按该具体 operation 已批准的实际 return/completion 规则裁决，不得根据推测的 Ctrl+C/debugger 因果生成 `interrupted`、`130` 或 diagnostic。没有获准分类或无法证明安全收尾时保持正常矩阵外。

## No-commit safe-finalization boundary

ADR 0099 的 command-owned typed live-resource ledger 在每项 operation 赢得 commitment 前先登记，并把随后返回的 handle、ownership、worker、Job、pipe、pending I/O 或 operation-owned callback 绑定到同一 entry；stop/cancel request、timeout、终止 API 返回、单独进程退出或发起 close 都不是 settle。Stop-new-work 后必须取得每项已登记 operation 的权威 completion，join 或静止所有可能继续触碰业务、I/O、root、staging、Job 或 capture 的执行单元，并服从 Codex Job/capture/overlapped-I/O 已有的更强 finalization boundary；cancellation profile 不属于这里要求 join 的 operation-owned callback，由 ADR 0100/0104 的 profile-specific zero-in-flight 与 source release 管理。

编排器在仍持有 writer ownership 时先冻结 no-commit cause、commit/target 结论和最终仲裁所需的本地不可变证据，再按 child-before-parent 与资源类型使用正确 close primitive。取得 mutex ownership 时必须由原编排线程以 depth 一成功 `ReleaseMutex` 后关闭 mutex handle；未取得 ownership 时不得 release，但有效 handle 仍须关闭。Data Root anchor 最后关闭，释放 ownership 后禁止重开或再访问 root/staging。没有 ID 时只证明本次没有建立自己的新 Answer 资源；已经完成的旧 orphan recovery 不回滚。已有 ID 但 no-commit 时必须证明 rename 未成功、target 不是本次 commit、没有 pending/不确定 rename、Answer I/O 已停止且 staging 无 live handle；staging 只在原 `answers/.staging/` 静止保留并被正式 reader 忽略，不移动、删除或修补。

只有 command-owned mutation 静止、live-resource ledger 清零且 commit/target/namespace 后置条件确定，才能锁存最终 no-commit outcome。Cleanup/close/release error 先按 ADR 0095 已有 cause 谓词分类，本身不新增第八项 failed；若仍有独立权威证据证明全部后置条件则保留既有候选。V1 无法证明 `ReleaseMutex`、`CloseHandle`、`FindClose`、pending I/O completion、rename/commit、target identity 或 staging isolation 时一律保持正常矩阵外，不重试或猜测不确定的 release/close，也不承诺同步 Win32 调用能被立即取消。

## No-commit cross-outcome priority

本次新 Answer 的 commit 状态已经确定为 no-commit、全部适用 mandatory operation 已停止且安全收尾成立后，最终 arbiter 对已经验证的候选 facts 固定使用 `failed > interrupted > blocked`。任一七项 closed failed cause 获胜；没有 failed 时，合格 ID 前 cancellation 获胜；两者均不存在时才保留 blocked。只有在有效最终边界前已经合法产生的候选才参加排序；不得为寻找高优先级 cause 而在 stop condition 后启动新 gate。排序不使用线程完成顺序、异常文本或动态时间比较，也不改变 failed/blocked 各自的内部静态表。

`NoCommitSafeBoundaryV1` 成立且 ADR 0100 command-state seal 完成后，晚到 cancellation callback 不得改写。若后来事实证明 commit 状态或安全边界当时并未成立，就不能发布或承认该正常 envelope，而不是保留旧 outcome。Cleanup/close/release API 报错先服从现有 cause binding；报错本身不自行制造 failed cause，只有 ADR 0099 的权威后置条件仍全部成立时才可继续仲裁，否则路径位于正常矩阵外。

## Committed process exit code

已进入 handled `knowledge.ask --json` path、`result` 为 committed receipt、完整合法 envelope 已成功写完且进程沿正常 handled-return 返回时，按 outer outcome 返回：

| outcome | exit code |
|---|---:|
| `succeeded` | `0` |
| `blocked` | `2` |
| `failed` | `1` |
| `interrupted` | `130` |

在这个严格范围内，exit code 与 primary code 和 supplemental diagnostics 数量正交。`130` 是 Gezhi 受控中断写完 committed envelope 后的应用级正常返回值，不是 Windows 外部强杀码，也不是 Codex 子进程的 `attempts[*].exit_code`。`2` 与参数解析可能使用同一数字，但不建立语义归类。

Exit code 不是 commit acknowledgment。Committed `blocked`、`failed` 与 `interrupted` 仍返回非 `null` result object；调用方必须检查包含规范末尾 LF 的完整 envelope。无 committed Answer 的正常 exit 由下一节单独映射；bootstrap、ADR 0115 权威判定超限的 `RawArgvPreflightV1` resource failure、未知参数、进入 handled path 前的失败、envelope/result/diagnostic 构造或 validation、Human write failure、commit 后崩溃、外部强制终止，以及 ADR 0108 排除的 pending/proof/异常路径均不由本表映射，也不得通过 fallback envelope 假装成 `failed`。Resource violation 由 ADR 0116 独立 bootstrap presenter 映射为 fixed stderr/empty stdout/exit `2`；preflight 即使看见 literal `--json` 也不选择 JSON/Human mode，因而不形成 fallback JSON、Human result、diagnostic 或 ADR 0108 presentation state。ADR 0108 只把已成功 seal/release 的 `NO_OUTPUT_PRESENTATION_FAILURE`、binary setup failure 与 completed synchronous invalid-write/I/O/broken-pipe failure 固定为无 cleanup/flush 的 `os._exit(1)`；ADR 0109 将 setup/write 收窄为 direct `msvcrt.setmode`/`os.write` 边界的 `OSError` 或 invalid count，并明确没有 Gezhi-owned/background/overlapped pending write。这不是本表的业务 failed 映射。完整 receipt 成功到达后发生的异常终止或 fail-stop 不撤销 acknowledgment。

## No-commit process exit code

`result=null` 的 no-commit `knowledge.ask --json` 只有在上表 outcome 与对应 primary 完整有效、已通过 ADR 0099 的 `NoCommitSafeBoundaryV1`、envelope 成功写完并沿正常 handled-return 返回时，才使用 `blocked=2`、`failed=1`、`interrupted=130`。该 exit code 不替代 primary，也不说明是否残留静止 staging。`2` 不把参数错误变成 `blocked`；`130` 不代表 Windows 外部强杀或 Codex 子进程 exit。

`RawArgvPreflightV1` resource failure、bootstrap、argument、envelope/result/diagnostic 构造或 validation、Human mode，以及 external termination、pending I/O、seal/release proof failure 和其他 ADR 0108 排除的 presentation failure 继续不在这张表内；它们不得发出另一形状或 fallback JSON。ADR 0110 冻结 pre-Typer seam/职责，ADR 0111 冻结 PASS 后才 lazy-import Typer/Rich/完整 command graph 的强入口顺序，ADR 0113 冻结唯一 argv snapshot、exact feed-through、禁用 Windows expansion 与关闭 shell completion，ADR 0114 冻结 argv0 计量排除，ADR 0115 冻结三个 ceiling、`len(str)` 单位、精确 aggregate 与 inclusive 判定，ADR 0116 冻结 resource violation 的无 payload classification、dimension non-disclosure、fixed fd2/empty fd1 与 normal return `2`，并授权该 production rejection。其余 bootstrap/internal、parser/argument 与 Human presentation/exit 仍待决。只有 ADR 0108 闭合的 serialization/cap no-output 与 completed setup/write failure 独立使用 `os._exit(1)`，也不进入本正常 outcome table。

## Module seam 与待决项

`RawArgvPreflightV1` 是所有 CLI 共用的 pre-command seam，不归 Knowledge module 所有；它消费完整 `argv_snapshot: tuple[str, ...]`，其中各项是 CPython 已解码而 Typer 尚未解释的 string，不是 `sys.orig_argv`、`GetCommandLineW` 或 Windows raw command line。Preflight 自身不产生本合同的 diagnostic、handled result、cancellation state 或持久资产，也不向 stdout/stderr 写入内容；只有收到 ADR 0116 无 payload violation verdict 后，独立的最小 bootstrap presenter 才拥有 fixed fd2 presentation。项目最小 bootstrap/preflight/presenter import closure 同样不得加载 Typer、Rich 或完整 command graph；解释器、site、entry stub 和这些最小项目模块自身的加载/失败位于该强入口保证之前。

Knowledge command adapter 先判定本次新 Answer 是否 committed。Committed manifest mapper 验证 manifest/result/outcome 并通过 ADR 0092 静态表构造 primary。No-commit pre-Answer gate 产生 provisional closed cause；ADR 0098 的 command-owned cancellation state 与 atomic pre-ID barrier 产生 provisional interruption 或不可逆 Answer identity cutover；ADR 0099 的 typed ledger 先证明全部 command-owned mutation 静止并冻结 no-commit 本地证据，cross-outcome arbiter 才按 ADR 0097 的 `failed > interrupted > blocked` 选择最终 outcome/cause，最终锁存为 blocked、failed 或 interrupted 时，各 primary constructor 分别按 ADR 0094、ADR 0095、ADR 0096 一对一绑定 code。Command-owned supplemental aggregator 补入已批准的附属事实；共享 `DiagnosticSetV1` 统一执行 role presence、同码唯一、排序、双 cap 与 omission。ADR 0107 JSON preparation 在 coherent snapshot 上形成完整 envelope 与 `READY_BYTES | NO_OUTPUT_PRESENTATION_FAILURE` disposition；ADR 0100 command-state seal 在同一转换锁存最终 outcome/result/diagnostics、disposition 与 payload 并停止 callback admission。所选 profile 的 zero-in-flight 与 source-specific release proof 成功后，Human renderer 或 JSON writer 才消费 authoritative candidate。只有 `READY_BYTES` 的 exact buffer（包括 LF）按 ADR 0109 由唯一 direct blocking fd `1` writer 完整写出后，normal-return exit adapter 才消费最终 outcome；`NO_OUTPUT_PRESENTATION_FAILURE` 或完成状态确定的 setup/write failure 由 ADR 0108 terminal seam 停止新 write 并恰好一次 `os._exit(1)`，不再返回 Python cleanup/flush 路径。

ADR 0106 的 launch profile、stdio/handle allowlist、Job assignment 与 child exit 都是内部 lifecycle 事实，本身不新增、删除或改写 diagnostic；只有独立满足既有 cause 谓词的进程生命周期失败才能进入已有矩阵。

仍待冻结：

- orphan、capture overflow、maintenance 等 supplemental code/context variants；
- 每个 code 的 Human 中文说明与处理建议；
- Human mode exit code、其余 CLI parser/bootstrap/internal/argument exit，以及 ADR 0108 排除的 JSON failure 与其他 Human presentation failure exit；
- 任何持久诊断资产。
