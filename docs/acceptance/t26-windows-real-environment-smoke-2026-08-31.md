# T26 Windows 真实冻结环境 smoke（2026-08-31）

## 结论

当前状态：**部分通过，Codex 业务角色仍受阻**。

- PASS：冻结核心环境、OCR 环境、项目锁定 Codex CLI 身份与登录探测。
- PASS：真实 RTX 4090 / CUDA MinerU 离线 OCR。
- PASS：真实 public CLI 的 OCR 提交与 Canonical Reading Asset 提交。
- PASS：Ctrl+C、pipe、broken pipe、文件占用、console/no-console Windows 边界。
- PASS：项目锁定 Codex CLI 的纯 synthetic 在线连通性。
- BLOCKED：Literature Reader 与 Knowledge Answerer 的 sealed runtime smoke。当前认证只存在于会产生隐藏 8.3 短别名的 `C:\Users\81048\.codex`；合同要求一个位于项目外、无 reparse、无隐藏短别名的既存 `CODEX_HOME` capability。

Reader/Answerer 完成前，本记录不能作为 T26 完成证明，Issue #27 不应关闭。

## 追溯范围

- GitHub Issue：[T26 / #27](https://github.com/Dulealex/Gezhi/issues/27)
- 基线：`main@cce159c6c93bfb6257c8025c31d506a0bd75b11e`
- 分支：`codex/t26-real-environment-smoke`
- T25 确定性证据：[Issue #26](https://github.com/Dulealex/Gezhi/issues/26)、[PR #52](https://github.com/Dulealex/Gezhi/pull/52)
- 本记录只描述真实环境 smoke；T25 继续拥有确定性 CI 全链证据。

## 安全与数据边界

- 未运行 WSL、Ollama、其他本地模型或备用 provider。
- 未安装、同步、升级或重新解析依赖。
- 下载目录中的科研 PDF 只在本机离线 OCR；安全门拒绝把它的内容发送给 Codex，未绕过该拒绝。
- 真实 Codex 调用只接收明确标注为 synthetic、无用户或机密内容的测试文本。
- 所有业务写入位于忽略的 T26 隔离根；未写默认正式 Data Root。

## 冻结身份

### Runtime

| 项目 | 实际值 | 结果 |
|---|---:|---|
| core CPython | `3.11.15` | PASS |
| OCR CPython | `3.11.15` | PASS |
| MinerU | `3.4.4` | PASS |
| torch | `2.9.1+cu130` | PASS |
| torchvision | `0.24.1+cu130` | PASS |
| Codex CLI | `0.146.0` | PASS |
| Codex 登录探测 | `Logged in using ChatGPT`，exit `0` | PASS |

### Versioned locks 与 manifests

以下 SHA-256 从实际执行 smoke 的根 checkout `E:\\Gezhi` 采集，且在 smoke 前后相同。T26 linked worktree 会把未声明 EOL 的三个文本 lock 展开为 CRLF，因此其 checkout 字节哈希不同；两个 checkout 的 Git clean 内容一致，相关 `git diff` 均为空：

| 路径 | bytes | SHA-256 |
|---|---:|---|
| `uv.lock` | 68,359 | `2d70cde6c074c69ff20de809f0573836882919b3789051c4201556ff19e12646` |
| `runtimes/ocr/uv.lock` | 66,165 | `c0afe6469f1501caa9ea611e396a4a46c9a8b3b3bdc59983c5e8e2117b3139e7` |
| `runtimes/codex/package-lock.json` | 4,293 | `cb894d9321814e1a4f47a66713a2f1184d879bd3da1217c1795d6ebc071eec3a` |
| `runtimes/codex/runtime-identity-v1.json` | 1,091 | `9150f78b346f05ab8e88a90d119c8053e4cdff60391070f614575d5900afc03c` |
| `runtimes/ocr/model-manifest.v1.json` | 8,100 | `c338109a48b0a979478e9fbae0650d169024fbe4e3f4fb37565551726303fb20` |

## 输入身份

| 输入 | bytes | SHA-256 | 用途 |
|---|---:|---|---|
| `sciadv.aef8657.pdf` | 3,151,369 | `ea3c0feb9025dab73e076d8fcd8bfa8208b8eb5c567d714770bbfe554af60bb0` | 代表性公开科研 PDF；只在本机处理 |
| `sciadv-aef8657-page1-raster.pdf` | 692,389 | `dd32be6b91c1817dd4f2538df38bd5d0e89f566315f62d7fc4db38b8e9a62a07` | 第一页 200 DPI 图像型派生；严格解析为 1 页、0 个可提取字符 |
| `gezhi-t26-safe-synthetic-note.pdf` | 162,242 | `06ba9857c54eef283cc3dacc53821dc844b85ef68cdf03e5e8a71bd521de957d` | 明确 synthetic 的全链输入；1 页、0 个可提取字符 |

synthetic note 固定包含 Research question、Method、Finding、Limitation 与 Open question，并明确写明 `SYNTHETIC TEST DATA - NO USER OR CONFIDENTIAL CONTENT`。

## Doctor 与实际环境

### 默认配置

命令：

```powershell
E:\Gezhi\.venv\Scripts\gezhi.exe doctor --json
```

结果：exit `2`、overall `blocked`。`configuration`、core Python、core dependencies、OCR runtime 与 Codex runtime 均 `ready`；默认 `E:\Gezhi\data\literature` 和 `E:\Gezhi\data\knowledge` 尚不存在，因此两项 Data Root 精确为 `blocked/data_root_unavailable`。结果与实际文件系统一致。

### T26 隔离 Data Root

两个 launcher 使用：

```text
--literature-data-root E:\Gezhi\data\t26-real-smoke\literature
--knowledge-data-root  E:\Gezhi\data\t26-real-smoke\knowledge
doctor --json
```

结果：两个 launcher 均 exit `0`，stdout 逐字相等，七项检查全部 `ready`，overall `ready`。

合同边界：当前 Doctor 的 `codex_runtime` 严格按 Operations v1 只证明项目锁定 CLI 的身份、版本和只读登录状态，并明确不运行 `codex exec` 或语义请求；它不承诺 Codex Role Invocation v1 的 sealed workspace、`TEMP` 或 `CODEX_HOME` capability。因而这里的 `ready` 与后文 Reader 的 `codex_runtime_unavailable` 不矛盾。T26 必须用独立业务角色 smoke 覆盖后者；扩展 Doctor 将改变冻结的 Operations 合同，不属于本票。

## 真实 OCR

### 离线代表性科研页

生产 `resolve_ocr_execution_runtime_v1` 先复验完整 model manifest、CUDA 与离线 profile，再形成以下实际调用：

```text
<frozen mineru.exe> -p <rasterized-page.pdf> -o <isolated-output> -b pipeline -m ocr -l ch
```

关键环境为：

```text
MINERU_MODEL_SOURCE=local
MINERU_DEVICE_MODE=cuda
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
NO_PROXY=127.0.0.1,localhost
```

结果：exit `0`，耗时 `68.875 s`，stdout 100 bytes，stderr 3,988 bytes，生成 8 个预期产物：Markdown、content list v1/v2、layout/origin/span PDF、middle/model JSON。

### Public CLI synthetic OCR

首次真实 `literature resume` 中 MinerU exit `0`，但 provider validator 错误返回 `ocr_failed`。保存的真实产物通过所有 JSON、inventory、image、页数、内容流和 XObject 检查；唯一差异是 Source 页高 `842.04` 与 MinerU origin 页高 `842.03998`。

修复采用测试先行：

1. 新增真实 public CLI 双 launcher 回归，OCR executable double 只复现 `-0.00002` 的坐标序列化差异。
2. 修复前：两个 case 均因 `ocr_failed` 失败。
3. ADR 0125 明确冻结 page MediaBox/CropBox 与既有 Form BBox 相同的提供方重写规则：source/origin 各自规范到四位小数后逐项精确比较，规范后仍有差异即拒绝。
4. 实现只按该规则规范 page-box 坐标；其他内容、页数与来源身份检查不变。
5. 新增 `-0.00011` 的边界外反例；两个 launcher 均在 OCR stage 拒绝。接受/拒绝矩阵合计 `4 passed`。
6. 原始真实 MinerU 现场离线 replay 由 `REPRO_RED` 变为 `REPRO_GREEN`。
7. 真实 recovery resume 新提交：
   - OCR run：`ocrrun_a163bde5-5e17-4a6b-b6d1-acff1b462d8b`
   - OCR manifest：`8b67b1d57d50d72170a48f4a8e8518dd34d37d77534b75a516125853ed80f1e6`
   - method/status/attempts：`mineru_ocr / succeeded / 1`
   - Canonical run：`canrun_ca5b81b1-cdb4-4cf1-9852-f044396a00a4`
   - Canonical content：`a2fa6b6b1a6ea6533045eb5c53f6dd87e2dbeccdbdb1fe117bdd1adf902bebf2`

## Codex

### 锁定 CLI 与在线服务

`tools/codex.ps1` 验证 package、native package、唯一原生 executable 与 `0.146.0` 后：

- `login status`：exit `0`，`Logged in using ChatGPT`。
- 纯 synthetic `codex exec`：exit `0`；JSONL types 为 `thread.started`、`turn.started`、`item.completed`、`turn.completed`。
- `--output-last-message`：18 bytes，SHA-256 `8298acd2217fb66528ee0ce2de1c696cd041ade4ad2b7083fd0c92d3890f52ca`，内容逐字为 `GEZHI_T26_CODEX_OK`。

直接 exec 期间出现非致命 model-cache/plugin/MCP 网络告警；该命令没有业务输入，也没有采用完整 role-owned tool-disable config，因此只能证明锁定 CLI、账户与核心在线 turn 可用，不能替代 Reader/Answerer。

### Reader / Answerer 阻塞

真实 Reader 连续两次形成 terminal semantic run：

- status/reason：`blocked / codex_runtime_unavailable`
- attempt count：`0`
- usage totals：全零

底层差分：

1. `resolve_codex_runtime_v1(E:\Gezhi)` 成功，锁定 executable 与版本正确。
2. 默认 `TEMP=C:\Users\81048\AppData\Local\Temp` 生成的 `temporary` child 具有隐藏短别名，sealed workspace 拒绝。
3. 外置 `E:\gztest` TEMP 使 workspace formation 通过。
4. 随后 `CODEX_HOME=C:\Users\81048\.codex` 因明确存在 `CODEX~1` 短别名而被 capability gate 拒绝。
5. 在已检查的安全 E: 范围内没有既存 `auth.json`；不得静默复制凭据或执行登录。

Knowledge Answerer 使用同一 Codex Role Invocation v1 的 `CODEX_HOME` capability，故在该前置条件解决前标为 BLOCKED/NOT RUN，而不是伪造为通过。

## Windows 边界

以下真实 Windows 内核/公开 subprocess smoke 共 `9 passed in 4.59s`：

- 匿名 pipe 容量与双向背压；
- root 退出后 descendant 仍持有 stdout 的 settlement；
- `CREATE_NO_WINDOW` 与 exact stdio kinds；
- ReadFile 到真实 broken-pipe EOF；
- Knowledge Ask 输出端 broken pipe 不回滚已提交 Answer；
- 两个 launcher 的真实 Ctrl+C 与 active Codex Job 停止；
- 跨进程 named mutex zero-wait；
- 外部 SQLite writer 占用映射为 registry busy。

另执行被独占 PDF 的 public CLI smoke：两个 launcher 均 exit `2`、stdout 逐字相等，返回 `literature.add.pdf_unavailable.v1`，正式 Work 文件数为 `0`。

## 回归门

| 验证 | 结果 |
|---|---|
| 新 public CLI 坐标规范化接受/拒绝矩阵 | `4 passed in 13.97s` |
| `tests/test_literature_ocr_stage.py` | `101 passed in 229.94s` |
| `tests/test_deterministic_end_to_end_v1.py` | `7 passed in 111.90s` |
| Windows 边界选择集 | `9 passed in 4.20s` |
| Ruff check `src tests` | PASS |
| Ruff format check（3 个变更 Python 文件） | PASS |
| mypy `src/gezhi` | PASS（38 source files） |
| `git diff --check` | PASS |

## 可复现命令与 T25 映射

以下命令从仓库或 T26 worktree 根目录执行，不安装、同步或升级任何依赖：

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD\tests"
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_deterministic_end_to_end_v1.py -k "coordinate_rounding or outside_four_decimals"
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_literature_ocr_stage.py
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/test_deterministic_end_to_end_v1.py
& E:\Gezhi\.venv\Scripts\python.exe -m ruff check src tests
& E:\Gezhi\.venv\Scripts\python.exe -m ruff format --check src/gezhi/_literature_resume.py tests/support/ocr_executable_double_v1.py tests/test_deterministic_end_to_end_v1.py
& E:\Gezhi\.venv\Scripts\python.exe -m mypy src/gezhi
```

Windows 边界选择集的精确 selectors：

```powershell
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider `
  tests/test_codex_child_process_v1.py::test_measured_pipe_capacities_prove_bidirectional_backpressure `
  tests/test_codex_child_process_v1.py::test_root_exit_does_not_complete_before_a_descendant_releases_stdout `
  tests/test_codex_child_process_v1.py::test_no_console_and_exact_stdio_kinds `
  tests/test_codex_child_process_v1.py::test_readfile_progress_sequence_reaches_real_broken_pipe_eof `
  tests/test_knowledge_ask_public_contract.py::test_json_broken_pipe_does_not_roll_back_the_committed_answer `
  tests/test_knowledge_ask_public_contract.py::test_real_ctrl_c_stops_the_active_codex_job_through_both_launchers `
  tests/test_windows_writer_ownership.py::test_global_named_mutex_blocks_another_process_without_waiting `
  tests/test_knowledge_intake_public_contract.py::test_external_sqlite_writer_is_classified_as_registry_busy
```

真实能力探测使用：

```powershell
& E:\Gezhi\.venv\Scripts\gezhi.exe doctor --json
& E:\Gezhi\runtimes\ocr\.venv\Scripts\mineru.exe -p E:\Gezhi\data\t26-real-smoke\input\sciadv-aef8657-page1-raster.pdf -o E:\Gezhi\data\t26-real-smoke\offline-ocr-public-paper -b pipeline -m ocr -l ch
& E:\Gezhi\tools\codex.ps1 --version
& E:\Gezhi\tools\codex.ps1 login status
& E:\Gezhi\tools\codex.ps1 exec --ephemeral --ignore-user-config --ignore-rules --strict-config -m gpt-5.6-sol -s read-only --skip-git-repo-check --json -o E:\gztest\t26-real-smoke-temp\direct-codex-final.txt "This is a Gezhi T26 synthetic connectivity smoke. Return exactly: GEZHI_T26_CODEX_OK"
```

每项真实边界与 [T25 / PR #52](https://github.com/Dulealex/Gezhi/pull/52) 的确定性证据对应如下：

| T26 真实边界 | T25 确定性 witness |
|---|---|
| console launcher / `python -m gezhi` 全链 | `test_scanned_pdf_reaches_a_citable_answer_and_governance_branches` |
| OCR failure、保留审计 run 与跨 launcher 恢复 | `test_ocr_failed_terminal_recovers_with_the_other_launcher` |
| pipe 容量、背压、descendant settlement、no-console/stdio、broken-pipe EOF | 上述四个 `test_codex_child_process_v1.py` selectors |
| committed Answer 的输出端 broken pipe | `test_json_broken_pipe_does_not_roll_back_the_committed_answer` |
| 两 launcher 的真实 Ctrl+C 与 active Codex Job stop | `test_real_ctrl_c_stops_the_active_codex_job_through_both_launchers` |
| 跨进程 Work writer 互斥 | `test_global_named_mutex_blocks_another_process_without_waiting` |
| 外部 SQLite writer contention | `test_external_sqlite_writer_is_classified_as_registry_busy` |
| 被占用/不可读取 PDF 的 public diagnostic | T26 真实独占句柄 smoke；T25 `test_missing_or_directory_pdf_is_pdf_unavailable` 固定相同无正式 Work 的 public failure contract |
| Doctor | Operations v1 的双 launcher contract suite；T26 另行运行真实冻结探测，不把 deterministic observation double 解释为真实环境证据 |

全仓 `ruff format --check src tests` 在未变更的 `main` 基线中会报告 37 个既有文件可重排；T26 不批量格式化无关文件。全仓 Ruff lint、mypy 与全部变更 Python 文件的 formatter gate 均通过。

## 独立审查

PR #53 相对 `origin/main@cce159c6c93bfb6257c8025c31d506a0bd75b11e` 由两个隔离 reviewer 并行完成 Standards 与 Spec 审查。首轮发现：

- Standards：1 个 hard finding，page-box 四位规范化尚未被 ADR 0125 授权，且缺少规范化单元外的拒绝 witness。
- Spec：同一合同问题、Doctor 边界措辞未闭合，以及复现命令/T25 逐项映射不足。

本轮已分别通过 ADR 0125 明确规则、双 launcher 边界外拒绝测试、Operations v1 合同说明和本节复现映射解决。Reader/Answerer 的安全 `CODEX_HOME` 登录仍是诚实的外部授权阻断，不因代码审查而降格为 PASS。

## 仍需人工动作

推荐在项目外使用短组件、无 reparse 的 E: 路径，例如：

```text
CODEX_HOME=E:\gzrt\codex
TEMP=E:\gzrt\temp
TMP=E:\gzrt\temp
```

需要用户明确批准并完成一次项目锁定 CLI 登录，使新 `CODEX_HOME` 获得该账户的认证状态。不得把整个默认 `.codex` 复制过去；它包含构建平面的配置、插件、rules、skills、历史与大型状态文件。认证完成后必须：

1. 用 production role plan 证明 safe TEMP 与 safe `CODEX_HOME`。
2. 对现有 synthetic Work 重跑真实 Reader，审核至少一个 Candidate 并导入 Knowledge。
3. 对该 Candidate 运行真实 Knowledge Answerer，验证引用闭环。
4. 重跑 Doctor，确认其合同限定的 CLI 身份/版本/登录探测仍与实况一致；Reader/Answerer role capability 继续由独立 smoke 证明，不扩展 Operations v1。
5. 更新本记录为全部 PASS，再关闭 Issue #27。
