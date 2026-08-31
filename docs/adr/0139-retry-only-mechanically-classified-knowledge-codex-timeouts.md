# ADR 0139：Knowledge Codex 只重试机械分类的超时

状态：已接受

`knowledge_answerer_v1` 继续锁定 Codex CLI `0.146.0` 的 `exec --json` profile。该 profile 不把 Core 的结构化 provider error kind 或 HTTP status 投影到格致可机械判别的事件字段，只提供不稳定的人类 `message`；因此 Knowledge v1 只把项目子进程适配器已经机械证明、且通过 capture/lifecycle 完整性门禁的 `timeout` 视为可重试 failure class。第一次与第二次 timeout 后分别使用既有 10 秒和 30 秒退避，同一 Answer 最多创建三个 attempt；三次机会耗尽，或 95 分钟共享 deadline 在 backoff/下一次 commitment 前胜出时，返回 `blocked: codex_timeout_exhausted`。每次 retry 仍必须使用同一冻结 runtime、prompt、Schema、角色、模型、reasoning 与共享 deadline，并创建全新的进程、session、临时目录和 capture namespace。

已安全收尾的其他 provider terminal、未知非零退出、结构无效的事件流、capture overflow、capture identity/读取失败和其他 lifecycle failure 一律保守归为 `process_error`，立即返回 `failed: codex_process_failed` 且不重试。零 record 本身仍是合法 framing：已经由机械事实证明为 `timeout` 或 `interrupted` 时保留该分类；只有 otherwise-clean completion 缺少唯一 `turn.completed` 时才归为 `process_error`。Commitment 前由冻结 runtime resolver 或 launch preflight 明确证明的运行时不可用仍使用 `blocked: codex_runtime_unavailable` 和 `attempts=[]`；commitment 后不得回退到该分类。实现不得读取或匹配 `error.message`、`turn.failed.error.message`、stderr、final message 或退出码文本来推断 network、429、5xx 或其他瞬时故障，也不得切换 transport、CLI、provider、模型或调用 Ollama。

既有 Answer manifest schema、十字段 attempt record、failure-class enum，以及 `codex_network_exhausted`、`codex_rate_limit_exhausted`、`codex_server_error_exhausted`、`codex_transient_exhausted` 的 committed diagnostic union 已作为 V1 读写兼容边界冻结，本决策不删除或迁移这些值；在当前锁定 profile 下，新的 Knowledge writer 只是不得生成这些四类未被机械证明的值。Reader/validator 仍可验证历史或其他已获批准 writer 形成的合法记录。只有未来新的锁定 CLI/profile 正式暴露并冻结机器可判别的 provider 字段时，才能通过新的版本化决策重新启用相应 writer 分类；不得静默扩大本决策。
