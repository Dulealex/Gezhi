# 交接前要求显式 Candidate Review

Literature 可以无人值守地完成来源处理、阅读和 Candidate Knowledge 提取，但所有候选必须经过用户显式审核后才能进入 Reviewed Handoff。审核采用异步 Review Queue，允许逐项决定或明确的批量操作，不要求用户守在流水线中间；运行模型不得审核并批准自己的输出。Knowledge 接收的仍是候选而非 Promoted Knowledge，因此 Candidate Review 与后续 Promotion Gate 保持独立。
