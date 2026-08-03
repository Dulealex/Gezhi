# 使用扁平且可审计的 Knowledge 资产树

Knowledge 的正式数据根固定为 `registry.sqlite3`、`imports/<handoff_id>/` 与 `answers/<answer_id>/`：Candidate Registry 及其 intake 状态以 SQLite 为权威数据，`imports` 原样保留经过校验的 `manifest.json` 和 `candidates.jsonl` 作为不可变跨上下文证据。每次通过前置校验并获得 `answer_id` 的 `knowledge ask` 都创建独立且不可变的终态 Answer 目录，保存 manifest，以及该运行实际到达阶段已经生成并验证的 `question.json`、`retrieval_query.json`、Codex 可见的 `retrieval_view.json`、仅供本地审计的 `retrieval_audit.json`、有效提示词/output schema 和 attempt 审计资产；只有 `succeeded` 必须且只能成对保存正式结构化结果 `answer_output.json` 与可读结果 `answer.md`，`blocked`、`failed`、`interrupted` 均不得包含任一正式结果文件。View 与 audit 分别哈希，不能互相替代。首版不引入“同一查询下多次执行”层级或 `current.json` 指针，重复提问直接产生新的 `answer_id`，以较小实现成本同时保留检索、生成和引用的完整审计链；Knowledge 不复制 PDF、Canonical Reading Asset 或 Literature 的其他内部资产。

“实际到达阶段”由 ADR 0071 的封闭 P0–P4 前缀与 C/O 原子对唯一细化，不允许实现按异常现场任意选择根级文件。`prompt.txt` 与 `schema.json` 只在批准的 synthesis 边界成对出现；attempt 审计资产只对应实际 launch commitment，并由 ADR 0072 固定为每项恰好一对 `events.jsonl` 与 `final_message.txt`。
