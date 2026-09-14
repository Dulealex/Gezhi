# T26 Windows 真实冻结环境 smoke（2026-08-31）

## 结论

当前状态（2026-09-14 更新）：**部分通过，真实 Reader 已通过，业务审核与 Answerer 待完成**。

- PASS：冻结核心环境、OCR 环境、项目锁定 Codex CLI 身份与登录探测。
- PASS：真实 RTX 4090 / CUDA MinerU 离线 OCR。
- PASS：真实 public CLI 的 OCR 提交与 Canonical Reading Asset 提交。
- PASS：Ctrl+C、pipe、broken pipe、文件占用、console/no-console Windows 边界。
- PASS：项目锁定 Codex CLI 的纯 synthetic 在线连通性。
- PASS：在用户授权的项目外隔离认证与 TEMP 目录中完成真实 Literature Reader sealed runtime smoke，单次 attempt 成功且 resource ledger 为零。
- PASS：三条冻结检索停止分支与未证明 release 的 fail-stop 修复；最终全仓分组回归合计 `1,320 passed / 1 skipped`，静态检查与两轴复审通过。唯一 skip 是 Windows symlink creation 权限不足（`1314`），不是依赖缺失或被静默忽略的失败。
- WAITING：对一个合成 Candidate 的显式人类 Candidate Review、Knowledge import 与真实 Answerer。上述步骤完成前不关闭 Issue #27 或合并 PR #53。

业务审核与真实 Answerer 完成前，本记录不能作为 T26 完成证明，Issue #27 不应关闭。

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
- 用户于 2026-09-14 确认仓库保持公开；本记录只公开合成测试证据与无敏感验收摘要，不提交认证代码、凭据、个人配置或 Data Root 中的原始及派生研究资料。

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

结果：两个 launcher 均 exit `0`，stdout 逐字相等，七项检查全部 `ready`，overall `ready`。2026-09-14 在下文隔离认证与 TEMP 配置下重跑，仍得到同一结果。

合同边界：当前 Doctor 的 `codex_runtime` 严格按 Operations v1 只证明项目锁定 CLI 的身份、版本和只读登录状态，并明确不运行 `codex exec` 或语义请求；它不承诺 Codex Role Invocation v1 的 sealed workspace、`TEMP` 或 `CODEX_HOME` capability。因而这里的 `ready` 与后文历史 Reader 的 `codex_runtime_unavailable` 不矛盾。T26 用独立业务角色 smoke 覆盖后者；2026-09-14 真实 Reader 已通过，Answerer 仍待完成。扩展 Doctor 将改变冻结的 Operations 合同，不属于本票。

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

### 历史 Reader / Answerer 阻塞（2026-08-31）

当时真实 Reader 连续两次形成 terminal semantic run：

- status/reason：`blocked / codex_runtime_unavailable`
- attempt count：`0`
- usage totals：全零

底层差分：

1. `resolve_codex_runtime_v1(E:\Gezhi)` 成功，锁定 executable 与版本正确。
2. 默认 `TEMP=C:\Users\81048\AppData\Local\Temp` 生成的 `temporary` child 具有隐藏短别名，sealed workspace 拒绝。
3. 外置 `E:\gztest` TEMP 使 workspace formation 通过。
4. 随后 `CODEX_HOME=C:\Users\81048\.codex` 因明确存在 `CODEX~1` 短别名而被 capability gate 拒绝。
5. 在已检查的安全 E: 范围内没有既存 `auth.json`；不得静默复制凭据或执行登录。

Knowledge Answerer 使用同一 Codex Role Invocation v1 的 `CODEX_HOME` capability，故当时在该前置条件解决前标为 BLOCKED/NOT RUN，而不是伪造为通过。历史 run 保持不可变；下节记录新 invocation 对该阻塞的解除。

### 安全隔离登录与真实 Reader（2026-09-14）

