# ADR 0128：冻结一个项目锁定的 Codex role invocation profile

状态：已接受

## 背景

[ADR 0033](./0033-use-two-isolated-codex-runtime-roles.md) 已决定 Literature Reader 与 Knowledge Answerer 只通过项目锁定的 Codex CLI 运行，并要求 ephemeral、只读、无交互、忽略用户配置与规则、禁用无关工具。现有决策没有冻结 exact argv 顺序、工作目录或 Unicode environment allowlist；[Codex Child Process v1](../contracts/codex-child-process-v1.md) 又要求这些值在进入进程模块前已经不可变。

继续让调用方临时拼 argv 或复制 `os.environ` 会令不同 Bot 获得不同权限，也会把用户插件、代理秘密、PATH shim 或调试变量静默带入 runtime plane。

## 决策

采用 [Codex Role Invocation v1](../contracts/codex-role-invocation-v1.md) 作为两个 V1 角色共享的唯一调用 profile：

- executable 只能来自 project-pinned resolver 形成的 sealed proof；proof 身份由语言中立 `runtimes/codex/runtime-identity-v1.json` 冻结，并携带 executable path、FileIdentity、size 与 SHA-256；test double 使用不同 `proof_kind` 的私有 factory；
- 固定 Codex CLI `0.146.0`、模型 `gpt-5.6-sol`、reasoning `high`；
- prompt 只经 stdin，Schema 与 final spool 只经 absolute path；
- cwd、TEMP、SQLite 与 capture parent 来自 non-cloneable sealed attempt workspace；公开构造、`dataclasses.replace`、字段复制或伪造 seal 均不产生授权值；attempt root 冻结恰含四个 child 的 entry set，四个 child 冻结为空，commitment 前连同当前 role 实际消费的 authoritative root identity 一并持有复验；Schema 另绑定 identity、size 与 SHA-256；
- 使用 `--ephemeral`、`--ignore-user-config`、`--ignore-rules`、`--strict-config`、只读 sandbox 与 `approval_policy="never"`；
- 显式关闭 web search、shell、browser、computer use、MCP/plugin/skill discovery、multi-agent 及其他无关模型工具；
- child environment 是大小写闭合、排序确定的最小 allowlist；不继承 PATH、HOME、USERPROFILE、APPDATA、LOCALAPPDATA、ComSpec、RUST_LOG 或未知变量；
- `CODEX_HOME` 只提供既存认证状态；`--ignore-user-config` 阻止其中的 `config.toml` 参与行为选择；`CODEX_SQLITE_HOME`、TEMP 与 TMP 指向 attempt-private 目录；
- raw JSONL 的 provider failure 与 usage/metadata receipt 解释不属于共享 child。T13 先冻结 raw capture 与 lifecycle evidence，T14/T22 的 role adapter 再按自己的版本化合同分类并形成 receipt。

## 结果

新增 Bot 若采用同一 process module，必须显式选择一个版本化 role invocation profile；不能通过环境变量 executable override、PATH fallback 或复制用户环境接入。Codex CLI 升级时必须先新增或更新合同、锁文件、feature list 与 deterministic tests，不能只更新全局 Codex。

[ADR 0134](./0134-prove-only-the-data-root-consumed-by-a-codex-role.md) 后续替换了同时证明 Literature/Knowledge 两个 root 的旧边界：workspace 绑定唯一 role，只 physical probe 该 role 实际消费的 Context Data Root。
