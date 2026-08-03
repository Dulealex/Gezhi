# 为 Answer error 使用四个领域阶段

Knowledge v1 的 `error.stage` 严格限于 `retrieval`、`synthesis`、`validation` 与 `rendering`：它们分别覆盖 Answer 建立后的检索与快照物化、Knowledge Codex 准备/调用/事件捕获及重试终结、模型或零候选 Python 输出到合法 `answer_output.json` 的校验，以及从合法结构化结果到完整 `answer.md` 的确定性渲染。非法 Question、查询原子、数据根身份与 writer mutex 发生在 `answer_id` 之前，因此不建立 `input`/`coordination`；retry、transport、timeout、filesystem、database 与 Codex 是故障类别或实现组件，usage 是 token 值缺失或畸形本身不直接产生错误的审计属性，它们都不成为阶段。运行时正式资产复验与 usage readiness 仍属于 `synthesis` 并参与既有时限裁决。Manifest 写入或原子改名失败只能留下 staging，无法再提交一份描述自身提交失败的 terminal Answer，因此也不建立 `commit`/`publication`；未来若需要第二套提交失败事务必须升级 Schema。ADR 0060 已把每个稳定错误码静态绑定唯一 `(status, stage)`，以领域资产边界而非函数、异常文本或 attempt failure class 决定阶段。

ADR 0080 冻结的 capture capacity overflow 属于 `synthesis`：它发生在 Codex 进程/provider 捕获与 attempt terminalization 边界，即使 witness 来自 `final_message.txt` spool 的关闭后权威复验，也不进入 `validation`。安全收尾完成的 overflow 固定映射 `failed: codex_process_failed` 与 `stage=synthesis`；安全边界无法证明时只留 staging，不建立其他 stage。
