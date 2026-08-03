# 将已提交 knowledge.ask 终态映射为主诊断与退出码

当 `command="knowledge.ask"` 的本次新 Answer 已完成 ADR 0090 定义的目录级 logical commit 时，Knowledge command adapter 必须从已验证 `schema_version="gezhi.answer_manifest.v1"` terminal manifest 通过静态表构造唯一 committed primary diagnostic。`succeeded` 不存在 primary；`blocked` 与 `failed` 的 primary code 与 manifest 十五项 `error.code` 一一对应；`interrupted` 因 manifest `error=null` 使用独立的 `knowledge.ask.user_interrupted.v1`。所有这些 primary variant 的 `context` 必须精确为 `{}`，不得复制 `status`、`stage`、裸 manifest error code、`answer_id` 或其他字段。

`blocked` 与 `failed` 的完整静态表为：

| manifest `error.code` | manifest `status` | manifest `error.stage` | primary `diagnostics[0].code` |
|---|---|---|---|
| `fts5_unavailable` | `blocked` | `retrieval` | `knowledge.ask.fts5_unavailable.v1` |
| `retrieval_view_too_large` | `blocked` | `retrieval` | `knowledge.ask.retrieval_view_too_large.v1` |
| `retrieval_query_failed` | `failed` | `retrieval` | `knowledge.ask.retrieval_query_failed.v1` |
| `retrieval_materialization_failed` | `failed` | `retrieval` | `knowledge.ask.retrieval_materialization_failed.v1` |
| `codex_runtime_unavailable` | `blocked` | `synthesis` | `knowledge.ask.codex_runtime_unavailable.v1` |
| `codex_timeout_exhausted` | `blocked` | `synthesis` | `knowledge.ask.codex_timeout_exhausted.v1` |
| `codex_network_exhausted` | `blocked` | `synthesis` | `knowledge.ask.codex_network_exhausted.v1` |
| `codex_rate_limit_exhausted` | `blocked` | `synthesis` | `knowledge.ask.codex_rate_limit_exhausted.v1` |
| `codex_server_error_exhausted` | `blocked` | `synthesis` | `knowledge.ask.codex_server_error_exhausted.v1` |
| `codex_transient_exhausted` | `blocked` | `synthesis` | `knowledge.ask.codex_transient_exhausted.v1` |
| `synthesis_input_invalid` | `failed` | `synthesis` | `knowledge.ask.synthesis_input_invalid.v1` |
| `codex_process_failed` | `failed` | `synthesis` | `knowledge.ask.codex_process_failed.v1` |
| `answer_output_invalid` | `failed` | `validation` | `knowledge.ask.answer_output_invalid.v1` |
| `citation_link_construction_failed` | `failed` | `rendering` | `knowledge.ask.citation_link_construction_failed.v1` |
| `answer_rendering_failed` | `failed` | `rendering` | `knowledge.ask.answer_rendering_failed.v1` |

这十五行是代码中的静态 lookup，不授权把任意 manifest 字符串拼成 diagnostic code。每个 code 只在表中对应的 outer outcome 下作为 index 0 primary；manifest 的既有 `(status, code, stage)` validator 先通过，adapter 才能选择该行。`interrupted` primary 只能来自已验证、已 committed 的 `status=interrupted,error=null` manifest，不能仅凭 Ctrl+C observation 或 attempt `failure_class=interrupted` 生成；它使用 `{"code":"knowledge.ask.user_interrupted.v1","context":{}}`，outer `outcome=interrupted`，且不得为迎合 CLI 而向 manifest 制造 error object。`succeeded` committed Answer 没有 primary，`answer_status=insufficient_evidence` 仍是正常成功且不产生错误 diagnostic；若有后续批准的 supplemental items，它们只按 ADR 0091 追加。

