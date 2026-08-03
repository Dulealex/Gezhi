# 使用逐字段独立且受检的 Answer usage totals

Knowledge v1 的 terminal manifest 顶层始终保存封闭的 `usage_totals` object，只含四个 token 总计且不增加重复的顶层 `usage_unavailable`。零 attempt 表示确定没有启动 Codex 用量，四项总计全部为 0；存在 attempt 时，每个字段分别且只对全部实际 attempts 的同名 manifest 值求和，任一值为 `null` 或数学和超过 signed 64-bit 上限时，该字段总计为 `null`，其他字段仍可得到精确总计。求和包含失败、超时、中断和最终成功的全部 attempts，不筛选“成功调用”，不补零、不饱和、不估算，也不把 cached input 从 input 中扣除或把 reasoning output 重复并入 output。该选择以 CreateProcess failure 等已存在但 usage 未知的 attempt 得到全 `null` 总计为代价，区分“明确没有 attempt 的零消耗”与“发生过 attempt 但审计不完整”；某项总计因未知值或算术溢出而为 `null` 本身不产生 Answer error，也无需金额模型或第三方算术依赖。

该求和算法无需因 ADR 0080/0081 改变，只能读取已经冻结且通过 usage 复验的 attempt token 字段。任一正式 events 长度恰为 cap 的 attempt 按 ADR 0081 四项 token 全为 `null`，因此 Answer 四项 totals 也全部为 `null`；final-only overflow 且 events 低于 cap 时，合法的逐字段值照常参与独立求和。不得从 events 再运行第二套 totals parser、因已知 `process_error` 擅自补零，或回写更早 attempt 的已知值。
