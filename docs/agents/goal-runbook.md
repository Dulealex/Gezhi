# Goal 长期运行手册

本手册用于在 Codex Goal mode 中持续完成 GitHub 父 Spec `#1` 下的实施子工单 `T01`–`T26`（GitHub `#2`–`#27`）。Goal 是协调器；GitHub Issues、提交、测试和 PR 是可恢复的持久进度，不以聊天上下文作为唯一状态来源。

## 启动前提

只有同时满足以下条件才能开始长期 Goal：

1. 本地 `main` 工作区干净，并与远端 `origin/main` 一致。
2. GitHub 父 Spec `#1`、26 个子工单及原生 `blocked by` 关系均可读取。
3. `AGENTS.md`、`CONTEXT-MAP.md`、相关 Context、ADR 和合同已提交到基线。
4. Python、OCR、Codex 和 native build 环境保持 `docs/environment-contract.md` 的冻结状态。
5. 当前 Goal 明确声明是否授权 commit、push、PR merge 和关闭子工单；未明确授权的动作不得从本手册推定。
6. Codex App 已启用运行期间防休眠和通知，工作区在运行期间保持可用。

## 事实来源顺序

发生冲突时，按以下顺序处理：

1. 用户在当前 Goal 中的明确指令。
2. 根目录 `AGENTS.md` 及任务路径下更近的指令。
3. GitHub Issue 的完整正文、评论、标签和原生依赖。
4. 父 Spec `#1`。
5. `CONTEXT-MAP.md`、Context 文档、已接受 ADR 和版本化合同。
6. 当前实现和测试所反映的既有行为。
7. WSL PaperBot 只作为只读行为和边界参考，不是代码或架构事实来源。

如果较低优先级来源与较高优先级来源冲突，不得静默选择；记录冲突并按“阻塞处理”执行。

## 完成定义

一个子工单只有在下列条件全部满足时才算完成：

- 工单全部验收标准已经实现并有证据。
- 相关测试、静态检查和合同检查通过。
- 从真实 Windows public CLI subprocess seam 验证可观察行为；只有公共 seam 无法穷举的合同才使用窄内部测试。
- 变更经过独立代码审查，且所有高优先级问题已解决。
- 没有未授权的依赖、锁文件、环境、仓库设置或范围变化。
- PR 已合并到 `main`，对应子工单已关闭；如果当前 Goal 未授权 merge/close，则停在 `ready-for-human`，不能声称完成。
- 合并后的 `main` 仍通过该工单的验收门。

整个 Goal 只有在 `T01`–`T26` 全部完成后才算成功。父 Spec `#1` 保持打开，等待最终人工验收；本手册不授权关闭或改写父 Spec。

## 调度循环

协调器在每次选择工作前执行以下循环：

1. 读取父 Spec `#1` 的全部子工单、标签、状态、评论和原生依赖。
2. 只把同时满足以下条件的工单放入 frontier：
   - 状态为 open；
   - 带 `ready-for-agent`；
   - 不带 `needs-info`、`ready-for-human` 或 `wontfix`；
   - 所有原生 blocker 均已关闭；
   - 当前 Goal 中没有其他 worker 已领取它。
3. 按 `Txx` 数字升序稳定排序；除非更高优先级的修复会解除更多 blocker，否则领取最小编号。
4. 最多同时运行三个 worker。并行工单必须在依赖和文件所有权上独立。
5. 每个 worker 结束后，协调器重新读取 GitHub 状态；不得依赖启动时缓存继续调度。
6. 如果 frontier 为空：
   - 所有 `T01`–`T26` 均关闭：运行最终验收并完成 Goal；
   - 仍有可推进 blocker：先推进 blocker；
   - 只剩 `needs-info` 或 `ready-for-human`：汇总一次人工介入报告并暂停；
   - 存在依赖环、缺失 blocker 或状态矛盾：按阻塞处理，不能猜测。

单张工单失败或阻塞不能终止整个 Goal，只影响消费该合同或依赖的分支。

## Worker 与 worktree

- 协调器负责任务选择、依赖核对、审查和合并，不与 worker 同时编辑相同文件。
- 每张工单使用一个新鲜执行上下文和独立分支，命名为 `codex/tXX-<short-slug>`。
- 并行 worker 使用仓库内被忽略的 `.worktrees/tXX-<short-slug>`；创建前验证解析后的绝对路径仍位于 `E:\Gezhi\.worktrees`。
- 同一分支不能同时被两个 worktree 使用；同一文件所有权不清时改为串行。
- worker 开始前必须基于最新 `origin/main`，并读取完整 Issue、评论和适用指令。
- 合并前重新同步 `main` 并运行相关验收；不得把旧基线测试结果带到新基线。
- 只有在 worktree 干净且对应提交已可从远端恢复时才允许复用或移除；本手册不授权删除含未提交内容的 worktree。

## 单张工单生命周期

