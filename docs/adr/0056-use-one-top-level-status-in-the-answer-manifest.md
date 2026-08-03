# 在 Answer manifest 顶层使用唯一 status

Knowledge v1 的 terminal manifest 在顶层使用唯一、必填且非 `null` 的 JSON string 字段 `status` 表示运行终态，值严格限于 `succeeded`、`blocked`、`failed` 与 `interrupted`。不得接受 `pending`、`running`、`busy`、大小写变体或其他别名，不提供默认值，也不得依据资产、错误、attempt 或目录内容反向推断、修复或改写；manifest 同时禁止 `terminal_status`、`run.status` 或任何第二份运行终态。顶层标量与已经存在的 `schema_version`、`assets` 保持同一简单 envelope，不引入暗示多 run 的 wrapper；错误对象、时间字段、attempt nesting 与其余已批准字段已经分别冻结，并共同构成 ADR 0083 的十一字段顶层闭包。
