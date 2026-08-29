# Codex Role Invocation v1 合同

状态：已冻结。本文关闭 [ADR 0033](../adr/0033-use-two-isolated-codex-runtime-roles.md) 与 [Codex Child Process v1](./codex-child-process-v1.md) 之间的 exact argv、cwd、environment 与 resolver-proof 缺口。本文不解析 provider events，不拥有 Reader Input、Question、Schema 内容或领域结果。

## 1. 唯一 runtime identity

每个 semantic invocation 在第一次 attempt commitment 前恰好解析一次项目 runtime，并让 proof 对本 invocation 的全部 retry 粘性不变。resolver：

- 从同一个 held project-root capability 相对读取语言中立 `runtimes/codex/runtime-identity-v1.json`、`package.json`、`package-lock.json`、installed package metadata 与 native executable；不得关闭 root 后按原始 pathname 另开一代目录；
- 严格验证 `@openai/codex` `0.146.0`、main/native lock integrity、六项 optional alias closure、installed main/native name 与 version；
- 证明 native package 全链无 reparse，且只有一个名为 `codex.exe` 的普通 leaf，位置恰为 `vendor/x86_64-pc-windows-msvc/bin/codex.exe`；
- 只返回 handle-derived absolute canonical path、file identity、size、SHA-256 与冻结版本；
- 不运行 `--version`、`login status` 或任何 child，不查 PATH、App Paths、npm shim、全局/桌面 Codex、PowerShell wrapper 或 WSL。

descriptor 以 no-follow handle 有界读取，必须是 strict UTF-8 JSON object；duplicate key、超过 1 MiB、身份漂移或关闭失败均拒绝 proof。Doctor 可以在 proof 之后另做自身拥有的只读在线探测，但 runtime invocation 不继承该行为。

## 2. role 与共同常量

| 字段 | 精确值 |
|---|---|
| role | `literature_reader_v1` 或 `knowledge_answerer_v1` |
| CLI | `0.146.0` |
| model | `gpt-5.6-sol` |
| reasoning | `high` |
| single-attempt duration | `1,800` 秒 |
| successfully-started shared window | `5,700` 秒 |
| prompt transport | exact immutable stdin bytes，argv 中只出现 `-` |
| stdout | `--json` JSONL raw bytes，由 child module 捕获 |
| stderr | child module 的 `NUL`，不捕获、不分类 |

role builder 只接受 resolver-sealed 且 `proof_kind=project_pinned` 的 opaque proof，不接受可直接实例化的 proof、executable path string、environment executable override 或 provider/router object。test-only executable double 只使用独立 private factory 形成的 `proof_kind=test_double` proof；两个 kind 在 plan validation 时交叉拒绝，且 test proof 不能进入 production config 或 fallback。

attempt workspace 与 launch plan 都是 non-cloneable sealed value：公开构造器拒绝直接实例化，只有本模块的 private builder 能按 exact field set 物化并计算 seal；`dataclasses.replace`、手工复制字段、伪造 seal 或把 test proof 换进 production plan 都不能形成可授权的实例。child module 在使用前重新验证完整 seal 与 proof kind，不能只因对象类型或 `proof_kind` 字符串相同就信任它。

## 3. exact argv

argv 第一项是 resolver-proof absolute executable path，随后按以下顺序逐项冻结；尖括号表示由当前 attempt 已验证并冻结的一个 argv element，不是 shell interpolation：

```text
<codex.exe>
exec
--ephemeral
--ignore-user-config
--ignore-rules
--strict-config
--skip-git-repo-check
--model
gpt-5.6-sol
--sandbox
read-only
--cd
<attempt-private-working-directory>
--output-schema
<absolute-versioned-schema-path>
--output-last-message
<fresh-writer-private-final-spool-path>
--json
--color
never
--config
approval_policy="never"
--config
model_reasoning_effort="high"
--config
web_search="disabled"
--config
agents.enabled=false
--config
allow_login_shell=false
--config
shell_environment_policy.inherit="none"
```

随后对下列 frozen sequence 中的每个值追加 `--disable` 与该值，最后追加唯一的 `-`：