1. **领取**：在 Issue 评论中记录工单、分支、worktree、开始时间和预期验收；不发明新的 in-progress 标签。
2. **理解**：读取完整 Issue、评论、适用 Context、ADR、合同和当前代码；列出只属于本票的目标与非目标。
3. **测试先行**：从公开 seam 写出会失败的验收，确认失败原因与本票目标一致。
4. **实现**：完成最窄的纵向切片；不得顺手实现后续工单或改变依赖。
5. **验证**：运行定向测试、相关测试集、格式/静态检查及必要的真实 subprocess 验收。
6. **审查**：由不同于实现上下文的 reviewer 检查标准符合性和实际 bug；修复后重跑验收。
7. **发布**：提交清晰 commit，push 分支，创建带 `Closes #<issue>` 的 PR，并附测试证据。
8. **结束**：
   - 当前 Goal 已明确授权且检查通过：合并 PR，确认 Issue 关闭，再推进下游；
   - 未授权 merge/close：移除 `ready-for-agent`，添加 `ready-for-human`，等待人工；
   - 失败或信息不足：按阻塞处理。

## MATT 与技能路由

- 规格和 tickets 已分别由 `to-spec`、`to-tickets` 完成；实施不得重新打开已批准范围。
- 开始每张票前判断应使用的最小 MATT skills 组合，并遵循其完整流程。
- 行为变更和 bug fix 默认优先采用测试先行；需要领域词汇或深模块决策时，分别使用领域建模或代码库设计流程。
- PR 合并前执行独立 code review；修复审查意见后重新验证。
- Skill 造成暂停或需要用户选择时，只阻塞它实际影响的工单。

## 依赖与环境冻结

- 禁止执行 `uv add`、`uv remove`、升级锁文件、`npm update`、切换模型供应商或任何隐式改变依赖图的操作。
- 允许按环境合同运行只读或冻结验证，例如锁一致性、已安装包兼容性和版本检查。
- 缺失、漂移或失效的依赖只阻塞消费它的工单；添加 `needs-info` 并继续其他 frontier。
- `uv.lock`、OCR lock、Codex `package-lock.json`、项目 package mode 和 console entry target 在普通实施票中不得变化。
- Codex CLI 是唯一语义 provider；不得加入 Ollama、本地小模型、模型 router 或 OpenAI Python SDK。

## GitHub 状态与阻塞处理

使用 `docs/agents/triage-labels.md` 的五种标签，不新增同义状态。

当工单需要人工介入时：

1. 在 Issue 评论中记录：阻塞事实、已完成证据、无法安全推导的最小问题、可选方案及影响。
2. 移除 `ready-for-agent`，添加 `needs-info`；已有可审查成果但只差人工动作时改用 `ready-for-human`。
3. 不关闭 Issue，不伪造验收，不把 staging 或 partial 解释为完成。
4. 重新计算 frontier，继续所有不受影响的工单。
5. 只有没有任何 frontier 时，向用户发送一份去重后的集中问题清单并暂停 Goal。

下列情况必须人工介入或取得新授权：

- Spec、合同和 ADR 无法决定的外部可观察产品选择。
- 新增、删除、升级依赖或改变冻结环境。
- 凭据、登录、仓库权限、Secrets、付费或外部账户操作。
- Release、部署、公开发布、删除权威数据或其他不可逆操作。
- 自动审批拒绝且安全替代路径不能完成验收。
- T26 需要的真实硬件、实际 PDF 或语义质量判断无法由现有环境提供。

普通编码选择、可逆重构、测试修复和已经由合同决定的细节不需要人工介入。

## 授权边界

长期 Goal 可以在目标文本明确授权后，在私有仓库 `Dulealex/Gezhi` 内执行以下动作：创建分支和 worktree、commit、push、创建 PR、在检查与独立审查通过后合并 PR并关闭对应子工单。

无论 Goal 文本是否授权上述动作，下列事项始终需要单独明确授权：

- 关闭或改写父 Spec `#1`；
- 改变依赖、锁文件、模型供应商或冻结工具链；
- 修改仓库可见性、成员、权限、Secrets、保护规则或计费；
- 创建 Release、部署或向仓库范围外发送项目数据；
- 删除无法从已推送 Git 历史或不可变资产恢复的数据。

Goal mode 不扩大 Codex 的 sandbox、网络或审批权限。工具权限不足时走现有审批；审批失败后采用安全替代路径或按阻塞处理。

## 检查点与恢复

每张工单结束时必须把以下信息写入 Issue 或 PR：

- branch、commit 和 PR；
- 已满足的验收标准；
- 执行的验证命令与结果摘要；
- 剩余风险、阻塞或后续工单；
- 是否改变 public contract（正常情况下应为否）。

Goal 被暂停、聊天压缩、应用重启或 worker 丢失后，从以下步骤恢复：

1. 读取本手册和 `AGENTS.md`；
2. 获取 `origin/main`、当前 open PR、父 Spec 子工单和原生依赖；
3. 检查所有 Goal worktree 的分支、HEAD、clean 状态和对应 PR；
4. 以 GitHub/提交/测试证据重建领取表，不根据聊天记忆猜测；
5. 对不确定的 worktree 保持只读并标记人工检查，继续其他可证明安全的 frontier。

## 最终验收

关闭最后一个子工单前，至少证明：

- `T01`–`T26` 的验收证据均可从 Issue/PR 追溯；
- 确定性全链测试通过，真实环境 smoke 与确定性 CI 分离；
- 两个 launcher、八个命令、Human/JSON、恢复、Ctrl+C 和引用闭环均满足 Spec；
- `main` 与 `origin/main` 一致，工作区干净；
- 冻结依赖和锁文件相对批准基线无漂移；
- 没有 open implementation PR、未登记 worktree 或被误判为成功的 `needs-info` 工单。

完成后向用户提交总报告，但保持父 Spec `#1` 打开，等待最终人工验收。
