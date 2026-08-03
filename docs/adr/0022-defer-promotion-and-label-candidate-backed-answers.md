# 延后 Promotion Gate 并标记候选支持回答

首个闭环只导入 Candidate Review 已 accepted 的候选，并统一保存为 `promotion_status=not_promoted`；Knowledge 的 search 与 ask 可以使用这些候选，但输出必须标记为 `candidate_backed`，不得描述成正式知识、已验证事实或自动蕴含证明。`answer.md` 在固定 `# 回答` 标题后始终由 Python 输出且只输出一次固定治理 blockquote，标题与 blockquote 之间、blockquote 与后续内容之间各恰好一个空行：`> 治理说明：本结果为候选知识支持（Candidate-backed）；可用内容仅来自已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。`；它适用于 answered 与 insufficient_evidence，不由模型改写，也不附论文引用。首版不提供 promote、demote 或 deprecate 状态变更，完整 Promotion Gate 延后；合同保留 Promotion Status，使未来可以增加 promoted-only Retrieval View 而不改变 Literature 或 Handoff。
