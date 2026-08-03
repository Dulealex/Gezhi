# 将 V1 Candidate Review 收窄为一个 Candidate 与一个 action

本 ADR 是对 [ADR 0008](./0008-require-explicit-candidate-review-before-handoff.md) 的局部 replacing decision：Windows V1 的公开 `literature review` invocation 必须恰好接收一个 `CANDIDATE_ID` 与一个 action，action 只能是 `--accept`、`--reject` 或 `--defer`。V1 不提供 batch selector、重复 Candidate、stdin/file list、interactive multi-select 或 `--note` token；本入口形成的 Review Decision 备注为 absent。它只 supersede ADR 0008 对 V1 public batch operation 的许可，不改变显式人工 Candidate Review、Review Queue 或 Promotion Gate 分离。

[ADR 0019](./0019-use-append-only-candidate-review-decisions.md) 的 append-only payload-hash binding、不可变历史与 current-decision 切换继续完整有效。未来若批准 batch，公开合同必须先单独版本化，并把一次 batch 确定性展开为逐 Candidate 的 ADR 0019 Review Decision；未来若批准 note，也必须先冻结 token、raw-value/domain validation、资产表示和隐私边界，不能从 V1 的 absent 值反推出空字符串或默认文案。

这个窄 interface 让单次命令只有一个治理对象和一个不可变 decision commitment，避免在首版引入部分成功、逐项失败呈现、批次身份或事务语义。改变 action 集合、一次处理多个 Candidate 或增加 note 都要求新的 replacing decision 与 CLI/domain contract revision。
