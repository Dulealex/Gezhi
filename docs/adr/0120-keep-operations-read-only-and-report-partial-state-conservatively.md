# 保持 Operations 只读并保守报告部分状态

Operations 只通过 `doctor()` 与 `status(work_id?)` 两个外部 interface 提供环境健康和跨 Context 状态投影；它拥有检查编排、保守聚合、诊断选择与 Human/JSON 报告，但不拥有 Literature 或 Knowledge 的业务状态，也不直接修复配置、环境、Data Root、SQLite、manifest、current pointer、staging、orphan 或 quarantine。`doctor` 显式检查全部 V1 运行能力和两个 Context Data Root；`status` 只从 Context 提供的只读投影与已验证权威事实汇总状态。若一个局部来源不可用而其他来源仍可形成自洽报告，`status` 返回明确的 `partial`，而不是把已观察部分冒充全局成功；若无法形成请求范围内的最小自洽报告，则命令 `blocked` 或 `failed`。这样以较少的公开 interface 集中跨 Context 可观测性，同时保留状态所有权、局部阻塞和未来通过静态 Context 投影扩展的位置；代价是 Operations 不提供自动修复，且新增 Context 必须显式扩展版本化投影合同。
