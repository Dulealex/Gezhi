# 在项目内精确锁定 Codex CLI

格致通过 `runtimes/codex/package.json` 和 `package-lock.json` 精确锁定已验收的 Codex CLI，并统一经 `tools/codex.ps1` 调用。不得依赖 Codex 桌面应用 WindowsApps 目录中的随附 CLI，因为该目录由桌面应用更新器管理，会随应用版本被替换；也不得依赖用户级 npm 包，因为它可能被其他项目升级。

CLI 版本可以被冻结，但在线 Codex 服务的最低兼容版本不能由本仓库冻结。如果服务端明确拒绝当前版本，只阻塞语义阶段；随后开启一次受控依赖变更窗口，升级精确版本并重新通过版本、登录和非交互调用验收，才能形成新的冻结基线。
