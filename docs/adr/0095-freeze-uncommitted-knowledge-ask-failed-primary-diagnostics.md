# 冻结未提交 knowledge.ask 的 failed 主诊断

当 `command="knowledge.ask"` 已进入 handled path、本次 invocation 没有提交自己的新 Answer，且 no-commit terminal-cause classifier 最终选择 `failed` 时，outer 必须为 `outcome="failed"`、`result=null`，`diagnostics[0]` 必须从下列七项封闭 cause 静态映射；完整合法 JSON envelope 沿正常 handled-return 返回时 process exit code 固定为 `1`。七项都只允许作为 primary，`context` 必须精确为 `{}`；禁止扩展 V1 union、增加 catch-all、复用 committed/blocked/supplemental code，或从异常类型、异常文本、路径、Win32 code 与内部阶段名动态构造 code。

| closed failed cause | required primary `code` |
|---|---|
| Caller-owned Question、Configuration 与 Git facts 已合法，但 `answer_id` 前无法机械构造或 canonical-serialize `QuestionEnvelopeV1`、role audit bytes 或 provenance object | `knowledge.ask.pre_answer_formation_failed.v1` |
| 初始 Data Root gate 成功后，强制 checkpoint 无法继续证明 root identity、canonical root、父链与 reparse 状态仍安全且相同 | `knowledge.ask.data_root_integrity_lost.v1` |
| Writer ownership 已取得且 root trust 仍成立，但 `answers/.staging/` 无法安全枚举或 invocation-wide orphan scan protocol 无法建立或完成 | `knowledge.ask.orphan_scan_failed.v1` |
| `answer_id` 已生成且 root trust 仍成立，但本次 staging direct child、non-terminal asset 或 writer-private entry 无法形成、写完、验证、安装或撤销，因而不能达到封闭 terminal asset set | `knowledge.ask.answer_staging_failed.v1` |
| 本次新 Answer 已进入 terminal manifest formation 且 root trust 仍成立，但 manifest canonical buffer/cap、direct exclusive-create、write/completion/close、readback、Schema/canonical identity、目录闭合或跨资产复验失败 | `knowledge.ask.answer_manifest_failed.v1` |
| 本次新 Answer 的 expected target 在 final checkpoint 已存在，或 non-replacing rename 明确返回 target-exists，且 root trust 仍成立 | `knowledge.ask.answer_target_conflict.v1` |
| Final checkpoint 已通过、root trust 仍成立且 target 不存在；non-replacing same-volume rename 返回其他确定失败，且能够证明 staging 未提交、target 不是本次 commit、操作已安全停止 | `knowledge.ask.answer_commit_failed.v1` |

初始 Data Root gate 一旦成功即不可逆锁存；后续 root trust loss 优先于 orphan scan、staging、manifest、target 与 commit failure。Manifest formation 前的 non-terminal asset failure 选择 staging code，formation 开始后的 terminal manifest failure 选择 manifest code；target-exists 与其他确定的 rename failure 必须分开。单个历史 orphan 的 invalid candidate、manifest invalid、target conflict 或 recovery rename failure 仍只可成为 supplemental，不能进入本 union。

七项只覆盖能够通过 ADR 0099 `NoCommitSafeBoundaryV1` 并形成 handled envelope 的确定 no-commit 路径。Rename 是否已经提交或 namespace 结果无法确定时，不得猜测 committed/no-commit。Cleanup、close 或 release API 报错必须先应用上表已有 cause 的完整谓词：若 cleanup 阻止 staging 或 manifest 达到终态，则使用对应 staging/manifest cause；报错本身不产生 `answer_writer_teardown_failed` 或其他 teardown primary，只有 typed live-resource ledger 清零且进程/I/O 静止、Answer commit/target 状态确定、ownership 已安全释放等权威后置条件仍成立时，才保留既有候选。任一后置条件无法证明时不进入正常 JSON 矩阵。

如果原业务或 runtime failure 仍成功形成并提交 terminal `status=failed` Answer，则走 ADR 0092 的 committed matrix，不属于本 union。`pre_answer_formation_failed` 只覆盖受控构造边界内无法形成或 canonical-serialize 合法值的机械失败；错误 shape/type 已逃出构造边界即属于内部不变量破坏。V1 不增加通用 internal failure；资源耗尽、内部不变量破坏、诊断/envelope 无法形成或其他未列且不能安全归类的路径仍位于正常矩阵外。不兼容扩展必须新增 ADR、versioned code 与 concrete Schema 版本，不能静默扩充这七项。
