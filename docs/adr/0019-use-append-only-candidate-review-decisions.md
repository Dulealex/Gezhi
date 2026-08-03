# 使用四状态追加式 Candidate Review

Candidate Review 只使用 `pending`、`accepted`、`rejected` 和 `deferred` 四种状态，只有 accepted 候选可以进入 Reviewed Handoff。审核不修改 Candidate，而是追加绑定 `candidate_id` 与完整 payload hash 的不可变 Review Decision，记录审核者、时间、状态和可选备注；改变决定时追加新记录并原子切换当前决定。批量操作必须展开为逐候选记录，运行端 Codex 无权写入任何 Review Decision。
