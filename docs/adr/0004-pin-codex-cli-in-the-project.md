# 在项目内精确锁定 Codex CLI

格致通过版本控制的语言中立 `runtimes/codex/runtime-identity-v1.json` 冻结唯一身份，并以同目录 `package.json` 和 `package-lock.json` 锁定已验收的 Codex CLI。`tools/codex.ps1` 是安装验收与人工项目入口；Literature/Knowledge runtime attempt 不把它当作 PowerShell wrapper，而是在 commitment 前由项目自有 resolver 从一个 held project-root capability 相对读取同一 identity、lock/package metadata 与 native executable，证明主包、Windows x64 native package 与唯一绝对 native CLI 路径，再按 [ADR 0106](./0106-run-command-owned-children-without-a-console.md) 直接以 `CreateProcessW` 启动该项目 `codex.exe`。这仍是调用 npm 锁定的 Codex CLI 原生实现；不得依赖 Codex 桌面应用 WindowsApps 目录中的随附 CLI，因为该目录由桌面应用更新器管理，会随应用版本被替换，也不得依赖用户级 npm 包，因为它可能被其他项目升级。`tools/codex.ps1`、runtime resolver 与 Doctor 必须消费同一 manifest；合同测试逐字段核对 version-controlled package/lock 并禁止脚本重新硬编码版本。每个业务 attempt 不运行隐藏的 `--version` child。

CLI 版本可以被冻结，但在线 Codex 服务的最低兼容版本不能由本仓库冻结。如果服务端明确拒绝当前版本，只阻塞语义阶段；随后开启一次受控依赖变更窗口，升级精确版本并重新通过版本、登录和非交互调用验收，才能形成新的冻结基线。
