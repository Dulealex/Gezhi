# ADR 0130：先发布 Reader 草稿，再物化正式 Candidate

状态：已接受

T14 / Issue #15 的 `literature_reader_v1` 在一次逻辑 semantic read 中同时生成 Reading Result 与 Candidate Draft，并在 Python 中完成 closed Schema、Evidence Block 范围、`source_term`、Descriptor locator 与 Draft 总数上限验证。T14 的不可变 Reader run 保存这两类已验证输出及完整 input/prompt/schema/attempt/capture provenance，但不创建 `candidate_id`、`payload_sha256`、正式 Descriptor Reference、Candidate Knowledge 或 pending Review Queue；manifest 记录实际 `candidate_draft_count`，`candidate_count` 固定为 `0`。为保持既有成功 bundle 的固定清单，`candidate_knowledge.jsonl` 是精确零字节占位，`review_queue.json` 的 `candidates` 精确为空；它们只证明“尚未物化”，不能被解释为 T15 已完成。

T15 / Issue #16 才消费一个完整有效的 Reader bundle，执行 Candidate Draft 的规范化、确定性去重、逐类型预算、内容身份、Evidence Pointer、Descriptor Reference、碰撞检查和 Review Queue 投影。T15 不得原地修改 T14 已提交 run，也不得仅为物化 Candidate 再调用 Codex；它必须通过新的不可变 successor publication 表达进展。该 successor 的精确路径、Schema、current 选择与恢复矩阵由 T15 在实现前冻结，T14 不提前猜测。

这一拆分不改变七个 Literature Stage，也不把 Candidate Review 变成构建期人工门。`read` 的模型语义仍一次产生 Reading Result 与 Candidate Draft；这里只把本地确定性物化放到下一张实施票。未来如果改变 Codex 输出字段、Reader 输入或语义职责，仍必须升级角色/Schema 版本。

T14 Reader bundle 是 `read` 内部可提交、可复用的中间结果，不是七阶段 `read` obligation 的成功终点。其公开 Resume 边界由 [ADR 0133](./0133-keep-t14-reader-bundles-inside-the-read-stage.md) 替换冻结；在T15 materializer可用前，不得因正式Candidate和pending Queue均为空而把流程解释为complete。