用户已授权建立项目外普通目录 `E:\gzrt\codex`、`E:\gzrt\temp`，手动开启设备代码授权，并用项目锁定 CLI 完成登录。只对当前验证进程设置 `CODEX_HOME`、`TEMP`、`TMP`，没有复制默认 `.codex` 或更改系统环境变量；未读取或公开 `auth.json` 内容。登录进程 exit `0`，独立 `login status` 亦 exit `0`、逐字为 `Logged in using ChatGPT`。

真实 public module launcher 使用 T26 worktree 的 `src` 和现有核心环境，复用已提交 OCR/Canonical，只调用 `literature_reader_v1`：

| 证据 | 实际值 |
|---|---|
| Reader run | `semrun_54cb1fe5-b5d3-47cf-a5ed-97cf48c5dc7f` |
| Reader manifest SHA-256 | `1e59589513f47b466e10b81c698a5139540689819e7064fdfa1fda9b69f27e4c` |
| role / CLI / model / reasoning | `literature_reader_v1 / 0.146.0 / gpt-5.6-sol / high` |
| attempt count / native child exit / elapsed | `1 / 0 / 50.563 s` |
| resource ledger | `0` |
| input bytes / text blocks / SHA-256 | `2,165 / 7 / f6eb889dbb68b4c6aceebb3d1b5676676181b0f41edac681d515c07516dc75f5` |
| events bytes / SHA-256 | `5,448 / 3fe0b18c25ad9e7932acee519f7b7941786b3ca22bd970b12a2cef45a489f45e` |
| final bytes / SHA-256 | `4,665 / 2cea295065ae1f986bed27ce8af04697d8b25fb6d95d9dbec36486f33f266796` |
| tokens: input / cached input / output / reasoning output | `8,126 / 0 / 1,990 / 749`，`usage_unavailable=false` |
| Candidate materialization | `matrun_e3eefeed-3aec-4138-abfc-926547de553e` |
| materialization manifest SHA-256 | `717bd8e5b5743b2c0e4d11faa93b7716990685d7ea9715a5e570f37fbcb1ffd7` |

Production resolver、workspace builder、launch plan 与 child commitment 的完整 capability 检查通过后才产生这次 attempt；成功不依赖 PowerShell runtime wrapper、test-double proof 或关闭 path gate。返回 receipt 的 `advanced_stages=["read"]`，随后按合同停在 `review/awaiting_review`，形成 4 个 pending Candidate。运行模型没有写 Review Decision。

console 与 module launcher 随后各自重跑同一 `resume`：native exit 均为 `2`，完整 JSON stdout 相同，`advanced_stages=[]`、`start_stage=stop_stage=review`、4 个 pending ID 不变；Reader 成功资产复用，未再次调用模型。PowerShell 外层采用显式 `exit $LASTEXITCODE` 保留 native exit，不把 shell 的成功/失败布尔退出映射当作产品退出码。

请求人类审核的合成 Claim 为 `cand_d9c18a7e7d42179d33817c5c`，payload SHA-256 `d9c18a7e7d42179d33817c5c79ba84d860da01a7f5f5d647cddaab57670174c8`；其 Evidence Pointer 直接指向 `blk_9dfe76c859de41023829f296`，Canonical 内容身份为上文已提交的 `a2fa6b6b1a6ea6533045eb5c53f6dd87e2dbeccdbdb1fe117bdd1adf902bebf2`，风险为 `numeric_claim`。正文只描述三次 synthetic trials，合成 Source 明确不支持真实世界结论。用户明确接受前，不执行 `--accept` 或 import；其他 3 个 Candidate 保持 pending，不默认接受。

### Knowledge 前置状态与受控检索停止

人工审核/import 尚未执行，隔离 Knowledge 根没有 `registry.sqlite3`。两个 launcher 直接 `knowledge ask` 都在约 `1.3 s` 以 native exit `1` 和 `RegistryUnavailableV1` traceback 结束，根仍为空，没有 committed Answer 或 Codex attempt；改为无凭据 profile 仍得到同一错误。该未初始化状态不是合法空 Registry：既有 `test_ask_treats_a_valid_empty_registry_as_insufficient_evidence` 双 launcher 用例 `1 passed in 1.18s`，验证后者正常成功且不调用 Codex。

