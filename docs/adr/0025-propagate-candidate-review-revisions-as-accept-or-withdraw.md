# 以 accept 或 withdraw 传播 Candidate 审核修订

Reviewed Handoff 的 `candidates.jsonl` 以 accept 和 withdraw 动作同步 Candidate Review：accept 用完整 payload 激活候选，withdraw 用最小墓碑记录把已导入候选设为 `intake_status=withdrawn`，保留历史但排除检索。每个动作携带严格递增的逐候选审核修订；重复修订幂等，倒序或同修订不同内容失败，更高修订可以重新 accept。Intake Status 与 Promotion Status 独立，未曾导入的 pending、deferred 或 rejected 候选不产生 Handoff 记录。
