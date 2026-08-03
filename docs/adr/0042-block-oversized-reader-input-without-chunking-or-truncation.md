# 超长 Reader 输入明确阻塞且不分块或截断

`literature_reader_v1` 在调用 Codex 前要求确定性 `input.jsonl` 的最终实际字节不超过 524288 且不超过 4096 条 block record；任一超限都返回 `blocked: reader_input_too_large`，记录同一最终字节的实际值、限制值与 SHA-256，不创建 attempt、静默截断、删除尾部、只取摘要、自动分块、Map-Reduce、第二次语义阅读、模型切换或降质回退。低于项目限制但仍被 Codex 拒绝的上下文返回 `blocked: model_context_limit` 并保留原始事件；同一逻辑 read 因网络、429、5xx 或超时执行的有限全输入传输重试不构成多次语义阅读。两类输入阻塞都不自动重试，只能在未来独立长文档角色或上限版本升级后通过 `resume` 继续，本规则不增加 tokenizer 依赖。
