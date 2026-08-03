# 首版只交付一个 Windows 原生 CLI

格致首版只提供统一的 `gezhi` CLI：日常交互使用简洁命令与 Rich 进度/表格，每个命令同时提供稳定 `--json` 输出，Literature、Knowledge 和未来上下文通过命名空间隔离。内部阶段可以通过正式子命令恢复和测试，但不维护重复的工具包装脚本；桌面 GUI、本地网页服务、后台守护进程和托盘程序延后，未来界面只能复用相同应用服务而不得重写业务流程。

ADR 0089 进一步把 `--json` 冻结为共享五字段 `CliResultEnvelopeV1`：Context adapter 不自行打印 JSON，共享 writer module 独占闭合、确定性序列化与 stdout；JSON mode 不混入 Rich progress。Concrete result、diagnostic 与 exit-code 合同按命令逐项冻结，新增 Context 通过静态 composition 复用该 interface，不建立插件系统。
