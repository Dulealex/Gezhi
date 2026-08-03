# 将 Codex attempts 建模为有序 launch 序列

Knowledge v1 的 terminal manifest 顶层始终保存长度 0–3 的非空值 `attempts` array，Attempt 身份只由 `(answer_id, array index + 1)` 构成并确定性映射到 `attempts/01/`..`03/`；不重复保存 attempt number/ID/count/path，不创建 `attempt.json` 或子资产清单。Attempt 在所有输入/runtime、审计位置、取消与预算检查完成后、单次 Windows 进程启动调用前的 launch commitment 成立，因此 OS 拒绝创建进程也留下真实 item，而 commitment 前失败或 backoff 中断不产生占位项。数组严格串行并按创建顺序保存，零 Candidate 成功为空，非零 Candidate 成功为 1–3 项，其他终态只保存实际 commitment 的 0–3 项；95-minute window 提前结束也不能补造未发起重试。该选择以 item 必须支持无进程、无 provider event/final-message bytes、无 exit code 和无 usage 的启动失败形态为代价；ADR 0072 仍为这种 item 保存两个 0-byte 捕获文件，从而避免丢失 launch 审计并消除平行编号与条件式文件清单。

ADR 0080 的 confirmed overflow attempt 必须是数组最后一项；它固定为不可重试的 `process_error`，item freeze 后同一串行转换关闭 attempt window，因此之后禁止 backoff 与新的 launch commitment。它之前若有 items，只能是已经按既有四类瞬时故障合法触发 retry 的实际 attempts，不得补造或重排。
