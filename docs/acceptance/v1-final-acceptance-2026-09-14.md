# 格致 Windows 原生候选 V1 最终验收包

日期：2026-09-14。仓库：[Dulealex/Gezhi](https://github.com/Dulealex/Gezhi)，按用户决定保持公开。项目根目录：`E:\Gezhi`。

## 交付结论与最终审核

本包交付可运行的 Windows 原生 CLI：本地 PDF → OCR → Canonical Reading Asset → Reader → 显式 Candidate Review → Knowledge Intake → 检索与 Citable Answer。T26 的真实 Reader、获批合成候选导入与真实 Answerer 已通过；当前生产代码的分组回归合计 **1320 passed / 1 skipped**，静态检查和独立 Standards/Spec 复审通过。

这是候选 V1 的工程验收包，父 [Spec #1](https://github.com/Dulealex/Gezhi/issues/1) 的最终人工硬审核尚未进行。本文随 T26 PR 冻结验收事实；最终 squash 提交、T26 关闭、主工作树同步与合并后验证结果记录在 [Issue #27](https://github.com/Dulealex/Gezhi/issues/27)。工程交付完成不自动关闭父 Spec。

## 实际交付范围

- 八条日常命令：`doctor`、`status`、`literature add/resume/review`、`knowledge search/show/ask`，支持 Human 与 JSON；正式启动器为项目 `gezhi.exe` 与 `python.exe -m gezhi`。
- Literature 拥有 Work、Source、OCR/Canonical/Reader 资产、Candidate 与 append-only Review Decision。一个获批 Candidate 可立即完成交接，其余候选独立待审。
- Knowledge 只接收已审核交接，维护 active/withdrawn 状态、双路 FTS5 与固定 RRF 检索；回答绑定本次 Retrieval View 中的候选与证据。导入不产生 Promoted Knowledge。
- Codex CLI 是唯一语义 provider，项目锁定 `0.146.0 / gpt-5.6-sol / high`；OCR 使用冻结 MinerU 与 CUDA 离线 profile。
- Windows 文件身份、目录边界、writer 互斥、恢复、Job/pipe/capture、Ctrl+C 与输出失败按冻结合同实现。
- 后续 Bot 从 [CONTEXT-MAP](../../CONTEXT-MAP.md) 扩展领域上下文及版本化交接，采用静态组合。没有预建无业务定义的 Bot、动态插件发现或通用 DAG。

入口依据：[CLI grammar](../contracts/cli-command-v1.md)、[Literature](../contexts/literature/CONTEXT.md)、[Knowledge](../contexts/knowledge/CONTEXT.md)、[环境合同](../environment-contract.md)。

## 工单、原生依赖与合并追溯

2026-09-14 通过 GitHub 原生 `sub_issues` 与 `dependencies/blocked_by` 读取全部 26 张子工单，未发现依赖环或缺失工单。表中是直接依赖；所有间接依赖可递推得到。冻结本包时 T01–T25 已关闭，T26 的实现与验收已完成，合并/关闭结果由 PR #53 和 Issue #27 的最终交付记录确认。

| Ticket | Issue | 直接依赖 | PR / 验证与审查记录 | squash commit |
|---|---|---|---|---|
| T01 | [#2](https://github.com/Dulealex/Gezhi/issues/2) | — | [#28](https://github.com/Dulealex/Gezhi/pull/28) | `53ed8ac` |
| T02 | [#3](https://github.com/Dulealex/Gezhi/issues/3) | — | [#30](https://github.com/Dulealex/Gezhi/pull/30) | `e5d96f2` |
| T03 | [#4](https://github.com/Dulealex/Gezhi/issues/4) | T02 | [#32](https://github.com/Dulealex/Gezhi/pull/32) | `dc95f9a` |
| T04 | [#5](https://github.com/Dulealex/Gezhi/issues/5) | T02 | [#33](https://github.com/Dulealex/Gezhi/pull/33) | `685b28e` |
| T05 | [#6](https://github.com/Dulealex/Gezhi/issues/6) | T02 | [#34](https://github.com/Dulealex/Gezhi/pull/34) | `6a69e12` |
| T06 | [#7](https://github.com/Dulealex/Gezhi/issues/7) | T02 | [#35](https://github.com/Dulealex/Gezhi/pull/35) | `8ea3c44` |
| T07 | [#8](https://github.com/Dulealex/Gezhi/issues/8) | — | [#29](https://github.com/Dulealex/Gezhi/pull/29) | `6646150` |
| T08 | [#9](https://github.com/Dulealex/Gezhi/issues/9) | — | [#31](https://github.com/Dulealex/Gezhi/pull/31) | `746e772` |
| T09 | [#10](https://github.com/Dulealex/Gezhi/issues/10) | T01、T02、T03 | [#36](https://github.com/Dulealex/Gezhi/pull/36) | `8b9194d` |
| T10 | [#11](https://github.com/Dulealex/Gezhi/issues/11) | T01、T04、T09 | [#37](https://github.com/Dulealex/Gezhi/pull/37) | `283708c` |
| T11 | [#12](https://github.com/Dulealex/Gezhi/issues/12) | T04、T10 | [#38](https://github.com/Dulealex/Gezhi/pull/38) | `59e3f2a` |
| T12 | [#13](https://github.com/Dulealex/Gezhi/issues/13) | T04、T11 | [#39](https://github.com/Dulealex/Gezhi/pull/39) | `7dece54` |
| T13 | [#14](https://github.com/Dulealex/Gezhi/issues/14) | T07、T09 | [#40](https://github.com/Dulealex/Gezhi/pull/40) | `e9a3ca7` |
| T14 | [#15](https://github.com/Dulealex/Gezhi/issues/15) | T04、T12、T13 | [#41](https://github.com/Dulealex/Gezhi/pull/41) | `c8611cf` |
| T15 | [#16](https://github.com/Dulealex/Gezhi/issues/16) | T04、T14 | [#42](https://github.com/Dulealex/Gezhi/pull/42) | `696c43a` |
| T16 | [#17](https://github.com/Dulealex/Gezhi/issues/17) | T04、T15 | [#43](https://github.com/Dulealex/Gezhi/pull/43) | `e87b4d0` |
| T17 | [#18](https://github.com/Dulealex/Gezhi/issues/18) | T04、T16 | [#44](https://github.com/Dulealex/Gezhi/pull/44) | `aebabae` |
| T18 | [#19](https://github.com/Dulealex/Gezhi/issues/19) | T09、T16 | [#45](https://github.com/Dulealex/Gezhi/pull/45) | `868eae9` |
| T19 | [#20](https://github.com/Dulealex/Gezhi/issues/20) | T05、T18 | [#46](https://github.com/Dulealex/Gezhi/pull/46) | `e1fc269` |
| T20 | [#21](https://github.com/Dulealex/Gezhi/issues/21) | T06、T08、T09、T18 | [#47](https://github.com/Dulealex/Gezhi/pull/47) | `f62a321` |
| T21 | [#22](https://github.com/Dulealex/Gezhi/issues/22) | T06、T08、T13、T20 | [#48](https://github.com/Dulealex/Gezhi/pull/48) | `0173d34` |
| T22 | [#23](https://github.com/Dulealex/Gezhi/issues/23) | T06、T07、T13、T21 | [#49](https://github.com/Dulealex/Gezhi/pull/49) | `05b2acf` |
| T23 | [#24](https://github.com/Dulealex/Gezhi/issues/24) | T06、T08、T21、T22 | [#50](https://github.com/Dulealex/Gezhi/pull/50) | `e1a15b8` |
| T24 | [#25](https://github.com/Dulealex/Gezhi/issues/25) | T03、T09、T17、T18、T23 | [#51](https://github.com/Dulealex/Gezhi/pull/51) | `00c12d9` |
| T25 | [#26](https://github.com/Dulealex/Gezhi/issues/26) | T17、T19、T23、T24 | [#52](https://github.com/Dulealex/Gezhi/pull/52) | `cce159c` |
| T26 | [#27](https://github.com/Dulealex/Gezhi/issues/27) | T25 | [#53](https://github.com/Dulealex/Gezhi/pull/53) | 见 PR 合并记录 |

T13 的真实 production `resolve → freeze → run` 验收是合并后的独立关闭门，[Issue #14](https://github.com/Dulealex/Gezhi/issues/14) 已记录登录、capture、schema final 与 ledger 0 后完成关闭。历史测试结果属于当时提交，不当作本轮代码的重跑；当前最终回归结果见下一节。

## 验证结果及证据入口

| 层次 | 证据与结果 |
|---|---|
| 最终确定性主体 | `1319 passed, 1 skipped, 1 deselected in 913.08s` |
| 隔离实机登录正向 case | `1 passed in 0.44s`；覆盖主体唯一 deselected case |
| 总覆盖 | 全部 1321 个 case，1320 通过，1 项明确平台 skip |
| Knowledge Ask 公开合同 | 49 passed；三类检索停止与未完成关闭边界共 8 case |
| 静态检查 | Ruff `src tests`、全部 7 个变更 Python formatter、mypy 38 个 source files、Git diff check 通过 |
| 独立审查 | T26 Standards 0 个 hard finding，Spec 0 项 finding；先前问题及修正过程见 T26 记录 |
| 确定性全链 | [T25 / PR #52](https://github.com/Dulealex/Gezhi/pull/52)：两个 launcher、八命令、Human/JSON、恢复、withdraw/reaccept、零匹配和正常回答，均从真实公开 subprocess seam 验证 |
| 真实冻结环境 | [T26 完整记录](./t26-windows-real-environment-smoke-2026-08-31.md)：RTX 4090 离线 OCR、Canonical、真实 Reader/Answerer、Windows 边界、Doctor 与资产 hash |
| 合并后确认 | Issue #27 最终交付记录：main/origin 同步、关键 public seam 复验、工单关闭与 PR 清单 |

唯一 skip：`tests/test_literature_add_public_contract.py:486`，当前测试账户无法创建 Windows 符号链接（错误 1314）。相应 gate 未被当作通过；没有为运行测试变更系统权限。

确定性主体使用不存在的隔离 CODEX_HOME，真实登录正向探测使用已授权的实机 profile；全部 case 都在适用 profile 中执行。T26 PR 的 GitHub check rollup 在核验时为空；质量门来自记录中的本地冻结环境测试和独立审查，不能把“无远端 checks”写成“GitHub CI 已通过”。本轮在最终全仓结果后只补业务 smoke 与交付文档，未再改变生产代码。

## 真实闭环样例

该样例仅包含明确的合成测试内容。公开仓库保存身份、hash 和验收摘要；原始 PDF、OCR 输出、模型 capture 与研究资料仍位于本地 Data Root。

| 身份 | 值 |
|---|---|
| Work | `wrk_cb7ef3ee-2434-40d8-94f7-0fa75ecf8866` |
| Source | `src_06ba9857c54eef283cc3dacc` |
| 原始 PDF SHA-256 | `06ba9857c54eef283cc3dacc53821dc844b85ef68cdf03e5e8a71bd521de957d` |
| Reader run | `semrun_54cb1fe5-b5d3-47cf-a5ed-97cf48c5dc7f`；1 attempt、exit 0、50.563 秒 |
| 获批 Candidate | `cand_d9c18a7e7d42179d33817c5c`；review revision 1 |
| Handoff | `hnd_b9f572a9c6d9a38bd2067787`；正常 import applied |
| Answer | `ans_d6b6fef9-41b1-4f24-9791-2e19cce8e97e`；1 attempt、exit 0、53.203 秒 |
| Answer manifest SHA-256 | `136ff6d3892da4803f842db4e60b443d14c7d5edacc6df7fdee6976353680475` |
| 引用的 Evidence Block | `blk_9dfe76c859de41023829f296` |
| Governance | `accepted / active / not_promoted` |

问题：“在 synthetic trials 中，Versioned identifiers 是否保留了 provenance？”真实回答为肯定，并限定在三次合成试验。Answer Unit → Candidate payload → Handoff/Import → Canonical 内容身份/Evidence Block → 原始 Source 的引用链已经核验。Answer 的 11 份资产大小与 hash 全部一致；Markdown 明确显示 Candidate-backed 治理说明和来源引用。

双 launcher 重放 review 后 revision 仍为 1；resume 保留另三条 pending Candidate。最终 status 观察到 1 个 active Candidate、1 个 succeeded Answer、3 个 pending review，staging/orphan/quarantine/inconsistent 计数均为 0；Doctor 七项 ready。pending 是预期的逐条业务审核状态，不是 T26 技术验收失败。

## 在当前机器使用

以下命令在合并并同步后的 `E:\Gezhi` 中执行；只设置当前 PowerShell 进程环境，使用已安装且冻结的环境。

```powershell
Set-Location E:\Gezhi
$env:PYTHONPATH = 'E:\Gezhi\src'
$env:CODEX_HOME = 'E:\gzrt\codex'
$env:TEMP = 'E:\gzrt\temp'
$env:TMP = 'E:\gzrt\temp'
$gezhiCli = 'E:\Gezhi\.venv\Scripts\gezhi.exe'
$gezhiRoots = @(
  '--literature-data-root', 'E:\Gezhi\data\t26-real-smoke\literature',
  '--knowledge-data-root', 'E:\Gezhi\data\t26-real-smoke\knowledge'
)

& $gezhiCli @gezhiRoots doctor
& $gezhiCli @gezhiRoots status
& $gezhiCli @gezhiRoots knowledge search 'Versioned identifiers provenance'
& $gezhiCli @gezhiRoots knowledge show cand_d9c18a7e7d42179d33817c5c
```

查看已完成的回答可直接打开本地文件：
`E:\Gezhi\data\t26-real-smoke\knowledge\answers\ans_d6b6fef9-41b1-4f24-9791-2e19cce8e97e\answer.md`。

日常新资料流程：`literature add PDF_PATH` 返回 Work ID，`literature resume WORK_ID` 推进至审核，用户针对 Candidate 执行 `literature review CANDIDATE_ID --accept/--reject/--defer`，然后 `knowledge ask QUESTION`。Ask 通过 pre-ID 检查后为本次请求生成独立 Answer ID；是否成功提交以完整回执为准。非空 Retrieval View 通过大小、runtime 与调用前置检查后才调用真实 Codex。每次审核只选择一个 action。需要机器输出时在 leaf command 后加 `--json`，每次执行后立即检查 `$LASTEXITCODE`。完整 token 和 option 位置以 CLI grammar 为准。

## 冻结环境与工作区交接

核心、OCR、Codex 三套锁及 runtime/model manifests 保持批准基线内容。根 checkout 的原始 bytes/SHA-256、worktree 的 CRLF 差异说明和实际版本见 T26 记录；使用 Git clean 内容比较，未重新解析或更新锁。环境缺失时阻断受影响工作，不在运行过程中自动安装依赖。

合并前已盘点根 checkout 加 21 个历史/当前 linked worktree，全部 clean，实际 `.worktrees` 目录与 Git 注册清单完全一致。历史工作树保留供追溯，没有删除。登记的目录为：

```text
t02-cli-contract                 t03-operations-contract
t04-literature-contract          t05-knowledge-read-contract
t06-knowledge-ask-observable      t07-codex-child
t08-answer-terminal              t09-doctor-windows-seam
t13-codex-role-attempt           t14-literature-reader
t15-candidate-materializer       t16-review-handoff
t17-literature-resume            t18-knowledge-import
t19-knowledge-read               t20-knowledge-ask-no-model
t21-citable-answer               t22-knowledge-attempt
t23-answer-terminal              t24-status
t26-real-environment-smoke
```

本包落盘期间的待提交修改只属于 T26 验收文档；提交并合并后再次检查 clean、main 与 origin/main 一致和无开放实施 PR，将准确 SHA 与结果追加到 Issue #27 的交付记录。公开状态不扩大凭据、个人配置、原始或派生研究资料的发布范围。

## 最终审核应知道的限制

1. 首次正常 import 之前，缺失 Registry 的 `knowledge ask` 尚无冻结的受控错误码，会在正常回执矩阵外退出。合法空 Registry 则正常返回证据不足。若要改善首次使用体验，需要后续单独演进合同。
2. 一项符号链接创建测试受当前 Windows 权限限制而 skip；本包如实保留这一未覆盖条件。
3. 真实模型 smoke 证明当前环境接通且合成证据闭环，不代替真实研究内容的语义质量评估。合成源作者、年份、题名未知，引用如实显示未知。
4. 当前交付为 CLI；GUI、自动联网收集、动态插件、Promotion Gate 与新 Bot 的具体业务不属于本轮 V1。未来扩展按 Context/ADR/合同流程推进。

用户最终审核重点是日常流程是否可用、引用与审核语义是否符合预期，以及是否接受上述已知限制。最终确认前，父 Spec #1 保持打开；若需要修改，按受影响范围建立或重开明确工单。
