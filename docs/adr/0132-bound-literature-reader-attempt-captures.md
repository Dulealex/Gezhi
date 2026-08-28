# ADR 0132：限制 Literature Reader attempt capture

状态：已接受

`literature_reader_v1` 为每个attempt独立冻结两个正式capture上限：`events.jsonl` 为16,777,216 bytes，实际存在的`final_message.txt`为1,048,576 bytes。两项上限都包含端点；恰好等于cap不是overflow，只有实际观察到第cap+1个byte才单调锁存overflow。正式资产保留从offset 0开始、长度恰为cap的exact prefix，witness与tail不进入资产；Reader没有实际final source时仍不创建`final_message.txt`，不能补成Knowledge式固定双文件。

events collector在overflow后进入drain-only并继续取得真实EOF；final通过active witness与Job退出后的权威复验绑定同一file generation。已确认overflow且Job仍非空时，orchestrator只执行一次整棵Job stop；若overflow只在Job已空后的权威复验中得到证明，则不对空Job发出伪终止。模块必须完成pipe、worker、Job、source与handle ledger的安全收敛，才返回`overflow=true`。任一Reader capture overflow固定为不可重试`failure_class=process_error`，公开`literature resume`映射为`failed: codex_process_failed`；已保留的exact prefix继续进入attempt与manifest的byte-length/SHA-256审计，但不得进入成功Reader结果验证。

Reader的两项常量虽然刻意采用与Knowledge当前相同的数值和已经验证的底层mechanics，但所有权、名称、测试与演进完全独立。这一选择在Reader输出Schema远小于1 MiB的前提下保留充足诊断空间，同时把单attempt审计资产的磁盘增长限定为可预测范围；它不修改Knowledge，也不成为未来Bot的默认值。以后改变任一数值、包含端点规则、exact-prefix、stop、failure mapping或缺失final语义，都必须通过新的Reader角色/合同版本决策，不能借修改Knowledge常量或共享模块默认值旁路演进。
