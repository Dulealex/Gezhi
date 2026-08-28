# 显式呈现 Reader 前置能力尚未就绪

Canonicalize 可以在 Reader role 实现之前独立发布成功，但 `literature resume` 的 sealed result 又必须把该次已提交阶段列入 `advanced_stages` 并停在下一个实际 stage；既有 `canonical_prerequisite_unavailable`、`reader_input_too_large`、`model_context_limit` 与各 Codex fault 都不能诚实表达这个构建顺序。Literature Commands v1 因此在 `read` 的 blocked reason 行首增加永久保留的 `reader_prerequisite_unavailable`：只有 Reader-owned prompt/schema/input projection 或执行 adapter 尚未随当前构建提供、且没有启动 Codex attempt 时可选择它；Canonical 成功后的 result 使用 `stop_stage=read`，本次提交的 `canonicalize` 可以进入 `advanced_stages`。一旦 Reader slice 已提供，正常路径不得继续使用该 reason；缺失或被明确移除的 Reader-owned 前置资产仍可使用它。它与“已进入 Reader 后实际输入超限、模型上下文不足、Codex executable/runtime/transport 故障”互斥，不能作为未知异常或实现失败的兜底。

[ADR 0133](./0133-keep-t14-reader-bundles-inside-the-read-stage.md) 后续替换并扩展了上述窄定义：T14 Reader bundle 是 `read` 内部中间提交；在 T15 确定性 Candidate materializer 尚未提供时，同一 reason 也可精确表示该剩余前置能力，且不得重跑已经成功的 Codex Reader。
