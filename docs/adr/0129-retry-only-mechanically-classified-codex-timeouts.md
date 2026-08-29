# ADR 0129：只重试可机械分类的 Codex 超时

状态：已接受

项目继续锁定 Codex CLI `0.146.0` 的 `exec --json` 调用 profile；该版本把 Core 的结构化 `codex_error_info` 与 HTTP status 投影成只有 `message` 的 `error` / `turn.failed`，而格致禁止根据自然语言、stderr 或未知退出码猜测 provider 故障。因此 Literature Reader v1 只把 T13 terminal evidence 已机械证明的 `timeout` 视为可重试故障，最多使用相同输入执行三次 attempt 和既有 10/30 秒退避；已安全收尾的其他 provider terminal、未知非零退出、capture overflow或事件结构故障一律保守归为 `process_error`，映射到 `failed: codex_process_failed` 且不重试。Commitment 前由 project resolver、认证与 launch-plan preflight 明确证明的运行时不可用仍可使用既有 `codex_runtime_unavailable` blocked 路径；原始 capture 在角色批准的上限内始终保留，overflow只保留由 [ADR 0132](./0132-bound-literature-reader-attempt-captures.md) 冻结的exact-cap prefix。Literature V1 移除 attempted `model_context_limit`、network、429、5xx 与混合 transient 耗尽分支；未来只有新的锁定 CLI/profile 正式透传机器可判别字段时，才能以新版本合同恢复这些分类。解析错误 message substring 与切换到未冻结 transport 均被拒绝。

Knowledge Answer 的既有 manifest schema、attempt failure-class enum 与 committed diagnostic union 已单独冻结；本 ADR 不在 T14 内静默改写它们。T22 实施前必须以独立版本化决策解决同一个 `exec --json` projection gap，并按其 Schema 演进规则处理，不得直接复制 Reader 的枚举变更或回退到 message parsing。
