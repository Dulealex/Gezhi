# Knowledge Answerer v1 合同

本次新 Answer 的 final checkpoint 已通过、Root trust 仍成立且 expected target 不存在时，若 non-replacing same-volume directory rename 返回非 target-conflict 失败，只有随后能够证明 staging 仍未提交、target 不是本次 commit 且全部操作已安全停止，才以 `{"code":"knowledge.ask.answer_commit_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`。禁止自动重试；带完整 terminal manifest 的 staging 原地保留，只能由后续 orphan recovery 独立复验后补交。Target-exists 使用 `answer_target_conflict`，Root trust loss 使用 `data_root_integrity_lost`。无法证明 rename 是否已提交时不得输出本码、`result=null` 或 committed result，路径位于正常矩阵外。

本次新 Answer 的 expected `answers/<answer_id>/` target 在紧邻 rename 的 checkpoint 已存在，或 non-replacing rename 明确报告 target-exists，且 Root trust 仍成立时，必须以 `{"code":"knowledge.ask.answer_target_conflict.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`。禁止覆盖、删除、合并、比较后复用目标或生成替代 `answer_id` 自动重试；即使目标完整有效且内容相同，也不能成为本次 result。本次 staging 原地隔离。历史 orphan 的 candidate-local target conflict 仍只作 supplemental；Root trust loss 使用 `data_root_integrity_lost`，其他 final rename failure 另行分类。

本次新 Answer 已开始形成 terminal `manifest.json` 且 Root trust 仍成立时，若 immutable canonical buffer 或 65,536-byte inclusive cap、direct `CREATE_NEW` 等价 leaf formation、write/completion/close、安全 readback、Schema/canonical byte identity、目录资产闭合或跨资产复验任一步失败，必须使用 `{"code":"knowledge.ask.answer_manifest_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`。Partial、既存或无效 manifest 留在 staging，禁止删除、修补、重写或规范化。该 code 只适用于本次新 Answer；历史 orphan manifest 无效仍只作 supplemental。Manifest formation 前的 non-terminal asset failure 使用 `answer_staging_failed`，Root trust loss 使用 `data_root_integrity_lost`，expected target conflict 与最终 directory rename failure 另行分类。

本次新 `answer_id` 已生成且 Root trust 仍成立时，若 `answers/.staging/<answer_id>/` 无法安全创建，任一 non-terminal asset 无法形成、写完、验证或安装，或 writer-private spool/tail/temp 无法撤销而不能达到封闭 terminal asset set，必须以 `{"code":"knowledge.ask.answer_staging_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`；已有 staging 原地隔离。该 code 不覆盖 terminal `manifest.json`、expected target conflict 或最终 directory rename failure。如果业务/runtime failure 仍能成功提交一个 `status=failed` Answer，则使用 committed primary；若 Root trust 丢失，`data_root_integrity_lost` 优先。

取得 Knowledge Answer writer mutex 后、生成本次新 `answer_id` 前，若 Data Root trust 仍成立，但 cancellation 线性化前已经赢得 commitment 的 enumeration/scan operation 独立证明 `answers/.staging/` 无法安全枚举，或 invocation-wide orphan scan protocol 无法建立/完成，必须立即停止并以 `{"code":"knowledge.ask.orphan_scan_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`；不得启动检索或 Codex。ADR 0098 在安全有界单元之间响应取消而不再启动下一 candidate/recovery，不是 scan protocol failure，预期 cancellation completion 也不得制造本码；无法区分独立失败与取消完成时保持矩阵外。若同一独立事实证明 root trust 已丢失，则 `knowledge.ask.data_root_integrity_lost.v1` 优先。单个 orphan 自身非法、manifest 无效、target conflict 或 candidate-local recovery rename failure 继续只作 supplemental、保留现场并处理下一个 candidate。

Question、Configuration 或 Provenance 的 caller-owned value/facts 已合法后，若 Gezhi 无法在 `answer_id` 生成前机械构造或 canonical-serialize `QuestionEnvelopeV1`、immutable role descriptor audit bytes 或 provenance object，只要能够安全收尾并形成 handled envelope，就必须以 `{"code":"knowledge.ask.pre_answer_formation_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null` 与正常 JSON exit `1`。三个内部构造点不拆码，不披露异常或内部字段；资源耗尽、内部不变量破坏或无法形成诊断时仍可能位于正常矩阵外。

状态：冻结中。`RetrievalViewV1` 的输入边界、最大规模、精确检索算法、文件边界、item 精确字段与 `QuestionEnvelopeV1` 已经冻结；`AnswerOutputV1` 的完整五字段 envelope、Schema 常量、`answer_output.json`、双层 byte budget、确定性渲染边界、双值 `answer_status`、单 Candidate `CitableAnswerUnitV1`、`answer_units`、`qualification_units`、`insufficiency_reason` 及其选择优先级，以及 `answer.md` 的 Source 级引用去重身份、实际使用来源集合、正文首次出现编号、逐单元纯文本 ` [n]` 标记、固定 Candidate-backed 治理披露、来自 `question.json` 的问题回显、`answered` 正文段落结构、条件式 qualification 紧凑列表、`insufficient_evidence` 固定提示、参考文献的 Source 短身份后缀、作者、题名、年份与外部标识符显示映射、链接载体、固定目标基址、标识符验证、percent-encoding、CommonMark destination 表示、链接构造失败终态、answered 参考文献区段与完整条目模板，以及 `PlainTextToCommonMarkV1` 的统一不可信文本 escaping 也已冻结；Knowledge Codex 的独立超时、传输重试、耗尽分类、用户中断、未知进程失败边界与 token 值缺失不直接产生错误的用量审计，所有 Answer 运行终态的同卷原子提交边界，按 Knowledge 数据根隔离的 Windows 单写者边界，无 owner crash staging 的保守恢复策略，根级 `manifest.json` 的封闭资产清单，manifest 不复制语义 `answer_status` 的状态所有权边界，顶层唯一 `status` 运行终态字段，顶层 `error` 的必填存在性矩阵，封闭的 `code` / `stage` error object，四值 `error.stage` 领域阶段，15 项 error code 与唯一 `(status, stage)` 映射，顶层 `answer_id` 与目录身份绑定，Answer 级 UTC 审计时间与单调持续时间，封闭且不含秘密的运行 provenance，manifest-bound `effective_config.json` 安全配置投影，由数组 ordinal 定位的 0–3 项 launch-attempt 容器，每项 attempt 的封闭十字段审计记录，唯一 `turn.completed.usage` 投影、顶层四字段 `usage_totals`、根级业务资产的 P0–P4 封闭阶段前缀与条件式 prompt/Schema、正式结果原子对，以及每个 committed attempt 固定成对的 `events.jsonl` / `final_message.txt` 捕获资产、统一的 `application/octet-stream` media identity、严格 UTF-8 且不修复的语义编码门禁，以及 raw LF 加可选 EOF tail 的 event record framing、限定于已提交正式资产的 capture retention 保证范围，以及逐文件、上界包含的 capture byte cap、overflow exact-prefix retention、cap+1 witness、attempt-scoped Job stop、mechanical drain、最高优先级不可重试 `process_error` 分类、`failed: codex_process_failed` synthesis 顶层映射，以及只从低于 16 MiB 的正式 events 投影 usage 的全局保守门禁也已冻结。Answer terminal manifest 的十一字段封闭顶层 envelope、规范 JSON 字节与严格复验、包含末尾 LF 的 64 KiB raw-byte cap、asset `byte_length` 非负 signed 64-bit 范围、有界 parser profile 与 staging 内 direct exclusive-create leaf formation、Knowledge Answer v1 的 process-level logical commit 与不承诺 power-loss durability 的边界，以及 `knowledge.ask --json` 的共享五字段 outer、四值 invocation outcome、committed-Answer parity 与两字段 `KnowledgeAskResultV1` process-level commit receipt，以及共享两字段 `CliDiagnosticItemV1` 的角色、排序、容量、omission 与隐私 profile，以及 committed Answer 的 15+1 primary union 与完整 committed JSON 正常返回 exit table，以及 no-commit 的 `blocked/failed/interrupted` 分类、`result=null` / `succeeded` 约束与正常 JSON `2/1/130` exit 也已冻结；根级纯文本/Schema 快照的精确 media identity、capture overflow 外部诊断与孤立 staging 的显式维护仍待逐项确认；no-commit blocked 的十一项、failed 的七项与 interrupted 的一项外部 primary 已分别由 ADR 0094、ADR 0095、ADR 0096 闭合，未确认部分不得由实现自行发明。

补充状态：`manifest.json` 的 Python 3.11 规范 JSON 字节、严格解析与 canonical byte round-trip 已由 ADR 0082 冻结，十一字段封闭顶层 envelope 已由 ADR 0083 冻结，包含末尾 LF 的 65,536-byte raw cap 已由 ADR 0084 冻结，`assets[*].byte_length` 的非负 signed 64-bit 范围已由 ADR 0085 冻结，有界 parser profile 已由 ADR 0086 冻结，staging 内 direct exclusive-create leaf formation 已由 ADR 0087 冻结，Knowledge Answer v1 不承诺 power-loss durability 的边界已由 ADR 0088 冻结；`knowledge.ask --json` 的共享五字段 outer、`command` binding、四值 invocation outcome 与 committed-Answer status parity 已由 ADR 0089 冻结，两字段 `KnowledgeAskResultV1` commit receipt 已由 ADR 0090 冻结，共享两字段 `CliDiagnosticItemV1`、角色、排序、容量、omission 与隐私 profile 已由 ADR 0091 冻结，committed Answer 的 15+1 primary union 与完整 committed JSON 正常返回 exit table 已由 ADR 0092 冻结，无 committed Answer 的 outcome/result 分类与正常 JSON exit 已由 ADR 0093 冻结；blocked/failed/interrupted primary、跨 outcome 仲裁、cancellation/identity cutover、no-commit safe-finalization 与 handled cancellation presentation cutover 已由 ADR 0094–ADR 0100 继续闭合。

ADR 0101 已进一步冻结 `WindowsConsoleCancellationBridgeV1` 的项目自有 native DLL、C-only handler、generation-checked conditional seal、accepted-in-flight drain、process-safe lifetime 与主线程 Python adapter。

ADR 0102 已冻结 future interactive profile 在 activation 前对当前 standalone CLI 进程清除 inherited Ctrl+C-ignore，且 release 不恢复未知 prior state。

ADR 0103 已冻结只读 `CONIN$`/`GetConsoleMode` 与 `ENABLE_PROCESSED_INPUT` interactive-candidate 门禁；stdin redirection 和 terminal 品牌不另立分支。

ADR 0104 已冻结 `capability_absent` 时的 `NoInteractiveCancellationBridgeV1`：命令静默继续、没有可接受 source，不加载 native bridge、不产生应用级 `interrupted/130`。

ADR 0105 已冻结 `interactive_candidate` 的一次性 current-process debugger gate：`IsDebuggerPresent` nonzero 时静默复用 no-source，zero 时才进入 native interactive path。

ADR 0106 已冻结 orchestrator-owned Codex attempt root 的 no-console/no-process-group profile、三路 stdio、handle allowlist，以及 suspended root 到 attempt-exclusive Job 的唯一 handoff。

ADR 0107 已冻结 concrete `knowledge.ask --json` 在 conditional seal 前形成的 closed presentation candidate、包含末尾 LF 的 65,536-byte inclusive cap、49,338-byte 保守上界证明，以及 `RELEASED` 后的 same-buffer unbuffered write。

ADR 0108 已冻结该 concrete path 在成功 seal/release 且无 pending I/O 后的 no-output/setup/completed-write presentation failure：不改写业务状态或 diagnostic，静默恰好一次 `os._exit(1)`。

ADR 0109 已冻结该 path 的 exact Windows stdout primitive：唯一 writer 在首次 I/O 前一次 direct binary `setmode`，随后以 direct blocking `os.write` 处理 authoritative buffer 的整个未写 suffix；只在每个直接调用边界捕获 `OSError`，不建立 timeout、第二 buffer 或 background/overlapped completion。

