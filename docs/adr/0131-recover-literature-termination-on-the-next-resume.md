# ADR 0131：在下一次 resume 恢复 Literature 外部终止

状态：已接受

Windows V1 的公开 `literature resume` 不安装 Knowledge Ask 专属的 Ctrl+C cancellation bridge，也不把 Literature 产品 adapter 伪装成可产生 handled cancellation 的命令。Reader 调用共享 Codex child 时使用 no-source cancellation observation；用户关闭终端、结束 CLI 或 Ctrl+C 导致的外部进程终止不承诺返回 Human/JSON `interrupted` 结果。

共享 child 的 mechanical `interrupted` evidence 仍作为组合能力和测试状态存在，但 T14 的公开 Literature adapter 不可到达该 handled 分支。若外部终止发生在 Reader staging 已建立之后，下次持有同一 Work writer ownership 的 `literature resume` 必须先安全盘点 staging，把能完整证明的 attempt/capture provenance 终态化为 immutable `status=interrupted` audit run，再开始新的逻辑 read；partial、foreign、reparse、歧义或无法证明的 staging 保持原位并返回 recovery failure，绝不补成 success。

这条边界保持“项目构建使用 Codex”和“格致运行时使用 Codex”互不共享取消能力：Codex Desktop/CLI 对仓库的开发会话不拥有产品命令的 Work lease、staging 或 Review capability；产品 Reader 子进程也不能取消或控制开发会话。
