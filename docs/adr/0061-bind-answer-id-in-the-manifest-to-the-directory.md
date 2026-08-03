# 将 manifest answer_id 绑定到 Answer 目录

Knowledge v1 的 terminal manifest 顶层必须包含严格匹配 `ans_<lowercase UUIDv4>` 的 `answer_id`，并在正常写入时要求编排器 expected ID、`.staging` 直接子目录 basename 与 manifest 字段逐 ASCII byte 相等；原子提交只移除 `.staging` 层，最终目录 basename 保持不变。正式读取与 crash recovery 都先验证安全直接子目录及 ID 语法，再要求目录名与 manifest 等值，任何不符均整体拒绝且不得补写、规范化、改名或仅信 manifest 拼接路径。目录是物理 locator，manifest 是不可变终态收据中的身份绑定，这一冗余用于发现误复制、错放与恢复身份错配，而不是两个可独立修改的事实来源。首版不增加 `question_id`、`run_id`、conversation/parent ID 或 provider session ID，以维持一个 Answer 对应一次终态执行、重试只属于 attempt 的模型。