ADR 0110 已冻结所有 one-shot CLI 共用的 `RawArgvPreflightV1` pre-command/pre-Typer seam 与职责：CPython 形成 `sys.argv` 后、Typer 解释任何 token 前，只允许静态 resource-ceiling 机械检查；[ADR 0115](../adr/0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 已冻结三个 inclusive ceilings、`len(str)` 单位、精确 aggregate 与 raw-before-domain 顺序，[ADR 0116](../adr/0116-return-2-with-one-fixed-stderr-line-for-raw-argv-resource-violation.md) 已冻结超限的无 payload verdict、fixed stderr/empty stdout 与 exit `2`。该层不归 Knowledge Answerer 所有，也不构造 JSON/Human handled result、diagnostic、cancellation 或 outcome。

ADR 0111 已冻结强入口 import ordering：最小 project bootstrap 只在 `RawArgvPreflightV1` PASS 后 lazy-import Typer、Rich 与完整 command graph；解释器、site、entry stub 与最小 bootstrap/preflight module 自身仍位于该保证之前。

## 职责

`knowledge_answerer_v1` 只把一个用户问题与 Python 已经冻结的 `RetrievalViewV1` 合成为 Candidate-backed Answer。它不拥有检索、Candidate 状态判断、证据成员资格或引用验收；这些都由确定性 Python 在 Codex 调用前后完成。

相关决策：[ADR 0021](../adr/0021-use-deterministic-sqlite-retrieval-before-codex-synthesis.md)、[ADR 0022](../adr/0022-defer-promotion-and-label-candidate-backed-answers.md)、[ADR 0028](../adr/0028-retry-only-classified-transient-failures.md)、[ADR 0031](../adr/0031-use-a-flat-auditable-knowledge-asset-tree.md)、[ADR 0033](../adr/0033-use-two-isolated-codex-runtime-roles.md)、[ADR 0043](../adr/0043-use-single-turn-self-contained-knowledge-questions-first.md)、[ADR 0044](../adr/0044-separate-semantic-retrieval-view-from-ranking-audit.md)、[ADR 0045](../adr/0045-use-structured-codex-output-and-deterministic-rendering.md)、[ADR 0046](../adr/0046-separate-answer-status-from-operational-terminal-state.md)、[ADR 0047](../adr/0047-bind-each-citable-answer-unit-to-one-candidate.md)、[ADR 0048](../adr/0048-use-only-validated-urls-as-bibliographic-link-targets.md)、[ADR 0049](../adr/0049-escape-untrusted-visible-text-with-one-pass-commonmark-tokens.md)、[ADR 0050](../adr/0050-treat-knowledge-codex-usage-as-non-blocking-audit.md)、[ADR 0051](../adr/0051-atomically-commit-every-terminal-answer-record.md)、[ADR 0052](../adr/0052-serialize-knowledge-answer-writes-with-a-windows-mutex.md)、[ADR 0053](../adr/0053-complete-only-fully-valid-orphaned-answer-commits.md)、[ADR 0054](../adr/0054-use-a-closed-answer-manifest-asset-inventory.md)、[ADR 0071](../adr/0071-use-closed-stage-prefixes-and-atomic-pairs-for-answer-root-assets.md)、[ADR 0072](../adr/0072-use-a-fixed-two-file-capture-for-every-knowledge-attempt.md)、[ADR 0073](../adr/0073-use-octet-stream-for-knowledge-attempt-captures.md)、[ADR 0074](../adr/0074-decode-knowledge-attempt-semantics-as-strict-utf-8.md)、[ADR 0075](../adr/0075-frame-knowledge-events-on-raw-lf-with-an-optional-eof-tail.md)。正式候选结构见 [Candidate Knowledge v1](./candidate-knowledge-v1.md)。

Capture retention 保证范围见 [ADR 0076](../adr/0076-scope-knowledge-capture-retention-to-committed-assets.md)；逐文件 cap 与包含边界见 [ADR 0077](../adr/0077-cap-knowledge-attempt-captures-per-file.md)；overflow 的 exact-prefix retention 见 [ADR 0078](../adr/0078-retain-exact-cap-prefixes-on-knowledge-capture-overflow.md)；overflow witness、Job stop 与 mechanical drain 见 [ADR 0079](../adr/0079-stop-the-knowledge-job-after-confirmed-capture-overflow.md)；overflow 的分类、优先级、不重试与顶层映射见 [ADR 0080](../adr/0080-classify-knowledge-capture-overflow-as-an-unretryable-process-failure.md)；正式 events 的全局 usage 长度门禁见 [ADR 0081](../adr/0081-project-knowledge-usage-only-from-sub-cap-events.md)。

Manifest 自身的规范序列化与 byte-level verification 见 [ADR 0082](../adr/0082-serialize-answer-manifest-as-canonical-json.md)。

Manifest 的十一字段封闭顶层 envelope 见 [ADR 0083](../adr/0083-close-answer-manifest-to-eleven-top-level-fields.md)。

Manifest 包含末尾 LF 的 64 KiB raw-byte cap 见 [ADR 0084](../adr/0084-cap-answer-manifest-at-64-kib.md)。

Manifest asset `byte_length` 的非负 signed 64-bit 范围见 [ADR 0085](../adr/0085-bound-answer-asset-byte-length-to-signed-int64.md)。

Manifest 的结构、节点与数字 parser resource ceilings 见 [ADR 0086](../adr/0086-bound-answer-manifest-parser-resources.md)。

Manifest 在 staging 内的 direct exclusive-create leaf formation 见 [ADR 0087](../adr/0087-directly-exclusive-create-answer-terminal-manifest.md)。

Knowledge Answer v1 的 process-level commit 与不承诺 power-loss durability 的边界见 [ADR 0088](../adr/0088-do-not-promise-power-loss-durability-for-knowledge-answers.md)。

CLI JSON 的共享五字段 outer 与首个 `knowledge.ask` binding 见 [ADR 0089](../adr/0089-use-one-closed-json-envelope-for-cli-results.md) 和 [CLI JSON v1](./cli-json-v1.md)；两字段提交收据见 [ADR 0090](../adr/0090-use-a-two-field-commit-receipt-for-knowledge-ask-results.md) 与 [Knowledge Ask Result v1](./knowledge-ask-result-v1.md)；共享诊断 item 与集合 profile 见 [ADR 0091](../adr/0091-use-two-field-code-discriminated-cli-diagnostics.md) 和 [CLI Diagnostics v1](./cli-diagnostics-v1.md)；committed primary 与正常 JSON exit 见 [ADR 0092](../adr/0092-map-committed-knowledge-ask-outcomes-to-primary-diagnostics-and-exit-codes.md)，no-commit outcome/result 分类与正常 JSON exit 见 [ADR 0093](../adr/0093-classify-uncommitted-knowledge-ask-outcomes-by-terminal-cause.md)，完整 binding 见 [Knowledge Ask Diagnostics v1](./knowledge-ask-diagnostics-v1.md)。

Handled cancellation 的命令窗口、final command-state seal、profile-specific zero-in-flight/source release 与 presentation cutover 见 [ADR 0100](../adr/0100-seal-the-handled-cancellation-window-before-presentation.md)。

具体 native Win32 bridge 见 [ADR 0101](../adr/0101-use-a-project-owned-native-win32-ctrl-c-bridge.md)。

Interactive profile 的 inherited-ignore normalization 见 [ADR 0102](../adr/0102-normalize-inherited-ctrl-c-ignore-before-activation.md)。

只读 console/processed-input capability gate 见 [ADR 0103](../adr/0103-require-a-read-only-conin-processed-input-capability-gate.md)。

Capability-absent no-source cancellation profile 见 [ADR 0104](../adr/0104-continue-with-a-no-source-cancellation-profile-when-capability-is-absent.md)。

Current-process debugger gate 与 debugger-present no-source selection 见 [ADR 0105](../adr/0105-use-the-no-source-profile-when-the-current-process-is-being-debugged.md)。

Orchestrator-owned Codex attempt root 的 console/process-group、stdio/handle 与 Job isolation 见 [ADR 0106](../adr/0106-run-command-owned-children-without-a-console.md)。

`knowledge.ask --json` 的 pre-seal immutable buffer、stdout cap 与 writer 边界见 [ADR 0107](../adr/0107-seal-one-bounded-immutable-knowledge-ask-json-buffer.md)。

`knowledge.ask --json` 的 controlled presentation failure hard fail-stop 见 [ADR 0108](../adr/0108-return-1-for-controlled-knowledge-ask-json-presentation-failure.md)。

`knowledge.ask --json` 的 Windows binary fd `1` setup、blocking whole-suffix writer、support profile 与异常边界见 [ADR 0109](../adr/0109-use-binary-fd1-and-blocking-os-write-for-knowledge-ask-json.md)。

[ADR 0110](../adr/0110-run-a-decoded-argv-resource-preflight-before-typer.md) 冻结 project-wide `RawArgvPreflightV1` seam 与职责；这里的 raw 是完整 `argv_snapshot: tuple[str, ...]` 中各项 CPython 已解码而 Typer 尚未解释的 string，不是 Windows raw command line。计量 domain 与 argv0 排除由 ADR 0114 冻结，具体 ceilings 与计量算法由 [ADR 0115](../adr/0115-cap-raw-argv-at-128-arguments-8192-elements-each-and-16384-total.md) 冻结。

[ADR 0111](../adr/0111-lazy-import-the-cli-framework-and-command-graph-after-argv-preflight.md) 冻结 preflight PASS 后才 lazy-import Typer、Rich、CLI app factory 与完整 command graph 的强入口边界。

## knowledge.ask CLI JSON outer 与 result

`knowledge ask --json` 使用共享 `CliResultEnvelopeV1`，root 恰好包含 `schema_version`、`command`、`outcome`、`result` 与 `diagnostics` 五项必填 key，且 `additionalProperties=false`。`schema_version` 精确为 `gezhi.cli_result.v1`，`command` 精确为 `knowledge.ask`，`outcome` 只能为 `succeeded`、`blocked`、`failed` 或 `interrupted`；`result` 为 object 或 `null`，`diagnostics` 始终为非 `null` array。Outer 不允许 `status`、`ok`、`error`、`warnings`、`data`、`message`、`committed` 或第六个 key。

对于本次 invocation 已经成功执行 Answer 目录 rename 的新 Answer，CLI `outcome` 必须逐值等于 terminal manifest `status`，但它从不复制 semantic `answer_status`。ADR 0092 进一步冻结 committed primary：`succeeded` 无 primary，`blocked/failed` 通过静态十五行表映射 manifest error，`interrupted` 使用 CLI-only `knowledge.ask.user_interrupted.v1`；全部 context 为 `{}`。未提交 staging 中已经锁存或看似完整的 `status` 不是 outcome 权威；启动时补交的旧 orphan Answer 也不是本次新 Answer，其 `status` 不支配本次 outcome。该 parity 不适用于以后只读取历史 Answer 的 `knowledge show`；没有本次新 committed Answer 时固定 `result=null` 且禁止 `succeeded`；Question 领域输入或可恢复前置条件形成 provisional `blocked`，本地 Answer 形成、验证或目录提交失败形成 `failed`，同一 cancellation latch 在原子 pre-ID barrier 先赢并完成安全收尾时形成 provisional interruption；ADR 0097 按 `failed > interrupted > blocked` 选择最终 no-commit outcome，正常 JSON exit 分别为 `1/130/2`。一旦 `answer_id` 已生成并锁存，安全取消必须尝试提交 `status=interrupted` Answer；提交失败属于 no-commit `failed` 或不安全矩阵外路径。ADR 0094、ADR 0095 与 ADR 0096 已分别冻结 no-commit blocked 的 11 项、failed 的 7 项与 interrupted 的 1 项 primary/context，ADR 0097 已冻结 blocked 内部仲裁与跨 outcome 静态优先级，ADR 0098 已冻结 cancellation latch、固定 checkpoints、stop-new-work 与 identity cutover，ADR 0099 已冻结 `NoCommitSafeBoundaryV1` 的完整 settle、typed cleanup 与矩阵外边界。Orphan 等附属 diagnostic 可以与 committed result 并存，但不能覆盖已经确定的 outcome 或回写 manifest。正常发布的 `answer_status=insufficient_evidence` 固定对应 CLI `outcome=succeeded` 与 manifest `status=succeeded`，且不产生 primary。

`KnowledgeAskResultV1` 必须且只能包含 `answer_id` 与 `answer_output`。本次新 Answer 目录 commit 成功时 `result` 为该 object，`answer_id` 与 expected ID、目录及 manifest 身份逐 byte 相等；该 committed result 的 `outcome=succeeded` 时，`answer_output` 是 committed `answer_output.json` 的完整 `gezhi.answer_output.v1` JSON value，其他三个 committed outcome 时为 `null`。没有本次新 committed Answer 时 `result=null`；旧 orphan、历史 Answer 与 staging 身份不能成为本次 result。

完整 outer 按 CLI JSON v1 的 Python 3.11 deterministic serializer 输出为 binary stdout 上唯一 JSON object 加一个 LF；无 BOM、ANSI、raw CR、pretty print、第二个 value 或 Rich/progress 污染，也不是 `codex exec --json` 的 provider JSONL。`result` 已由 ADR 0090 闭合，共享 diagnostic profile 已由 ADR 0091 闭合，committed Answer 的 15+1 primary 与完整 committed JSON 正常 exit 已由 ADR 0092 闭合；无 committed Answer 的 outcome/result 分类与正常 JSON exit 已由 ADR 0093 闭合；no-commit blocked 的 11 项、failed 的 7 项与 interrupted 的 1 项 primary/context 分别由 ADR 0094、ADR 0095 与 ADR 0096 闭合，blocked 内部仲裁、跨 outcome 静态优先级、cancellation/identity cutover 与 no-commit safe-finalization 分别由 ADR 0094、ADR 0097、ADR 0098、ADR 0099 闭合。ADR 0107 又冻结每个 coherent generation 的 pre-seal `READY_BYTES | NO_OUTPUT_PRESENTATION_FAILURE` candidate、65,536-byte inclusive cap 与 same-buffer writer；当前任一合法 envelope 的保守上界为 49,338 bytes。ADR 0108 冻结成功 release、无 pending I/O 的 closed no-output/setup/completed-write failure 为静默 `os._exit(1)`，它不产生新 diagnostic 或业务 outcome。ADR 0109 冻结 direct `msvcrt.setmode(1, os.O_BINARY)`、direct blocking `os.write(1, whole_remaining_view)`、同步 endpoint profile、short-write loop 与 direct-call `OSError` contract；Human 和其他 command 不继承。ADR 0110 冻结所有 CLI 共用、先于 command recognition 的 `RawArgvPreflightV1` seam/职责；ADR 0115 权威判定超限的 preflight resource failure 即使看见 literal `--json` 也不选择 JSON/Human mode，不产生本合同的 result、diagnostic、cancellation、outcome 或 ADR 0108 presentation state。ADR 0111 冻结项目只在该 seam PASS 后 lazy-import Typer、Rich 与完整 command graph。[ADR 0113](../adr/0113-feed-one-immutable-argv-snapshot-to-preflight-and-typer.md) 冻结唯一 immutable argv snapshot、exact feed-through、固定 `prog_name="gezhi"`、禁用 Windows environment/`~`/glob expansion 与关闭 shell completion；[ADR 0114](../adr/0114-exclude-argv-zero-from-raw-argv-resource-measurement.md) 冻结全部资源计量排除 argv0；ADR 0115 冻结三个 inclusive ceilings、`len(str)` 单位、精确 aggregate 与 raw-before-domain 顺序；ADR 0116 让最小 bootstrap presenter 独立尝试 fixed fd2 bytes、保持 fd1 empty 并返回 `2`，不建立本合同 envelope。[CLI Command v1](./cli-command-v1.md) 已冻结不生成 Knowledge outcome/diagnostic 的 controlled `CLI_BOOTSTRAP_FAILED` 与 `CLI_ARGUMENT_FAILED` fixed stderr/empty stdout/exit。Supplemental code/context、Human 中文文案/exit、未被 T02 typed-verdict/grammar table 分类的 internal/entry fault 与 ADR 0108 排除的 presentation failure 仍待后续冻结；不得用任意 dict 或异常文本填补这些未决路径。

## 已冻结的 RetrievalViewV1 边界

Python 只从 Candidate Registry 中 `intake_status=active` 的 Candidate Knowledge 生成一次不可变 Retrieval View。每个问题最多选择 12 条 Candidate；选择与排序必须完全由 SQLite/Python 确定，Codex 不参与召回、过滤、重排或补充检索。零条 Candidate 时直接返回 `insufficient_evidence`，不创建 Codex attempt。

Retrieval View 只携带回答和引用所需的信息：

- 固定的 rank，以及 `candidate_id`、`payload_sha256` 和 Candidate 类型；
- Candidate 的规范陈述、`source_terms`、Evidence Support 与 Review Risk Flag；
- 最小 Work/Source 引用身份和书目信息；
- Reviewed Handoff 中已经校验的短证据摘录及对应 Evidence Pointer；
- Candidate 的 Descriptor Reference，以及回答所需且可按完整 hash 验证的 Descriptor snapshot；
- 当前 intake/review provenance 中回答披露所必需的最小状态。

每个 View item 必须能追溯到一个导入成功且当前 active 的 Candidate；View 在 Codex 调用前写入本次 Answer staging，并以实际字节计算 SHA-256。后续 Registry 状态变化不能改写已经冻结的 View 或既有 Answer。

## RetrievalViewV1 精确结构

顶层 object 必须且只能包含以下字段：

```json
{
  "answer_kind": "candidate_backed",
  "candidate_count": 0,
  "items": [],
  "schema_version": "gezhi.retrieval_view.v1"
}
```

`candidate_count` 是 `0..12` 的 integer，必须等于 `items` 长度。`items` 按 `rank` 升序；rank 从 1 开始、连续且无重复。零匹配时 `candidate_count=0` 且 `items=[]`，`answer_kind` 仍固定为 `candidate_backed`。顶层不得复制 `answer_id`、Question、搜索原子、检索分数、Registry revision 或文件哈希。

每个 item 必须且只能包含以下字段；示意中的空 object 代表下文要求的完整版本化 object，不是合法空值：

```json
{
  "candidate": {},
  "citation": {
    "arxiv_id": null,
    "author_count": null,
    "doi": null,
    "primary_authors": [],
    "source_id": "src_<24 位小写十六进制>",
    "source_sha256": "<64 位小写十六进制>",
    "title": null,
    "work_id": "wrk_<lowercase UUIDv4>",
    "year": null
  },
  "descriptor_snapshots": [],
  "evidence_snapshots": [],
  "governance": {
    "intake_status": "active",
    "promotion_status": "not_promoted",
    "review_status": "accepted"
  },
  "rank": 1
}
```

所有层级 object 都禁止额外字段。`candidate` 是完整且已验证的 `CandidateKnowledgeV1`，不得改成摘要、字段投影或引用；其规范值必须与 Registry 中该 revision 导入的正式 Candidate 完全一致。首个可执行切片禁止 `candidate_type=relevance`。同一 View 内 `candidate_id` 与 `payload_sha256` 都不得重复。

## CitationSnapshotV1

`citation.work_id`、`source_id` 与 `source_sha256` 必须逐项等于 Candidate payload 的同名值。其余字段来自该 Work/Source 的已验证书目身份快照：

- `title` 为原书目标题，缺失时为 null；
- `primary_authors` 按原书目顺序保存最前面的最多 3 位作者，不排序；作者信息完全缺失时为 `[]`；
- `author_count` 在完整作者表可用时保存其非负总人数，并满足 `primary_authors` 恰为前 `min(3, author_count)` 位；作者信息完全缺失时为 null；
- `year` 保存已验证值，缺失时为 null；`doi` 与 `arxiv_id` 必须是 [Literature Reader v1](./literature-reader-v1.md)“DOI 与 arXiv 规范值”所定义的规范裸标识符或 null，并在 View 物化时重新执行同一验证；禁止从正文、文件名或模型输出推断补齐。

View materializer 还必须对非 null `title` 与每个 `primary_authors` item 重新执行 Literature Reader 已冻结的显示安全验证：不得包含除 U+0009 CHARACTER TABULATION 与 U+000A LINE FEED 之外的 Unicode General_Category `Cc`。检查使用快照中的原 code point 序列，不得重新规范化、删除、替换或重映射；任一违规返回既有 `failed: retrieval_materialization_failed`，不创建 Knowledge Codex attempt，也不把字段改成 null 或回退文案。

View 冻结的是当次回答使用的引用快照；后续 Identity Alias 修订不得改写既有 View。书目字段不进入 Candidate 内容身份。

## EvidenceSnapshotV1

`evidence_snapshots` 必须有 1–42 项。物化器先取得 `candidate.payload.statement.evidence_pointers` 与全部 `descriptor_snapshots[*].payload.value.evidence_pointers` 的确定性去重并集，再按 `(canonical_content_sha256 ASCII ASC, block_id UTF-8 bytes ASC)` 排序；数组必须与该并集逐项完全相同，不得缺项、多项或重复。42 来自一条 Candidate statement 最多 6 个 Pointer，加上最多 6 个 Descriptor 各自最多 6 个 Pointer；相同 Pointer 只保留一次。每项必须且只能包含：

```json
{
  "excerpt": "<原语言短摘录>",
  "page_index": null,
  "pointer": {
    "block_id": "<Canonical Evidence Block ID>",
    "canonical_content_sha256": "<64 位小写十六进制>",
    "schema_version": "gezhi.evidence_pointer.v1"
  }
}
```

`pointer` 必须逐字段等于上述并集中的正式 `EvidencePointerV1`；所有 Pointer 的 `canonical_content_sha256` 必须等于 Candidate 顶层的同名值。Candidate statement 或任一 Descriptor payload 通过 Pointer object 相等关系即可定位其 Evidence snapshot，不增加角色标签或第二套映射。`excerpt` 必须是该 Evidence Block 的原语言直接摘录，不得翻译、释义或生成；CRLF 与 CR 先转为 LF，再做 Unicode NFC 与 `str.strip()`，规范化后必须为 1–800 Unicode code point。`page_index` 是与该 block 对应的 0-based 页索引；没有可靠页位置时为 null。View 不携带 bbox、文件路径、Canonical run ID 或完整 block 正文。

1–800 是 Reviewed Handoff 对整个去重并集的供给合同，不是 View 阶段的裁剪预算。materializer 必须验证每个 Candidate statement 与 Descriptor Pointer 都有且只有一个匹配的摘录和页索引，不得在组装 View 时重新截断、换写或补造摘录。

## DescriptorSnapshotV1

`descriptor_snapshots` 必须有 0–6 项，并与 `candidate.payload.descriptor_refs` 构成完全相同、顺序相同且不重复的集合；每项必须且只能包含；示意中的空 `payload` 代表完整 `DescriptorPayloadV1`：

```json
{
  "payload": {},
  "reference": {
    "descriptor_id": "desc_<24 位小写十六进制>",
    "kind": "method|object|dataset|experiment|metric",
    "payload_sha256": "<64 位小写十六进制>",
    "schema_version": "gezhi.descriptor_reference.v1"
  }
}
```

`reference` 必须逐字段等于 Candidate 中对应的 `DescriptorReferenceV1`；`payload` 必须是完整 `DescriptorPayloadV1`，按 CanonicalJsonV1 重新计算的 SHA-256 必须等于 `reference.payload_sha256`，短 ID 与 kind 也必须一致。禁止缺项、多项、模糊匹配、只传名称或只传 Descriptor 引用。

## 自包含、治理与物化失败

每个 item 都是自包含的模型输入单元：完整 Candidate、Citation snapshot、Candidate statement 与全部 Descriptor 证据的去重并集、Descriptor snapshots 与 Governance disclosure 全部嵌套在该 item 内。不同 item 引用了相同 Work、Source、Descriptor 或证据时允许重复保存；首版禁止建立顶层共享 object pool、跨 item 指针或模型可见的外部查找表。单个 item 的 42 条理论上限不扩大文件预算，所有重复内容仍统一受 `retrieval_view.json` 的 262144-byte 总上限约束。

`governance` 三个值固定为 `review_status=accepted`、`intake_status=active`、`promotion_status=not_promoted`。它只披露回答资格，不携带私人审核备注、审核收据、revision、时间戳或操作者身份。

任何一个已选 Candidate、书目身份、Evidence snapshot 或 Descriptor snapshot 缺失、不一致、越界、无法重新验 hash，或 governance 不满足固定三态时，本次 Answer 返回 `failed: retrieval_materialization_failed`，且不得创建 Codex attempt。实现不得丢弃该 Candidate、改排后续 Candidate、缩减已经确定的结果数、改用未验证内容或发布部分 View。

## 已冻结的检索排序原则

可检索文本只由以下四类内容构成：

- Candidate 的规范陈述；
- Candidate 的 `source_terms`；
- 已验证 Descriptor snapshot 的名称与来源术语；
- Work 标题。

短证据摘录不进入 FTS 索引或相关性评分，只在 Candidate 入选后随 Retrieval View 提供给 Codex；Candidate 类型、发表年份、Review Risk Flag 和审核时间也不参与加权。Risk Flag 只负责向 Codex 与用户披露审核风险，不能暗中降权、隐藏或淘汰 Candidate。

`unicode61` 与 `trigram` 是两条独立的 FTS5 召回分支，各自产生稳定 branch rank，再由固定 Reciprocal Rank Fusion（RRF）合并；不得直接混合不可比较的原始 BM25 数值。融合分数降序后以 `candidate_id` 升序作为最终稳定并列规则，取前 12 条。Codex 不参与融合或第二次重排；两路都没有文本匹配时直接返回 `insufficient_evidence`。

## SearchTextV1 与安全查询原子

索引文本和检索问题都先执行相同的基础规范化：

1. CRLF 与 CR 转为 LF；
2. Unicode NFKC；
3. Python 3.11 `str.casefold()`；
4. Unicode control 与 separator 字符转为 ASCII space；
5. 合并连续空白并去除首尾空白。

该规范化只生成可重建的搜索投影，不修改 Candidate、Question 或 Answer 的规范 payload。技术词内部的 `+`、`#`、`.`、`_`、`/`、`-` 可以保留；其他标点只充当分隔符。实现不得把用户原始问题直接交给 FTS `MATCH`，也不得允许用户注入 `AND`、`OR`、`NOT`、列过滤或其他 FTS 语法。

`unicode61` 分支使用 `unicode61 remove_diacritics 2`。索引四个已批准字段时，连续 Han 字符串被确定性替换为去重的重叠二字窗口，其他 Unicode Letter/Number 与受控技术词按规范 token 保存；查询端执行相同拆分。这样 `位姿`、`分割` 等两字中文可由该分支检索。

`trigram` 分支使用 `trigram case_sensitive 0`，索引四个字段的基础规范化原文；查询端把连续 Han 字符串拆为去重的重叠三字窗口，非 Han 技术词只有长度至少 3 个 Unicode code point 时才进入该分支。两字拉丁缩写可以只由 `unicode61` 检索，两字中文可以只由二字窗口检索；某一路因规则没有查询原子时，视为成功返回空集合而不是分支故障。

基础 Unicode/control 与 CR/LF、NFC、`strip()` 规范化先执行，非法或规范化后为空返回 `invalid_question`；随后执行 2000-code-point / 8192-byte 规模门禁，超限返回 `question_too_large`。只有规模合法才检查纯符号或只含一个 Han 字符，命中返回 `invalid_question`；最后才形成查询原子。每一路查询原子按 UTF-8 bytes 去重排序，逐项使用 FTS 双引号字面量规则转义，再以 `OR` 连接并通过 SQL 参数绑定；任一路去重后超过 128 个原子返回 `question_too_complex`，不静默截断。上述任一失败都不查询数据库或调用 Codex。

## 已冻结的 branch rank 与 RRF

四个索引字段的 BM25 权重首版全部为 `1.0`，不通过重复词项制造隐含权重。每一路必须先连接 Candidate Registry 并过滤 `intake_status=active`，再按 `bm25 ASC, candidate_id ASCII ASC` 排序并最多保留 48 条；branch rank 从 1 开始。

Python 对两路结果按 Candidate 合并，使用精确有理数计算：

```text
rrf_score(candidate) =
    Σ 1 / (12 + branch_rank)
```

求和只包含 Candidate 实际出现的分支。Python 必须以整数分数或标准库 `fractions.Fraction` 比较，不能依赖浮点近似决定顺序；按 `rrf_score DESC, candidate_id ASCII ASC` 取前 12 条。每个入选项的两路 branch rank、精确 RRF 值和最终 rank 都必须进入 `retrieval_audit.json`；只有最终 rank 进入 Retrieval View。

启动 `doctor` 必须实际创建并查询 `unicode61 remove_diacritics 2` 与 `trigram case_sensitive 0` 测试表；任一 tokenizer 不可用时 Knowledge 返回 `blocked: fts5_unavailable`，不得降级成单路。运行时任一路执行异常返回 `failed: retrieval_query_failed`，不得用另一支静默兜底；只有两路都成功且最终零匹配时才返回 `insufficient_evidence`。

## QuestionEnvelopeV1

首版只接受以下 object，所有字段必须出现且禁止额外字段：

```json
{
  "question": "<单轮且自包含的问题>",
  "schema_version": "gezhi.question.v1"
}
```

原始 `question` JSON string 必须先拒绝 NUL 与非配对 surrogate，再把 CRLF 和 CR 转为 LF，并执行 Unicode NFC。在调用任何 `strip` 之前，Python 必须拒绝除 U+0009 CHARACTER TABULATION 与 U+000A LINE FEED 外的全部 Unicode General_Category `Cc`；因此 U+000B、U+000C、U+001C–U+001F、C1 或其他非法控制字符即使位于字符串首尾也必须返回 `invalid_question`，不能被后续空白处理吞掉。只有通过该检查后才使用 Python 3.11 `str.strip()` 去除首尾空白；内部换行、空白、标点和大小写保留，Codex 只接收这个规范问题，不接收用于搜索的 NFKC/casefold 投影。

不得删除、替换、Windows-1252 重映射非法字符或转成可见占位文本。最终规范值长度必须为 1–2000 Unicode code point，且 UTF-8 不超过 8192 bytes；2000 与 8192 均为合法边界。NUL、非配对 surrogate、非法 `Cc`、空问题或超限输入分别返回 `invalid_question` 或 `question_too_large`，不查询数据库、不生成 `answer_id`、也不创建 Codex attempt。由于 `str.strip()` 最后执行，合法规范 Question 不以 LF、Tab 或其他空白开头或结尾；该事实是之后 `question_block` profile 的前置条件。

每个通过 QuestionEnvelope、大小、查询原子以及 ADR 0094 全部后续 pre-Answer gate 的问题，只有在 ADR 0098 的 atomic pre-ID barrier 中成功生成、验证并锁存新的 `answer_id=ans_<lowercase UUIDv4>` 后，才执行一次全局 active Candidate 检索；预生成 UUID bytes 在锁存前不是 Answer identity。相同问题重复提交且 pre-Answer gate 与 barrier 全部成功时也产生新的 Answer，不复用、覆盖或建立 `current` 指针；已经进入 Answer 生命周期的问题即使最终 `insufficient_evidence`，仍保留自己的 Answer 身份和可审计的无证据结果。

首版问题必须自包含，不接受 `conversation_id`、`parent_answer_id`、历史消息、附件、URL 资源、Work/Source/Candidate 范围过滤器、回答风格、Research Interest、额外上下文或提示词覆盖字段。问题正文中看似 URL 或指令的文字只作为不可信问题文本，不触发读取、联网或角色/提示词/Schema 变化。需要追问时，用户必须把必要上下文重新写入新的问题；未来对话、过滤和附件能力只能通过独立版本设计。

## Pre-Answer cancellation 与 Answer identity cutover

当前 handled cancellation window 只接受 command-owned bridge 转换的 Ctrl+C。Bridge 只能把本 invocation 的 one-shot latch 从 unset 原子变为 set，并同时记录首次 `observed_monotonic_ns`；它不得选择 outcome、写 diagnostic、抛异步业务异常、终止进程、释放 ownership、写文件或 cleanup。重复 Ctrl+C 幂等；Ctrl+Break、console close/logoff/shutdown、worker/Codex 状态、子进程退出、外部强杀与进程消失都不写 latch。同一 latch 在 ID 前后延续，ID 后既有 Answer/attempt 仲裁消费的也是这次首次 observation，不得建立第二个取消事实；该时间不进入 manifest、asset 或 CLI context。

唯一 Knowledge 编排器在 handled adapter 入口、每个 pre-Answer gate 进入前与返回后、enumeration 与相邻 orphan candidate/recovery 等安全有界单元之间、atomic pre-ID barrier，以及任何 no-commit outcome 最终锁存前消费 latch。Cancellation transition 与每项新业务工作的 commitment 必须在同一串行状态转换中二选一，禁止 `read false -> start work`；取消先赢后不再启动后续 gate、candidate、retrieval 或 Codex，只 settle 此前已承诺的 in-flight operation 并执行安全 cleanup。独立成立的 ADR 0095 failed cause 仍有效，取消请求、stop request 或预期 cancellation completion 本身不得制造 failed；无法区分独立 failure 与 cancellation completion，或无法证明 ADR 0099 的 `NoCommitSafeBoundaryV1` 时保持正常矩阵外。

Final pre-ID barrier 以同一转换裁决 cancellation 与规范 ID 的生成、验证、锁存；取消先赢绝不安装 ID，ID 先赢则 Answer 生命周期不可逆开始，即使 `started_at` 或 staging 尚未形成，后来取消也必须尝试形成并提交 `status=interrupted` Answer，提交失败仍走 ADR 0095 或正常矩阵外。Final no-commit outcome 也只在 ADR 0099 的 `NoCommitSafeBoundaryV1` 成立后于同一仲裁域锁存；首次 monotonic observation 只供 ID 后既有 deadline 规则使用，不能以 wall clock、callback 调度、异常到达或事后时间比较重解释 pre-ID cutover。Barrier 内 UUID 生成/验证失败不属于 `pre_answer_formation_failed`，当前没有获准 V1 cause 时保持矩阵外。

## Handled cancellation window 与 presentation cutover

每次 one-shot CLI invocation 先在 CPython 形成 `sys.argv` 后、Typer 解释任何 token 前经过 project-wide `RawArgvPreflightV1`。它只拥有静态 resource-ceiling 机械检查，不识别 command、literal `--json`、Human、help、version 或 known/unknown token；ADR 0113 已关闭 Typer shell completion，因此没有 environment-owned completion arguments 作为第二套输入。ADR 0115 权威判定超限的 resource failure 位于 Knowledge Answerer 与 handled command window 外，不形成 JSON/Human handled result、diagnostic、cancellation profile/control state、latch 或 outcome；ADR 0116 只由最小 bootstrap presenter 尝试 fixed stderr、保持 stdout empty 并返回 `2`。ADR 0113 要求 bootstrap 恰好一次形成 immutable snapshot，preflight 消费完整 tuple；ADR 0114 又冻结全部资源计量只覆盖 snapshot suffix、完全排除 argv0；ADR 0115 冻结 suffix count `128`、单项 `8192` 个 `str` 元素与 aggregate `16384` 个元素的 inclusive ceilings，并令 raw failure 优先于 normalization 与领域校验。只有 seam 通过，项目才 lazy-import Typer、Rich 与完整 command graph，并把同一 snapshot 的 exact argument suffix 以显式 `args`、固定 `prog_name="gezhi"` 和 `windows_expand_args=False` 交给 parser。随后 parser 才可识别 `knowledge ask`、完成 grammar 并保留 recognized raw values；`HandledCancellationWindowV1` 此后才能建立。所选 cancellation profile 的 control state 初始化与 `ARMED_PASS_THROUGH -> ACCEPTING` 激活必须在第一项 Question、configuration、provenance、Data Root 或其他领域 gate commitment 前证明成功。`capability_absent` 直接选择 no-source；`interactive_candidate` 在 capability handle 关闭后恰好调用一次 `IsDebuggerPresent`，nonzero 选择 no-source，zero 才允许 native registration/control block、normalization 与 interactive activation。Debugger gate/interactive setup 失败不得降级。Parser/argument failure 与激活前 Ctrl+C 不写 ADR 0098 latch；profile identity、activation 或 ownership 无法证明时不得启动领域工作，也不形成正常 envelope。Resource violation 的 classification/presentation/exit 已闭合并可 production 使用；[CLI Command v1](./cli-command-v1.md) 也已闭合 controlled `CLI_BOOTSTRAP_FAILED` 与 `CLI_ARGUMENT_FAILED` receipt。未被 T02 typed-verdict/grammar table 分类的 preflight/internal entry fault 与 activation failure 仍保持各自未决边界。

Interactive profile 的 callback admission 与 final command-state seal 在同一串行状态域竞争。`ACCEPTING` callback 先赢时只锁存一次取消事实和首次 `observed_monotonic_ns`；每次 callback 的 accepted/pass-through 裁决一经取得便保持到返回，不因并发 phase 改变而重解释。No-source profile 没有 callback/admission writer，只有唯一主编排线程执行逻辑 seal。两种 profile 都必须先完成领域执行、适用 safe-finalization、result 与 diagnostic 的构造及验证，才可建立完整 mode-specific pending candidate；`knowledge.ask --json` 又必须按 ADR 0107 把 exact triple 与 `READY_BYTES` 的完整 envelope/exact canonical buffer/byte length，或与 buffer-absent `NO_OUTPUT_PRESENTATION_FAILURE` 一次性绑定给 fresh token。一个 seal 转换共同锁存 exact immutable final `outcome`、`result`、`diagnostics`、presentation disposition 与 payload 并进入 `SEALED_PASS_THROUGH`；interactive callback 先赢时整项 candidate/token 作废并重新消费 latch/仲裁，seal 先赢后到的 callback 不得触碰上述状态、cleanup 或 commit。

Seal 后必须按所选 profile 证明 accepted-in-flight 为零并完成 source-specific release，最后进入 `RELEASED`。Interactive profile 排空 seal 前已赢得 admission 的 callback，再撤销并证明 Gezhi 自身 matching registration 已移除；unregister 成功不等于 callback quiescence。No-source profile 证明 `source=none && accepted_in_flight=0` 以及本 invocation 从未建立 Gezhi-owned registration，不执行 removal call。ADR 0101 已冻结 native interactive path，ADR 0102 已冻结其 inherited-ignore normalization，ADR 0103 已冻结只读 capability gate，ADR 0104 已冻结 no-source lifecycle，ADR 0105 已冻结 debugger-present selection，ADR 0106 已冻结 orchestrator-owned Codex attempt root 的 no-console/no-process-group 与 Job-owned stop，ADR 0107 已冻结 JSON candidate 的 65,536-byte inclusive cap 与 same-buffer writer，ADR 0109 已冻结该 writer 的 direct binary fd `1` setup、blocking whole-suffix loop、endpoint profile 与异常边界。JSON 与 Human presentation 都只能在 `RELEASED` 后开始；其中 `knowledge.ask --json` 的 `READY_BYTES` 只写 authoritative buffer，`NO_OUTPUT_PRESENTATION_FAILURE` 恰好写零 bytes 并按 ADR 0108 `os._exit(1)`，完成状态确定的 setup/write failure 也使用同一 terminal seam；Human 仍服从独立且待冻结的 adapter，不使用该 union、cap 或 ADR 0109 primitive。此后的外部/default Ctrl+C 语义可能令 JSON 输出为零字节、exact buffer prefix 或完整结果，也可能令 Human presentation 被截断；但不得重分类 sealed 状态、回滚 commit、追加 fallback、重算 envelope，或由 Gezhi 选择应用级 normal-return `130`。External termination、pending I/O 与 seal/release proof failure 不被 ADR 0108 改写；Codex root/Job exit 也不得反向写 cancellation latch 或按数值生成 `interrupted/130`。

Task Manager、父进程终止、`TerminateProcess`，以及实际由 prior/default/runtime 投递的 Ctrl+C、signal 或 `KeyboardInterrupt` 都不写 cancellation latch，也不得由 top-level `BaseException`/`KeyboardInterrupt` fallback 捕获后转换为 Answer terminal cause、CLI outcome、diagnostic、fallback envelope 或 normal-return `130`；外部退出数值偶合 `130` 仍不是 Gezhi 应用级 `130`。

`DBG_CONTROL_C` 导致 alertable wait 返回或终止不是 cancellation fact；只能按该具体 operation 已批准的实际 return/completion 规则裁决，不能根据推测的 Ctrl+C/debugger 因果生成 Answer terminal cause、CLI `interrupted`、diagnostic 或 `130`。没有获准分类或无法证明安全收尾时保持正常矩阵外。

## No-commit safe-finalization boundary

`NoCommitSafeBoundaryV1` 使用唯一编排器拥有的 command-owned typed live-resource ledger。每项 gate、orphan candidate/recovery、业务或 I/O operation、worker、collector、monitor、operation-owned callback、子进程、Job、pipe、pending I/O、扫描/文件/目录/mutex/Data Root handle 与 mutex ownership，都必须先登记 commitment 再启动；operation 返回的新资源在同一 entry 中转为 owned。Stop-new-work 后，只有取得权威 completion、执行单元已 join 或静止且不能再触碰本次状态或 namespace，entry 才可 settle；cancel/stop request、timeout、`TerminateJobObject` 返回、进程退出或发起 close 都不够。Codex Job/capture 与 overlapped I/O 继续满足后文更强的 Job 空、pipe EOF、sink 复验、collector/monitor join 与 operation completion 门禁；不承诺阻塞同步调用可被立即或有界取消。Cancellation profile 不属于本 ledger 的 operation-owned callback；它的 profile-specific zero-in-flight、source release 与 presentation cutover 由 ADR 0100 和 ADR 0104 独立证明。

全部 mutation 静止后，编排器在 writer ownership 仍成立时先冻结 no-commit cause、rename/target/commit 结论与之后只在内存仲裁所需的不可变证据，再以 child-before-parent 顺序使用各资源正确的 close primitive。`WAIT_OBJECT_0` 与 `WAIT_ABANDONED` 都表示同一编排线程取得 depth 一 ownership，必须成功 `ReleaseMutex` 一次后关闭 mutex handle；`WAIT_TIMEOUT`、`WAIT_FAILED` 或其他未取得 ownership 的路径不得 release，但有效 mutex handle 仍须关闭。Data Root anchor 在 descendant I/O/handle settle 且 mutex 已释放并关闭后最后关闭；root trust 丢失时不得重遍历不可信 namespace，从 raw path 重开 root 也不是 cleanup proof。Ownership 释放后不再访问 root/staging，后继 writer 的 orphan recovery 不改变当前 invocation 已冻结的 no-commit 事实。

未锁存 ID 时，本 invocation 不得建立自己的 Answer staging、target、asset、Codex Job 或 capture resource；已确定完成的旧 orphan recovery 不回滚，也不是本次 commit。已锁存 ID 但 no-commit 时，必须证明 non-replacing rename 未成功、expected target 不是本 invocation 的 commit、没有 pending 或结果不明的 rename、全部 Answer I/O 已停止且 staging 无 live handle；staging 仅原地静止保留在 `answers/.staging/` 并被正式 reader 忽略，不移动、删除、修补或伪装为 quarantine。持久 staging entry 不是 live-resource ledger entry。

只有 command-owned mutation 静止、live-resource ledger 清零且 commit/target/namespace 后置条件确定，才能锁存最终 no-commit outcome。Cleanup/close/release error 先应用 ADR 0095 已有 cause binding，本身不新增第八项 failed；若独立权威证据仍证明全部后置条件则按现有候选仲裁。`ReleaseMutex`、`CloseHandle`、`FindClose`、pending I/O completion、rename/commit、target identity 或 staging isolation 无法证明时保持正常矩阵外，不重试或猜测不确定的 release/close。

## Question 与搜索投影审计

每个正常进入 FTS/SQL 检索的有效 Answer staging 必须先按封闭前缀依次保存：

- `question.json`：`gezhi.question.v1` 与规范 `question`；
- `retrieval_query.json`：`gezhi.retrieval_query.v1`、SearchTextV1 `normalized_text`、排序后的 `unicode61_atoms` 与 `trigram_atoms`。

`question.json` 完整形成后只推进到 P1，`retrieval_query.json` 完整形成后才推进到 P2；正常开始检索必须已经达到 P2。当前文件形成失败或用户在此前中断时，只允许保留最后一个完整前缀，不能用本节的正常路径要求补造缺失文件。

两个文件都使用 Python 3.11 `json.dumps(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))` 的 UTF-8 bytes，并在文件末尾追加一个 LF；无 BOM，物理换行只使用 LF。Manifest 分别记录实际文件 byte length 与 SHA-256，文件不内嵌自身哈希。Codex 只看到 `question.json` 中的规范问题和之后冻结的 Retrieval View，不看到搜索原子、BM25、SQL 或 Registry。

## Retrieval View 与检索审计文件

正常检索在最终选择形成后必须先生成审计文件；只有语义 View 完整合法且未超预算时，才再生成 View 并推进到 P4。达到 P4 的检索因此拥有两个职责不同的文件；`retrieval_view_too_large` 固定停在只有合法 audit 的 P3：

- `retrieval_view.json`：`gezhi.retrieval_view.v1`，是 Codex 唯一可见的检索语义输入；只保存最终 rank、最多 12 条 Candidate 及回答、引用和候选治理披露必需的内容。
- `retrieval_audit.json`：`gezhi.retrieval_audit.v1`，只供确定性 Python、验收和人工审计；保存算法版本、question/retrieval-query/Registry snapshot 哈希、两路最多 48 条 branch 结果、原始 BM25、branch rank、精确 RRF 分数、最终选择及 Candidate/revision provenance。

Codex 不得读取 `retrieval_audit.json`，`retrieval_view.json` 也不得包含查询原子、原始 BM25、branch rank、RRF、SQL、Registry revision 或未入选 Candidate。最终 rank 属于语义 View，可以提供给 Codex；排名如何产生只属于 audit。

两个文件都使用 Python 3.11 `json.dumps(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))` 的 UTF-8 bytes，并追加一个 LF；无 BOM，物理换行只使用 LF。Manifest 分别记录实际 byte length 与 SHA-256，文件不内嵌自身哈希。`retrieval_view.json` 的实际最终文件大小必须不超过 262144 bytes（256 KiB），262144 合法，262145 即返回 `blocked: retrieval_view_too_large`，不创建 Codex attempt。

超限时禁止截断短证据摘录、删除尾部 Candidate、降低 12 条选择结果、删除 Descriptor、只取摘要、调用第二轮模型压缩、切换模型或以 `retrieval_audit.json` 代替语义 View。有效的 Question、搜索投影、最终选择与超限详情由合法的 `retrieval_audit.json` 保留，并按后文 P3 前缀发布为 blocked 审计目录；would-be View 的超限 bytes 只能留在内存或实现私有临时位置，不得以正式 `retrieval_view.json` 进入 terminal Answer。超限详情在 `RetrievalAuditV1` 中的精确字段仍须单独冻结，未冻结前实现不得自行发明；以后需要更紧凑或更大的 View 时必须创建新角色或 Schema 版本。

零匹配时仍可以生成 `candidate_count=0` 的 View 与完整 audit，用于发布可审计的 `insufficient_evidence` 结果，但不得调用 Codex。

## AnswerOutputV1 表示与渲染边界

每个 Codex attempt 必须只输出一个符合版本化 `AnswerOutputV1` Schema 的 JSON object。JSON 前后不得有解释文字、Markdown code fence、第二个 JSON 值或其他尾随内容；所有层级都执行严格类型、必填字段、枚举、长度和 `additionalProperties=false` 校验。已经冻结的字段与预算必须逐项满足，尚未冻结部分不得由运行时自行添加。

Codex 负责形成回答语义，但没有最终展示格式的控制权。模型生成的每个事实性回答单元正式称为 `CitableAnswerUnitV1`，并且必须显式携带恰好一个 `candidate_id`；该 ID 必须以大小写敏感的完全相等方式属于本次 Retrieval View。不得使用多个 Candidate ID、Descriptor ID、Evidence Pointer、rank、标题文字或模糊名称来替代这一单一 Candidate 引用。文本预算、`answer_units`、`qualification_units` 与 `insufficiency_reason` 已经在下文冻结。

确定性 Python validator 在任何发布或渲染前完成 JSON、Schema、Candidate 成员资格、引用完整性与状态一致性校验。它不得猜测、修补、宽松提取或自动替换模型输出中的无效 JSON、字段或 Candidate ID；校验失败只属于该 Codex attempt，并按后文已冻结的策略禁止自动重试，Answer 终态固定为 `failed: answer_output_invalid`。

只有通过验证的结构化语义结果才能由 Python 确定性生成面向用户的 `answer.md`、引用标记和引用列表。渲染器可以使用 Retrieval View 中已冻结的 Citation snapshot 和稳定顺序，但不得翻译、改写、摘要、扩写或新增事实，不得重新检索、调用第二轮模型或改变 Candidate 归属。
模型生成的字符串以及 Citation snapshot 中来自外部书目的标题、作者和标识符一律视为不可信纯文本。渲染器必须执行冻结的确定性 Markdown escaping/encoding 后才能插入 `answer.md`；这种表示层转义不属于语义改写。任何模型字符串或外部显示字符串都不得被解析为 Markdown、HTML 或 URL；链接目标只能由 Python 从明确允许且已验证的 Citation 字段按固定模板构造。Citation URL allowlist、target、encoding 与 template 已由后文章节冻结；全部不可信可见字段的精确 escaping 由后文 `PlainTextToCommonMarkV1` 唯一冻结。

Codex 不直接生成最终 Markdown、HTML、脚注编号、引用列表、文件路径或任意 URL；这些展示元素只能由 Python 从已验证结构与 Citation snapshot 构造。原始 Codex 输出保留在不可变 attempt 审计资产中，但不是正式 Answer，也不得绕过 validator 直接展示给用户。

## AnswerStatusV1

`AnswerOutputV1` 顶层必须包含：

```json
{
  "answer_status": "answered|insufficient_evidence"
}
```

`answer_status` 是回答语义状态，不是 Codex attempt、Answer run 或 manifest 的运行终态。它只允许两个值：

- `answered`：当前 Retrieval View 足以支持至少一个事实性回答单元；必须至少有一个事实性单元，且每个单元都满足 Candidate 引用合同。
- `insufficient_evidence`：当前 Retrieval View 不足以支持事实性回答；不得包含事实性回答单元、推测性补全或伪装成建议的答案，并必须通过受控 `insufficiency_reason` 枚举说明原因。

零条 Candidate 时，Python 不调用 Codex，而是确定性生成符合最终 Schema 的 `answer_status=insufficient_evidence` 结果。非零 Candidate 时 Codex 可以输出任一合法状态，Python validator 必须验证状态与其余字段的一致性。

存在局限、风险或部分覆盖但仍能形成至少一个合规事实性回答时，使用 `answered` 并通过 `qualification_units` 说明边界；若证据冲突或缺口使任何可靠事实性回答都无法成立，则使用 `insufficient_evidence`。首版不增加 `partial`、`uncertain`、`conflicting` 或相似第三状态。

`failed`、`blocked` 及其具体原因只属于运行与 manifest，绝不是合法 `answer_status`，也不得由模型借助其他字段请求或伪造。一个通过验证并成功发布的 `insufficient_evidence` 是正常语义结果，不是运行失败。

## CitableAnswerUnitV1 单 Candidate 边界

每个可引用回答单元的语义核心必须且只能是：

```json
{
  "candidate_id": "cand_<24 位小写十六进制>",
  "text": "<一个连贯的自然语言回答单元>"
}
```

`candidate_id` 使用单数，并且恰好绑定 Retrieval View 中一个完整 Candidate；禁止 `candidate_ids` 数组、多 Candidate support 列表、第二引用字段或在 `text` 中手写 Candidate ID、脚注号和来源标记。

`text` 按以下规则校验和规范化：

1. 原始 JSON string 禁止 NUL、非配对 surrogate、Unicode general category `Cc`、`Zl` 或 `Zp`；因此 CR、LF、Tab 与其他控制字符都无效，而不是可修复空白；
2. 执行 Unicode NFC；
3. 使用 Python 3.11 `str.strip()` 去除首尾非控制空白；
4. 规范化后必须为 1–400 Unicode code point。

`text` 是单行不可信纯文本，允许自然语言标点，但不得被解释为 Markdown、HTML、URL、脚注或引用控制语法。Prompt 要求一个单元通常使用 1–3 句话表达一个连贯命题；validator 不执行语言相关的句号计数，而以单 Candidate 绑定、单行和 400 字符上限作为机械边界。

一个 Citable Answer 可以按语义阅读顺序包含来自不同来源的多个 Citable Answer Unit，但每个单元中的全部事实性内容都必须由它唯一绑定的 Candidate 支持。模型可以选择、排序和自然表达这些单元，但不得仅因多个 Candidate 同时被检索到，就生成“共同证明”“总体优于”“跨研究一致”等新的跨 Candidate 联合结论；只有某一个已审核 Candidate 自身已经表达该综合结论时，才能由绑定该 Candidate 的单元复述。

Python validator 可以严格证明 ID 格式、View 成员资格和一对一结构，却不能机械证明 `text` 被 Candidate 语义蕴含；因此正式回答仍称为 Candidate-backed Answer，而不是 Verified Fact 或 Entailed Answer。未来若确需跨 Candidate synthesis，必须使用新 Schema 并提供逐分句支持映射，不能放宽本版本的单 Candidate 不变量。

## answer_units 集合与顺序

`AnswerOutputV1` 顶层必须包含 `answer_units` array：

```json
{
  "answer_units": [
    {
      "candidate_id": "cand_<24 位小写十六进制>",
      "text": "<1–400 code point 的单行纯文本>"
    }
  ]
}
```

`answer_status=answered` 时数组必须有 1–12 项；`answer_status=insufficient_evidence` 时必须严格为 `[]`。每项都是完整 `CitableAnswerUnitV1` 且禁止额外字段。每个 `candidate_id` 必须属于本次 Retrieval View，并且在整个 `answer_units` 中只能出现一次；Codex 可以不使用某些已检索 Candidate，不要求覆盖全部 View。

数组位置就是回答的语义阅读顺序。Python 必须原样保留该顺序，不按 Retrieval rank、Candidate ID、来源或引用编号重新排序；Schema 不提供 `rank`、`position`、`unit_id`、`kind` 或其他平行顺序字段。

顶层不提供模型可写的 `title`、`summary`、`conclusion`、`markdown` 或 `html` 字段。超过 12 项、重复 `candidate_id`、无效 `text`、额外字段或状态/数组不一致都会使 Codex attempt 校验失败；Python 不截断、合并、去重、改写或重新排序。

## CitableQualificationUnitV1 与 qualification_units

`AnswerOutputV1` 顶层必须包含 `qualification_units` array。每项是 `CitableQualificationUnitV1`，其结构必须且只能是：

```json
{
  "qualification_units": [
    {
      "candidate_id": "cand_<24 位小写十六进制>",
      "text": "<1–400 code point 的单行纯文本>"
    }
  ]
}
```

`answer_status=answered` 时数组允许 0–4 项；`answer_status=insufficient_evidence` 时必须严格为 `[]`，不得借局限、建议或风险说明字段输出事实性答案。每个 `candidate_id` 必须属于本次 Retrieval View，并且在 `qualification_units` 内只能出现一次；同一 Candidate 可以同时出现在 `answer_units` 与 `qualification_units`，因为一个单元表达回答，另一个单元披露该回答的适用边界。

`text` 完整复用 `CitableAnswerUnitV1` 已冻结的原始控制字符拒绝、NFC、Python 3.11 `str.strip()`、1–400 code point、单行不可信纯文本与 Markdown escaping 边界，不建立第二套规范化或渲染规则。单元中的全部事实性内容必须由其唯一 Candidate 支持。

`qualification_units` 只用于适用范围、证据缺口、审核风险，以及单个 Candidate 自身披露的冲突或不确定边界；不提供 `kind`、自由标题、置信度、无引用说明或多 Candidate support。跨 Candidate 冲突必须拆成分别绑定各 Candidate 的多个 qualification；若冲突使任何可靠回答都不能成立，则使用 `insufficient_evidence`，此数组仍为空。

数组位置就是“局限与边界”部分的语义展示顺序，Python 必须原样保留；只有数组非空时，Python 才生成固定的“局限与边界”标题，并为每项追加确定性引用标记。超过 4 项、重复 Candidate、无效文本、额外字段或状态不一致都会使 attempt 校验失败；Python 不截断、合并、去重、改写或重排。

## insufficiency_reason

`AnswerOutputV1` 顶层必须包含 `insufficiency_reason`：

```json
{
  "insufficiency_reason": null
}
```

`answer_status=answered` 时必须为 null。`answer_status=insufficient_evidence` 时必须且只能是以下四个 string enum 之一：

- `no_matching_candidates`：两路检索成功但 Retrieval View 的 `candidate_count=0`；只能由 Python 在不创建 Codex attempt 的零匹配分支生成。
- `retrieved_candidates_not_responsive`：View 非空，但其中 Candidate 不能回答当前问题，因而无法形成任何合规 Citable Answer Unit。
- `unresolved_evidence_conflict`：View 中存在相关但无法消解的证据冲突，并且冲突使任何可靠 Citable Answer Unit 都不能成立。
- `evidence_support_too_weak`：View 中 Candidate 与问题相关，但证据支持关系或质量不足以形成任何可靠 Citable Answer Unit。

非零 View 且最终为 `insufficient_evidence` 时，Codex 必须按以下顺序选择唯一主因，命中后停止：

1. 如果没有任何 Candidate 实质回应问题，选择 `retrieved_candidates_not_responsive`；
2. 否则，如果至少两个实质相关 Candidate 存在无法消解的冲突，并且该冲突本身足以阻止任何可靠 Citable Answer Unit，选择 `unresolved_evidence_conflict`；
3. 否则，已有实质相关 Candidate 但仍无法形成可靠单元，选择 `evidence_support_too_weak`。

因此，当实质冲突与支持不足同时存在且都足以阻止回答时，`unresolved_evidence_conflict` 优先于 `evidence_support_too_weak`。若仍存在至少一个不受该冲突影响且合规的 Citable Answer Unit，则不得使用不足状态，而应返回 `answered` 并通过 `qualification_units` 披露边界。

非零 View 的 Codex 只能按照上述顺序在后三个 enum 中选择，输出 `no_matching_candidates` 属于状态/输入不一致并使 attempt 校验失败。Python 可以机械验证 enum、null、`candidate_count`、`answer_status`、`answer_units=[]` 与 `qualification_units=[]` 的组合，但不能证明“实质回应”、冲突充分性或支持强度判断正确；这些判断与主因选择属于 Codex 的受控语义职责。

Schema 不提供自由文本不足说明、建议、补充问题或模型自报原因。Python 根据 enum 生成固定中文提示；标题与四个 enum 的精确中文映射已经在下文 `insufficient_evidence` 固定区段中冻结，且不得添加事实性答案。非法组合不得自动改成其他 reason，也不得退化为 `failed` 或 `blocked`。

`failed`、`blocked`、timeout、invalid output 或其他运行原因都不是合法 `insufficiency_reason`。这个字段只解释正常发布的不足证据语义结果，不描述运行失败。

## AnswerOutputV1 完整 envelope 与 answer_output.json

通过验证的 `AnswerOutputV1` 顶层必须且只能包含以下五个字段，并且五个字段在两个合法语义状态下都必须出现：

```json
{
  "answer_status": "insufficient_evidence",
  "answer_units": [],
  "insufficiency_reason": "no_matching_candidates",
  "qualification_units": [],
  "schema_version": "gezhi.answer_output.v1"
}
```

`schema_version` 必须严格等于 `gezhi.answer_output.v1`。其余四个字段必须满足前文已经冻结的类型、长度、枚举、Candidate 成员资格、集合唯一性与跨字段状态规则；所有层级 object 都禁止额外字段。顶层不提供 `answer_id`、Question、`answer_kind`、独立 Citation 列表、文件哈希、模型身份或用量字段；这些身份、运行信息与审计信息由 Python 和 Answer manifest 拥有，模型不得复制或伪造。

非零 Candidate 分支中，Codex final assistant text 的唯一 byte 来源是最后一个正常结束 attempt 的 `attempts/NN/final_message.txt`；不得从 `events.jsonl` 的 agent message、stderr、stdout 的其他解释、模型自然语言或任何临时副本重建、择优或回退。Validator 必须先直接检查该原始捕获 byte sequence 的实际文件长度，不得先解码、修复、剥离 BOM、规范化或重编码后计数：0 bytes 表示没有可供 validation 的 final text；非零捕获不得超过 65536 bytes，65536 合法，65537 及以上即使其中 JSON 语义本可通过也无效。0 bytes 或超限都按既有 `answer_output_invalid` 处理。只有 1–65536 bytes 才进入 ADR 0074 的严格 UTF-8 门禁；leading BOM 或解码失败同样得到 `answer_output_invalid`，且不得回写正常结束 attempt 的 `failure_class=null`。解码得到的完整文本包含 JSON 前后的全部空白，并且必须仅包含一个 JSON object：禁止 Markdown code fence、解释文字、第二个 JSON 值和任何非空白尾随内容。解析器必须在任意 object 层级拒绝重复 key，不得使用“后值覆盖前值”的宽松行为；同时拒绝 JSON 语法之外的 `NaN`、`Infinity`，并拒绝任何 float 数值。

Python 只有在完整完成 JSON、Schema、字符串规范化、Candidate 成员资格和所有跨字段约束校验后，才能把规范值序列化为正式结果文件 `answer_output.json`。规范字节必须精确等于：

```python
json.dumps(
    value,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
).encode("utf-8") + b"\n"
```

文件无 BOM，物理换行只使用 LF；object key 由 `sort_keys=True` 排序，`answer_units` 与 `qualification_units` 的语义顺序保持不变。`answer_output.json` 的实际最终文件大小包含末尾 LF，必须不超过 32768 bytes；32768 合法，32769 使该 attempt 无效。超限时禁止截断、压缩、删除字段或单元、合并单元、重新排序，或把模型重试用作语义压缩手段。

零 Candidate 分支由 Python 直接构造上例所示的合法不足结果，不创建 Codex attempt，因此不适用 65536-byte 原始模型文本上限，但仍必须满足同一 Schema、规范序列化规则和 32768-byte 正式文件上限。Answer manifest 记录 `answer_output.json` 的实际 byte length 与 SHA-256；文件不得内嵌自身哈希。Codex 原始输出只保留在对应 attempt 的固定双文件审计资产中，不是 `answer_output.json`，也不是可发布的正式 Answer。

## 引用去重身份

`answer.md` 中书目引用条目的唯一去重键固定为有序 pair `(source_id, source_sha256)`。两个值都必须来自该回答单元所绑定 Candidate 对应的 `CitationSnapshotV1`，并且已经按前文规则与 Candidate payload 逐字段验证一致；比较使用规范值的大小写敏感完全相等，不做二次规范化、别名解析或模糊匹配。

对每个 `answer_units` 或 `qualification_units` 单元，Python 必须用 `candidate_id` 在本次 Retrieval View 中定位唯一 item，再从该 item 取得上述 Source pair。具有完全相同 pair 的多个单元或多个不同 Candidate 只对应一条书目引用；同一个 Candidate 同时出现在回答与 qualification 中也复用同一条引用。这个去重只合并展示层的书目身份，不合并、删除或改写回答单元、Candidate provenance、Citation snapshot 或 `answer_output.json`。

`candidate_id` 仍是每个 Citable Unit 的唯一语义支持绑定，不能成为书目去重键，否则同一 Source 的多个 Candidate 会制造重复书目。`work_id`、DOI、arXiv ID、标题、作者、年份、渲染后的书目字符串或任意 URL 也不能作为去重键，否则会隐藏同一 Work 的不同 Source/版本，或把缺失、可修订和外部文本错误地当作内容身份。

因此，同一 Work 下 pair 不同的 Source 必须保留为不同书目引用，即使两条引用的显示元数据完全相同；字节不同但视觉上近似的来源也不得自动合并。未来可以另加不改变底层 Source 身份的 Work 级视觉分组，但首版不执行这种分组。

本节只冻结引用条目的身份与等价关系，不决定引用编号的扫描顺序、标记语法、参考文献条目格式、Markdown escaping 或 Citation URL 模板。

## 参考文献集合边界

`answer.md` 的参考文献集合必须且只能是全部 `answer_units` 与 `qualification_units` 实际绑定 Candidate 所映射 Source pair 的并集；并集相等性严格使用前节冻结的 `(source_id, source_sha256)`。每个被任一单元使用的 Source 必须恰好对应一条书目引用，不能遗漏；同一 Source 被多个单元使用时仍只有一条。

仅进入 Retrieval View、但未被任何回答或 qualification 单元选择的 Candidate 及其 Source 不得出现在 `answer.md`。渲染器不得输出“检索到的其他来源”“已考虑材料”或完整 View 书目清单，也不得因为 Work、rank、风险标记或检索分数而把未使用来源加入参考文献。

`answer_status=insufficient_evidence` 时，`answer_units=[]` 且 `qualification_units=[]`，因此参考文献集合严格为空；即使 Retrieval View 非空，也不得生成参考文献标题、空列表或检索来源列表。完整检索输入与排名审计仍分别保存在 `retrieval_view.json` 与 `retrieval_audit.json`，`answer.md` 只表示受到实际 Citable Unit 支持的用户答案，而不是检索报告。

这条集合边界不增加 `AnswerOutputV1` 字段；非空集合的编号与排列由下一节冻结，引用标记和书目文本格式仍不由本节决定。

## 引用编号与参考文献顺序

Python 必须先按数组原始语义顺序扫描全部 `answer_units`，再按数组原始语义顺序扫描全部 `qualification_units`。对每个单元，以其 `candidate_id` 定位唯一 Retrieval View item 并取得已经验证的 `(source_id, source_sha256)`；该 Source pair 第一次出现时获得下一个从 1 开始的正整数编号，后续再次出现时复用原编号。

最终编号必须恰好是 `1..N` 的连续整数，其中 `N` 是前节参考文献集合中的唯一 Source pair 数量；不得出现 0、负数、空号、重复分配或未被单元使用的编号。编号映射不能按 Retrieval rank、Candidate ID、Work ID、Source ID、书目标题、发表年份或其他字段预排序，也不能为了稳定某次以外的编号而改变模型给出的单元语义顺序。

参考文献列表必须按编号升序排列。编号过程只从单元顺序派生，不得重新排列 `answer_units` 或 `qualification_units`；同一 Source 在回答与“局限与边界”中重复出现时，两处使用相同编号。`answer_status=insufficient_evidence` 时参考文献集合为空，因此没有编号，也不生成参考文献区段。

给定同一个已验证 `AnswerOutputV1` 与同一个 Retrieval View，重复渲染必须产生相同编号映射。正文引用标记由下一节冻结；书目条目模板、Markdown escaping 与 Citation URL 模板仍不由本节决定。

## 正文引用标记

每个 `answer_units` 与 `qualification_units` 单元都必须在其最终转义后的文本末尾追加一个引用标记。标记的规范字符序列精确为一个 ASCII space、ASCII `[`、该单元 Source 已分配编号的无前导零十进制表示、ASCII `]`；即：

```text
 [n]
```

编号只能是前节已经分配的 `1..N`，因此合法实例为 ` [1]`、` [2]` 等。渲染器不得在文本与标记之间使用 Tab、NBSP、换行或多个空格，不得把标记移到句内、句首、独立一行或区段标题，也不得为了补标点而修改模型文本；无论单元文本以何种自然语言标点结尾，标记都直接追加在其后。

每个单元必须恰好有一个标记。相邻单元映射到同一 Source、或同一 Source 同时出现在回答与“局限与边界”时，每个单元仍分别追加相同编号的标记；禁止省略重复标记、合并相邻单元、生成编号范围、或在一个单元后追加多个编号。

该标记是 Python 渲染器产生的可信固定文本，不来自 `CitableAnswerUnitV1.text`。模型文本中看似脚注、方括号或引用标记的字符仍按不可信文本执行后文已冻结的 `PlainTextToCommonMarkV1`，不能被识别为正式引用。

` [n]` 只作为普通可见文本：不得写成 Markdown footnote `[^n]`、inline/reference link、HTML、`<sup>`，也不得生成会让 `[n]` 变成链接的 Markdown reference definition。`answer_status=insufficient_evidence` 没有单元，因此没有正文引用标记。本节不决定单元采用段落还是列表、固定区段结构、参考文献条目格式、escaping 算法或 Citation URL 模板。

## Candidate-backed 治理披露

`answer.md` 必须在固定标题 `# 回答` 之后立即输出一个单行 Markdown blockquote，标题与 blockquote 之间恰好隔一个空行；blockquote 与任何后续内容之间也必须恰好隔一个空行，以终止 CommonMark blockquote 并禁止 lazy continuation。标题、首个空行和治理说明的规范文本精确为：

```markdown
# 回答

> 治理说明：本结果为候选知识支持（Candidate-backed）；可用内容仅来自已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
```

该 blockquote 在 `answer_status=answered` 与 `answer_status=insufficient_evidence` 两种正常语义结果中都必须出现且只能出现一次；零 Candidate 分支也不能省略。渲染器不得翻译、改写、缩短、换行、插入动态状态、Candidate 数量、模型名称或其他字段。

这段文字是 Python 根据冻结的 Candidate-backed 治理合同生成的可信固定文案，不来自模型、Question、Citation snapshot 或任一 Candidate，不进入 `AnswerOutputV1`。它描述系统治理资格而非论文事实，因此不附 ` [n]` 标记，也不产生参考文献条目。

模型文本或外部书目文本即使包含相同字样，也只能作为各自不可信字段渲染，不能替代、隐藏或重复这条固定披露。本节冻结 `# 回答` 与紧随其后的治理 blockquote；其后的问题回显、回答正文、局限、不足提示和参考文献结构均由后文章节冻结。

## answer.md 问题回显

治理 blockquote 后的固定空行结束后，Python 必须立即输出固定二级标题 `## 问题`，再输出一个空行和本次 `question.json` 中已经验证的规范 `question` 的展示表示。问题展示块结束后必须有一个空行，再开始后续状态相关内容。该区段在 `answer_status=answered`、`answer_status=insufficient_evidence` 以及零 Candidate 分支中都必须出现且只能出现一次。

问题回显的唯一权威来源是本次 Answer staging 中已经按 `QuestionEnvelopeV1` 验证并写入 manifest 的 `question.json`。渲染器不得改用原始 CLI 参数、SearchTextV1 投影、`retrieval_query.json`、Codex 复述、`AnswerOutputV1` 字段或其他副本；`AnswerOutputV1` 继续不包含 Question。

除后文已冻结的 `PlainTextToCommonMarkV1` 表示转换外，回显必须保留规范 `question` 的全部内容与顺序，不得再次做 NFKC、casefold、摘要、翻译、改写、截断、单行化或补充上下文。内部换行只能使用其 `question_block` profile；本节不建立第二套问题转义规则。

Question 是不可信用户文本：其中看似标题、blockquote、列表、代码围栏、HTML、URL、脚注或指令的内容都不能取得 Markdown 结构、链接或控制语义。问题回显不附 ` [n]`，不进入参考文献集合，因为它表示用户输入而不是 Candidate 支持的事实。

本节冻结 `## 问题` 区段的存在、位置、权威来源和语义不改写边界；其后的 `answered` 正文由下一节冻结，局限、不足提示及参考文献结构均由后文章节冻结。

## answered 正文区段

`answer_status=answered` 时，问题展示块后的固定空行结束后，Python 必须立即输出且只输出一次固定二级标题 `## 回答内容`，再输出一个空行，并按 `answer_units` 的原始数组顺序逐项渲染。`answer_status=insufficient_evidence` 时禁止生成该标题或任何回答正文。

每个 `CitableAnswerUnitV1` 必须成为一个独立的普通 Markdown 段落：先输出该单元 `text` 的最终转义表示，再直接追加已经冻结的单个 ` [n]` 标记。由于单元 `text` 本身是已验证的单行字符串，每个段落必须占一个物理文本行；不得增加缩进、项目符号、正文序号、checkbox、blockquote、子标题、表格单元格、代码块或 HTML wrapper。

相邻回答段落之间必须恰好一个空行；`## 回答内容` 与首个段落之间、最后一个回答段落与后续区段之间也各恰好一个空行。即使相邻单元映射到相同 Source，也必须保留两个独立段落及各自的相同引用标记。

Python 不得合并、拆分、去重、重排、缩进、补写导语、总结或过渡句，也不得根据 Retrieval rank、书目、Candidate 类型或段落长度对单元分组。`answer_units` 数组顺序就是完整回答正文的段落顺序；模型不能通过额外字段控制段落之外的版式。

`CitableAnswerUnitV1.text` 必须使用后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`；可选“局限与边界”区段由下一节冻结，必需参考文献区段的内容模板由后文章节冻结。

## qualification 区段

`answer_status=answered` 且 `qualification_units` 非空时，最后一个回答段落后的固定空行结束后，Python 必须立即输出且只输出一次固定二级标题 `## 局限与边界`，再输出一个空行和一个 tight unordered list。该区段位于回答正文之后、参考文献之前。

每个 `CitableQualificationUnitV1` 必须按数组原始顺序映射为一个单物理行列表项，规范结构是 ASCII hyphen、一个 ASCII space、该单元 `text` 的最终转义表示，以及已经冻结的单个 ` [n]` 标记：

```text
- <escaped qualification text> [n]
```

相邻列表项之间不得插入空行，因而列表保持 tight；最后一个列表项与后续参考文献区段之间恰好一个空行。禁止使用其他 bullet 字符、ordered list、checkbox、嵌套列表、续行段落、子标题、blockquote、表格、代码块或 HTML wrapper。

每个 qualification 都必须保留独立列表项与自己的引用标记；即使相邻项映射到同一 Source，或该 Source 已在回答正文出现，也不得合并、去重或省略标记。Python 不得按 Candidate、Source、风险类型或引用编号重排、分组或补写无引用说明。

`qualification_units=[]` 时整个 `## 局限与边界` 标题和列表都必须省略，回答正文后的固定空行直接分隔随后的参考文献区段。`answer_status=insufficient_evidence` 时该数组按 Schema 必为空，因此同样禁止生成此区段。

`CitableQualificationUnitV1.text` 必须使用后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`；参考文献条目模板由后文章节冻结。

## insufficient_evidence 固定区段

`answer_status=insufficient_evidence` 时，问题展示块后的固定空行结束后，Python 必须立即输出且只输出一次固定二级标题 `## 证据不足`，再输出一个空行和一段由 `insufficiency_reason` 唯一确定的固定中文文案。`answer_status=answered` 时禁止生成该标题或任一不足文案。

| `insufficiency_reason` | 固定中文文案 |
| --- | --- |
| `no_matching_candidates` | 本次检索未找到与该问题匹配、且当前可参与检索的已审核 Candidate Knowledge，因此无法形成候选知识支持的回答。 |
| `retrieved_candidates_not_responsive` | 已检索到 Candidate Knowledge，但其内容不能实质回应该问题，因此无法形成候选知识支持的回答。 |
| `unresolved_evidence_conflict` | 已检索到与问题相关的 Candidate Knowledge，但其中存在尚未消解的证据冲突，因此无法形成可靠的回答单元。 |
| `evidence_support_too_weak` | 已检索到与问题相关的 Candidate Knowledge，但现有证据支持不足，因此无法形成可靠的回答单元。 |

渲染器必须按大小写敏感的 enum 完全相等选择且只选择对应一段，不得显示机器 enum、拼接多项原因、自由改写、翻译、缩短或补充 Candidate 数量、检索详情、模型判断、建议、追问、推测性答案或下一步操作。该文案是 Python 的可信固定文本，不需要执行外部文本 escaping。

不足区段不附 ` [n]`，不生成 `## 回答内容`、`## 局限与边界`、参考文献标题、空参考文献列表或检索来源清单。完整 `insufficiency_reason` 仍保存在 `answer_output.json`，完整检索资产仍保存在 View 与 audit；`answer.md` 只显示面向用户的固定原因文案。

零 Candidate 分支由 Python 使用 `no_matching_candidates` 映射；非零 View 的后三个 reason 使用同一确定性映射。非法或不一致 reason 在渲染前已使结果校验失败，渲染器不得选择默认文案或回退到其他原因。

## 参考文献 Source 身份显示

`answered` 分支的每一条参考文献都必须在条目末尾显示一次且只显示一次对应的短 Source 身份，规范可见字符序列为：

```text
Source：src_<24 位小写十六进制>
```

`Source` 使用上述固定 ASCII 大小写，标签与 ID 之间使用一个全角冒号 U+FF1A，不增加空格、反引号、括号、链接或其他样式。`src_` 后必须是 Citation snapshot 中已经验证的 24 位小写十六进制 `source_id`；该 fragment 是 Python 生成的可信纯文本，不执行外部书目字段 escaping，也不得由模型提供。

Source fragment 必须是该参考文献条目的最后一个可见片段，其后不得追加句号、哈希、路径或其他字段。它与前一书目 fragment 之间固定使用后文完整条目模板定义的一个全角分号 U+FF1B `；`，分号前后不增加空格。

`answer.md` 不显示完整 `source_sha256`、`work_id`、`candidate_id`、Retrieval rank、本地文件路径、裸露可见 URL 或运行标识。URL 只能按本合同冻结的链接载体、固定基址、标识符验证与编码规则构造，并由后文已冻结的完整书目模板插入；不能作为 Source 身份字段、可见 URL 文本或模型提供的内容。可见 label 必须先通过后文 `PlainTextToCommonMarkV1.inline_fragment`，且只有其全部后置条件与 destination byte round-trip 同时成立时才能生成链接。`answer_output.json` 只保留每个单元的 `candidate_id` 绑定，Retrieval View 保存该 Candidate 到完整 `(source_id, source_sha256)` 的映射，Answer manifest 保存相关资产的 byte length、SHA-256 与运行 provenance；本节不向 `AnswerOutputV1` 增加字段。

同一 Work 的不同 Source 即使作者、标题、年份和外部标识符完全相同，也必须形成不同参考文献条目，并由各自不同的 Source ID 在可读结果中区分。Source ID 只用于版本追溯，不替代 DOI、arXiv ID 或之后冻结的书目显示字段。`insufficient_evidence` 没有参考文献，因此不显示 Source fragment。

## 参考文献作者显示

每条参考文献的作者片段必须只由对应 `CitationSnapshotV1.primary_authors` 与 `author_count` 确定。渲染前已经满足前文冻结的不变量：`author_count=null` 时 `primary_authors=[]`；非 null 时为非负整数，且数组恰好是完整作者表的前 `min(3, author_count)` 项。

| 条件 | 规范作者片段 |
| --- | --- |
| `author_count=null` | `作者未知` |
| `author_count=0` | `无署名作者` |
| `author_count=1..3` | 按原书目顺序，用 U+3001 `、` 连接全部 `primary_authors` |
| `author_count>3` | 按原书目顺序，用 U+3001 `、` 连接三项 `primary_authors`，再追加一个 ASCII space 与固定汉字 `等` |

因此，前三位为 `甲`、`乙`、`丙` 且 `author_count>3` 时，片段精确形如 `甲、乙、丙 等`；`author_count=3` 时则是 `甲、乙、丙`，不得追加 `等`。作者数量不作为数字显示，也不生成“et al.”或其他语言变体。

每个作者字符串保持 Citation snapshot 中的原顺序和内容；禁止排序、去重、缩写、扩展 initials、交换姓与名、翻译、转写、大小写修正或从正文推断作者。每个作者字符串先执行后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`，再由 Python 插入可信的 `、` 与可选 ` 等`；固定回退文案不执行外部文本 escaping。

作者片段不是链接，不由模型提供，也不影响 Source 级引用身份、去重或编号；它在条目中的顺序、与年份/题名的连接字符以及与外部标识符和 Source fragment 的分隔规则由后文完整条目模板唯一确定。

## 参考文献题名显示

每条参考文献的题名片段必须只由对应 `CitationSnapshotV1.title` 确定。`title=null` 时使用固定可信回退文案 `题名未知`；`title` 非 null 时，使用 Citation snapshot 中已经验证的完整字符串，并先执行后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`。

除上述表示转换外，Python 必须完整保留非 null 题名，不得翻译、转写、改写大小写、增加或删除标点、执行 title case、从副标题中拆分或合并内容，也不得因为显示长度而截断、增加省略号或生成摘要。固定回退文案不执行外部文本 escaping。

缺失题名时不得从文件名、PDF 正文、Work/Source 路径、DOI、arXiv ID、作者、模型输出或其他字段推断补齐。题名片段不由模型提供，也不影响 Source 级引用身份、去重或编号；题名片段保持纯文本，不成为书目链接。它在条目中的顺序和连接字符由后文完整条目模板唯一确定。

## 参考文献年份显示

每条参考文献的年份片段必须只由对应 `CitationSnapshotV1.year` 确定。非 null `year` 必须已经验证为 1000–9999 的整数，并渲染为对应的四位 ASCII 十进制数字；`year=null` 时使用固定可信回退文案 `年份未知`。渲染器不得使用本地化数字、全角数字、千位分隔符或前后空白。

年份片段本身不添加括号、逗号、句号、ASCII space 或汉字 `年`；这些连接字符只能由之后冻结的完整书目条目模板提供。年份不得改写为日期范围、`online first`、`in press`、`n.d.` 或其他替代表达。

缺失年份时不得从文件名、PDF 正文、DOI、arXiv ID、题名、作者、模型输出、文件时间、系统当前日期或其他字段推断补齐。年份片段不由模型提供，也不影响 Source 级引用身份、去重或编号；年份片段保持纯文本，不成为书目链接。它在条目中的顺序和连接字符由后文完整条目模板唯一确定。

## 参考文献外部标识符显示

每条参考文献的外部标识符片段必须只由对应 `CitationSnapshotV1.doi` 与 `arxiv_id` 确定。非 null `doi` 显示为 `DOI：<doi>`，非 null `arxiv_id` 显示为 `arXiv：<arxiv_id>`；`DOI` 与 `arXiv` 使用上述固定 ASCII 大小写，标签和值之间使用一个全角冒号 U+FF1A，不增加空格。标签由 Python 生成且不执行外部文本 escaping，值使用 Citation snapshot 中已经验证的完整规范字符串，并执行后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`。

当两个字段都非 null 时必须同时显示，固定先 DOI、后 arXiv，并按后文完整条目模板用一个全角分号 U+FF1B `；` 连接，分号前后不增加空格。只有一个字段非 null 时只生成对应片段；两者都为 null 时不生成任何外部标识符片段，不显示 `标识符未知`、空标签、占位符或空链接。

渲染器不得改变标识符值的大小写、增加或删除前缀、移除 arXiv 版本号、缩写、截断、重新规范化或从其他字段推断。可见片段不得添加 `https://doi.org/`、`https://arxiv.org/abs/` 或其他 URL 前缀；本节冻结可见文本与两类标识符的相对顺序，其可点击规则与固定链接目标基址见下节。

DOI 与 arXiv ID 仍是可修订的 Identity Alias，不由模型提供，也不参与 Source 身份、引用去重或编号；即使两个 Source 的外部标识符相同，仍按已经冻结的 Source pair 分别生成参考文献条目。

## 参考文献链接载体与目标基址

只有完整的外部标识符可见片段可以成为 Markdown 链接。最终 inline-link 形状分别是 `[DOI：{escaped_doi}](<{doi_destination_source}>)` 与 `[arXiv：{escaped_arxiv_id}](<{arxiv_destination_source}>)`；这里的 `{...}` 是合同元变量而不是输出字符，目标外的一对 ASCII `<`、`>` 是最终 CommonMark link destination 语法。`*_destination_source` 是下一节从已验证 target URI 派生的 Markdown source representation，不一定与 target URI 的字面字符序列相同；可见值必须使用后文已冻结的 `PlainTextToCommonMarkV1.inline_fragment`。

链接的 scheme 必须是小写 ASCII `https`，authority 必须分别是小写 ASCII `doi.org` 或 `arxiv.org`，不得包含 userinfo、显式端口、query 或 fragment，也不得由 Citation snapshot、模型、Question、配置或环境变量提供其他 URL、host、scheme 或 path base。固定 scheme、authority 与 path base 由 Python 可信代码逐字生成。

当 DOI 与 arXiv 同时存在时，两个外部标识符片段各自生成独立链接，不选择优先目标，也不把题名链接到其中之一。作者、题名、年份与 `Source：src_<24 位小写十六进制>` 始终保持纯文本；Source fragment 仍是参考文献条目的最后一个可见片段。

Python 构造链接时不得发起网络请求、跟随或解析重定向、查询 DNS、探测页面状态、检查目标内容或根据可达性切换目标。下一节冻结标识符复验、URL byte encoding、CommonMark destination 与失败终态，再后节冻结完整参考文献模板，随后由 `PlainTextToCommonMarkV1` 冻结可见 label escaping；只有全部规则与后置条件同时成立时渲染器才能生成链接。

## 链接标识符验证、编码与失败

Retrieval View 物化器必须对每个非 null `citation.doi` 与 `citation.arxiv_id` 重复执行 Literature Reader v1 的完整规范值验证，不能只相信上游标签。任一值不合格都返回既有 `failed: retrieval_materialization_failed`，不创建 Knowledge Codex attempt，不把非法值改为 null，也不删除对应 Candidate。`null` 仍是正常缺失值，不创建片段或链接。

DOI URL path 按 DOI Handbook 的 UTF-8 byte 算法生成。Python 在首个 `/` 处分出 prefix 与 suffix，分别按原 code point 序列编码为 UTF-8 bytes，不加 BOM、不做任何 Unicode normalization；对每个 byte，只有下列 ASCII byte 原样输出：

`ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~!$&'()*+;=:@`

其余每个 byte 都编码为一个 ASCII `%` 加两位大写十六进制 `%HH`；不得识别或保留输入中的既有 `%HH`。编码后的 prefix 与 suffix 用且只用一个字面 ASCII `/` 连接，因此 suffix 内的每个 `/` 都成为 `%2F`，`%`、`#`、`?` 分别至少成为 `%25`、`%23`、`%3F`。最终 target bytes 是固定 `https://doi.org/` 后接该路径。

arXiv ID 先按已冻结的 modern 或 legacy 完整语法验证。除 legacy 形式中 archive 与七位编号之间唯一的语法分隔符 `/` 外，其余允许字符均为 ASCII unreserved；modern ID 作为一个 path segment 原样追加，legacy ID 只保留该 `/` 作为 path delimiter，其余内容逐字追加。最终 target URI 是固定 `https://arxiv.org/abs/` 后接该路径；不得添加、删除或改写 `vN`。

两个已构造的 target URI 都必须是纯 ASCII。Python 必须先对未进入 Markdown 的 target URI 重新断言 scheme、authority、path base 与前节完全相同，且没有 userinfo、显式 port、query、fragment、反斜杠、CR、LF 或未经 `%HH` 表示的非 ASCII byte；link label 与 target URI 分开构造，label 中的任何字符都不能进入 URI 结构位置。

随后单独生成 CommonMark destination source representation：把 target URI 中每个字面 U+0026 `&` 替换为恰好五个 ASCII 字符 `&amp;`，除此之外不得改变任何 target byte，再以一对字面 ASCII `<`、`>` 包裹。这样 DOI 官方 byte encoder 仍保留合法 `&`，但 CommonMark 不会把后续 `quest;`、`num;`、`sol;`、`bsol;` 或 `amp;` 解释成改变 URI 结构的字符引用。

实现必须验证 CommonMark 对该 source representation 执行一次且仅一次字符引用解析后，得到的 destination URI 与原 target URI byte-for-byte 完全相同，并再次执行相同 URI postcondition。例：target 中的 `x&quest;y` 必须写成 destination source `x&amp;quest;y`，解析结果仍是字面 `x&quest;y`，绝不能变成 `x?y`。任何不等、未防护的字面 `&`、额外字符引用或递归解码都属于链接构造失败。

对已通过 View 复验的标识符，若 UTF-8 编码、byte encoder、target postcondition 或 Markdown destination 构造出现异常，Answer 返回稳定终态 `failed: citation_link_construction_failed`。不得发布部分 `answer.md` 或任何成功 Answer 结果，不得仅省略构造失败的标识符链接、把链接降级成纯文本、切换 DOI/arXiv 目标、修改标识符或重试 Codex；已经产生的 Codex attempt 与失败诊断保留在 staging，并按后文已冻结的 Answer 原子提交边界发布为不含正式结果的 failed 审计目录。

## answered 参考文献区段与完整条目模板

`answered` 分支必须把已经冻结的非空参考文献集合渲染为 `answer.md` 的最后一个区段；`qualification_units` 非空时放在 `## 局限与边界` 之后，否则直接放在 `## 回答内容` 之后。前一区段与标题之间恰好一个空行，标题固定为 `## 参考文献`，标题与首个列表项之间恰好一个空行。`insufficient_evidence` 继续完全省略本区段。

参考文献使用 tight Markdown ordered list，按已经冻结的编号升序逐项输出；每项恰好一个物理行，项间没有空行。列表 marker 必须是该项无前导零十进制编号、一个 ASCII `.` 和一个 ASCII space，即 `{n}. `；不得全部写成 `1.`、使用自动编号、括号编号、无序列表或 HTML list。

每个列表项先构造有序 fragment 数组：

1. 必有的首 fragment：`{author}（{year}）：{title}`；
2. `doi` 非 null 时追加完整 DOI link fragment，否则不追加；
3. `arxiv_id` 非 null 时追加完整 arXiv link fragment，否则不追加；
4. 必有且最后的 `Source：src_<24 位小写十六进制>`。

Python 使用且只使用一个全角分号 U+FF1B `；` 连接相邻 fragment，分号前后不增加空格。首 fragment 内作者与年份之间使用全角左/右括号 U+FF08 `（`、U+FF09 `）`，右括号后立即使用一个全角冒号 U+FF1A `：` 再接题名；这些连接字符都是 Python 生成的可信文本，不执行外部文本 escaping。

因此，两个外部标识符都存在时，规范形状是：

`{n}. {author}（{year}）：{title}；{doi_link}；{arxiv_link}；Source：src_<24hex>`

两者都缺失时，规范形状是：

`{n}. {author}（{year}）：{title}；Source：src_<24hex>`

可选 fragment 的省略必须发生在 join 之前，所以不得产生连续 `；；`、悬空分号、空 link、占位符或为缺失标识符保留位置。作者、题名与年份使用前文冻结的回退值，因此同时未知时可精确形成 `作者未知（年份未知）：题名未知；Source：src_<24hex>`。

条目不得增加期刊名、会议名、卷期、页码、出版社、出版地、类型标签、访问日期、文件名或任何 Citation snapshot 不拥有的字段，也不得从模型、正文或 URL 推断这些字段。Source fragment 后不得有句号、空格、HTML comment 或其他可见/不可见条目内容；最后一条列表项之后只保留 `answer.md` 的一个最终 LF，不增加空白行。

作者、题名、年份与 Source fragment 始终是纯文本；只有 DOI/arXiv fragment 可以按前文规则成为链接。所有不可信可见文本在进入本模板前必须先通过后文已冻结的 `PlainTextToCommonMarkV1`；其 profile、可信 token 边界和后置条件全部成立后，本完整模板才可执行。

## PlainTextToCommonMarkV1

`PlainTextToCommonMarkV1` 是 `answer.md` 中所有不可信可见文本唯一允许使用的表示层转换，兼容性基准固定为 CommonMark 0.31.2。它必须由确定性 Python 标准库代码实现；生产运行时不依赖 Markdown parser，也不调用 Codex、网络、模板过滤器或第三方转义包。CommonMark 官方参考实现可以作为验收测试 oracle，但不得成为发布路径中的动态修复器。

转换只有两个固定 profile，调用方、模型、Question、Citation 或配置都不能选择或改写 profile：

| profile | 固定输入字段 | LF 的规范载体 |
| --- | --- | --- |
| `question_block` | `QuestionEnvelopeV1.question` | 一个可信 U+005C 反斜杠后立即跟一个物理 LF，形成 CommonMark hard line break |
| `inline_fragment` | `CitableAnswerUnitV1.text`、`CitableQualificationUnitV1.text`、每个非回退作者字符串、非 null 题名、非 null DOI 与 arXiv 可见值 | 十进制字符引用 `&#10;`，不得产生物理 CR 或 LF |

固定标题、治理说明、不足文案、作者/题名回退文案、年份、`、`、` 等`、全角括号与分隔符、列表 marker、` [n]`、`DOI：`、`arXiv：`、`Source：src_<24hex>`、Markdown link wrapper 以及已经冻结的 destination source representation 都是 Python 拥有的可信 token，不是本转换的输入。渲染器必须先分别转换不可信字段，再把结果插入可信容器；禁止对已组装 fragment、链接、列表项、区段或整个 `answer.md` 再运行本转换。

### 输入前置条件

每个字段必须先完成其权威合同已经冻结的规范化与校验。Question 不含 NUL、非配对 surrogate 或除 Tab/LF 外的 `Cc`，且因 `str.strip()` 不以任何空白开头或结尾；Answer 与 qualification `text` 已经拒绝全部 `Cc`、`Zl`、`Zp` 并成为单行；Citation 作者与题名不含 NUL、非配对 surrogate 或除 Tab/LF 外的 `Cc`；DOI 与 arXiv 已满足各自更严格的标识符语法。渲染器不得借 escaping 接受、修复或隐藏不符合这些前置条件的值。

Question 的非法控制字符按前文返回 `invalid_question`；Reader metadata 作者或题名中的非法控制字符返回 `failed: reader_input_invalid`；Citation snapshot 防御性复验失败返回 `failed: retrieval_materialization_failed`。这些分支都发生在对应 Codex 调用前，不得把非法字符删除、替换、重映射为 Windows-1252 字符、改成 `\uNNNN` 可见文本或降级为回退文案。

### 单遍 token 转换

Python 必须按输入 Unicode scalar 从左到右恰好扫描一次，并直接追加输出 token。优先级与规范输出如下；一旦某项命中就处理下一个输入 scalar：

1. 输入为 U+000A LF 时，`question_block` 输出一个可信 U+005C 后紧跟一个物理 LF；`inline_fragment` 输出恰好五个 ASCII 字符 `&#10;`。
2. 输入 U+0020 SPACE 位于该字段输入开头的最大连续 Space/Tab run 时，输出恰好五个 ASCII 字符 `&#32;`。`question_block` 在每个输入 LF 后重新进入行首 run；`inline_fragment` 只在字段输入开头进入一次。run 状态必须按输入 scalar 推进，所以已经输出为 `&#9;` 的 Tab 仍属于同一个前导 run。
3. 输入为 U+0009 CHARACTER TABULATION 时，无论位置都输出恰好四个 ASCII 字符 `&#9;`。
4. 输入为 U+2028 LINE SEPARATOR 或 U+2029 PARAGRAPH SEPARATOR 时，分别输出 `&#8232;` 或 `&#8233;`。
5. 输入属于 ASCII punctuation 范围 U+0021–U+002F、U+003A–U+0040、U+005B–U+0060 或 U+007B–U+007E 时，输出一个 U+005C 后跟原输入字符。该集合精确为：

```text
!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~
```

6. 其余输入 scalar 原样输出，不做 NFC/NFKC、casefold、trim、空白折叠、翻译、转写或标点改写。

算法处理的是输入 scalar，不是已经生成的 source token。由步骤 1–4 生成的反斜杠或字符引用不得再次进入步骤 5，也不得在组装后递归 escaping。输入中的 U+005C 仍属于步骤 5，因此必须输出两个连续反斜杠；输入 `&quest;` 的 source representation 精确为 `\&quest\;`，CommonMark 只解析一次后仍是字面 `&quest;`，绝不能变成 `?`。

对 `question_block`，每个输入 LF 的可信反斜杠必须是对应物理行的最后一个 source 字符；输入行尾空格位于它之前，因此不能自行控制 hard break。连续两个输入 LF 必须形成两次 hard break，中间物理行只包含可信反斜杠而不是空白行，所以整个 Question 仍是一个 paragraph。对 `inline_fragment`，输入 LF 只能成为 `&#10;`，从而作者、题名与其他字段无论包含何种合法换行都不能破坏参考文献“一项一个物理行”的合同。

所有 profile 都保护字段开头的 Space/Tab run。这个规则即使字段被插入可信列表 marker 后仍必须执行：例如作者字段以四个 Space 开头时，输出必须以四个连续 `&#32;` 开头，不能把原始空格交给 CommonMark 当作 ordered-list padding 或 indented code。非前导 U+0020 保持原样，以维持正常 Markdown source 的可读性。

### 验收后置条件

实现必须至少包含以下精确测试向量；右侧是字段自身的 source representation，不包含外层可信模板：

| profile 与规范输入 | 规范 source representation |
| --- | --- |
| 任一 profile：`# 标题` | `\# 标题` |
| 任一 profile：`&quest;` | `\&quest\;` |
| 任一 profile：`[x](y)` | `\[x\]\(y\)` |
| 任一 profile：四个前导 Space 后接 `# x` | `&#32;&#32;&#32;&#32;\# x` |
| `inline_fragment`：`甲`、LF、`乙` | `甲&#10;乙` |

`question_block` 的 `甲`、LF、`乙` 必须生成以下两个物理 source 行，其中第一行末尾的反斜杠是可信 hard-break token：

```text
甲\
乙
```

在 CommonMark 0.31.2 单次解析语义下，`question_block` 必须只形成一个 paragraph；每个规范 Question LF 一一对应一个 hard line break，把 text 与 hard-break 节点反投影后必须逐 scalar 等于原规范 Question。`inline_fragment` 在其冻结容器内只能贡献原字段的 text；当它位于 DOI/arXiv link label 时，唯一 link 必须仍由可信 wrapper 创建，字段不能关闭 label、增加第二链接或改变 destination。

任一不可信字段都不得产生 heading、blockquote、list、thematic break、indented/fenced code、code span、raw HTML、autolink、image、emphasis、reference definition、table、task item、strikethrough 或其他结构节点。合同只承诺 CommonMark 0.31.2；正式 GFM 扩展的常见结构标点也会被步骤 5 中和，但不得据此承诺任意第三方或未来 Markdown 的二次处理。

整个发布链只能执行一次 CommonMark/entity interpretation。禁止先解析 field、再序列化并解析整份文档，禁止 HTML entity decode 后再次送入 Markdown，也禁止浏览器端或后处理器递归解码。任何实现若不能满足精确 token 映射、可信容器边界或上述后置条件，都不得发布部分 `answer.md`，不得回退到 raw text、HTML、code block、删除字符或省略链接；除前文已经单列的 `citation_link_construction_failed` 外，确定性 renderer 失败终态固定为 `failed: answer_rendering_failed`。

## 明确排除

`knowledge_answerer_v1` 不得看到或访问：

- `registry.sqlite3`、SQL、FTS 索引或任何数据库连接；
- PDF、Canonical Reading Asset、完整 Reading Result 或 Literature 私有资产；
- 未进入本次 View 的 Candidate；
- rejected、deferred、pending 或 withdrawn Candidate；
- 私人审核备注、内部冲突调查记录或不属于回答披露范围的治理信息；
- 检索工具、文件搜索、网络搜索、模型自主扩展上下文或第二轮模型重排。

最多 12 条、上述检索算法、单轮 Question Envelope 和 View/Audit 文件边界都是 `knowledge_answerer_v1` 的版本化语义限制。以后可以通过新角色或 Schema 版本调整，不迁移或改写既有 Retrieval View 与 Answer。

## Knowledge Codex 超时与传输重试

`knowledge_answerer_v1` 拥有独立于 `literature_reader_v1` 的 runtime 配置；首版有意使用相同的超时、退避和耗尽分类数值，但不得让两个角色读取同一个可变配置键或因一方调整而隐式改变另一方。以后调整 Knowledge 数值必须产生新的版本化有效配置并由新运行记录，不迁移或改写既有 Answer。

零 Candidate 分支由 Python 直接构造已经冻结的 `insufficient_evidence`，不创建 Codex attempt，因此本节不适用。非零 Retrieval View 才能进入 Knowledge Codex attempt window；window 使用单调时钟，从第一次 Codex 子进程成功启动时开始，只管理 synthesis 的进程运行、provider 捕获、失败分类与 retry backoff。它在运行序列确定结束时关闭：进程/provider 正常完成并准备把 final text 交给 validation；不可重试失败或瞬时耗尽已经分类；或者 deadline 在 backoff 或下一次 launch commitment 前到达。后续 Answer validation 与 rendering 均不属于该 window。

每个 Codex attempt 的 wall-clock 超时固定为 30 分钟，从该 attempt 子进程成功启动时计算固定 monotonic deadline，到进程完全退出、最终 provider 输出捕获关闭且 attempt classification-ready 为止。Deadline 先到时只锁存 timeout terminal signal，必须停止整个 Codex 子进程树并保留已经产生的事件；即使此前出现看似完整的 final JSON，输出也不得验证、复用或发布。对于没有观察到 capture overflow 的 attempt，final `failure_class` 仍由下文两阶段裁决唯一确定：更早或同刻的用户取消可以得到 `interrupted`，生命周期完整性失败得到最高优先级 `process_error`，其余 deadline 分支才得到 `timeout`。若在 capture-finalization boundary 前已经或随后锁存任一 overflow，则不比较这些 signal 的时间先后，安全门通过后固定为不可重试的 `process_error` 并结束整个 attempt window。下一个 attempt 只有在前一进程树确认终止、collectors 关闭、item 冻结且 Answer 尚未锁存顶层终因后才能启动；overflow item 之后永不允许下一次 commitment。

首次调用失败后，只允许以下四类明确瞬时故障触发自动重试：

- provider transport 网络中断；
- 明确的 HTTP 429 rate limit；
- 明确的 provider HTTP 5xx server error；
- 上述 30 分钟 wall-clock timeout。

分类必须来自 Codex 事件、transport/HTTP 状态或 Python 自己的 timeout watchdog；未知非零退出、空事件、无法分类的 stderr 文本或模型自然语言不得猜成网络或 server error。第一次瞬时失败后固定等待 10 秒，第二次瞬时失败后固定等待 30 秒；最多重试两次，因此同一 Answer 最多创建 3 个 Knowledge Codex attempt。进程/provider 捕获正常结束并把可选 final text 交给 validation 时，synthesis launch 序列立即停止且关闭 attempt window，不创建多余 attempt；后续 validation 失败不得重新打开 window 或触发重试。

每次 attempt 必须启动全新 Codex 进程、ephemeral session 与独立临时目录，并使用 byte-for-byte 完全相同且已哈希的 `question.json`、`retrieval_view.json`、`prompt.txt` 与 `schema.json`，以及相同的角色版本、模型、reasoning、锁定 Codex CLI 和有效 runtime 配置。任何 attempt 的事件、partial output、final message、会话状态、临时文件或模型建议都不得进入下一次 attempt；禁止用后续 prompt 要求“修复上一份 JSON”，也禁止切换模型、reasoning、provider、Ollama 或输入内容。

从第一次进程成功启动开始，整个 attempt window 共享一个固定的 95-minute monotonic deadline，跨越最多三个实际 attempt、10 秒与 30 秒退避、进程树终止、provider 捕获和失败分类。Deadline 在活跃 attempt 的进程启动调用、进程/provider 捕获或 attempt 分类尚未全部完成时到达，就为该真实 item 锁存 timeout terminal signal：必须立即停止仍存活的进程树并停止等待更多 provider 语义输出；若进程启动调用仍未返回，则在取得 handle 后不得让新进程继续执行，并立即进入终止收尾。为确认进程树终止、关闭 collectors、保留已捕获 bytes 并形成审计 item 所必需的 mechanical drain 仍须读到 pipe EOF；这些动作可以在 deadline 触发后结束，但不是继续模型执行或接受语义输出，也不得进入 validation 或启动额外重试。Deadline 在 backoff 或下一次 commitment 前到达时不创建新 item，并与该阶段已观察到的用户取消按下文 Answer 级锁存规则裁决。正常路径通常早于上限结束；95 分钟不是必须等待时长、单个 attempt 的宽限期，也不是 validation/rendering deadline。该 timeout signal 只有通过下文两阶段裁决后才成为 final `failure_class=timeout`；任一 capacity overflow 并存时由 ADR 0080 的 `process_error` 胜出并禁止重试。

当重试序列因三次机会用尽或 95-minute deadline 结束时，如果全部实际创建的 attempt 都以同一种瞬时故障失败，分别返回：

- timeout：`blocked: codex_timeout_exhausted`；
- network：`blocked: codex_network_exhausted`；
- 429：`blocked: codex_rate_limit_exhausted`；
- 5xx：`blocked: codex_server_error_exhausted`。

若这些实际 attempt 包含两种或更多瞬时分类，返回 `blocked: codex_transient_exhausted`。Deadline 在活跃 attempt 内触发、且没有观察到 capture overflow 的 item 通过下文完整性门禁后最终分类为 `timeout` 时，这个真实值参与上述同类或混合判断；对同样没有 overflow 的 item，若完整性门禁把它裁决为 `process_error`，则立即走 `failed: codex_process_failed`，不作为 transient 耗尽或重试。已经锁存 overflow 的 item 固定为 `process_error`，不进入瞬时耗尽集合；它在安全收尾并按 ADR 0081 冻结必填 usage 字段后以 `failed: codex_process_failed` 结束 Answer，禁止 backoff 与后续 attempt。Deadline 在 backoff 或下一次 commitment 前胜出时，不创建占位 item、不回写既有 item，也不向分类集合注入虚构的 timeout，只使用已完成 attempt 的实际 failure classes；若用户取消早于或等于这个固定 deadline，则改为锁存顶层 `interrupted`。因此因 window 提前结束而只有一项或两项 attempt 仍可使用对应的单类耗尽 code。每个 attempt 的实际事件捕获 bytes 和最终 `failure_class` 都必须保留在 Answer staging；manifest 中的 attempt item 由下文封闭十字段记录拥有，原始捕获文件布局与 Answer 级 usage totals 已由后文/前文分别冻结，目录提交遵守已经冻结的 Answer 原子边界。

用户主动中断只要在尚未锁存 Answer 顶层终因时于 retrieval、synthesis 调用包形成或首次 commitment 前、active attempt、backoff、validation 或 rendering 中先胜出，并且当前阶段能够满足既有安全收尾与封闭资产边界，就返回顶层 `interrupted` 且不自动重试。Attempt commitment 前的中断不创建 item，并按后文根级矩阵保留最后一个完整 P0–P4 前缀及可选 C 对；在没有观察到 capture overflow 的 active attempt 内，中断才要求当前 item 最终分类为 `interrupted`。已经锁存的 `process_error`、`runtime_unavailable`、瞬时耗尽或其他 terminal cause 不得被 manifest 形成期间的晚到取消覆盖。对于没有观察到 capture overflow 的 attempt，若生命周期完整性门禁得到 `process_error`，则该更高优先级事实返回 `failed: codex_process_failed`，不能伪装成干净中断。若同一 active attempt 在 capture-finalization boundary 前锁存任一 overflow，则不论中断 observation 更早、同刻或更晚，安全门通过后都固定为 `process_error` 与 `failed: codex_process_failed`；安全门无法证明时仍只留 staging。未被四类瞬时故障或 runtime-unavailable 明确覆盖的非零退出，在 non-overflow 路径也返回 `failed: codex_process_failed`；登录、锁定 CLI、模型或必要能力不可用返回 `blocked: codex_runtime_unavailable`。Codex 正常退出但 final text 缺失、超出 byte budget、带 leading BOM、不是严格 UTF-8、不是唯一 JSON object，或未通过 JSON、Schema、字符串、Candidate、引用、状态及跨字段校验时均不得自动重试，并返回 `failed: answer_output_invalid`。确定性 input、View、budget、link 或 renderer 错误同样不创建语义重试，并使用后文封闭表中各自唯一的 code；绝不能把 retry 当作修复、压缩或重新回答机制。

## Knowledge Codex 用量审计

每个 Knowledge Codex attempt 都记录 `input_tokens`、`cached_input_tokens`、`output_tokens`、`reasoning_output_tokens`、`started_at`、`finished_at`、`elapsed_ms`、`exit_code`、`failure_class` 与 `usage_unavailable`。字段集合与 `literature_reader_v1` 对齐，但由 Knowledge 自己的版本化合同与本文件下文的 terminal manifest item 拥有；以后任一角色增删或改变字段语义，都不得隐式改变另一角色或改写历史记录。

四个 token 字段只能在 ADR 0081 的全局长度门禁允许后，取自下文冻结的单个 usage-eligible `turn.completed.usage` 正向投影，不得从文本、字节数、模型自然语言、其他 event、其他 attempt 或在线 collector 状态推算。Capture-finalization boundary 后必须先复验正式 `events.jsonl` 的实际逻辑长度、asset `byte_length`、固定 identity 与 SHA-256：实际长度恰为 `16,777,216` bytes 时，无论是否 overflow、内容是否可解析或是否包含完整 usage，四项全部为 JSON `null` 且 `usage_unavailable=true`；只有实际长度小于该 cap 时才运行唯一严格全流 usage adapter。长度超过 cap 使资产和 terminal manifest 无效，不能降级为 usage 不可用。长度门禁不证明 overflow、不改变 `failure_class` 或 Answer 终态；合法事件内的用量缺失或畸形也只是审计不完整，不得把已经通过全部语义校验的 Answer 改成 blocked 或 failed，也不得触发重试。

### 单一 turn.completed usage 投影

[OpenAI Codex 非交互模式说明](https://learn.chatgpt.com/docs/non-interactive-mode.md) 把 `codex exec --json` 的 stdout 定义为 JSONL，并展示 `turn.completed` 顶层 `usage` object 中的 `input_tokens`、`cached_input_tokens`、`output_tokens` 与 `reasoning_output_tokens`。Knowledge v1 把这个位置冻结为四项 attempt token 的唯一来源；这是本项目对锁定 Codex CLI 的 role-owned adapter 合同，不表示接受任意未来 CLI 版本或从其他位置回退。

只有已复验正式 `events.jsonl` 的实际长度处于 `0..16777215` 时，usage adapter 才对这份正式资产的全部不可变 bytes 执行 ADR 0074 的 leading-BOM 拒绝与全文件严格 UTF-8 解码，再按 ADR 0075 只用原始 `0x0A` 确定 record 边界；“全部”只量化正式文件，不声称 collector 已取得 provider 的完整 stdout。JSON parser 只能接收与每个 raw slice 对应的已解码 `str`，不得把 raw bytes 直接传给会自动探测编码的 API。正式 bytes 自身的 BOM、解码或 framing/JSON 结构失败都不允许抢救更早看似合法的 usage，四项 token 全部为 `null`；已知 collector truncation/I/O failure 只按既有 lifecycle 规则影响 `failure_class`，不改变由正式资产唯一决定的 usage eligibility。完整 record 序列形成后，适配器才把零个或一个 usage-eligible `type="turn.completed"` 交给投影；第二个同类 terminal event 仍使整个 event stream 结构无效，不得选择、合并或伪装成普通 usage 缺失。实际长度恰为 cap 时不执行 usage-directed 解码、framing、JSON 或投影，也不得复用其他权威分类 consumer 或在线 collector 已看到的 usage；这不禁止 non-overflow clean-EOF exact-cap events 为非 usage 的终态分类目的接受既有 event adapter。

Usage 投影本身采用以下封闭规则：

1. 没有已接受的 `turn.completed` 时——包括 ADR 0075 得到零条 record 的情况——四项 token 全部为 `null` 且 `usage_unavailable=true`。这条规则只确定 usage 值；零条 record 本身不选择 failure class，该事件序列对 timeout、interrupted、provider failure 或正常完成是否有效，仍由完整 event adapter 矩阵和已冻结 terminal-signal 裁决决定。
2. 已接受的 `turn.completed` 没有 `usage`，或 `usage` 不是 JSON object 时，同样把四项全部设为 `null` 且 `usage_unavailable=true`；仅此 usage 形状不完整不产生 `process_error`。
3. `usage` 为 object 时，只读取大小写精确的四个 allowlisted key。每项分别按 `0..9223372036854775807` JSON integer 且排除 boolean 的既有规则验证；缺失或无效项独立为 `null`，其他合法项原样保留。Object 中其他 key 不进入 manifest、不参与计算且不导致失败，只随原始 event bytes 保存。
4. 不读取 `turn.started`、`turn.failed`、`error`、`item.*`、stderr、`--output-last-message` 文件或模型输出中的同名值；不对多个 event 求和、取最后值、取最大值、推断差值或补零。

在实际长度小于 cap 的分支，只要一个 `turn.completed.usage` event 已被完整接受，其合法字段就属于该 attempt 已观察到的审计事实；若进程后来未在 deadline 前完整退出而最终分类为 `timeout`，或只有 final capture overflow，这些值仍按逐字段规则保留。相反，timeout、interrupted、CreateProcess failure、provider failure 或结构失败没有 usage-eligible `turn.completed` 时不得从部分输出估算 token。实际长度恰为 cap 的 clean EOF 与 events-overflow exact prefix 一律四项为 `null`，双 overflow 相同；final-only overflow 只有在 events 小于 cap 时才可投影。该规则只需现有 Python 标准 JSON 能力与 duplicate-key 检查，不增加项目第三方依赖。

### Answer usage_totals

每个 Answer terminal manifest 顶层必须包含非 `null`、封闭的 `usage_totals` object；四种运行终态和零 Candidate 分支都必填。Object 必须且只能包含以下四个 key，全部必填；字段书写顺序不构成语义：

~~~json
{
  "cached_input_tokens": 800,
  "input_tokens": 1200,
  "output_tokens": 500,
  "reasoning_output_tokens": 200
}
~~~

每个总计分别为 JSON `null` 或 `0..9223372036854775807` 的 JSON integer；boolean、float、string、负数和超限值无效。`usage_totals` 不增加 `usage_unavailable`、`attempt_count`、currency、cost、price/version 或估算字段；某项是否不可用直接由该项为 `null` 表达，避免第二个派生事实。

当 `attempts=[]` 时，四项总计必须全部为 integer `0`。这不是把未知值补零，而是明确表示本 Answer 没有任何 launch commitment，因此没有 Codex attempt token；该规则适用于零 Candidate 成功、retrieval 终态、首次 commitment 前的 runtime unavailable，以及 commitment 前中断等所有合法零-attempt 组合。

当 `attempts` 非空时，四个字段必须彼此独立地按以下算法计算：

1. 依数组顺序读取全部实际 attempt 的同名字段，不得只选择最后一次、成功一次、`failure_class=null` 的一次或已经产生 final text 的一次。
2. 只要任一 attempt 的该字段为 `null`，对应总计就是 `null`；其余三个字段继续独立判断。不得把未知值补零或把已知部分和冒充总量。
3. 全部同名值均为 integer 时，先用 Python 精确整数计算数学和；结果不超过 `9223372036854775807` 时保存该整数，超过时保存 `null`。禁止 wraparound、饱和、截断、浮点求和、字符串化或使 Answer 失败。

因此一个 CreateProcess failure item 的四项 token 全为 `null` 时，四项 Answer 总计也全为 `null`，即使可以推测远端没有消费；合同优先保留“发生过 attempt 但 provider usage 不可证”的边界。某 attempt 只有 `cached_input_tokens=null` 时，只让 cached 总计为 `null`，其他三项仍可精确求和。`cached_input_tokens` 与 `input_tokens` 是 provider 给出的两个独立审计量，不做相减；`reasoning_output_tokens` 也不再加到 `output_tokens` 中。

总计只能从已经冻结且通过 ADR 0081 复验的 manifest `attempts[*]` 字段计算，不能再次读取原始 events 或形成第二套 totals parser。Writer 在全部 attempts 冻结、Answer terminal cause 已锁存后且采集 Answer `finished_at` 前形成它；validator 与 crash recovery 必须用同一算法重新计算并要求逐字段完全相等。Null 或 token-sum arithmetic overflow 只降低用量审计完整性，不产生 Answer error、不改变状态且不触发重试。任一 attempt 的正式 events 恰为 cap 时，该 item 四项 token 全为 `null`，所以 Answer 四项 totals 也全部为 `null`；更早 attempts 的已知 item 值不回写。

首版不估算人民币、美元或其他金额，不维护价格表，也不依据 provider/模型自报 token 数设置运行中预算闸门或提前终止 Codex。Token 数值只用于审计，不作为运行预算或停止依据；运行时正式资产复验与 usage readiness 仍进入 classification-ready，并参与硬性的 attempt 超时和 95 分钟安全上限裁决。逐 attempt 的精确 JSON 类型、时间、exit/failure、`usage_unavailable` 规则与正式捕获文件名，以及 Answer terminal manifest 的顶层字段闭包、64 KiB aggregate cap 与有界 parser profile 均已冻结；这些 manifest reader 边界不改变 attempt 文件边界。

## Answer 原子提交边界

每个已经通过 QuestionEnvelope、大小与查询原子校验并获得 `answer_id` 的请求，只能在 Knowledge 正式数据根下的 `answers/.staging/<answer_id>/` 写入；其唯一提交目标是同一卷上的 `answers/<answer_id>/`。`answer_id` 生成后、开始检索前就创建 staging，检索、Codex attempt、确定性校验与渲染的全部中间资产都先进入该目录。任何阶段都不得直接创建、修改或补写目标目录中的文件。

Codex `--output-last-message` 的 writer-private spool 只能存在于当前 Answer 的活跃 staging 私有命名空间，并且必须位于正式 `attempts/NN/` 路径空间之外；具体 leaf name 不是稳定合同，但每个 attempt 必须使用 fresh、唯一且 launch 前不存在任何 entry 的私有路径，禁止跨 attempt 复用。它不是 manifest asset、不得直接成为 Answer validation 输入，也不得进入 terminal Answer。形成 terminal manifest 前必须安全关闭并撤销全部此类私有文件；如果无法撤销，封闭资产集合验证失败，只能留下 staging，禁止原子提交。

进入运行终态时，Python 先完成、验证并关闭 terminal manifest 以外的全部应保留资产并撤销全部私有临时 entry，再按 ADR 0087 直接排他创建、写入、验证并关闭字面 terminal `manifest.json`；只有所有文件与目录句柄都已关闭，才能把整个 staging 目录同卷原子改名为目标目录。目标必须不存在；如果目标已经存在或原子改名失败，禁止覆盖、合并、删除目标后重试、逐文件移动或以复制后删除模拟成功提交。此时 staging 仍不是正式 Answer，并按后文已冻结的保守恢复策略处理；确定的 target-exists 与其他确定 rename failure 分别使用 ADR 0095 的 `knowledge.ask.answer_target_conflict.v1` 与 `knowledge.ask.answer_commit_failed.v1`，显式维护方式仍待定，rename 结果不确定时位于正常矩阵外。

Writer 必须先按 ADR 0084 对 ADR 0082 形成且包含末尾 LF 的完整 canonical bytes 执行 65,536-byte inclusive 门禁，确认不存在第 65,537 个 byte 后，才可在安全 staging 根内用 `CREATE_NEW` 语义直接排他创建字面 `manifest.json`。Writer 对同一 immutable buffer 循环处理正长度 short write，直至精确写满；不得创建 manifest temp leaf、执行 leaf rename/replace、重新序列化、覆盖、删除或修补。写 handle 成功关闭后由共享 terminal-manifest reader 安全重开并从头读到 EOF，先复验同一 cap，再依次执行 framing/strict UTF-8、ADR 0086 parser profile、当前 Schema、canonical reserialization、逐 byte identity、目录闭合与全部跨资产验证；生成、容量检查、exclusive create、写入、用户态 flush、关闭、重读或验证任一步失败都禁止本次 writer 提交，只留下 staging。该门禁不改变前文“其他资产先完成并关闭、manifest 最后形成并关闭、随后目录原子改名”的提交顺序。

ADR 0088 把上述目录改名成功定义为 process-level logical commit：只有 non-replacing 同卷 staging-directory rename 返回成功后，当前调用才可报告 Answer 已提交。V1 不调用或依赖 `FlushFileBuffers`、`os.fsync`/`_commit`、file/directory/volume flush、`FILE_FLAG_WRITE_THROUGH`、`MOVEFILE_WRITE_THROUGH` 或其他 write-through 机制；正常 I/O completion、用户态 buffer flush、close、readback 与验证仍是必需门禁，但都不把提交升级为断电持久性保证。

`succeeded`、`blocked`、`failed` 与 `interrupted` 四种运行终态都必须通过上述边界提交一个可审计且不可变的 `answers/<answer_id>/`。`succeeded` 必须且只能成对包含已经通过完整验证的 `answer_output.json` 与 `answer.md`；其他三种终态禁止包含任一正式结果文件，即使 staging、Codex 原始事件或 `final_message.txt` 中曾出现看似完整、部分或无效的输出。`answer_status=insufficient_evidence`，包括零 Candidate 的 Python 分支，是正常 `succeeded`，因此仍提交完整的正式结果对。

提交后的 Answer 目录不得原位修改、补写、重命名或复用；重复问题继续产生新的 `answer_id`。首版不在 Answer 下增加 `runs/`、`current.json`、成功指针或“同一问题的当前版本”，也不让任何终态取代另一个终态。失败审计记录可能持续占用空间；清理只能由以后单独冻结的显式维护操作完成，日常 ask、resume 或启动流程无权自动删除。

ADR 0076 的 capture retention 保证只量化单个已提交 Answer 的正式 attempt capture 资产，不量化历史 Answer 的累计占用或 orphan staging；这不构成垃圾回收、删除、覆盖、修复或改写既有 Answer 与 staging 的权限。

崩溃遗留的 `answers/.staging/<answer_id>/` 不具备 terminal manifest 加原子目录提交这一完整边界，因此列表、检索、回答读取与其他正常消费者都必须忽略它，绝不能把它当作正式 Answer、成功结果或可引用来源。是否仍有存活 writer 只按后文单写者 mutex 判断；已经证明无 owner 后，只允许按后文策略补交完整有效的既有 terminal commit，其余 staging 原样隔离，不能自动改写为 `interrupted` 或继续执行。

## Knowledge Answer 单写者与活跃所有权

初始 Data Root gate 成功后即锁存“本 invocation 不再具有 Data Root blocked 资格”。此后的持锁 orphan recovery、创建本次 staging 前或最终目录改名前若 checkpoint 无法继续证明 root identity、canonical root、父链或 reparse 状态仍安全且相同，必须停止并选择 no-commit `failed`、`result=null`，与是否已经生成 `answer_id` 无关。唯一 primary 是 `{"code":"knowledge.ask.data_root_integrity_lost.v1","context":{}}`，正常 JSON exit 为 `1`；明确漂移与证明不可重建使用同一码，禁止披露 path、file identity、permission、Win32 code 或异常文本。Root 已失去信任时不得继续形成或提交 terminal `status=failed` Answer；本次新 staging 若已存在则原地隔离。单个历史 orphan 自身无效或 target conflict 仍只产生 supplemental，不等同于 invocation-wide root trust loss。

Knowledge v1 假设没有恶意或高权限本机进程在检查与实际文件操作之间并发替换目录组件。Data Root preflight、创建本次 `answers/.staging/<answer_id>/` 直接子目录之前，以及新 Answer commit 或 orphan recovery 的最终目录改名之前，必须复核冻结 root handle 的 physical identity、handle-derived canonical root、目标父链与 reparse 状态。所有 descendant path 只能从该 frozen canonical root 派生，不得重新使用 raw configured path。检测到漂移必须停止，但 V1 不要求所有 descendant I/O 使用 handle-relative Win32/NT API，也不承诺消除最后一次复核与操作之间的 hostile TOCTOU。下文“root handle、physical identity 与 mutex name 保持同一对象绑定”仅指 identity/mutex 锚点与 canonical-root 来源不漂移，不是更强的 race-free 声明。

`knowledge ask` 的 Data Root gate 只 safe-open 并验证冻结的 `knowledge.data_root`，不得打开、查询或以 existence/access/physical identity 验证 `literature.data_root` 或 future Context root；其他 Context 的状态不能阻塞 Knowledge。允许的输入等价仅限 Windows 大小写、separator、`.` / `..` 归一与普通 DOS/local extended DOS 前缀。若 safe-open 后证明路径依赖 8.3 short name、SUBST、额外 drive-letter、volume mount 或其他隐藏 filesystem alias，必须选择 `knowledge.ask.data_root_unsafe.v1`；无法完成该判定但尚无 unsafe 肯定证据时选择 `knowledge.ask.data_root_unavailable.v1`。

Knowledge v1 对每个经过验证的 Knowledge 数据根只允许一个 Answer writer。`knowledge ask` 必须在扫描或处理任何 `answers/.staging/`、生成新 `answer_id`、读取本次检索快照或创建 Codex attempt 之前，先以非阻塞方式取得字面 `Global\` Windows 内核对象命名空间中的 named mutex。取得后一直持有到 `answers/<answer_id>/` 原子提交完成；如果命令没有生成 `answer_id`，或已经生成身份但原子提交未完成，则必须先停止本次命令拥有的全部子进程与 staging/提交操作、关闭全部相关句柄并结束主流程，再以 `finally` 语义释放 mutex。原子改名失败时不得提前释放后继续触碰 staging。

锁身份固定使用已经打开的 Knowledge 数据根目录本身，而不是用户提供的路径字符串。V1 只接受本机 non-remote DOS drive-absolute 或等价 local extended DOS root；项目外本地根允许，relative/drive-relative/root-relative、UNC/WSL UNC/extended UNC、remote mapped drive、device/NT/Volume GUID namespace、ADS 与 drive separator 之外 colon 按 ADR 0094 选择 `data_root_unsafe`。`/`、`.` 与 `..` 只作词法 alias，规范化不得越过 volume root。数据根与从配置入口到该根的全部路径组件必须通过 [ADR 0014](../adr/0014-separate-versioned-code-durable-data-and-rebuildable-local-state.md) 的 no-follow 安全校验；符号链接、junction、任何 reparse point 及其 broken target evidence 直接拒绝。缺失、非 ordinary directory、拒绝访问或无法完成 handle-derived final-path 核对选择 `data_root_unavailable`，命令不得自动创建 root。随后通过同一 handle 的 Windows `GetFileInformationByHandleEx(FileIdInfo)` 取得 `FILE_ID_INFO.VolumeSerialNumber` 与原样 16-byte `FileId`；API/structure 失败或 FileId 全零选择 `data_root_identity_unavailable`，API 成功且 FileId 合法时 volume serial `0` 仍按 unsigned 64-bit 原样接受。按 ASCII 前缀 `gezhi.knowledge_answer_writer.v1`、一个零字节、8-byte unsigned little-endian volume serial 和 16-byte file ID 的顺序连接，再取 SHA-256 lowercase hex；mutex 名称固定为 `Global\Gezhi.KnowledgeAnswerWriter.v1.<64hex>`。因此同一真实目录经允许的路径 alias 打开时仍得到同一身份，不同同时存在的目录按 Windows 文件身份隔离。三项 blocked primary context 均为 `{}`；禁止退回路径字符串哈希、PID 文件或 session-local mutex。成功验证的 root handle、physical identity 与 mutex name 必须保持同一对象绑定，root handle 在命令期保留作 identity/mutex 锚点；不能算出 mutex name 后关闭 root handle，再从 raw configured path 重开。Descendant path 只从 frozen handle-derived canonical root 派生并服从指定 checkpoint，不要求每项 I/O 都由 root handle 相对寻址。

如果 mutex 已被另一个 writer 持有，第二个 `knowledge ask` 必须立即返回 `knowledge.ask.answer_writer_busy.v1`，不等待、不排队、不重试、不生成 `answer_id`、不创建 staging、不读取 Candidate 检索快照，也不启动 Codex。这里的“立即”只指抵达 zero-wait writer gate 并观察到 `WAIT_TIMEOUT` 后立即停止，不覆盖 ADR 0094 中更早的 Question、Configuration、Provenance 与 Data Root gate。`knowledge search`、`knowledge show` 与其他只读消费者不取得 Answer writer mutex，并继续只读取已经原子提交的正式资产。

操作系统持有的 mutex 是活跃 Answer writer 所有权的唯一权威。PID、进程名、启动时间、墙钟时间、heartbeat、`owner.json`、锁文件内容或 staging 修改时间都只能作为诊断信息，不得单独或组合证明 owner 已死亡，也不得覆盖一个仍被持有的 mutex。对 mutex 执行零等待取得时，`WAIT_OBJECT_0` 与 `WAIT_ABANDONED` 都表示当前编排线程已经取得所有权，并且都必须进入完整 crash-staging scan；后者只说明前 owner 异常消失，不证明存在 orphan。只有 `WAIT_TIMEOUT` 表示 `answer_writer_busy`；mutex 建立/打开/等待失败、`WAIT_FAILED` 或其他未批准返回值表示 `answer_writer_coordination_unavailable`，两项 primary context 都为 `{}`。Mutex 必须由取得它的同一编排线程持有并在 `finally` 中释放、随后关闭 handle；未取得 ownership 的 timeout/failure 路径不得调用 release。进程崩溃时由 Windows 释放或标为 abandoned，下一进程只有成功取得同一 mutex 后，才有资格把该数据根现存 staging 视为没有活跃 writer。

这一 mutex 只串行化同一 Knowledge 数据根的 Answer 写入，不是整个格致项目的全局锁：Literature、未来同级 Bot 与其他 Knowledge 数据根不得复用它。它只使用 Windows 与 Python 标准能力，不增加第三方包。以后若需要同根并行回答，可以由新运行版本改成每 Answer 所有权；已经原子提交的 Answer 目录不迁移、不改写。

## Crash staging 保守恢复

每次 `knowledge ask` 成功取得 Answer writer mutex 后、生成本次新 `answer_id` 前，必须先枚举 `answers/.staging/` 的直接子目录并处理已经没有活跃 owner 的历史 staging。枚举与验证只允许在持锁期间执行；目录按名称的 UTF-8 bytes 升序处理，以使报告顺序确定。只接受名称严格匹配 `ans_<lowercase UUIDv4>` 且通过既有安全路径边界的真实目录；其他文件、非法目录名、符号链接、junction 或 reparse point 不得跟随或修改，只作为孤立异常报告。

历史 staging 只有同时满足以下条件时，恢复器才可以完成原定提交：terminal manifest 完整通过届时冻结的 Answer manifest Schema；manifest 中列出的全部资产逐项存在且实际 byte length、SHA-256、Schema identity 或 media type 与记录一致；目录没有 manifest 禁止的未列出资产；运行终态、错误信息、attempt、用量以及成功结果存在性等全部跨字段不变量通过复验；`answers/<answer_id>/` 目标不存在。Usage 复验属于 terminal-manifest semantic verification：恢复器按 ADR 0081 对 exact-cap events 强制四项 `null`，对低于 cap 的正式 events 运行同一严格 usage adapter，并要求 item 完全相等。恢复器必须关闭验证过程中打开的全部文件与目录 handle，然后只执行一次原定的同卷目录原子改名。它保留 manifest 的原终态与全部既有字节，不重新运行检索、Codex、Answer validation、renderer 或任何工作流阶段，不生成新 `answer_id`，也不重写 manifest、时间戳、哈希或任何资产。该动作只完成 manifest 已经证明存在的原运行 terminal commit，不创建新的 crash-recovery result，也不从部分资产推断成功；没有完整有效 terminal manifest 的现场继续不得包含或发布成功结果。

恢复器对 terminal manifest 的“完整有效”判断必须先包含 ADR 0084 的 raw-byte cap：从同一 binary handle 读取到 EOF 或第 65,537 个 byte，只有不超过 65,536 bytes 且已经观察到 EOF 才可继续。随后依次执行 ADR 0082 的原始 framing 与 strict UTF-8、ADR 0086 的结构 preflight、数字/constant/duplicate hooks 与全部 parser ceilings、当前 Schema，以及 canonical byte round-trip；允许结构深度内任何 decoded duplicate key 都直接拒绝。即使某个 manifest 只是超限，或在宽松 parser 看来语义等价但原始 bytes 不规范，也不得补交；恢复器保留现场，不能 fallback、截断、strip BOM/换行、重排 key、替换 escape 或重写规范副本。

ADR 0087 的 direct-create 允许崩溃 staging 中存在缺失、空、partial 或尚未经原 writer 重读的字面 `manifest.json`，但 leaf 的存在不表示终态或提交点。Recovery 只验证字面最终名称，不寻找或接受 manifest temp、backup、marker 或 sidecar，也不补写、删除、截断、重命名、replace 或从其他 entry 安装 manifest；缺失或无效 leaf 原样隔离。若遗留 leaf 的实际完整 bytes、目录闭合、全部资产与跨字段不变量后来由 recovery 独立全部证明，且正式目标不存在，则即使原 writer 崩溃在自身 readback 之前，也仍可按既有规则只补做一次原定 staging-directory rename。

突然断电或系统崩溃后的下一进程只信重新观察到的实际 namespace 与全量验证结果：target 与 staging 都缺失表示该 Answer 当前不存在；只有有效 staging 且 target 缺失时才可按上段补交；无效 staging 原样隔离。Target 存在时由正式 reader 独立全量验证，有效才可读取，无效则整体拒绝且保持不可变；任何同身份 staging 都因 target conflict 不能自动补交，即使 target 无效而 staging 有效也不得覆盖、合并、删除或择优。断电前的成功返回、日志、时间戳、manifest/目录存在和 mutex 状态都不是持久证据。

只要上述任一条件不成立，包括 manifest 缺失、无法解析、Schema 无效、哈希或长度不符、资产缺失或多余、终态不变量失败、路径不安全、目标已存在，或者验证通过后的原子改名失败，该 staging 就保持原路径和原有文件字节。恢复器不得修补、删除、重命名、移动、补写 manifest、把未知值补零、复用部分结果、改成 `interrupted`，或将其复制到正式 Answer 树；原子改名失败也不得自动重试或降级成逐文件操作。它仍被所有正式消费者忽略；当前 `ask` 必须以人用输出和稳定 `--json` 诊断报告该孤立目录，但这些孤立项本身不阻止本次新问题继续获得新的 `answer_id` 并执行。诊断的完整 Schema 与单项稳定 code 随后冻结。

Knowledge v1 不新增公开的 `knowledge resume`，也不把孤立 staging 当作可恢复语义会话。若用户仍需要该问题的答案，只能重新执行 `knowledge ask` 并产生新的 Answer 身份。对孤立目录进行归档、删除或显式终态化属于以后独立批准的维护功能；日常 `ask`、`search`、`show`、`status` 与 `doctor` 均无权执行这些变更。

## manifest.json 封闭顶层 envelope

每个已经形成的 Answer terminal `manifest.json` 根值必须是 JSON object，并且必须且只能包含以下十一项顶层 key；十一项在 `succeeded`、`blocked`、`failed`、`interrupted` 与零 Candidate 分支中全部 required，root `additionalProperties=false`：

```text
schema_version
answer_id
status
error
started_at
finished_at
elapsed_ms
provenance
attempts
usage_totals
assets
```

不得省略字段、注入默认值、接受别名或保存第十二个 key。`schema_version` 必须精确为 `gezhi.answer_manifest.v1`；其他字段分别遵守本合同已经冻结的身份、终态、error、时间、provenance、attempt、usage 与资产 Schema 及全部跨字段不变量。

在这十一个顶层 value 中，只有 `error` 的 Schema 允许 JSON `null`：`succeeded` 与 `interrupted` 时必须为 `null`，`blocked` 与 `failed` 时必须为封闭两字段 object。该规则只约束顶层 value，不取消既有嵌套 nullability；`provenance.git.revision`、attempt 条件式字段与 `usage_totals` 成员仍按各自 Schema 允许 `null`。`attempts`、`usage_totals` 与 `assets` 顶层自身始终非 `null`；`attempts` 可以为空，`assets` 因 P0 至少包含 `effective_config.json`。

十一项只对已经形成的 terminal manifest 必填。`answer_id` 生成前的阻塞，或完整 terminal manifest 形成前的进程崩溃，可以没有合法 manifest，不得为满足闭包补造半终态；若现场已有字面 manifest，只能由共享 reader 与 ADR 0053/0088 的恢复规则裁决。以后新增任何顶层 key 都必须升级 Answer manifest Schema；`answer_status`、第二个运行终态、`attempt_count`、顶层 `usage_unavailable`、配置副本/哈希、额外身份/时间、provider ID、overflow latch 与外部诊断当前都不是 v1 顶层字段。

上述列举顺序只表达批准的集合，不是 object 的语义顺序。ADR 0082 的 `sort_keys=True` 决定规范 bytes 中实际顺序为 `answer_id`、`assets`、`attempts`、`elapsed_ms`、`error`、`finished_at`、`provenance`、`schema_version`、`started_at`、`status`、`usage_totals`；array 顺序不受影响。

## manifest.json 封闭资产清单

每个终态 Answer 根目录的 terminal manifest 文件名固定为大小写精确的 `manifest.json`。顶层 envelope 由前节完全封闭；其中 `schema_version` 必须严格等于 `gezhi.answer_manifest.v1`，未知或缺失版本直接拒绝。`assets` 按每项 `path` 的 UTF-8 bytes 严格升序排列，`path` 不得重复；顺序错误、重复或等值路径别名都使整个 manifest 无效，validator 不得自动排序或去重。

每个 asset item 必须且只能包含 `path`、`byte_length`、`sha256`，以及 `schema_id` 与 `media_type` 二者中的恰好一个：

- `path` 是从 Answer 根目录出发、使用 `/` 分隔的相对普通文件路径；不得为空、以 `/` 开头或结尾、包含 `\`、冒号、空 segment、`.` 或 `..` segment，不得带 Windows drive-relative、UNC、device 或 extended-length prefix，也不得解析到 Answer 根之外。解析 JSON string 时只接受能解码为 Unicode scalar value 序列的内容：合法 UTF-16 surrogate pair 解码为对应 scalar，任何非配对 surrogate 或解码后残留的 U+D800..U+DFFF code point 直接拒绝，因此每个合法 `path` 都有唯一 UTF-8 byte 序列。任何 segment 含 U+0000..U+001F、`<`、`>`、`"`、`|`、`?`、`*`，或以 U+0020 SPACE / U+002E FULL STOP 结尾时直接拒绝。设备名检查的 basename 固定为每个 segment 中首个 U+002E FULL STOP 之前的子串；没有 U+002E 时取整个 segment。该 basename 按 ASCII 大小写不敏感比较，`CON`、`PRN`、`AUX`、`NUL`、`CLOCK$`、`CONIN$`、`CONOUT$`、`COM1`..`COM9`、`LPT1`..`LPT9` 以及使用 U+00B9/U+00B2/U+00B3 的对应 `COM`/`LPT` 名称都禁止，所以 `CON.foo.bar` 等多扩展名形式也必须拒绝。每个路径组件及其最终文件都必须通过 ADR 0014 的路径安全边界，禁止符号链接、junction 与任何 reparse point；根级 `manifest.json` 本身及其任何 Windows 大小写别名都禁止作为 asset path。
- `byte_length` 是必填且非 `null` 的 JSON integer，合法闭区间严格为 `0..9223372036854775807`；JSON boolean、float、string、`null`、负数或更大的值都无效。它必须精确等于该普通文件未命名主数据流从起点到逻辑 EOF 的实际 byte 数；目录、链接与 alternate data stream 不是合法 asset。
- `sha256` 是该文件主数据流原始 bytes 的 SHA-256，必须为恰好 64 个 lowercase ASCII hexadecimal 字符 `0-9a-f`。
- `schema_id` 与 `media_type` 都是非空字符串；Gezhi 拥有且具有版本化 Schema identity 的文件使用 `schema_id`，provider 原始事件、prompt、原始 final message 与其他不注入 Gezhi envelope 的文件使用 `media_type`。未选中的 key 必须缺失而不是 JSON `null`。两个 attempt 固定捕获文件的 asset item 必须选择 `media_type`，值逐字精确为无参数 `application/octet-stream`，并省略 `schema_id`；根级业务文件与 attempt 双文件的路径/存在性矩阵已冻结，根级纯文本与 Schema 快照的精确 identity 仍由后续合同冻结。

`byte_length` 的 signed 64-bit 闭区间只是通用表示域，不是单文件读取预算、`assets` 合计 quota 或 Answer 目录容量承诺。任一路径已有的更小 byte cap 必须与该范围取交集并优先执行，不能被通用上界扩宽；声明长度也不能用作预分配或跳过实际长度与 SHA-256 复验的依据。`manifest.json` 不自列，ADR 0084 的 manifest raw-byte cap 与本字段范围相互独立。

路径唯一性除 JSON 字符串逐 byte 不重复外，还必须对任意两条 `path` 调用 Windows `CompareStringOrdinal(..., bIgnoreCase=TRUE)` 并要求结果不相等；不得依赖当前 volume 是否启用大小写敏感目录。根目录枚举得到的 terminal manifest 文件名必须逐字符精确为 lowercase `manifest.json`；任何另一个在上述 ordinal-ignore-case 比较下等于 `manifest.json` 的目录项都使 manifest 无效。比较 API 失败时不得退回 locale collation、Unicode casefold 或当前进程 locale。

terminal validator 必须在不跟随链接或 reparse point 的前提下递归枚举 Answer 目录；枚举中发现任何 symlink、junction 或其他 reparse-point entry 都立即使 manifest 无效，不能仅跳过后继续接受目录。除根级 `manifest.json` 外，实际存在的全部普通文件路径集合必须与 `assets[*].path` 一一完全相等：清单项不得缺少实际文件，目录也不得含清单未列出的普通文件；每项的实际长度、哈希和 identity/media type 还必须通过复验。除 Answer 根本身外，实际普通目录集合也必须精确等于全部 `assets[*].path` 所隐含的非空 proper parent path 集合；不得存在没有获准 asset 后代的空目录、临时目录、备份目录或额外 attempt ordinal 目录。所有隐含目录继续接受与 asset path segment 相同的安全、设备名、ordinal-ignore-case 与 reparse 检查，但不作为 asset item。validator 同时读取所属 volume 的 filesystem flags：没有 `FILE_NAMED_STREAMS` 能力时视为不支持 alternate data stream；存在该能力时，必须以 `FindFirstStreamW`/`FindNextStreamW` 枚举 Answer 根、每个子目录、根级 `manifest.json` 和每个 asset 文件，普通文件只允许唯一默认未命名 `::$DATA`，目录不允许任何 `$DATA` stream。任一 named stream、意外 stream type、枚举错误或无法完成全量枚举都使 manifest 无效；不得忽略、删除或把 stream 内容并入主文件哈希。任一缺失、多余、路径非法、类型错误、长度错误、哈希错误、identity 组合错误、目录闭合错误或 stream 错误都不能原子提交或由 crash recovery 补交。

`manifest.json` 不得在 `assets` 中列出自己，也不保存自己的 byte length、SHA-256 或其他形式的自哈希；无 `current.json` 的 Answer 不为解决自引用而建立第二份 sidecar。新增任何持久 Answer 或 attempt 审计文件、改变既有文件的 identity/media type，或者扩展允许路径矩阵，都必须升级 Answer manifest Schema；旧读取器遇到未知版本必须拒绝，不能把新文件当作可忽略附件。

### manifest.json 规范 JSON 字节

Writer 只能对已经冻结并通过当前 `gezhi.answer_manifest.v1` Schema 与跨字段不变量验证的 manifest value，按 Python 3.11 标准库执行以下精确调用：

```python
json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
```

最终文件使用 binary I/O；不得带 UTF-8 BOM，不得出现 raw `0x0D`，且唯一 raw `0x0A` 必须是最后一个 byte。`sort_keys=True` 递归排序 object keys，不排序 arrays；`assets`、`attempts` 与其他数组仍必须分别通过既有领域顺序验证。禁止自定义 encoder、`default`、Unicode normalization、Windows newline translation、whitespace/escape rewriting 或任何修复。

共享 reader 先按 ADR 0084 取得不超过 65,536 bytes 且已经观察到 EOF 的完整原始序列，再验证 framing，并对去掉末尾 LF 的 payload 做 strict UTF-8 decode。随后必须在建立 JSON object/list 前通过 ADR 0086 的 quote/escape-aware structural preflight，再用每次调用私有的 strict hooks 解析唯一顶层 object，并完成全部 parser counters；允许结构深度内任意 decoded duplicate key、`NaN`、`Infinity`、`-Infinity`、任何 float/exponent number、第二个顶层值、comment 或其他非标准 JSON 都直接拒绝。Reader 在使用 manifest 值打开 asset path 前，必须继续通过当前 Schema、路径字段安全验证，并用上面同一调用重序列化 parsed value，要求与原始 bytes byte-for-byte 相等；通过后才执行目录闭合、reparse/ADS、长度、哈希、identity、usage、终态及其余跨资产复验。

Writer、terminal validator、crash recovery 与正式 reader 必须共享这一实现。Writer 只有在最终 `manifest.json` 重读通过且全部句柄关闭后才可提交目录；recovery 对 raw cap 或 parser profile 超限、non-canonical、partial 或语义不一致的 manifest 只隔离，不得重写。该规则不让 manifest 自列或自哈希；顶层 envelope 已由 ADR 0083 冻结，raw-byte cap 已由 ADR 0084 冻结，asset `byte_length` 范围已由 ADR 0085 冻结，有界 parser profile 已由 ADR 0086 冻结，direct exclusive-create leaf formation 已由 ADR 0087 冻结，V1 不承诺断电 durability 的边界已由 ADR 0088 冻结；ADR 0089 已冻结 invocation-local CLI 外部载体，ADR 0091 已冻结共享 diagnostic item/profile，ADR 0092 已冻结 committed primary subset，ADR 0093 已把阻止本次 commit 的 manifest 形成/验证/提交失败固定为 no-commit `failed` 并冻结正常 JSON exit，ADR 0095 已闭合这些分支的七项 primary code/context，ADR 0097 已冻结 no-commit `failed > interrupted > blocked` 静态优先级，ADR 0098 已冻结 cancellation observation、work commitment 与 Answer identity cutover，ADR 0099 已冻结完整 drain、cleanup/release 与 no-commit 安全后置条件。其他 variants 仍待批准。

### manifest.json 64 KiB raw-byte cap

`gezhi.answer_manifest.v1` 的完整 `manifest.json` 固定最多 `65_536` raw bytes。计数从文件第一个 byte 到 EOF，包含规范末尾 LF，也包含随后会被其他门禁拒绝的 BOM、CR、非法编码、空白或其他 byte。`0..65_536` 只表示通过容量门禁；长度恰为 `65_536` 合法，只有确认存在第 `65_537` 个 byte 才超限。不得截断、只解析 prefix、trim 后计数或把超限文件重写成较短规范副本。

Writer 在规范序列化后、direct exclusive-create 字面 `manifest.json` 前先检查完整 canonical bytes；超限时不能形成 terminal manifest 或提交目录。共享 reader 在任何 BOM/framing、UTF-8 decode、JSON parse、Schema 或 path 使用之前，从已经安全打开的同一 binary handle 循环读取到 EOF 或累计 `65_537` bytes；short read 不等于 EOF。取得第 `65_537` byte 即拒绝，只有累计不超过 cap 且明确到达 EOF 才把保留的完整 bytes 交给后续门禁。禁止只信预报文件长度或先无界读取。

该 cap 是 v1 新增的 aggregate validity condition，而不是由各字段上限推导出的精确最大值；不进入配置、manifest 字段、asset item 或 sidecar。Writer 写后复验、terminal validator、crash recovery 与正式 reader 全部共享它。超限不改变已经锁存的 Answer terminal cause，也不允许在 manifest 内新增诊断；若本次新 Answer 因此无法 commit、root trust 仍成立且能够安全停止，外部使用 ADR 0095 的 no-commit `knowledge.ask.answer_manifest_failed.v1`。本节不替代 ADR 0086 的 parser profile；direct exclusive-create leaf formation 由 ADR 0087 冻结，V1 不承诺断电 durability 的边界由 ADR 0088 冻结。

### manifest.json 有界 parser profile

ADR 0086 为 `gezhi.answer_manifest.v1` 固定以下 inclusive ceilings；第 `limit + 1` 个 occurrence 才因对应门禁拒绝：

| 计数项 | inclusive maximum |
|---|---:|
| container depth | `8` |
| 单个 object pairs | `16` |
| 全文 object pairs | `128` |
| 单个 array items | `16` |
| 全文 array items | `32` |
| object/array containers 合计 | `32` |
| JSON value nodes 合计 | `256` |
| integer token 的 ASCII decimal digits | `19` |

Root object/array 的 container depth 为 `1`；每个 object/array 都算一个 container，root 也算一个 value node。Pair 与 item 按原始 occurrence 计数，unknown 与 duplicate pair 不能先投影或合并；object key 不算 node。每个 object member value 与 array element 各算一个 value node，因此单一合法 tree 满足 `nodes = 1 + total_pairs + total_array_items`。即使把互斥分支的局部最大保守相加，v1 也只需要 depth `3`、单 object `11`、总 pairs `114`、单 array `15`、总 items `18`、containers `25`、nodes `133` 与 integer digits `19`；考虑跨字段互斥后真正可同时达到的是总 pairs `112`、containers `24`、nodes `131`。兼容性证明使用较高的保守值，仍不会被本 profile 误拒。

Structural preflight 必须在 strict UTF-8 后、建立 Python JSON tree 前运行，并正确理解 JSON string 与 escape；string 内的括号、冒号、逗号或 escaped quote 不参与结构计数。随后显式使用 `json.loads(..., strict=True, ...)`；`parse_int` 在 `int()` 前检查 digits，optional `-` 不计入位数，19 digits 仍必须通过字段专属范围。`parse_float` 拒绝全部 fraction/exponent number，`parse_constant` 拒绝 `NaN` / `Infinity` / `-Infinity`，`object_pairs_hook` 在生成普通 mapping 前基于完整 ordered pairs 拒绝 decoded-key duplicate 并复核 pair ceilings；decoded key 比较大小写敏感、不做 Unicode normalization。所有 stack、counter 与 hook state 都是单次 reader 私有状态，禁止修改或依赖进程全局 recursion/int-digit 设置。

完整 reader 顺序严格为：ADR 0084 raw cap并确认 EOF → ADR 0082 framing与strict UTF-8 → ADR 0086 structural preflight与strict hooks parse → 唯一顶层 object及全部计数复核 → 当前 Schema与path字段安全 → canonical byte round-trip → asset path使用与跨资产验证。任何 profile failure 都使 writer 禁止提交、recovery 原样隔离、正式 reader 整体拒绝；不得 fallback、截断、删字段、补默认值或重写。Raw cap 只约束输入 bytes，不承诺 Python object graph 或峰值内存也是 64 KiB。String、key 与 whitespace 不另设独立 parser ceiling，其原始表示由 raw cap 约束，语义继续由 Schema、路径与 canonical 规则约束。

这些门禁是 v1-only reader 在读出 `schema_version` 前执行的 outer profile，不进入配置、manifest 或 sidecar。未来 reader 若支持更宽版本，必须先显式扩大自己的 outer pre-version profile，解析后仍对声明为 v1 的文档强制本组上限；旧 reader 保持安全拒绝。该 profile 只适用于 terminal `manifest.json`，不扩展到 `events.jsonl` 或其他 JSON 资产。

### manifest.json direct exclusive-create leaf formation

Writer 只有在 terminal manifest 以外的全部应保留资产已经完成、验证并关闭，writer-private spool、tail、临时与备份 entry 已全部撤销，而且同一 immutable canonical byte buffer 已通过 ADR 0084 cap 后，才可形成 terminal leaf。字面 lowercase `manifest.json` 及其任何 Windows ordinal-ignore-case alias 必须不存在；预先枚举只用于 fail closed，真正的不覆盖保证来自随后一次 `CreateFileW(..., CREATE_NEW)` 等价操作。写 handle 存续期间拒绝 write/delete sharing，并使用同步完成或逐次等待确认的 I/O；`CREATE_NEW` 不替代安全根包含、父路径/leaf no-reparse 与创建后普通文件验证。

Writer 只能从 offset `0` 把已检查的同一 buffer 写入这一个 handle。正长度 short write 在同一 handle 上继续剩余 suffix；zero write、超出本次请求的 write count、I/O exception、未完成或失败的异步 completion、用户态 flush 或 close 失败都禁止本次 writer 提交。V1 不创建 manifest temp leaf，不执行 leaf rename/replace，不使用 backup、marker、sidecar、hard link、copy-delete、重新序列化、删除后重试、截断、重开写入或修补。

Write handle 成功关闭后，writer 以拒绝 write/delete sharing 的安全 read handle 重开字面最终 leaf，并用共享 reader 从头读到 EOF，执行 raw cap、framing/strict UTF-8、parser profile、当前 Schema、canonical round-trip、与原 immutable buffer 的逐 byte identity、目录闭合与全部跨资产验证。验证通过后关闭 root anchor 以外的全部 operation-specific 文件/目录 handles；紧邻 rename 前，从 frozen canonical root 重新派生 staging/target，并复核 retained root handle identity、canonical root、两条父链 no-reparse、同卷关系与 target 仍不存在。Checkpoint 成功后才可执行一次既有的同卷 staging-directory rename；leaf 的创建、写满或 close 都不是 commit point，整个目录改名成功才是唯一正式发布点。

进程崩溃可在仍被正式消费者忽略的 staging 中留下缺失、空、partial 或完整-looking 的字面 leaf。Recovery 不寻找 manifest temp/backup/marker/sidecar，也不补写、删除、截断、重命名、替换或安装 leaf；缺失或无效现场原样隔离，只有实际 bytes、全部资产与不变量被独立完整证明且目标不存在时才可只补做目录改名。本边界只串行化服从同一 Knowledge writer mutex 的 Gezhi writer/recovery，不声称抵抗不服从 mutex 的本地篡改。普通 I/O completion、用户态 flush、close、readback 与 rename 仍是进程级门禁，但 ADR 0088 已冻结 V1 不调用强制持久化 API、也不承诺断电 durability。

### Answer V1 断电持久性边界

Process-level logical commit 与 power-loss durability 是两个不同边界。全部内容重读验证通过、全部 handle 关闭并且唯一 non-replacing 同卷 staging-directory rename 返回成功，是当前进程唯一可以报告“Answer 已提交”的线性化点；它不表示 `fsynced`、power-safe 或 durably persisted。V1 不调用或依赖 `FlushFileBuffers`、`os.fsync`/`_commit`、file/directory/volume flush、`FILE_FLAG_WRITE_THROUGH`、`MOVEFILE_WRITE_THROUGH` 或其他 write-through 机制，也不把操作系统/设备的后台落盘当作合同证据。

突然断电、系统崩溃、强制重启或存储设备/控制器故障可能使最近一次 Answer 缺失、留在 staging、出现在 target、两侧并存、内容 partial，或使 manifest 与资产彼此不一致；V1 不承诺进程内 write/close/rename 顺序按相同顺序持久化。下一进程不得从先前 CLI success、日志、时间戳、路径存在、manifest 存在、预报长度或 mutex 状态推导提交，只能重新安全打开当前实际路径并完成共享 reader 与目录 validator。

| target | 同身份 staging | 后续行为 |
|---|---|---|
| 缺失 | 缺失 | 当前没有该 Answer；不补造终态，不复用同一 `answer_id`。 |
| 缺失 | 完整有效 | 持同一 mutex 再次全量验证并关闭全部 handle，确认 target 仍缺失后，只补做一次 non-replacing rename。 |
| 缺失 | 无效或不完整 | 原字节原位置隔离，正式消费者忽略。 |
| 完整有效 | 缺失或任意状态 | 正式 reader 接受 target；并存 staging 保持 target-conflict orphan 并报告。 |
| 无效、不完整或非法 target | 缺失或任意状态 | 正式 reader 整体拒绝 target；target 的存在阻止任何 staging 自动补交，两侧均不修复、覆盖、合并、删除或择优。 |

本策略以最近一次已报告成功的 Answer 在断电后仍可能缺失或无效、有效 staging 可能被无效 target conflict 阻断、孤立现场可能积累为代价，保持数据完整性门禁而不承担首版强制刷新与设备差异。这里的隔离始终是原路径上的逻辑忽略、拒绝与报告，不是物理移动；V1 不新增启动时全树 scrub，`knowledge ask` 仍只按既有规则扫描 staging，正式 reader 只在消费 target 时完整验证。拔电/系统崩溃后仍保留最近 Answer 不是 V1 验收条件；测试继续覆盖正常提交顺序、禁止 API 未调用、进程崩溃注入、recovery、冲突与正式 reader 的整体拒绝。以后增强保证必须另行冻结支持的文件系统/设备范围、完整 flush 顺序、失败语义、性能预算与 success acknowledgment 点，不能追溯重解释既有 v1 Answer。

## 根级资产封闭阶段前缀

从 `assets` 中取不含 `/` 的根级业务文件路径；由于 manifest 按定义不自列，该投影不包含根级 `manifest.json` 自身，也不包含已经由后文固定双文件矩阵闭合的 `attempts/NN/` 嵌套资产。Knowledge v1 只允许以下五个连续前缀：

```text
P0 = {effective_config.json}
P1 = P0 ∪ {question.json}
P2 = P1 ∪ {retrieval_query.json}
P3 = P2 ∪ {retrieval_audit.json}
P4 = P3 ∪ {retrieval_view.json}
```

每个 terminal Answer 至少且必须达到 P0；P1–P4 只能按顺序推进，不得跳过前项、倒序安装或组合任意已验证文件。`effective_config.json` 无法形成终态资产时没有合法最小前缀，因此不能提交 terminal Answer。`retrieval_audit.json` 在逻辑与进程内资产形成顺序上先于 View 冻结；`retrieval_view.json` 只有在完整 Schema、快照复验和 262144-byte 上限全部通过后才能推进到 P4。`retrieval_view_too_large` 固定停在 P3，超限的 would-be View 不得出现在 terminal `assets` 或最终根级路径中。

每个文件只有在规范值形成、确定性序列化、实现私有临时文件写入并关闭、实际 byte length 与 SHA-256 取得、Schema/media identity 和全部文件后置条件通过后，才可安装到最终根级名称并推进前缀。当前文件在任一步失败时不得进入 terminal `assets`，writer 只可提交最后一个完整前缀；crash recovery 不根据时间、残留 bytes 或文件名猜测进度，也不补齐前缀。若临时、部分、备份或其他未批准文件或目录无法在采集 `finished_at` 与写 terminal manifest 前安全关闭并从本次活跃 staging 撤销，实际目录就不能满足封闭资产清单，因此只能留下 staging。

在 P4 之后定义两个原子对：

```text
C = {prompt.txt, schema.json}
O = {answer_output.json, answer.md}
```

C 只能在 `retrieval_view.json.candidate_count` 为 `1..12`，并且 prompt、Schema、Question/View 调用包、有效配置与固定 runtime 参数全部通过 synthesis 前置复验后，才以最终名称成对安装。任一条件失败时两项都不得出现；`synthesis_input_invalid` 固定为 P4 且无 C。零 Candidate 分支、P0–P3 retrieval 终态也禁止 C。每个实际 launch attempt 必须 byte-for-byte 绑定该 Answer 的同一 C 对；`attempts` 非空必然推出 P4、C 完整且 Candidate 非零。

O 当且仅当 `status=succeeded` 时以最终名称成对存在；`blocked`、`failed` 与 `interrupted` 两项都禁止。通过 validation 的结构化输出在 rendering 与结果对全部后置条件完成前仍只是实现私有临时资产，不能先取得正式 `answer_output.json` 名称。C 或 O 安装到一半时，writer 必须在 terminalization 前撤销已安装成员；无法证明两项全有或全无时不得提交，只能留下 staging。

根级文件存在性必须且只能匹配下表；表中 `candidate_count` 只在 P4 存在时从已验证的 `retrieval_view.json` 读取，manifest 不复制该值：

| terminal 条件 | 连续前缀 | C | O | `candidate_count` | `attempts` |
|---|---:|---:|---:|---:|---:|
| `succeeded`，零 Candidate | P4 | 禁止 | 必须 | `0` | `[]` |
| `succeeded`，非零 Candidate | P4 | 必须 | 必须 | `1..12` | 1–3 项 |
| `blocked: fts5_unavailable` | P2 | 禁止 | 禁止 | 不适用 | `[]` |
| `blocked: retrieval_view_too_large` | P3 | 禁止 | 禁止 | 不适用 | `[]` |
| `failed: retrieval_query_failed` | P2 | 禁止 | 禁止 | 不适用 | `[]` |
| `failed: retrieval_materialization_failed` | P0、P1、P2 或 P3 | 禁止 | 禁止 | 不适用 | `[]` |
| `failed: synthesis_input_invalid` | P4 | 禁止 | 禁止 | `1..12` | `[]` |
| `blocked: codex_runtime_unavailable` | P4 | 必须 | 禁止 | `1..12` | 0–3 项 |
| 任一 Codex transient-exhausted `blocked` code | P4 | 必须 | 禁止 | `1..12` | 1–3 项 |
| `failed: codex_process_failed` | P4 | 必须 | 禁止 | `1..12` | 1–3 项 |
| `failed: answer_output_invalid`，零 Candidate | P4 | 禁止 | 禁止 | `0` | `[]` |
| `failed: answer_output_invalid`，非零 Candidate | P4 | 必须 | 禁止 | `1..12` | 1–3 项 |
| 任一 rendering 阶段 `failed` code，零 Candidate | P4 | 禁止 | 禁止 | `0` | `[]` |
| 任一 rendering 阶段 `failed` code，非零 Candidate | P4 | 必须 | 禁止 | `1..12` | 1–3 项 |
| `interrupted`，retrieval 尚未达到 P4 | P0、P1、P2 或 P3 | 禁止 | 禁止 | 不适用 | `[]` |
| `interrupted`，已达 P4 但 C 尚未形成 | P4 | 禁止 | 禁止 | `0..12` | `[]` |
| `interrupted`，C 已形成 | P4 | 必须 | 禁止 | `1..12` | 0–3 项 |

Confirmed capture overflow 复用 `failed: codex_process_failed` 行，不新增矩阵分支：当前 overflow attempt 必须是数组最后一项且 `failure_class=process_error`，之后禁止重试或新的 commitment；更早项只能是已经合法进入 retry 的瞬时失败。Final exact prefix 不得形成 O 或进入 Answer validation。

`blocked` 只允许表中的 retrieval/synthesis 行；validation/rendering 不产生 blocked。`failed` 的前缀必须与具体 `error.code` 及其固定 `error.stage` 行联合匹配，不能仅因同属一个 stage 而任选前缀。`interrupted` 继续要求 `error=null`，validator 直接按表中的有限前缀集合验证，不增加、猜测或复制 `terminal_phase` / `error.stage`。任何未列出的前缀、C/O 半对、后续组存在但依赖前缀缺失，或 `attempts`、Candidate 数与表不一致的组合都使 terminal manifest 无效，不能提交或由 crash recovery 补交。Attempt 子树还必须满足后文固定双文件矩阵；任何其他 `attempts/NN/*` 都是禁止的额外资产。

## manifest 不复制语义 answer_status

Answer terminal manifest 只拥有运行终态，不拥有回答语义状态。manifest 顶层必须且只能有一个运行终态字段，字段名精确为 `status`；它是必填、非 `null` 的 JSON string，值必须严格为 `succeeded`、`blocked`、`failed` 与 `interrupted` 四者之一。不得接受 `pending`、`running`、`busy`、大小写变体、空字符串或其他别名；不得提供默认值，也不得根据资产、错误、attempt 或目录内容反向推断、修复或改写。manifest 不得再出现 `terminal_status`、`run.status` 或任何第二份运行终态。

manifest 不得包含名为 `answer_status` 的字段，也不得以 `semantic_status`、布尔标记或其他等价摘要变相复制 `answered` / `insufficient_evidence`。

对 `succeeded` Answer，语义状态的唯一持久权威是已经通过 `gezhi.answer_output.v1` 完整验证的 `answer_output.json.answer_status`；历史查询、展示或筛选消费者必须读取并验证该文件，不能从 manifest、Candidate 数量、参考文献数量或渲染文本推断。ADR 0090 只允许产生本次 Answer 的 CLI 在目录 commit 成功后临时投影与正式文件逐规范 byte 相等的完整 `result.answer_output`，它不是第二持久事实源。对 `blocked`、`failed` 与 `interrupted` Answer，正式结果对按既有原子提交边界禁止存在，因此这些终态没有 `answer_status`，`result.answer_output` 也必须为 `null`，不得映射成 `insufficient_evidence`。

terminal validator 继续机械验证 `status` 与正式结果对的存在性不变量，但不从其他字段补出 `status`，也不把 `answer_status` 回写到 manifest。该分离保持 ADR 0046 的两个状态域各有唯一事实来源；代价是只读 manifest 的列表不能直接显示成功 Answer 的语义状态，确有需要时必须额外读取小型结构化结果文件。错误对象、时间字段与 attempt nesting 由后续已冻结章节分别拥有，并与 ADR 0083 的十一字段顶层闭包共同验证。

## manifest error 存在性矩阵

Answer terminal manifest 顶层必须包含字段名精确为 `error` 的必填字段；四种 `status` 下都不得省略。其值只能按以下矩阵出现：

| `status` | `error` |
|---|---|
| `succeeded` | 必须为 JSON `null` |
| `blocked` | 必须为 JSON object |
| `failed` | 必须为 JSON object |
| `interrupted` | 必须为 JSON `null` |

`succeeded` 即使包含先失败后成功的 Codex 重试，顶层 `error` 仍必须为 `null`；历史 attempt 的失败只属于 attempt 审计，不能冒充 Answer 终因。Knowledge v1 的 `interrupted` 当前只表示用户主动中断，顶层 `status` 已完整表达该终因，因此 `error` 必须为 `null`，不得制造 `user_interrupted` 错误码，也不得把中断前某次 attempt 的失败提升为 Answer error。以后若引入其他中断原因或要求顶层携带中断阶段，必须显式演进 manifest Schema，不能在 v1 object 中偷偷扩展。

`blocked` 与 `failed` 的 `error` 必须是非 `null` object，并严格使用下一节冻结的封闭两字段形状；不得用 string、array、number、boolean、空 object 或自行发明的 object shape 代替。validator 不得根据 `status` 补造 `error`，也不得根据 `error` 的有无反推、修复或改写 `status`；任何缺失或矩阵不一致都使 terminal manifest 无效，不能原子提交或由 crash recovery 补交。

## 封闭的 manifest error object

`status=blocked` 或 `status=failed` 时，非空 `error` 必须且只能是以下形状；所有字段必填且禁止额外字段：

```json
{
  "code": "<稳定错误码>",
  "stage": "<稳定阶段枚举>"
}
```

`code` 与 `stage` 都必须是非 `null` JSON string，并且只能取自下文冻结的各自封闭枚举。实现不得接受任意字符串、空字符串或自行发明值。两字段必须作为一个完整对象同时出现，缺少任一字段、增加任何第三字段，或将任一字段写成 `null`、number、boolean、array 或 object，都会使 terminal manifest 无效。

v1 明确禁止在 `error` 中预留或写入 `message`、`details`、`cause`、`traceback`、`exception_type`、`retryable`、绝对路径、Windows/provider 原始错误字段，以及始终为 `null` 的兼容占位字段。manifest 是稳定终态收据而不是日志；人用说明由 CLI 根据稳定 `code` 映射生成，不能持久化受语言、Windows 本地化、依赖版本或异常文本影响的 message。

Codex 原始事件和已经批准保留的失败现场继续受封闭资产清单约束；其他原始诊断只有在以后明确冻结独立、版本化、限长且经过敏感信息边界设计的审计资产后才能持久化，不能先塞入 manifest。未来确需新增 error 字段时必须升级 Answer manifest Schema，不能让 v1 reader 忽略未知字段。`code` 与 `stage` 的封闭枚举由紧随其后的章节冻结；CLI 文案映射与其他诊断资产 Schema 仍待后续决定。

## error.stage 四值领域阶段

`error.stage` 必须严格为以下四个 lowercase ASCII string enum 之一：

| `stage` | 精确边界 |
|---|---|
| `retrieval` | `answer_id` 已建立并创建 staging 后，从保存问题/搜索审计与准备检索开始，到完整、已哈希并通过预算和快照复验的 `retrieval_view.json` / `retrieval_audit.json` 形成结束。FTS 能力或查询失败、Candidate/Citation/Evidence/Descriptor/Governance 物化失败、Retrieval View 超限均在此阶段。 |
| `synthesis` | 从准备锁定的 Knowledge Codex prompt、Schema、CLI 与运行能力开始，到每个实际 attempt 的进程/provider 捕获、运行时正式资产复验、usage readiness、attempt 终态与十字段 item 已经确定，并据此进入重试、进入 validation 或锁存 Answer terminal cause 为止。登录、锁定 CLI、模型或能力不可用，network/429/5xx/timeout 耗尽，未知非零退出、进程树、事件捕获或 capture capacity overflow 均在此阶段。 |
| `validation` | 从 Codex 正常退出后的可选 final text，或零 Candidate 分支的 Python 确定性输出开始，到完整合法并通过规范 byte budget 的 `answer_output.json` 形成结束。final text 缺失或超限、JSON/Schema/字符串/Candidate/引用/状态/跨字段校验失败均在此阶段。 |
| `rendering` | 从已经验证的 `answer_output.json` 开始，到完整 `answer.md` 通过引用集合、编号、链接、escaping、模板、byte budget 与全部确定性后置条件结束。 |

Codex 正常退出但没有 final text 属于 `validation`；进程、transport 或 provider 事件捕获本身失败属于 `synthesis`。Retrieval View 中的 Citation 快照不合法属于 `retrieval`，模型返回的引用绑定不合法属于 `validation`，已经合法的引用在 URL 或 Markdown destination 构造时失败属于 `rendering`。零 Candidate 分支跳过 `synthesis`，但仍经过 `validation` 与 `rendering`。

v1 不增加 `input` 或 `coordination`，因为 Question、查询原子、数据根身份与 writer mutex 在生成 `answer_id` 前失败时没有 Answer terminal manifest；也不把 `retry`、`transport`、`timeout`、`process`、`filesystem`、`database`、`codex` 或 `usage` 当作阶段，这些是故障类别、实现组件或不独立构成领域阶段的审计属性。文件写入失败按当时正在形成的领域资产归入上述四阶段；token 值缺失或畸形本身继续不产生 Answer error，而 usage readiness 仍属于 `synthesis` 的既有时限边界。孤立 staging recovery 只判断或完成既有提交，不产生新的 recovery Answer，因此没有 `recovery` stage。

v1 也不设置 `commit` 或 `publication` stage。terminal manifest 必须在原子改名前已经完整写入、验证并关闭；manifest 自身写入/验证失败或目录原子改名失败时，系统无法诚实提交一份描述自身提交失败的 terminal Answer，只能按 ADR 0051/0053 留下 staging。未来若设计第二套独立事务来发布提交失败记录，必须升级 manifest Schema，而不能给现有四值枚举偷加第五值。

每个稳定 error `code` 必须在后续错误码表中静态绑定唯一一个 `status` 与唯一一个 `stage`；validator 按冻结表验证 `(status, code, stage)`，运行时不得依据函数名、最后一条事件、异常文本或 attempt `failure_class` 猜测或改写 stage。本节不冻结 error code 全集。

## error.code 封闭表

Answer terminal manifest 的非空 `error.code` 必须严格取自以下 15 项 lowercase ASCII string enum；每个 code 只允许表中唯一的 `status` 与 `stage` 组合：

| `code` | `status` | `stage` |
|---|---|---|
| `fts5_unavailable` | `blocked` | `retrieval` |
| `retrieval_view_too_large` | `blocked` | `retrieval` |
| `retrieval_query_failed` | `failed` | `retrieval` |
| `retrieval_materialization_failed` | `failed` | `retrieval` |
| `codex_runtime_unavailable` | `blocked` | `synthesis` |
| `codex_timeout_exhausted` | `blocked` | `synthesis` |
| `codex_network_exhausted` | `blocked` | `synthesis` |
| `codex_rate_limit_exhausted` | `blocked` | `synthesis` |
| `codex_server_error_exhausted` | `blocked` | `synthesis` |
| `codex_transient_exhausted` | `blocked` | `synthesis` |
| `synthesis_input_invalid` | `failed` | `synthesis` |
| `codex_process_failed` | `failed` | `synthesis` |
| `answer_output_invalid` | `failed` | `validation` |
| `citation_link_construction_failed` | `failed` | `rendering` |
| `answer_rendering_failed` | `failed` | `rendering` |

manifest 的 `code` 只保存表中的裸值；合同和人用文档里的 `blocked: code` / `failed: code` 只是 `status` 与 `code` 的显示简写，冒号、空格与状态前缀不得进入 JSON 字段。表外 code、大小写变体、别名或合法 code 与错误 `status` / `stage` 的组合都使 manifest 无效；validator 不得纠正、猜测或用近似 code 代替。新增、删除、拆分、合并或改变任何映射都必须升级 Answer manifest Schema。

四个新增的最小闭合 code 边界如下：

- `codex_runtime_unavailable`：锁定的 Codex CLI、登录、模型或必要运行能力不可用；这是可由用户修复环境后重新提问的 `blocked`，不得伪装成进程失败。
- `synthesis_input_invalid`：已经选定并应锁定的 prompt、Schema、Question/View 调用包不能按冻结合同形成或复验；这是确定性本地输入构造失败，不创建语义重试。
- `answer_output_invalid`：统一覆盖 final text 缺失或超限、leading BOM、非严格 UTF-8、不是唯一 JSON object、JSON/Schema/字符串/Candidate/引用/状态/跨字段校验失败，以及规范 `answer_output.json` byte budget 失败；首版不按每条 validator 规则拆出更多终态 code。
- `answer_rendering_failed`：覆盖除 `citation_link_construction_failed` 之外的 escaping、可信模板、引用集合/编号、Markdown byte budget 或渲染后置条件失败；已命名的链接构造失败始终使用更具体 code。

`codex_process_failed` 覆盖所有未被 runtime-unavailable 或四类瞬时耗尽明确分类的本地 Codex 进程生命周期、进程树终止与 provider 事件捕获失败，包括完整 `events.jsonl` 的 leading BOM、非严格 UTF-8 或无法建立必需事件流结构；不得把模型自然语言或未知 stderr 文本猜成 transient code。它也按 ADR 0080 覆盖已经完成安全收尾的 confirmed capture overflow，并固定使用 `status=failed`、`stage=synthesis`，不增加第 16 个 code。已有五个 Codex 耗尽 code 继续按前文冻结的 non-overflow attempt 分类和混合优先级选择。

`retrieval_query_failed` 专用于已开始的 FTS/SQL 检索执行异常。`question.json`、`retrieval_query.json`、`retrieval_view.json` 或 `retrieval_audit.json` 在规范 object 形成、确定性序列化、临时文件写入、关闭、原子就位、byte length/SHA-256 计算或既有后置条件复验中的失败，统一使用 `retrieval_materialization_failed`；这扩展的是既有码的 retrieval 资产物化边界，不新增通用 filesystem code。若 terminal manifest 自身无法形成、写入、验证或关闭，则仍不能提交一份自述该失败的 Answer，只能留下 staging。

`invalid_question`、`question_too_large` 与 `question_too_complex` 在生成 `answer_id` 前返回，不进入 Answer manifest；`reader_input_invalid` 属于 Literature Reader，上游未拦截而在 Knowledge 快照复验中发现的对应问题使用 `retrieval_materialization_failed`。attempt 的七个非空 `failure_class`——`timeout`、`network`、`rate_limit`、`server_error`、`runtime_unavailable`、`process_error` 与 `interrupted`——都不是顶层 error code；`insufficient_evidence` 是成功 Answer 的语义状态，也不是 error code。

## manifest.answer_id 身份绑定

每个 Answer terminal manifest 顶层必须包含必填、非 `null` JSON string `answer_id`。其值必须完整匹配以下 ASCII 正则，也就是带标准连字符、lowercase hexadecimal、RFC 4122 variant 的 UUIDv4，并以 `ans_` 开头：

```text
^ans_[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$
```

不得接受大写、花括号、无连字符 UUID、其他 UUID version、首尾空白、Unicode lookalike，或经过 trim、大小写折叠、Unicode normalization、解析再格式化后才“等价”的输入。`answer_id` 从生成起就是 40 个 ASCII byte 的规范值，validator 只能比较原值，不能规范化或修复。

正常写入时，编排器持有的 expected `answer_id`、安全验证后的 `answers/.staging/<answer_id>/` 直接子目录 basename 与 `manifest.answer_id` 必须逐 ASCII byte 完全相等。提交目标只能是同一 Knowledge 数据根下 basename 不变的 `answers/<answer_id>/`；原子提交只移除路径中的 `.staging` 层。不得仅信任 manifest 值构造任意路径，也不得在三者不等时选择一方为权威、重命名目录、重写 manifest 或大小写修复。目标冲突继续按既有原子提交规则拒绝覆盖。

正式读取时，安全验证后的 `answers/<answer_id>/` 直接子目录 basename 必须与 `manifest.answer_id` byte-for-byte 相等；任何不符都使整个 terminal Answer 无效，正常消费者不得读取其结果。Crash recovery 必须先证明候选 staging 是 `.staging/` 下安全、非 reparse 的直接子目录并验证 basename 正则，再读取 manifest 并要求等值，最后只从已经验证的同一个 basename 导出目标；不符时原目录保持孤立，禁止补交、改名、移动或修补。

目录 basename 是物理 locator，manifest 字段是不可变终态收据中的身份绑定；二者均不可原位修改且不一致即整体拒绝，因此不是两个可独立演进的事实来源。四种运行终态都必须包含该字段；`question.json`、Retrieval View、`answer_output.json` 与 `answer.md` 不复制 `answer_id`。

v1 不增加 `question_id`：Question 不是独立聚合，相同问题每次都产生新的 Answer。也不增加 `run_id`：一个 `answer_id` 已对应一次不可变终态执行，Codex 重试只是 attempt，不能重新引入 ADR 0051 已排除的 `runs/current` 模型。`conversation_id`、`parent_answer_id` 已由 QuestionEnvelopeV1 排除；Codex/provider session 或 request ID 只可属于后续 attempt 审计合同，不是 Answer 领域身份。

## Answer 级时间字段

每个 Answer terminal manifest 顶层必须包含 `started_at`、`finished_at` 与 `elapsed_ms`，四种运行终态下都必填且不得为 JSON `null`。

`started_at` 与 `finished_at` 必须是固定 24 个 ASCII byte 的 UTC string，完整匹配：

```text
^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$
```

正则匹配后还必须通过真实 proleptic Gregorian 日期时间校验：year 为 `0001..9999`，hour 为 `00..23`，minute 与 second 为 `00..59`；不接受 leap second `60`。小数部分恰好三位毫秒，只接受大写 `T` 与 `Z`；`+00:00`、其他 offset、空格、缺失或额外小数位都无效。Python 使用 timezone-aware UTC datetime；序列化到毫秒时直接截断亚毫秒部分，不四舍五入。

`started_at` 在成功生成规范 `answer_id` 后立即采集，并早于 staging 创建、任何本次 Answer 资产写入或检索开始；writer mutex 获取与孤立 staging 扫描不属于本次 Answer 生命周期。`finished_at` 在运行终态、`error` 与全部应保留的非 manifest 资产已经确定、验证并关闭后，开始生成 terminal manifest 前采集；它表示终态内容冻结时间，不是 manifest 写入完成或目录原子改名成功时间。v1 不增加 `created_at`、`committed_at`、时钟 offset 或 `clock_regressed` 字段。

`elapsed_ms` 必须是 `0..9223372036854775807` 的 JSON integer；JSON boolean、float、string 与 `null` 均无效。编排器在上述两个生命周期边界各读取同一进程的 Python `time.monotonic_ns()`，并固定计算：

```text
elapsed_ms = (finished_monotonic_ns - started_monotonic_ns) // 1000000
```

结果向下取整，不足 1 ms 合法地记为 `0`；不得从两个 UTC timestamp、attempt 时长之和或文件时间推算。单调差为负、超过上限或无法取得时不能形成有效 terminal manifest，不得钳制为零、改用墙钟或填入 `null`。

系统墙钟可能因用户修改或校时回拨，因此允许 `finished_at` 在日历顺序上早于 `started_at`。validator 不要求二者有序，也不要求墙钟差与 `elapsed_ms` 相等或接近；不得交换、钳制、修补时间，或由 `started_at + elapsed_ms` 合成 `finished_at`。`elapsed_ms` 是持续时间的唯一权威，两个 UTC 字段只用于审计与排序提示。

可控用户中断在尚未锁存其他 Answer terminal cause 时先赢得下文线性化裁决，才可以提交完整 `interrupted` manifest。若它发生在没有观察到 capture overflow 的 active attempt，必须先按生命周期完整性门禁停止并确认子进程树、关闭 collectors 和应保留资产：完整性失败得到 `failed: codex_process_failed`，始终无法确认安全收尾则只留下 staging；不得为了迎合用户取消而伪造干净 `interrupted`。若同一 active attempt 在 capture-finalization boundary 前锁存 overflow，则按 ADR 0079 安全收尾；边界成立后 overflow 覆盖中断并固定得到 `failed: codex_process_failed`，边界始终无法成立时仍只留下 staging。若其他 Answer terminal cause 已先锁存，晚到取消不改写它；正确实现不得在 active attempt 的 overflow monitor/collector 尚未 join 时抢先锁存顶层终因。随后才采集 Answer 结束边界并形成对应 terminal manifest。进程崩溃若发生在完整 terminal manifest 形成前，只留下未完成 staging，不得以 `finished_at=null` 伪造终态；若字面 manifest 已存在，则只能按共享 reader 判断其是否构成可补交终态。Crash recovery 只验证三字段的类型、格式与范围并原样补交既有 terminal commit，不重新计算或改写；这些时间不得用于判断 mutex owner 存活、staging 年龄、提交先后或恢复发生时间。

## 运行 provenance

每个 Answer terminal manifest 顶层必须包含以下封闭 `provenance` object；`provenance` 与嵌套 `git` 均禁止额外字段，列出的字段全部必填：

```json
{
  "codex_cli_version": "0.146.0",
  "git": {
    "revision": null,
    "state": "unborn"
  },
  "model": "gpt-5.6-sol",
  "reasoning_effort": "high",
  "role_version": "knowledge_answerer_v1"
}
```

`role_version`、`model`、`reasoning_effort` 与 `codex_cli_version` 都是非 `null` JSON string，v1 必须分别严格等于 `knowledge_answerer_v1`、`gpt-5.6-sol`、`high` 与 `0.146.0`。这些值表示本 Answer 在生成身份前已经绑定的项目角色与请求配置，不证明 Codex 进程实际启动或远端服务接受了请求；零 Candidate、retrieval 阶段终止或 `codex_runtime_unavailable` Answer 也照常记录同一组绑定值。`model` 只表示发送给 Codex 的在线 selector，不是不可变服务端 build、权重版本或 fingerprint；v1 不增加 `resolved_model`。

`git.state` 必须严格为 `clean`、`dirty` 或 `unborn`：

- `clean` 与 `dirty` 时，`git.revision` 必须是当前 HEAD object ID 的恰好 40-character lowercase ASCII hexadecimal string；`clean` 要求 index 与 worktree 都无变化，`dirty` 包括 staged、tracked unstaged 与所有非 ignored untracked 项。
- `unborn` 只表示当前仓库尚无首个 commit，此时 `git.revision` 必须为 JSON `null`。

其他组合均无效：有 HEAD 时不得用 `null` 隐藏 dirty 状态，`unborn` 不得携带 revision，Git 查询失败、输出非法或仓库状态无法确定也不得伪装成 `unborn`。Provenance 必须在生成 `answer_id` 前完成；无法形成该 object 时不建立 Answer，并返回 `knowledge.ask.provenance_unavailable.v1` 与空 context。成功形成后必须冻结并在 ID 后原样复用，不能在持锁期间或 ID 后重新查询 Git；validator 不得 trim、大小写转换、缩短 object ID 或从目录内容猜测 Git 状态。

provenance 不记录 Git branch、tag、remote URL、author、email、commit message、changed path、diff 或工作树 digest。`dirty` / `unborn` 诚实表示不能仅靠 revision 复现实际代码；v1 不把这种状态自动变成 blocked，也不对可能含未跟踪秘密的内容计算指纹。若以后需要强制 clean 运行，应另立前置门禁而不是伪造 revision。

整个 provenance 以及后续有效配置均不得保存或散列 API key、token、cookie、代理凭据、Codex 登录/账户/组织/项目、`.env`、环境变量名或值、配置来源层、CLI argv、用户名、机器名、项目根、数据根、可执行文件、临时目录、缓存路径、Question、检索投影或插入了 Question 的动态 prompt。不得以长度、`present=true`、占位符或秘密 hash 间接披露这些值。Prompt/Schema 的公开快照与哈希由封闭资产清单拥有。原样 `events.jsonl` 可能不可避免地携带 provider 分配的 thread/session/request ID 或结构化诊断，它是唯一获准的不透明本地审计窄例外；实现不得提取、复制、索引、展示、遥测或把这些值提升到 manifest、provenance、独立文件及其他数据结构。

## manifest-bound 有效配置资产

共享 configuration resolution 必须同时验证所有 Context Data Root 的 namespace 隔离：规范化 Windows path namespace 两两不同且互不嵌套；任一 root 都不得等于或包含项目根 `E:\Gezhi`；项目内 root 必须是 `E:\Gezhi\data` 的严格后代而不能直接使用该共享容器，项目外本机 root 仍允许。未来 Context 同样受该 pairwise rule 约束。全部 source 合并后，能够无文件系统 I/O 纯词法归一为本机 DOS 绝对路径的 final values 若已经相同、嵌套或侵犯项目边界，Configuration gate 选择 `configuration_invalid`；无法在此层形成受支持本地绝对路径的 namespace 留给 Data Root gate。文本通过后，只有 safe open 的 reparse evidence、handle-derived final path 或 physical identity 才能证明的隐藏别名、真实对象重合/嵌套或物理边界冲突选择 `data_root_unsafe`。Configuration gate 禁止为此访问文件系统。

每个 Answer 根目录必须保存大小写精确的根级普通文件 `effective_config.json`。它只是 `knowledge_answerer_v1` 自己拥有的非秘密 runtime 配置安全投影，不是整个 Gezhi settings、Pydantic model 或配置来源的通用 dump；内容必须且只能是：

```json
{
  "attempt_timeout_ms": 1800000,
  "attempt_window_limit_ms": 5700000,
  "retry_backoff_schedule_ms": [10000, 30000],
  "schema_version": "gezhi.knowledge_answerer_effective_config.v1"
}
```

object 封闭，四个字段全部必填且非 `null`；四个字段名必须大小写精确。两个 timeout/limit 字段是 JSON integer，分别严格等于 1800000 与 5700000；JSON boolean 或 float 无效。`retry_backoff_schedule_ms` 是长度恰好为 2 的 array，两项 JSON integer 按顺序严格等于 10000 与 30000，分别用于第一次和第二次可重试失败后；最大 attempt 数只由 `1 + len(retry_backoff_schedule_ms) = 3` 派生，不再保存可能漂移的 `max_attempts` / `max_retries`。`schema_version` 必须严格等于 `gezhi.knowledge_answerer_effective_config.v1`。

文件 bytes 固定使用 Python 3.11 `json.dumps(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))` 的 UTF-8 编码，禁止 BOM 和物理 CR，并在规范 JSON 后追加恰好一个 LF。manifest `assets` 必须以 `path=effective_config.json`、实际 `byte_length`、覆盖包括最终 LF 在内全部实际 bytes 的 SHA-256，以及 `schema_id=gezhi.knowledge_answerer_effective_config.v1` 绑定该文件。配置文件不保存自哈希，manifest 顶层不嵌入第二份配置，也不增加重复 `config_sha256`。

External deployment configuration 只能在 CLI 参数、`GEZHI_*` 环境、local TOML、default TOML 与程序安全默认值按 ADR 0029 的优先级完成严格解析。内置安全默认值是完整可信基线；default TOML 是必需的版本化 partial patch，local TOML 是可选的版本化 partial patch，CLI/env 是不允许设置 `config_version` 的无版本 partial raw patch。Active TOML 的 version grammar 精确为 `gezhi.config.vN`，当前只支持 `gezhi.config.v1`，且 default/local generation 必须相同；metadata 不进入 final runtime config 或本资产。Source 必须按上述高到低顺序发现和验证；local 合法缺席跳过，default 缺失无效，第一个 active source 的错误停止后续 source。每个 patch 只验证 source-owned required key 与实际提供字段；全部 source 通过后，closed configuration Schema 对每个已知 leaf path 选择最高优先级第一个 present value。Nested table 只覆盖 present leaf，scalar 与 array 原子整体替换，不拼接、不逐项 merge；V1 没有 null/unset/delete/tombstone，空字符串是 present value。Final runtime config 只有 nonempty string `literature.data_root` 与 `knowledge.data_root`，完整内置默认值分别为 `E:\Gezhi\data\literature` 与 `E:\Gezhi\data\knowledge`；unknown Context/table/leaf 无效。本命令只消费冻结的 `knowledge.data_root`，但同一次 shared configuration resolution 仍按全局 closed Schema 验证两个 leaf。Final required/cross-field 规则只对合并结果执行；`.env` 秘密加载不参与本 merge。

本节的 `effective_config.json` 不从 external deployment config 投影。它由 immutable `knowledge_answerer_v1` role descriptor 正向构造，且只保存本节已经锁定的 timeout/window/backoff audit values。Model、reasoning、Codex CLI version、attempt count、检索/捕获/Schema/cap 与全部其他 role/runtime policy 都不是 configuration field；任何 TOML、CLI 或 `GEZHI_*` source 提供这些名称时作为 unknown field 选择 `configuration_invalid`，不得建立“只接受固定值”的假配置旋钮。`configuration_incompatible` 在 V1 只覆盖 grammar-valid unsupported `config_version` 或 active TOML generation mismatch。Configuration gate 成功时必须同时冻结已验证 deployment config 与 role descriptor 生成的 canonical `effective_config.json` bytes；ID 后只写同一 bytes，不能重新读取 source、dump settings 或重新构造。Role descriptor/bytes 构造或其他内部机械失败不伪装成 blocked；能够安全收尾并形成 handled envelope 时留给 no-commit `failed`，否则可能位于正常矩阵外。具体 external patch/final 字段闭包由实现前的 concrete configuration contract 冻结。

该资产不复制 provenance 已拥有的角色、模型、reasoning、Codex CLI 与 Git，也不复制 role/Schema 已冻结的 Candidate 上限、检索算法、byte budget、sandbox、工具、网络或 retryable failure class。它不得包含或散列任何路径、配置来源层、环境变量名/值、CLI argv、用户名、机器名、Question、检索内容、凭据、Codex 登录或这些值的长度、占位符和 presence flag。任何以后真正影响 Answer 行为且需要成为可变配置的新键，都必须升级本资产 Schema、Answer manifest Schema 与允许资产矩阵；影响语义时还必须升级 role version。

四种 Answer 终态与零 Candidate 分支都必须保存该文件，因为 role descriptor 的有效 runtime 审计 bytes 在 `answer_id` 生成前已经绑定。该规则细化 ADR 0029 的运行收据边界：role runtime audit 以 manifest-bound 封闭资产保存，manifest 通过 path、Schema identity、byte length 与实际文件 SHA-256 记录其 bytes；不把同一 object 再嵌入 manifest，也不把 Data Root 等 deployment config 混入本资产。读取器与 crash recovery 必须同时验证文件 Schema、规范 bytes 与 asset entry。

## attempts 有序 launch 序列

每个 Answer terminal manifest 顶层必须包含非 `null` JSON array `attempts`；四种终态均不得省略，长度只能为 0–3。上限由 `1 + len(effective_config.retry_backoff_schedule_ms) = 3` 派生，不增加 `attempt_count`。

Attempt 的领域身份固定为 `(answer_id, ordinal)`，其中 `ordinal = attempts array index + 1`。数组顺序就是不可变创建顺序，不能按时间、结果或 failure class 重排；attempt 严格串行，不得并发或跳号。manifest item 不保存 `attempt_number`、`attempt_no`、`attempt_id`、provider session/request ID、path 或 asset prefix，避免与数组位置形成第二身份源。

ordinal 唯一派生固定两位 ASCII 十进制资产前缀：第一项对应 `attempts/01/`，第二项对应 `attempts/02/`，第三项对应 `attempts/03/`。不得出现 `attempts/00/`、第四项、其他零填充形式或 array 中没有对应 item 的 attempt 目录资产。Attempt 摘要只存在于 manifest array item；v1 不创建重复 `attempts/NN/attempt.json` 或子资产清单，根级 manifest `assets` 是唯一文件清单。每个 ordinal 的固定双文件存在规则由下一节冻结；这不重新打开已经冻结的根级 C 对。

### Attempt 固定双文件捕获资产

令 `n = len(manifest.attempts)`。当 `n=0` 时，Answer 目录中不得存在 `attempts/` 目录或任何该前缀资产；当 `n>0` 时，全部且仅有的 attempt asset path 集合必须精确等于：

```text
for ordinal in 1..n:
    attempts/<two-digit ordinal>/events.jsonl
    attempts/<two-digit ordinal>/final_message.txt
```

因此一个、两个或三个 committed attempts 分别严格产生 2、4 或 6 个 attempt assets；两个文件对每个 ordinal 都必须同时列入根级 `assets`、实际存在并通过 byte length、SHA-256 与固定 media identity 复验，任一文件都独立允许 0 bytes。不得以空文件反推 attempt 是否成立或具体 process error 原因；attempt 身份仍只来自 manifest array 位置。目录集合继续由这些实际路径唯一隐含，禁止空 ordinal、跳号、额外 ordinal、更深层级或任何第三个文件。

上述两个 path pattern 的每个 asset item 都必须含逐字精确、无参数的 `"media_type":"application/octet-stream"`，同时必须省略 `schema_id` key。该值不因 bytes 为空、合法、畸形或截断，也不因 `failure_class`、Answer 终态或文件扩展名而改变；`application/jsonl`、`application/x-ndjson`、`application/json`、`text/plain`、任何参数、大小写变体与其他值都无效。资产 identity pass 只复验该固定 identity、路径/成对存在、实际 byte length 和 SHA-256，不执行解码、BOM、换行、JSONL 或 final Answer validation；terminal validator 与 recovery 在 identity pass 完成后，仍必须按 ADR 0081 对低于 cap 的正式 events 运行 usage semantic pass。因此 `application/octet-stream` 不证明内容有效，也不放宽后续语义层规则。

`events.jsonl` 定义为本地 stdout collector 对该次 `codex exec --json` 专用 stdout pipe 实际取得的原始 bytes；`final_message.txt` 定义为本地 final collector 对 `--output-last-message` 通道实际取得的原始 bytes。ADR 0106 另行冻结 prompt 使用专用 stdin pipe、stderr 使用 `NUL`，两者均不是 capture。两个正式文件是 capture transcript，不声明 Codex/provider 必然产生过事件、消息或文件：CreateProcess failure、通道未建立或没有输出时，对应 capture 规范为 empty bytes。除已经证明 capacity overflow 时按 ADR 0078 形成 exact cap prefix 的唯一例外外，writer 不注入 header、缺失标记、截断标记或补充 LF，也不重排、重序列化、脱敏、主动截断或从另一通道合成内容；任何情况下都不得为了满足 validation 改写捕获 bytes。既有 65536-byte final text budget 只决定 Answer validation 是否通过，不是捕获文件的截断上限；capture retention 的保证范围由 ADR 0076 冻结，逐文件 cap 与包含边界由 ADR 0077 冻结，overflow prefix 表示由 ADR 0078 冻结，cap+1 witness、Job stop 与 mechanical drain 由 ADR 0079 冻结，classification/top terminal/nonretry 由 ADR 0080 冻结，正式 events 的 usage 长度门禁由 ADR 0081 冻结；overflow 外部诊断继续后续冻结。

可安全关闭、读取并哈希的 0-byte `events.jsonl` 是产生零条 record 的合法 asset，不能由 framing 层单独选择 failure class；其终态由完整 event/terminal matrix 决定。对于没有 capture overflow 且完整捕获的事件流，leading BOM、非严格 UTF-8、非法 framing/JSON、语法不完整 EOF tail 或已知 collector truncation 是导致 `process_error` 的实际捕获现场；clean EOF 下没有末尾 LF 但最后 object 完整不是截断。资产层 validator 不能因任何语义结果拒绝合法 path/hash，event 编码/结构与 `failure_class` 的一致性由 attempt validator 单独判断。对于没有观察到 capture overflow 的 attempt，若 collector I/O 或已知完整流捕获失败，但两个捕获 sink 最终都能安全关闭、读取、哈希并成对安装，则保留实际取得的 bytes 并分类为 `process_error`；这种未持久化生命周期事实不改变 ADR 0081 的 usage gate，低于 cap 的正式 bytes 若自身严格合法仍可投影 usage，validator/recovery 也不得从 `process_error` 反推 truncation。若任一 overflow latch 成立且 capture-finalization boundary 通过，则无论并存 collector/event 事实如何都按 ADR 0080 固定为最高优先级 `process_error` 且不重试。若任一 sink 无法达到该边界，或双文件安装到一半且无法撤销，则无论是否 overflow 都不能冻结完整 item、写 terminal manifest 或由 recovery 补齐，只留下 staging。

对于非零 Candidate，只有结束 synthesis 且 `failure_class=null` 的最后一个实际 attempt 的 `final_message.txt` 才能作为 Answer validation 输入；更早 attempt、非空 failure attempt、`events.jsonl`、stderr 与任何临时副本都不得成为回退来源，也不因 final 的编码内容重新分类。Eligible 文件为 0 bytes、leading BOM、非严格 UTF-8 或不符合后续 Answer 规则时得到 `answer_output_invalid`，但 attempt 仍为 `failure_class=null`；timeout、interrupted、provider/process failure 或 confirmed overflow 即使捕获文件中出现看似完整结果，也不得进入 validation、复用到下一次 attempt 或发布为正式 Answer，overflow final exact prefix 永远不是 eligible final。

首版禁止在 attempt 子树或 manifest 中持久化、散列或以 presence/length 侧写 stderr、argv、环境、独立 provider session/request/thread ID、session state、`attempt.json`、stdout 副本、逐 attempt prompt/schema、response schema 临时副本、临时/备份文件及其他诊断。ADR 0106 已把 stderr 唯一导向 `NUL`，禁止从中分类或重建输出。原样 `events.jsonl` 内不可避免的 provider ID 与结构化诊断只按前文不透明审计例外存在，不得提取或传播。两个 capture 的严格 UTF-8、不修复语义门禁由 ADR 0074 冻结，event record framing 由 ADR 0075 冻结，retention 保证范围由 ADR 0076 冻结，逐文件 cap 与包含边界由 ADR 0077 冻结，overflow 的 exact-prefix retention 由 ADR 0078 冻结，witness、Job stop 与 mechanical drain 由 ADR 0079 冻结，分类、优先级、不重试与顶层映射由 ADR 0080 冻结，正式 events 的 usage 长度门禁由 ADR 0081 冻结；invocation-local 外层载体已由 ADR 0089 选定，共享 diagnostic item/cap/敏感信息 profile 已由 ADR 0091 冻结，committed `codex_process_failed` primary 已由 ADR 0092 冻结；capture-overflow 专属 supplemental context 与任何持久形式继续后续冻结，在这些边界冻结前不得由实现自行选择。

### Attempt capture retention 保证范围与逐文件 cap

该保证只量化单个已经原子提交的 terminal Answer 中，由根级 `manifest.assets` 列出的 `attempts/NN/events.jsonl` 与 `attempts/NN/final_message.txt` 普通文件主数据流。限制以正式资产的逻辑 byte length 为度量，并且必须在 staging 内、形成 terminal manifest 与执行同卷原子改名前通过验证；提交后不得为了满足限制再截断、改写或替换不可变资产。该度量不声称覆盖 NTFS 分配簇、目录项或其他文件系统元数据。

每个 launch-committed attempt 的两个上限逐文件独立且包含端点：

| 正式 asset path | 合法 `byte_length` | 精确 cap |
|---|---:|---:|
| `attempts/NN/events.jsonl` | `0..16777216` | `16,777,216 bytes = 16 MiB` |
| `attempts/NN/final_message.txt` | `0..1048576` | `1,048,576 bytes = 1 MiB` |

长度恰等于 cap 合法；只有确认存在第 `cap + 1` 个 byte，也就是逻辑长度大于 cap，才满足 capture overflow 谓词。长度恰等于 events cap 不证明 overflow，但 ADR 0081 为保证 usage 可由正式资产唯一复验，保守地令该 attempt 四项 token 全为 `null` 且 `usage_unavailable=true`；这项 usage-only 门禁不改变 capture 或终态分类。两项额度不得在同一或不同 attempt 之间互借。令 `n = len(manifest.attempts)`，则正式 capture 资产合计最多为 `n * 17,825,792 bytes`；`n=3` 时是 `53,477,376 bytes = 51 MiB`。这个值只是两项逐文件 cap 与最多三次 attempt 的算术推论，不是第三个 aggregate quota，也不包含根级业务资产、`manifest.json` 或 ADR 0076 已排除的对象，因此不是整个 Answer 的大小上限。

这些 cap 是版本化 `knowledge_answerer_v1` role-owned contract constants，不进入 `effective_config.json`，也不增加 manifest 顶层、attempt item、asset item、marker 或 sidecar 字段；`manifest.assets[*].byte_length` 只记录实际逻辑长度，writer、terminal validator 与 recovery 按本合同常量复验。`final_message.txt` 的 `1 MiB` retention cap 不替代 eligible final 的 `65536-byte` validation budget：实际长度 `65,537..1,048,576` bytes 不是 retention overflow，但 eligible final 仍按既有规则得到 `answer_output_invalid`。

一旦某一 capture 已确认存在第 `cap + 1` 个 byte，该路径的正式资产必须是同一原始 byte sequence 的 `source[0:cap]` exact prefix，实际 `byte_length` 恰好等于自身 cap。第 `cap + 1` 个 witness byte 和其后 tail 不进入正式资产；writer 不添加 marker、header、说明文字、BOM 或 LF，不重编码、规范化、补齐 UTF-8 code point、拼接 JSON record 或回退到较早边界。Prefix 因此允许结束在 UTF-8 sequence、JSON token 或 event record 中间，hash 只覆盖原样 prefix。若只有一项 overflow，另一项按自身实际 capture 形成；两项都 overflow 时分别使用自己的 exact prefix，固定双文件仍成对安装。

Exact-prefix retention 是唯一的 capacity-driven 主动截断例外，只能用于已证明的 overflow，不能用于修复 collector I/O、编码、framing、JSON、Schema 或 Answer validation 失败。Overflow prefix 是审计资产，不证明完整通道语义有效，也不得通过解析恰好有效的 prefix 来清除已经观察到的 overflow `process_error`；final prefix 永不进入 Answer validation。Events exact prefix 必然达到 cap，因此 ADR 0081 的 usage consumer 不对它执行解码、framing、JSON 或投影并固定得到四项 `null`；相同 usage 结果也适用于不是 overflow 的 exact-cap clean EOF，不能据此把后者反推为 prefix 或 overflow。本规则不增加 marker、sidecar、asset path 或 manifest/attempt 字段。

`--output-last-message` 的 writer-private spool、没有 owner 的 orphan staging、全部历史 Answer 的累计占用、Answer 根与 Knowledge 数据根的总占用都不在该保证的量词域内；这不是允许无限写入或忽略 I/O 故障，既有安全收尾、封闭资产、原子提交、不可变历史和保守 recovery 规则全部继续适用。完整 spool 仍必须按前文限定在当前 Answer 的活跃 staging 私有命名空间，不能成为正式资产或备用 validation 来源；发生 final capture overflow 时，在 ADR 0079 的 Job 安全收尾以及 source 关闭后，只能从 offset 0 形成 final exact prefix，并在采集 `finished_at`、形成 terminal manifest 与原子提交前撤销完整 spool、overflow tail 和全部私有临时文件。两个正式 sink 必须安全关闭、读取、哈希并成对安装；任一环节失败或私有文件无法撤销时只能留下 staging。Crash recovery 不得从 orphan source 或 oversized spool 截取 prefix、删除 tail、修复或补造资产，只能按既有规则复验并补交已经拥有完整有效 terminal manifest 的结果。首版不增加有界 staging 卷、目录 quota 或新 final streaming 接口，timeout 与单写者 mutex 也不是 byte quota。

每个 attempt capture 都有进程内、逐通道且不可逆的 overflow latch。Events collector 按原始 binary chunk 到达顺序只把仍可容纳的 `min(chunk_length, cap - retained_length)` bytes 写入 prefix sink；只有同一 chunk 还有剩余 byte，或恰好 cap 后又实际读到下一次非空 chunk，才以真实第 `cap + 1` 个 byte 锁存 overflow。恰好 cap 后 EOF 不 overflow。锁存后 events pipe 仍机械读取到 EOF，tail 直接丢弃且不解析/哈希；final overflow 触发停止时，未 overflow 的 events 通道仍保留 drain 实际取得的 bytes 直到自身 cap。

Final spool 使用前文冻结的 fresh、唯一私有路径。活跃期只做 best-effort 监测，轮询 cadence 是实现细节，pathname metadata length 只能作为唤醒提示。活跃期证明必须从安全打开的同一 file generation/identity 实际读取 offset `cap` witness；未创建、sharing violation、暂时打不开或漏检不证明未 overflow，也不单独构成 collector failure，`turn.completed`、root exit 与 exit code 都不是 source close signal。Job 静止且 writer source 关闭后必须权威复验最终 source：此时新发现 `> cap` 就锁存并形成最终 generation prefix，无需终止已空 Job；提前 latch 时最终 generation 必须仍独立证明 overflow。若提前 latch 后 source 缺失、不可读、缩至 `<= cap`，或 replacement 后的新 generation 未独立 overflow，就不能清除 latch 或降级为空，只能留下 staging；新 generation 自身也 overflow 时可以独立重新证明。

每个 Codex attempt 必须按 ADR 0106 建立唯一启动计划：项目 resolver 已证明的绝对 native Codex CLI root 使用 suspended/no-window/extended-startup/Unicode-environment flags 与三项 stdio handle allowlist 直接创建，加入该 attempt 独占、non-breakaway、`KILL_ON_JOB_CLOSE` 的 Windows Job Object，父进程关闭 child-side duplicates，并且只有 `ResumeThread` 精确返回 previous suspend count `1` 才承认 provider 已开始。所有 stop facts 只交给唯一编排器；确认任一 overflow 时，若整个 Job 尚未证明为空就请求终止整个 Job，若 root 已 signaled 且 Job active-process count 为零则不请求。Root 退出或终止 API 返回成功都不单独证明 Job 静止；自然退出/调用竞态以最终 root signaled 加 Job active-process count 为零收敛。调用失败但随后证明 Job 已空不单独决定分类。

Stop request 后 Job teardown 与 mechanical drain 并行：父进程停止写入并关闭 stdin-write，stdout collector 从运行期持续读到 EOF；stderr 已预先导向 `NUL`，不存在 stderr pipe 或 drain branch。Drain 不执行 semantic parse、validation、retry 或新模型调用。只有 Job 已空、stdout EOF、final 关闭后复验、双 sink 安全关闭/读取/哈希/成对安装、spool/tail/私有临时文件撤销，以及 stdin writer、stdout collector 与全部 monitor join 完成且不可能再产生 latch，才能到达 capture-finalization boundary；任何条件无法证明时只留 staging。边界成立后对两个不可逆 latch 做 OR，任一为 true 就固定 `failure_class=process_error`，压过所有 timeout/interrupt/provider/runtime/exit/lifecycle 事实且不重试；随后按 ADR 0081 从已复验正式 events 长度冻结 usage，并以 `failed: codex_process_failed`、`stage=synthesis` 终结 Answer。终止 API 调用失败但最终 Job 已空且边界成立不改变该映射；调用成功但边界无法证明仍只留 staging。[Codex Child Process v1](./codex-child-process-v1.md) 已冻结内部 Job stop DWORD 为 `0x475A0001`；外部 capture-overflow supplemental diagnostic 仍待定。

### Attempt 捕获的严格 UTF-8 语义门禁

固定 `application/octet-stream` 只描述原始审计 bytes，不声明编码有效；asset identity pass 只复验 path、pair、media、byte length 和 hash，不得解码。完成该 pass 后，terminal validator 与 recovery 的 semantic pass 必须按 ADR 0081 只对实际长度低于 events cap 的正式资产重算 usage。获准的语义消费者必须先拒绝输入绝对 offset 0 的 `EF BB BF`，再对完全相同的 byte sequence 使用等价 `decode("utf-8", errors="strict")`；禁止 `utf-8-sig`、BOM stripping、默认/locale/Windows code page、自动编码探测、fallback、转码、Unicode normalization，以及 `replace`、`ignore`、`surrogateescape` 或其他非 strict handler。实现必须把解码所得 `str` 而不是 raw bytes 交给 JSON parser，避免 parser 自动接受 BOM、UTF-16 或 UTF-32。

该门禁禁止解码器自行生成 replacement character，不禁止原始 bytes 合法编码的 U+FFFD，也不禁止 JSON string 内合法的 U+FEFF；这些 code point 仍由正常 JSON、Schema 与字符串规则判断。非 overflow `events.jsonl` 的 BOM/解码失败进入 lifecycle 的 event-stream 结构失败并得到 `process_error`，原始 capture 仍作为合法 asset 保留。只有最后一个 `failure_class=null` attempt 的 eligible final 才执行既有原始 byte-length 门禁和严格解码；其 BOM/解码失败得到 `answer_output_invalid`，不得把 attempt 改成 `process_error`。ADR 0078 的 overflow prefix 不是完整语义输入，允许结束在 UTF-8 sequence 中间；overflow 的 `process_error` 直接来自 latch 与 ADR 0080，不因 prefix 解码成功而清除，也不因解码失败改成普通 event-stream failure 或 eligible-final `answer_output_invalid`。Final prefix 永不作为 Answer validation 输入；是否为未来外部诊断解码仍待相应合同。ADR 0081 令 usage consumer 对任何 exact-cap events 跳过严格解码，低于 cap 时才运行本门禁；这不禁止 non-overflow exact-cap clean EOF 为非 usage 终态分类目的进入权威 event adapter。Event framing 由下一节与 ADR 0075 冻结；精确 capture cap 见前节与 ADR 0077。

### Event records 的 raw LF framing

令 `raw` 为已经完整捕获并通过 ADR 0074 全文件编码门禁的 `events.jsonl` bytes。`raw == b""` 时 record sequence 精确为空。否则 framer 从 offset 0 开始扫描：每遇到一个且仅一个 byte `0x0A`，就以它之前尚未消费的 byte slice 形成一条 record，并排除该 terminator；扫描结束后，只有最后一个 `0x0A` 之后仍有至少一个 byte 时才追加 EOF record。因此最终 LF 产生的空 suffix 不算 record，但开头 LF 与连续 LF 仍分别结束空 record。严格 UTF-8 且不做任何 normalization 时，decoded `str` 中的 U+000A 与 raw `0x0A` 一一对应；实现仍必须从 raw bytes 保持或证明这些边界，不得使用文本模式 universal newline、`splitlines()`、正则 `\r?\n`、其他 Unicode line separator、`strip()` / `rstrip()` 或过滤空项。

CRLF 中的 raw `0x0D` 留在 record 尾部，并只能按 JSON grammar 的 CR whitespace 处理；孤立 CR 从不分隔 record。每个 record 的对应 decoded `str` 可以在 object 前后含 JSON SP、HTAB 或 CR whitespace，但必须被 parser 完整消费且顶层恰为一个 object。空 record、仅含这些 JSON whitespace 的 record、任意 object 深度的 duplicate decoded key、语法不完整、多个 JSON values、array/scalar 顶层以及 `NaN` / `Infinity` 等非标准扩展都属于结构失败；不得用 Unicode `strip()` 扩大 whitespace 集合、丢弃坏 record、拼接相邻 record 或把 pretty-printed 多行 JSON 重组为一个 object。Clean EOF 可以结束一条非空且完整的最后 record，不要求末尾 LF；已知 collector truncation 即使保留前缀恰好可解析也仍按 collector failure 处理。

Framing 或任一 record 失败在两个 capture 已安全关闭、读取、哈希并可成对安装后得到 `process_error`，raw asset 原样保留；若安全收尾本身失败则仍只留 staging。零条 record 不由本节决定 failure class、必需 event、usage 以外的字段或 Answer 终态，只交给完整 event/terminal matrix。本节不规定 record 数量或单 record 上限；文件 cap 见 ADR 0077，overflow prefix 见 ADR 0078。Overflow prefix 不是这里所称的完整 `raw`，framer 不参与 ADR 0080 的 `process_error` 分类；ADR 0081 的 usage consumer 对任何 exact-cap events 都不运行 framing，低于 cap 时才对完整正式资产使用本节规则。

一个 attempt 在 launch commitment 时成立。编排器必须按以下不可分割顺序执行：

1. 完成本次固定 prompt、Schema、Question/View、有效配置与 Codex runtime 前置检查，并准备好该 ordinal 的审计接收位置；
2. 在进入 commitment 前最后检查用户中断，以及仅在先前成功启动已建立时才存在的 95-minute shared attempt-window deadline；首个 attempt 前不存在可检查的单-attempt absolute deadline；
3. 将当前 ordinal 不可逆地加入本次 Answer 的 attempt 序列；
4. 紧接着按 ADR 0106 的已证明 launch plan 恰好调用一次 Windows `CreateProcessW`，直接创建绝对路径的项目 native Codex CLI root；不存在 PowerShell/“等价 wrapper”、shell、版本探针或普通启动回退。

因此 attempt 在 OS 返回进程创建结果之前已经存在。Windows 拒绝创建进程仍保留该 item，终态通常为 `failed: codex_process_failed`；它没有任何 provider event/final-message bytes、exit code 或 token usage，但仍按固定矩阵保存两个 0-byte 捕获文件，且不得按 transient 自动重试。相应字段使用下一节冻结的 `exit_code=null`、`failure_class=process_error`、四个 token 均为 `null` 且 `usage_unavailable=true`。若 runtime、登录、模型、必要能力或调用输入在首次 commitment 前失败，则 `attempts=[]`。如果前面已有 attempt、但在下一次 commitment 前发生 runtime 失败、中断或 window 结束，只保留已经创建的 items，不为尚未发起的重试建立占位项。

零 Candidate 的确定性成功固定为 `attempts=[]`，非零 Candidate 成功必须有 1–3 项。一次或两次允许的瞬时失败后成功时，数组按实际创建顺序含 2 或 3 项；在 backoff 中中断只保留已完成项。瞬时耗尽通常有 3 项，但 95-minute window 若更早终止，只能保留实际 commitment 的 1–3 项，不得补造。Confirmed overflow 终态必须有 1–3 项，overflow `process_error` item 是最后一项且之后没有 backoff、retry 或新 commitment；它之前只能有已经合法触发 retry 的瞬时失败项。`interrupted` 可有 0–3 项；受控中断发生在 commitment 与 OS 返回之间时仍包含当前 item。完整 terminal manifest 形成前的进程崩溃只有未完成 staging，恢复器不得根据残留目录猜测或补写 attempts；若字面 manifest 已存在，其完整性仍只由共享 reader 与恢复合同裁决。

完整合法组合最终必须联合 `status`、`error.code`、Candidate 数量、每个 attempt item、根级资产矩阵与固定双文件集合验证；不得仅凭数组长度反推终态。每个 item 的封闭字段、时间、exit/failure 与 usage 规则由下一节冻结，跨 item 的 usage totals 已由前文冻结；双文件的 retention 保证范围由 ADR 0076 冻结，逐文件 cap 与包含边界由 ADR 0077 冻结，overflow 的 exact-prefix retention 由 ADR 0078 冻结，witness、Job stop 与 mechanical drain 由 ADR 0079 冻结，分类、优先级、不重试与顶层映射由 ADR 0080 冻结，正式 events 的 usage 长度门禁由 ADR 0081 冻结；[Codex Child Process v1](./codex-child-process-v1.md) 已冻结内部 Job stop DWORD 为 `0x475A0001`；外部 capture-overflow supplemental diagnostic 继续后续冻结。

## Attempt 十字段记录

`attempts` 的每个 item 必须是扁平、封闭的 JSON object，以下十个字段全部必填且禁止额外字段；字段在 object 中的书写顺序不构成语义：

~~~json
{
  "started_at": "2026-08-01T20:30:00.000Z",
  "finished_at": "2026-08-01T20:31:00.000Z",
  "elapsed_ms": 60000,
  "exit_code": 0,
  "failure_class": null,
  "input_tokens": 1200,
  "cached_input_tokens": 800,
  "output_tokens": 500,
  "reasoning_output_tokens": 200,
  "usage_unavailable": false
}
~~~

`started_at` 与 `finished_at` 逐字复用 Answer 级时间字段冻结的 24-byte UTC 毫秒格式、Gregorian 有效性和截断规则，均不得为 `null`。Attempt 自己的 wall clock 与 monotonic clock 在 launch commitment 成立、当前 ordinal 不可逆加入序列时采集开始边界，紧接着执行唯一一次进程启动调用。结束边界只能在以下内容已经冻结后采集：进程创建失败已经分类；或者已确认 root signaled 且整个 Job active-process count 为零、provider pipes 已到 EOF、final source 已关闭并完成权威复验；并且该 ordinal 的两个捕获 sink 都已安全关闭、可读取和哈希，spool/tail/私有临时文件已撤销，全部 collector/monitor 已 join 且不可能再产生 latch，最终 exit/failure/usage 值已经确定。若仍无法确认进程树终止、collector/source 停止、final 权威复验、monitor/collector join 或双文件达到该边界，就不能以一个看似完整的 item 形成 terminal manifest。

`elapsed_ms` 必须是 `0..9223372036854775807` 的 JSON integer，JSON boolean、float、string 与 `null` 无效。它使用该 attempt 两个边界的同一进程 `time.monotonic_ns()` 差值向下取整到毫秒，不能由 UTC timestamp 推算，也不能由 Answer elapsed 分摊。它包含 commitment、进程创建、运行、终止、provider 捕获收尾，以及运行时正式资产复验和 usage readiness；这些步骤参与既有 30/95-minute classification-ready 裁决。它不包含前一 attempt 后的 backoff、全部 item 冻结后的 `usage_totals`、本次输出的 validation/rendering、terminal validator/crash recovery 的后验复算或后续 attempt。30-minute watchdog 只从进程成功启动开始并按既有边界运行，而进程创建、强制终止与安全捕获收尾没有另一个可验证的固定时长上限，因此合法 attempt `elapsed_ms` 可以大于 `attempt_timeout_ms=1800000`。Attempt 的 UTC 墙钟允许回拨，validator 不要求 `finished_at >= started_at`，也不要求 wall-clock 差与 `elapsed_ms` 相等或接近。

`exit_code` 必须为 JSON `null` 或 `0..4294967295` 的 JSON integer；boolean、float、string、负数和更大值无效。只有 root process handle 已进入 signaled 状态后，才能把 [`GetExitCodeProcess`](https://learn.microsoft.com/zh-cn/windows/win32/api/processthreadsapi/nf-processthreadsapi-getexitcodeprocess) 取得的最终 Win32 DWORD 写入该字段；若语言绑定把高位已置位的 DWORD 暴露为有符号负数，writer 必须按同一 32-bit bit pattern 转为 unsigned integer，不能钳制、拒绝或映射成 POSIX signal。进程没有成功创建，或者最终 DWORD 无法取得时为 `null`。在已经确认 handle signaled 后，`259` 可以是真实退出码，不得再解释为“仍在运行”。

四个 token 字段 `input_tokens`、`cached_input_tokens`、`output_tokens` 与 `reasoning_output_tokens` 各自必须为 JSON `null` 或 `0..9223372036854775807` 的 JSON integer；boolean、float、string、负数与超限值均不是可接受计数。先按 ADR 0081 复验正式 `events.jsonl` 的实际长度：恰为 `16,777,216` bytes 时四项必须全部为 `null` 且 `usage_unavailable=true`；小于该 cap 时，每个值只能来自同一正式资产经唯一严格 adapter 接受的 usage-eligible `turn.completed.usage` 投影。缺失、畸形或无法取得的字段独立写为 `null`，不得解析数字字符串、估算、补零或因一个字段无效而丢弃其他有效字段。`usage_unavailable` 是必填 JSON boolean，并严格满足：四项全为 integer 时只能是 `false`；至少一项为 `null` 时只能是 `true`。它只表达四项 token 审计是否完整，不表达 exit、时间、final output 或整个 Answer 是否可用。

`failure_class` 必须为 JSON `null`，或以下七个 lowercase ASCII string 之一：

~~~text
timeout
network
rate_limit
server_error
runtime_unavailable
process_error
interrupted
~~~

四个瞬时值只允许来自既有重试合同批准的证据：Python watchdog 的 `timeout`、明确 transport 网络中断、明确 HTTP 429 或明确 provider HTTP 5xx。`runtime_unavailable` 表示 launch commitment 后才由 Codex 进程/provider 事件确认的锁定 CLI、登录、模型或必要能力不可用；同一问题若在 commitment 前已确认，则不创建该 attempt。`interrupted` 只可能来自 commitment 后、item 冻结前观察到的用户中断；commitment 前或 backoff 中的中断不创建新 item。

### Attempt terminal signal 唯一裁决

每个 attempt 从 launch commitment 起到十个字段全部冻结前都处于 active 状态。进程、collector、watchdog、overflow monitor 与用户取消不能分别写 manifest；唯一 Knowledge 编排器必须串行化它们的事实与 stop request。Capture-finalization boundary 成立前，timeout、interrupt、provider/runtime、exit、events/final overflow 与其他 lifecycle 观察都只是 provisional facts，不能先冻结 item class 或 Answer 顶层终因。Overflow latch 一旦为 true 就不被 EOF、I/O failure、进程退出、final replacement、timeout 或 interrupt 清除；同时到达的 events/final overflow、timeout 与 interrupt 可以合并为一次 Job stop request，但全部事实都保留。到达 boundary 后先对两个 latch 做 OR：任一为 true 就不比较 observation 时间，直接选择最高优先级 `process_error`；两项都为 false 才运行下述 non-overflow 裁决。若 item freeze 后还能产生新 latch，说明 collector/monitor 未真正停止；在原子提交前发现时必须放弃 terminalization 并只留 staging，不能回写 item。对于 non-overflow attempt，30-minute attempt deadline 与共享 95-minute window deadline 都是由各自成功启动 monotonic anchor 加固定 limit 得到的绝对 `monotonic_ns` 目标，不以 watchdog 回调被调度的时刻代替；当前有效 deadline 是已经存在者中的较早值。用户取消在本进程记录自己的 monotonic observation，进程/provider/exit/usage 全部可分类时记录 classification-ready boundary。取消 observation 早于有效 deadline 与 ready boundary 时选择取消；与 deadline 或 ready boundary 同值时也由取消优先。否则 deadline 早于或等于 ready boundary 时选择 timeout，只有 ready boundary 严格更早时才能接受 provider/exit 完成。每次状态转换都按这些已记录边界裁决，不得依赖线程回调恰好先被调度。

第一阶段是生命周期完整性门禁，优先于所有主终止 signal：

- 若尚未确认 root signaled、Job active-process count 为零、全部相关 pipes EOF、final source 关闭后权威复验、两个 sink 安全关闭/读取/哈希并成对安装、spool/tail/私有文件撤销以及全部 collector/monitor join，就不得冻结 item、形成 terminal manifest 或释放 Answer writer 所有权；现场只能继续安全收尾。始终无法达到该边界时只留下 staging，不得谎称 `interrupted`、`timeout` 或 `process_error` 已经完整提交。
- 边界成立后，只要 events/final 任一 overflow latch 为 true，final class 就固定为 `process_error`。该结果覆盖 lifecycle、collector、event-structure、deadline、interrupt、provider/runtime 与 exit facts，禁止自动重试；witness 在 drain 或 final post-close 复验中才出现也相同。`TerminateJobObject` 返回成功或失败不改变该分类：最终安全边界成立就按 overflow `process_error`，无法成立就适用上一项只留 staging。
- 对于两个 overflow latch 都为 false 的 attempt，达到安全收尾边界且两个捕获 sink 仍能安全关闭、读取、哈希并成对安装后，只要发生 Windows 进程创建失败、成功创建后的最终 Win32 DWORD 无法取得、进程树/job 生命周期操作失败、collector I/O/已知完整流捕获失败，或按照冻结的 Codex event adapter 因 leading BOM、非严格 UTF-8、framing/JSON 或其他结构问题无法建立必需事件流，final class 就必须是 `process_error`。Clean EOF 下没有末尾 LF 但最后 record 完整不属于捕获失败。该普通 `process_error` 仍覆盖已经观察到的 interrupt、deadline 或 provider 故障且不允许自动重试。
- 对 non-overflow attempt，ADR 0081 的 usage 候选值在 classification-ready 前确定并在主终止裁决后原样冻结；overflow attempt 则在 ADR 0080 固定 `process_error` 后按同一长度门禁冻结 usage。正式 events 恰为 cap 时四项固定为 `null` 且 `usage_unavailable=true`，这既不证明 overflow，也不得把 exact-cap clean EOF 提升为 `process_error`；正式 events 小于 cap 时，仅有一个或多个 usage 字段缺失、类型错误、为负数或超限仍按逐字段规则落 `null`，不得提升为 `process_error`。小于 cap 的正式 bytes 若发生编码、framing、JSON 或 terminal-event 结构失败，则不能抢救更早 usage，四项全为 `null`；collector truncation/I/O 事实只影响上一项的 lifecycle 分类，不改变由正式 bytes 重算的 usage。

以下第二阶段只适用于两个 overflow latch 都为 false 的 attempt。已经证明 overflow 且第一阶段安全边界通过时，不进入既有 signal/exit 裁决，`failure_class` 已唯一确定为 `process_error`；编排器随后按 ADR 0081 从已复验正式 events 长度冻结 usage，采集 attempt 结束时间，并把十字段 item freeze 与锁存 `status=failed`、`error.code=codex_process_failed`、`error.stage=synthesis` 放在同一串行状态转换中，立即关闭 attempt window，禁止 backoff、retry、validation 与后续 commitment。安全边界或 usage 唯一复验无法成立时仍只留下 staging。

对于没有观察到 capture overflow、第一阶段通过且没有 `process_error` 的 attempt，第二阶段才按以下顺序得到唯一主终止类别：

1. 用户取消在 item 冻结前被观察到，且其 monotonic observation 早于当前有效 deadline 与 classification-ready boundary；与其中任一边界同值时也选择 `interrupted`。若 item 已先冻结，后来的取消不得回写。
2. 否则，只要当前有效 30/95-minute deadline 早于或等于 classification-ready boundary，就选择 `timeout`。先出现的 provider 诊断或看似完整 final 不覆盖 timeout；例如已经收到 429 但进程未在 deadline 前完整结束，仍是 `timeout`。
3. 二者都未先终止且进程/provider 捕获正常完成时，才解析获准的 terminal provider 证据。若同一 attempt 同时满足多个类别，固定按 `runtime_unavailable > rate_limit > server_error > network` 选择；因此明确的锁定 CLI、登录、模型或能力不可用胜过泛化 HTTP 5xx，明确 HTTP 429 胜过 5xx，已取得明确 HTTP 响应胜过伴随的 transport 中断。没有冻结证据的 stderr 文本或模型自然语言不参与。
4. 没有上述类别但 root process 最终 `exit_code != 0` 时选择 `process_error`；没有上述故障且 `exit_code=0` 时选择 JSON `null`。

因此 `failure_class=null` 只说明 root process 以 `exit_code=0` 正常退出、provider event/final 捕获正常结束且没有 attempt 级运行故障；它不证明 final text 存在、是严格 UTF-8、无 leading BOM、合法或通过 Answer validation/rendering。正常进程随后因 final 编码或其他 `answer_output_invalid`、`citation_link_construction_failed` 或 `answer_rendering_failed` 终止整个 Answer 时，该 attempt 仍为 `failure_class=null`。相反，获准 provider 类别即使伴随 `exit_code=0` 也保存对应非空 class；未知非零退出才回退为 `process_error`。

进程创建失败 item 固定为 `exit_code=null`、`failure_class=process_error`、四个 token 均为 `null`、`usage_unavailable=true`，两个固定捕获文件均为 0 bytes；三个时间字段仍按真实 commitment 与达到安全分类收尾边界的时间保存。若 deadline 或 interrupt 已在阻塞的进程启动调用期间锁存，而调用随后失败，完整性门禁仍得到 `process_error`；若调用成功，则在取得 handle 后立即终止，安全收尾通过时按两个本地 signal 的先后得到 `timeout` 或 `interrupted`。没有 capture overflow 的 timeout、transport/provider failure 与中断应保留已经合法取得的最终 exit code、低于 cap 的正式 events 中按 ADR 0081 合法投影的每项 token，以及两个捕获文件的实际 bytes。发生 overflow 时捕获资产按 ADR 0078 保存 exact prefix，`failure_class` 固定为 `process_error`，`exit_code` 仍保存可取得的真实最终 DWORD 或 `null`；events overflow 与双 overflow 因 events 正式长度恰为 cap 而四项 token 全为 `null`，final-only overflow 在 events 小于 cap 时按完整流逐字段投影、events 恰为 cap 时也保守全为 `null`。

Item 十字段一经冻结，后续 user interrupt、deadline、validation、rendering、backoff 或 Answer terminalization 都不得回写；单个 `failure_class` 也不单独决定顶层 `status` 或 `error`。编排器必须紧接 item freeze、在同一串行状态转换中执行下一步：`process_error`、`runtime_unavailable`、`interrupted` 或已经耗尽的 transient 集合立即锁存对应 Answer terminal cause；仍有时间与次数的 transient 进入 backoff 而不锁存；`null` 关闭 synthesis window 并进入 validation。ADR 0080 的 overflow `process_error` 在该转换中只能锁存 `failed: codex_process_failed` 与 `stage=synthesis`，并且永不进入 backoff、retry 或 validation。进入 backoff、validation 或 rendering 后，Answer 仍可接受取消，直到某个 terminal cause 被锁存。

在 backoff 或下一次 commitment 前没有 active item 时，用户取消 observation 与固定 95-minute deadline 使用相同的 monotonic 比较：取消早于或等于 deadline 时锁存顶层 `interrupted`；deadline 更早时根据全部实际 attempt 的 final classes 锁存对应 blocked exhaustion，不创建新 item。Validation/rendering 完成与用户取消也由同一编排器线性化，接受完成前先处理已经更早或同刻观察到的取消。任一 `status` / `error` terminal cause 一经锁存，后来的用户取消、deadline 或其他回调只能被忽略，不能在生成非 manifest 资产、采集 `finished_at`、写入 manifest 或原子提交期间覆盖它。

完整结果仍按重试序列、耗尽规则、Candidate/输出状态及封闭 error 表联合验证。不得增加 `success`、`invalid_output`、`validation_error`、顶层 error code、自由文本错误、provider request/session ID 或嵌套 `usage` object。

## 尚待冻结

- `knowledge.ask --json` 的 supplemental code/context union、Human 中文文案/exit、未被 [CLI Command v1](./cli-command-v1.md) typed-verdict/grammar table 分类的 internal/entry fault、ADR 0108 排除的 JSON failure 与其他 Human presentation failure exit；controlled `CLI_BOOTSTRAP_FAILED`/`CLI_ARGUMENT_FAILED` receipt 已由 T02 冻结；尚无路径专属 cap 的 Answer 资产读取额度；根级纯文本/Schema 快照的精确 media identity，capture overflow 专属 supplemental diagnostic，`retrieval_view_too_large` 诊断的精确 audit 字段与其规范序列化，以及孤立 staging 的显式维护；内部 Job stop DWORD 已由 [Codex Child Process v1](./codex-child-process-v1.md) 冻结为 `0x475A0001`。