Confirmed capture overflow 已由 Answer manifest 映射为 `failed: codex_process_failed`，因此其 committed primary 仍是 `knowledge.ask.codex_process_failed.v1`。以后若批准 capture-overflow supplemental code，它只能补充可安全公开的本次 invocation 事实，不能替换 primary、改 outcome、扩展当前空 context 或产生第十六个 manifest error code。

已进入 handled `knowledge.ask --json` path、`result` 为非 `null` committed receipt、完整合法 envelope 已成功写完且进程沿正常 handled-return 返回时，使用以下 process exit mapping：

| command outcome | process exit code |
|---|---:|
| `succeeded` | `0` |
| `blocked` | `2` |
| `failed` | `1` |
| `interrupted` | `130` |

在上述 committed JSON 正常返回范围内，exit code 只由 outer outcome 决定，primary/supplemental code 与诊断数量不能另行改变它。`130` 是 Gezhi 受控中断完成 committed envelope 后的应用级正常返回值，不是 Windows 外部强杀码，也不是 `attempts[*].exit_code` 中 Codex 子进程的 Win32 DWORD。`2` 即使与常见参数解析退出值数字相同，也不把参数错误归类为 `blocked`。

非零 exit code 不证明本次没有 commit。对于本 ADR 覆盖的 committed `blocked`、`failed` 与 `interrupted`，ADR 0090 的两字段 `result` 仍是非 `null` commit receipt；自动调用方必须取得并验证包含规范末尾 LF 的完整 JSON envelope，不能用进程码反推目录状态。反过来，commit 后 envelope/result/diagnostic 构造或 validation failure、外部强制终止、进程崩溃、pending I/O 不确定或 seal/release proof failure 可能没有正常 presentation，也不能伪造更小的 failed envelope。ADR 0108 只把成功 seal、进入 `RELEASED` 且无 pending I/O 后的 closed `NO_OUTPUT_PRESENTATION_FAILURE`、stdout setup/completed synchronous write failure 固定为无 cleanup/flush 的 `os._exit(1)`；这个 presentation-plane `1` 不属于本表，也不表示业务 `outcome=failed`。无 committed Answer 的完整 handled JSON 正常 exit 后续由 ADR 0093 冻结；Human mode、bootstrap/argument 与 ADR 0108 排除的其余 failure 继续后续冻结。即使完整 committed receipt 已经成功到达调用方，之后发生的异常进程终止或 presentation fail-stop 也不撤销该 acknowledgment。

这组 committed primary code 的 machine 语义绑定 `gezhi.answer_manifest.v1` 当前十五项表；未来接受新的 manifest generation 或改变任一 manifest code 语义时，不得静默重解释现有 diagnostic `.v1`。Knowledge command adapter 拥有 manifest-to-primary 静态映射、committed 跨字段验证与 command outcome；共享 `DiagnosticSetV1` 继续拥有角色 presence、唯一性、排序、容量与 omission，共享 JSON writer 只拥有 outer/serialization/channel，committed JSON normal-return exit adapter 只映射已经锁存的 handled outcome。Human renderer 与 JSON adapter 消费同一个最终 diagnostic set，不复制这十五行映射；本决策不据此冻结 Human mode 的 process exit。

本决策本身不冻结无 committed Answer 的 outcome/primary-diagnostic/exit-code matrix；后续 ADR 0093 冻结其 outcome 分类与正常 JSON exit，ADR 0094、ADR 0095 与 ADR 0096 分别冻结 blocked、failed 与 interrupted primary code/context，ADR 0097 冻结跨 outcome 静态优先级，ADR 0098 冻结 cancellation/identity cutover，ADR 0099 冻结 no-commit drain/cleanup 安全证明，ADR 0107 冻结 `knowledge.ask` JSON stdout cap 与 immutable buffer，ADR 0108 冻结受控 JSON presentation failure 的独立 exit `1`。Supplemental orphan/capture/maintenance codes、逐 code Human 中文文案、Human mode exit code、parser profile、bootstrap/argument 与其余 presentation failure exit code、持久诊断资产、依赖、配置或模型调用仍不在本决策范围。
