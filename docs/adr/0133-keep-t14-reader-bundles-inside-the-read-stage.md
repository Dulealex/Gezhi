# ADR 0133：让 T14 Reader bundle 保持在 read 阶段内

状态：已接受

ADR 0130冻结的T14 Reader bundle只完成`read`阶段中的模型阅读、Draft验证和不可变审计发布；T15的确定性Candidate materializer及successor publication仍是同一个七阶段`read` obligation的一部分。精确零字节`candidate_knowledge.jsonl`和空`review_queue.json`只表示“尚未物化”，不能让Resume把`read`、`review`或整个pipeline判为成功。

在当前构建尚未提供T15 materializer时，公开`literature resume`必须复用既有`stage_blocked(read, reader_prerequisite_unavailable)`，不新增临时reason。若同次invocation刚发布T14 bundle，它仍不把`read`列入`advanced_stages`；`stop_stage=read`、`pipeline_complete=false`、`pending_candidate_ids=[]`，`start_stage`保持invocation初始Continuation Point。再次resume必须验证并复用已提交bundle而不再调用Codex，然后返回同一blocked边界。

本决策替换扩展`reader_prerequisite_unavailable`的既有窄定义：它既可表示attempt启动前缺少Reader-owned prompt、Schema、input projection或执行adapter，也可表示一个有效T14 bundle之后缺少完成同一`read` obligation的确定性materializer。后一分支已经提交的bundle不是失败或staging，且下一次调用不能重做语义阅读。T15提供materializer后应消除该blocked分支，以新的不可变successor完成`read`并进入正式Review语义。