```text
apps
auth_elicitation
browser_use
browser_use_external
browser_use_full_cdp_access
code_mode_host
computer_use
goals
hooks
image_generation
in_app_browser
multi_agent
plugins
request_permissions_tool
skill_mcp_dependency_install
skill_search
shell_tool
tool_call_mcp_elicitation
tool_suggest
workspace_dependencies
```

`--strict-config` 令未知配置失败而不是静默降级。不得追加 profile、MCP、plugin、skill、image、`--add-dir`、live search、OSS/local provider、resume 或 bypass-sandbox 参数。

Literature 的条件式 final capture 不改变 production argv：它仍提供 fresh spool pathname；若 Codex 未产生该 pathname，Literature 不补造正式 `final_message.txt`。test-only D27 可以构造没有 final pathname 的静态 capture profile，但不是 production invocation。

## 4. Windows quoting

项目实现自己的 CommandLineToArgvW-compatible quoting：

- 每个 element 保持原始 Unicode scalar sequence；NUL 拒绝；
- 空 element 或含 space、tab、quote 的 element使用双引号；
- quote 前连续 backslash 数量加倍并再加一；结束 quote 前的尾部 backslash 数量加倍；
- elements 之间恰有一个 U+0020；不经 shell、cmd、PowerShell 或环境展开。

不可变 quoted value 以 UTF-16LE bytes 计算 SHA-256 用于 audit identity。传给 `CreateProcessW` 的 writable、NUL-terminated copy 由 child module 私有拥有；Windows 对 copy 的原地改写不得回写 argv、quoted value 或 hash。

## 5. cwd 与 path profile

role builder 先形成一个绑定唯一 role 的 sealed attempt workspace。其 root 恰好只有 `captures`、`sqlite`、`temporary`、`working` 四个 immediate directory，四者在 plan formation 与 commitment 前复验时都为空；root 与四个 child 的 canonical path 和 FileIdentity 一并冻结。只有该 role 实际消费的 authoritative root 取得 FileIdentity：`literature_reader_v1`只证明 Literature root，`knowledge_answerer_v1`只证明 Knowledge root；未消费 Context 的 root 不做 physical open/probe。role-owned root只冻结 identity而不冻结业务 entry set，并与 attempt root物理隔离。attempt ordinal 只由 builder 派生 `captures/NN` 与 `captures/.NN.codex-stage`，调用方不能分别拼接这些路径；精确边界由 [ADR 0134](../adr/0134-prove-only-the-data-root-consumed-by-a-codex-role.md) 冻结。

working directory、Schema、`CODEX_HOME`、`CODEX_SQLITE_HOME`、TEMP/TMP 与 capture parent 都必须在 commitment 前通过 no-follow、无 reparse 的 absolute local path validation。plan 到 commitment 之间，child module 重新打开并持有关键 path capability：attempt root 必须仍是同一 FileIdentity 且 immediate entry set 恰为上述四个目录；`captures`、`sqlite`、`temporary`、`working` 四个 child 必须仍是各自冻结的 FileIdentity 与 exact empty entry set；唯一 role-owned authoritative root 与 `CODEX_HOME` 只复验 directory identity；project-pinned executable 必须仍匹配 runtime proof 的 identity、size 与 SHA-256；Schema 必须仍匹配 plan 冻结的 identity、size 与 SHA-256。同路径删除重建、pathname replacement 或原地内容修改均在 `CreateProcessW` 前拒绝。working directory：

- 已存在、attempt-private，且不是项目目录、当前 role-owned authoritative store 或其祖先；
- 不依赖 Git，故 argv 固定使用 `--skip-git-repo-check`；
- 不含项目 `.codex`、`AGENTS.md`、rules、plugins、skills 或业务资产；
- read-only sandbox 仍保留为第二道 model-tool 防线，不能替代禁用工具。

capture target 与 private staging 是同一 validated parent 下两个尚不存在的安全 sibling。final spool 位于 private staging，launch 前 pathname 不得存在。

`CODEX_HOME` 是部署者提供的共享 auth/state capability：只冻结并复验 directory identity，不冻结 entry set，也不把正常 token refresh 当成 attempt workspace 漂移；`--ignore-user-config` 仍保证其中配置不参与行为选择。composition 必须保证 attempt-private root 在本 attempt 中只有一个可信 owner；同权限外部进程在最后一次 entry-set 复验后主动向该 private namespace 注入新 entry 不属于对抗性 sandbox 承诺。