**已知合同缺口，不计为 PASS**：Ask 的冻结 15+1 committed primary 和 11/7 no-commit union 没有 Registry opening cause。不得借 `search/show` 的 `registry_unavailable`，也不得把打开之前的缺失数据库误归为已开始 FTS/SQL 的 `retrieval_query_failed`、root trust loss 或四份 retrieval 资产的 `retrieval_materialization_failed`。因此本票不新增 error code/catch-all、不创建空 Registry 或改变合同；真实非零 Answerer 继续等待正常审核→Intake 初始化。若要闭合“首次导入前 Ask”的受控界面，须单独重新决策并演进相应版本化合同，最终人工审核包必须披露这一限制。

另外三条既有合同已明确授权的检索停止分支缺失 runtime/report/presentation 接线，按 TDD 逐条修复：

| slice | red | green | 冻结 terminal |
|---|---|---|---|
| 合成 fixture 的 Evidence snapshots 缺失 | 双 launcher traceback，`2 failed in 2.61s` | `2 passed in 1.45s` | `failed / retrieval_materialization_failed / retrieval`，P2 |
| SQLite 系统边界的 FTS execute 故障 double（合成错误） | 双 launcher traceback，`2 failed in 1.16s` | 两条 slice 合计 `4 passed in 2.41s` | `failed / retrieval_query_failed / retrieval`，P2 |
| SQLite 系统边界的 required trigram tokenizer unavailable 故障 double | 双 launcher exit `1` 而非 `2`，`2 failed in 1.14s` | 三条 slice 合计 `6 passed in 4.56s` | `blocked / fts5_unavailable / retrieval`，P2 |

只在既定 public CLI seam 断言正式 receipt，并独立验证完整 canonical stdout bytes/末尾 LF，以及 committed manifest 的精确 P2 inventory、每份资产的 byte length/SHA-256/schema identity、零 attempt 与零 usage。数据库/SQLite 是系统边界；没有 mock Knowledge 自有 collaborator，没有改动 SQLite 安装或真实 T26 业务 Candidate。正式失败/阻塞 receipt 绑定新 committed Answer，`answer_output=null`；三条分支都无 Audit/View、C/O 对或模型 attempt，保留冻结最小前缀与 error 表。

