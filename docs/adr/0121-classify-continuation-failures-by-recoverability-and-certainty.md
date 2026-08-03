# 按可恢复性与确定性分类审核续行故障

Review Decision 后的 Handoff 与 Knowledge import 续行中，已知缺失且可由环境修复或后续显式重试满足的前置条件分别形成 `handoff_blocked` 或 `import_blocked`；continuation 已开始后，确定性的本地完整性、协议、revision、commit 或 Registry conflict 形成 `handoff_failed`、`import_failed` 或对应 stage failure，commit outcome uncertain 仍位于正常 handled 矩阵外。本决定部分取代 [ADR 0026](./0026-continue-review-through-handoff-and-knowledge-import.md) 对 Handoff/import failure 的笼统 blocked 映射；此前已明确提交的 Decision、Handoff 或 Registry facts 不回滚，后续 invocation 必须以相同 Candidate、payload、revision 与 Handoff identity 重试。
