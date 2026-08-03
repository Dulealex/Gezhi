# 审核后自动续行到 Handoff 与 Knowledge Import

`gezhi literature review` 在原子保存 Review Decision 后，由格致编排层计算新增 accept/withdraw 修订、发布不可变 Reviewed Handoff，并调用 Knowledge 的正式导入接口；Knowledge 只在自己的 SQLite 事务中修改 Candidate Registry。跨上下文流程不伪造分布式事务：Handoff 失败记为 `handoff_blocked`，导入失败记为 `import_blocked`，已成功的前置事实不回滚；`gezhi literature resume <work_id>` 使用同一 Handoff ID 和审核修订幂等续跑，并分别报告 Review、Handoff 与 Import 状态。