独立复审发现旧 producer 在 `connection.close()` 未完成时也抛 `RetrievalQueryFailedV1`，不能据此声称已经释放连接。本轮新增 readonly Registry close 系统边界故障 double：双 launcher 在 `2 failed in 1.26s` 中复现错误的完整 receipt。修复后，connection 或 guard release 未取得成功完成证明时抛独立内部 `RetrievalLifecycleUnsettledV1`，不继承 Ask 已捕获的检索/root-loss 类型，不进入 publisher 或正常回执矩阵，不重试 close，不新增 wire code。已观察 root loss 保留在因果链中；release 全部成功时，root loss 仍不可逆地优先于查询失败。关闭负例与三个检索停止分支合计 `8 passed in 4.19s`：关闭负例没有 stdout receipt、新 committed Answer、staging 资产或模型 attempt，且 close 恰好尝试一次。未知 Registry opening/schema 错误继续在正常矩阵外。

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
| 新 Knowledge 检索停止矩阵（3 cause × 2 launcher） | `6 passed in 4.56s` |
| 增强的 Knowledge 检索停止与未完成关闭边界（4 × 2 launcher） | `8 passed in 4.19s` |
| `tests/test_knowledge_ask_public_contract.py`（收尾修复后） | `49 passed in 59.41s` |
| 真实 CLI 身份/登录正向测试（实机 profile，最终复验） | `1 passed in 0.44s` |
| 最终无凭据主体全仓回归（当前生产修改） | `1319 passed, 1 skipped, 1 deselected in 913.08s` |
| 两个 profile 合并覆盖 | 全部 `1321` 个 case：`1320 passed / 1 skipped`；主体唯一 deselected case 已在实机组单独通过 |
| Ruff check `src tests` | PASS |
| Ruff format check（全部 7 个变更 Python 文件） | PASS |
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
& E:\Gezhi\.venv\Scripts\python.exe -m ruff format --check src/gezhi/_knowledge_ask.py src/gezhi/_knowledge_commands.py src/gezhi/_knowledge_retrieval.py tests/test_knowledge_ask_public_contract.py
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
& E:\Gezhi\tools\codex.ps1 --version
& E:\Gezhi\tools\codex.ps1 login status
& E:\Gezhi\tools\codex.ps1 exec --ephemeral --ignore-user-config --ignore-rules --strict-config -m gpt-5.6-sol -s read-only --skip-git-repo-check --json -o E:\gztest\t26-real-smoke-temp\direct-codex-final.txt "This is a Gezhi T26 synthetic connectivity smoke. Return exactly: GEZHI_T26_CODEX_OK"
```

代表性科研页的 MinerU 原生调用形状见“真实 OCR”节，仅为历史执行示意，不是可直接复制运行的复现命令。该次执行先经过 `resolve_ocr_execution_runtime_v1` 校验冻结 runtime/model manifest，再注入完整 profile（包括 `MINERU_TOOLS_CONFIG_JSON`、local model source、CUDA 和 offline 配置）。不得绕过 resolver 或依赖父进程残留环境变量直接启动 MinerU；不得让默认用户配置或自动模型来源触发联网下载。

2026-09-14 的 Reader 与双 launcher Doctor 从 T26 worktree 根目录执行。以下实机各项应作为独立命令运行，并立即用 `exit $LASTEXITCODE` 保留其 native exit；`resume` 重放复用已有 Reader，按合同停在待人工审核（exit `2`），不会重新调用模型或接受 Candidate：

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD\tests"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:CODEX_HOME = 'E:\gzrt\codex'
$env:TEMP = 'E:\gzrt\temp'
$env:TMP = 'E:\gzrt\temp'
$t26LiteratureRoot = 'E:\Gezhi\data\t26-real-smoke\literature'
$t26KnowledgeRoot = 'E:\Gezhi\data\t26-real-smoke\knowledge'
$t26WorkId = 'wrk_cb7ef3ee-2434-40d8-94f7-0fa75ecf8866'

& E:\Gezhi\.venv\Scripts\python.exe -m gezhi --literature-data-root $t26LiteratureRoot --knowledge-data-root $t26KnowledgeRoot literature resume $t26WorkId --json
& E:\Gezhi\.venv\Scripts\gezhi.exe --literature-data-root $t26LiteratureRoot --knowledge-data-root $t26KnowledgeRoot literature resume $t26WorkId --json
& E:\Gezhi\.venv\Scripts\python.exe -m gezhi --literature-data-root $t26LiteratureRoot --knowledge-data-root $t26KnowledgeRoot doctor --json
& E:\Gezhi\.venv\Scripts\gezhi.exe --literature-data-root $t26LiteratureRoot --knowledge-data-root $t26KnowledgeRoot doctor --json
```

确定性业务回归不得继承上述实机登录。2026-09-14 的首轮误用实机 `CODEX_HOME`：全仓 `23 failed, 1289 passed, 1 skipped in 1142.02s`，失败均为 public `resume` 的 `15 s` `TimeoutExpired`。最小用例 `test_native_text_resume_publishes_canonical_success_and_stops_at_read[0]` 连续两次在约 `15.8 s` 复现；该测试明确预期 `read/codex_runtime_unavailable`。只把 `CODEX_HOME` 改为已确认不存在的隔离路径、保留同一 TEMP/代码/输入时，`1 passed in 3.22s`；双 launcher 再验 `2 passed in 6.39s`。因此修正验证 profile，不更改生产 runtime gate、依赖或测试超时。

