# 交接前要求显式 Candidate Review

> Supersession note: [ADR 0118](./0118-limit-v1-candidate-review-to-one-candidate-and-action.md) 只替换本文对 Windows V1 public batch review 的许可；V1 的 `literature review` 一次恰好处理一个 Candidate 与一个 action，且没有 note token。本文关于显式人工审核、异步 Review Queue、自审禁令与 Promotion Gate 分离的其余决定继续有效。

Literature 可以无人值守地完成来源处理、阅读和 Candidate Knowledge 提取，但所有候选必须经过用户显式审核后才能进入 Reviewed Handoff。审核采用异步 Review Queue，允许逐项决定或明确的批量操作，不要求用户守在流水线中间；运行模型不得审核并批准自己的输出。Knowledge 接收的仍是候选而非 Promoted Knowledge，因此 Candidate Review 与后续 Promotion Gate 保持独立。
