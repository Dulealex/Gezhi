# 使用静态装配与上下文深模块

格致通过唯一 `open_gezhi()` 组合入口静态装配 `Operations`、`Literature`、`Knowledge` 及以后显式加入的同级上下文；CLI 只翻译参数并渲染结果，稳定 interface 限于 `doctor/status`、`add/resume/review`、`search/show/ask`，Literature 到 Knowledge 的唯一写入 seam 是版本化 Reviewed Handoff 及 `KnowledgeIntake.apply()`。七阶段、身份、资产布局、恢复、审核、检索和引用校验隐藏在各自深 module 内，MinerU、Literature Codex 与 Knowledge Codex 使用语义独立的 process adapter，共享层只承载配置、安全路径、原子发布和 Windows 进程机制；首版不建立 application 转发层、通用 Workflow/DAG、Command Bus、Context Plugin、通用 Repository/FileSystem port 或万能 LLM provider。该决策冻结上下文所有权、最小公开 interface 与跨上下文合同，而不冻结私有文件名和内部拆分；内部可以持续重构，若以后改变稳定边界或持久合同，则以新 ADR 取代本决策并为既有数据或调用方提供迁移。

ADR 0089 的共享 CLI JSON writer 是 presentation seam 上的深 module：它只拥有封闭 outer、outer/JSON 可编码性验证、serialization 与 stdout channel，不拥有 concrete result/diagnostic Schema、命令跨字段矩阵、diagnostic 选择或领域状态转换。Human renderer 与 JSON writer 是同一 command outcome seam 的两个 adapter；这项复用不授权增加 Command Bus、万能 application result、动态 Context registry 或把 Literature/Knowledge 逻辑搬进 CLI。