首次无凭据全仓重跑（启动时尚未添加上述 6 个新用例）为 `1 failed, 1311 passed, 1 skipped in 828.62s`。唯一失败 `test_project_locked_codex_identity_and_login_are_ready` 明确要求真实登录；它在上述实机 profile 下单独 `1 passed in 0.39s`。最终在当前生产修改上另起分组回归：无凭据主体为 `1319 passed, 1 skipped, 1 deselected in 913.08s`，唯一 deselected case 用实机 profile 独立 `1 passed in 0.44s`，全部 `1321` 个 case 合计 `1320 passed / 1 skipped`；不是忽略失败或把未执行 case 宣称通过。唯一 skip 为 `tests/test_literature_add_public_contract.py:486` 的 Windows symlink creation unavailable (`1314`)，保留明确的平台资格限制。主体使用以下无凭据进程：

```powershell
$env:PYTHONPATH = "$PWD\src;$PWD\tests"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:TEMP = 'E:\gzrt\temp'
$env:TMP = 'E:\gzrt\temp'
$env:CODEX_HOME = 'E:\Gezhi\data\t26-deterministic-no-credentials'
if (Test-Path -LiteralPath $env:CODEX_HOME) {
  throw 'The deterministic no-credentials path must remain absent.'
}
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -rs -p no:cacheprovider -k 'not test_project_locked_codex_identity_and_login_are_ready'
exit $LASTEXITCODE
```

实机 profile 还需独立执行（同样立即 `exit $LASTEXITCODE`）：

```powershell
$env:CODEX_HOME = 'E:\gzrt\codex'
$env:TEMP = 'E:\gzrt\temp'
$env:TMP = 'E:\gzrt\temp'
& E:\Gezhi\.venv\Scripts\python.exe -m pytest -q -rs -p no:cacheprovider tests/test_doctor_runtime.py::test_project_locked_codex_identity_and_login_are_ready
exit $LASTEXITCODE
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

上述代码与文档问题已分别通过 ADR 0125 明确规则、双 launcher 边界外拒绝测试、Operations v1 合同说明和本节复现映射解决，修订后的两轴复审未发现阻断。2026-09-14 的隔离登录已解除历史授权阻断，真实 Reader 已通过；业务 Candidate Review 与 Answerer 不因代码审查而自动通过。新增 Knowledge 接线复审随后发现 Standards 1 个 P1（未证明 close completion）与 Spec 2 项（同一 P1、P2 的 canonical bytes/正式资产覆盖不足）；修复与上述 8 个 public case 已通过。两位独立 reviewer 对当前生产修改、公开仓库边界和恢复验收记录再次复核：Standards 0 个 hard finding/无有价值 smell，Spec 0 项 finding。该只读结论不替代最终全仓回归、人工 Candidate Review 或真实 Answerer 验收。

## 隔离部署与剩余验收

推荐在项目外使用短组件、无 reparse 的 E: 路径，例如：

```text
CODEX_HOME=E:\gzrt\codex
TEMP=E:\gzrt\temp
TMP=E:\gzrt\temp
```

用户已明确批准并完成项目锁定 CLI 的隔离登录。没有复制整个默认 `.codex`；它包含构建平面的配置、插件、rules、skills、历史与大型状态文件。该登录解除 2026-08-31 的授权阻断，不扩大业务审核权限。当前状态与剩余项：

1. 已通过真实 Reader 的 production role plan 与 child commitment 证明 safe TEMP 和 safe `CODEX_HOME`；保留其不可变审计证据。
2. 由用户明确审核至少一个已生成的 synthetic Candidate，再用 public review seam 导入 Knowledge。
3. 对该 Candidate 运行真实 Knowledge Answerer，验证引用闭环。
4. 已在隔离配置下重跑双 launcher Doctor，七项 ready 与实况一致；Reader/Answerer role capability 继续由独立 smoke 证明，不扩展 Operations v1。
5. 当前生产修改已通过最终分组全仓回归、静态检查与两轴复审；业务审核与真实 Answerer 完成后，还须补齐其验收证据与最终复核，才允许合并 PR #53、关闭 Issue #27。唯一平台 skip 与 Registry 未初始化限制仍须披露，不能改写为全部 case 无条件 PASS；父 Spec #1 继续打开，等待最终人工硬审核。