## 6. exact Unicode environment allowlist

source environment 先按 Windows case-insensitive name 建索引；任何大小写碰撞、空 name、name 中 `=`、或 name/value 中 NUL 都令 plan formation 失败。输出使用以下 canonical names：

必需且由 plan 覆盖：

```text
CODEX_HOME
CODEX_SQLITE_HOME
SystemRoot
TEMP
TMP
```

可选、仅在 source 中非空存在时原值复制：

```text
ALL_PROXY
CODEX_ACCESS_TOKEN
CODEX_API_KEY
CODEX_CA_CERTIFICATE
HTTP_PROXY
HTTPS_PROXY
NO_PROXY
SSL_CERT_FILE
```

除上述名称外不得继承任何变量。尤其禁止 PATH、PATHEXT、ComSpec、HOME、USERPROFILE、APPDATA、LOCALAPPDATA、OPENAI_API_KEY、RUST_LOG、Python、uv、Ollama 与项目 secret aliases。

entries 按 canonical name 的 Unicode casefold ascending 排序，以 `name=value` 编码为 UTF-16，entry 间一个 NUL，末尾两个 NUL。environment block 只在 attempt memory 中存在，repr、manifest、provenance、diagnostic 与 CLI output 只能记录允许的 name set，不能记录 value、value hash 或 block hash。

`CODEX_HOME` 必须已存在，只用于 Codex auth/state root；`--ignore-user-config` 保证其中的 `config.toml` 不参与本次运行。`CODEX_SQLITE_HOME`、TEMP、TMP 指向当前 attempt 的既存私有目录，隔离 session/state/temp writes。`--ephemeral` 禁止 session rollout 持久化。provider HTTPS/WebSocket transport 与 Windows system trust store不属于 model web/network tool，仍可使用；显式 CA/proxy变量只在部署者已经提供时透传。

## 7. capture 与 provider boundary

本合同只形成 [Codex Child Process v1](./codex-child-process-v1.md) 所需的 frozen launch plan。child module先完成 raw capture、Job tree settlement、timeout/cancel/overflow/lifecycle evidence 与 ledger=0，再返回 immutable evidence。

Codex `0.146.0` 的 `exec --json` 会把 Core 的结构化错误信息投影成只有 `message` 的 `error` / `turn.failed`，因此没有可供 role adapter 稳定区分 `runtime_unavailable`、`rate_limit`、`server_error`、`network` 或上下文不足的 machine discriminator。[ADR 0129](../adr/0129-retry-only-mechanically-classified-codex-timeouts.md) 要求 T14 Literature Reader adapter：

- 只消费已经安装并冻结的 raw capture；
- 禁止从 stderr、自然语言、exit `130`、`259` 或内部 Job DWORD猜测；
- 只把 T13 terminal evidence 已机械证明的 `timeout` 作为可重试 failure class；
- 不解析 `message`、stderr、自然语言或退出码来猜测 provider 类别；
- 将已安全收尾的其他 provider terminal、未知 nonzero exit 与事件结构失败最终映射为 `process_error`，且不重试。

因此 T13 terminal evidence 只拥有 raw capture、mechanical outcome、lifecycle facts 与可用的 monotonic anchors，不包含 role usage/metadata receipt。Literature receipt 由 T14 形成；Commitment 前由 resolver、认证或 launch-plan preflight 确认的 runtime failure 仍不创建 attempt，并保留 Reader 的 `codex_runtime_unavailable` blocked 路径。Knowledge 的 provider/usage/retry receipt 仍由 T22 拥有，但其既有 manifest Schema 与 diagnostic union 已单独冻结；T22 必须先以版本化决策解决相同 projection gap，不能从本合同推导 message parsing 或自动继承 Reader 的枚举变更。Issue T13 中的“usage/metadata receipt”交付项由这个显式的 role-owned post-capture seam 满足，而不是把 provider Schema 泄漏进共享 child module。

未来 Bot 不能因复用 invocation/process module 而自动继承任一现有 role 的 provider、usage、retry、capture cap 或领域结果语义。
