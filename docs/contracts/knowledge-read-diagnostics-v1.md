# Knowledge Read Diagnostics v1 合同

状态：已冻结。本合同是 [Knowledge Read v1](./knowledge-read-v1.md) 的 concrete diagnostic、Human 中文与 process-exit binding；它只适用于 `knowledge.search` 与 `knowledge.show`。

## Diagnostic profile

两个 command 的 V1 diagnostic item 都必须是 [CLI Diagnostics v1](./cli-diagnostics-v1.md) 的两字段 object，`context` 精确为 `{}`。V1 不批准任何 command-owned supplemental；成功固定为 `diagnostics=[]`，非成功固定只有 index 0 的一个 primary。共享 `cli.diagnostics_omitted.v1` 因此不会由合法 V1 read report 触发。

### knowledge.search

Blocked primary 按 gate 顺序组成下列封闭 union：

| cause | code |
|---|---|
| Query 无法规范化、为空、纯符号或只有一个 Han 字符 | `knowledge.search.invalid_query.v1` |
| 规范 Query 超过 2000 code point 或 8192 UTF-8 bytes | `knowledge.search.query_too_large.v1` |
| 任一路安全查询原子超过 128 项 | `knowledge.search.query_too_complex.v1` |
| Configuration source/schema/final cross-field 无效 | `knowledge.search.configuration_invalid.v1` |
| Configuration generation 不受支持或不兼容 | `knowledge.search.configuration_incompatible.v1` |
| Knowledge Data Root 缺失、不可访问或不是目录 | `knowledge.search.data_root_unavailable.v1` |
| Knowledge Data Root namespace、reparse、alias、重合或物理边界不安全 | `knowledge.search.data_root_unsafe.v1` |
| safe-open 后不能取得合法 File ID/physical identity | `knowledge.search.data_root_identity_unavailable.v1` |
| `registry.sqlite3` 缺失、不可只读打开或暂时不能取得 read snapshot | `knowledge.search.registry_unavailable.v1` |
| Registry generation 或所需确定性 search projection generation 不受支持 | `knowledge.search.registry_incompatible.v1` |
| SQLite FTS5 或任一冻结 tokenizer profile 不可用 | `knowledge.search.fts5_unavailable.v1` |
| 完整合法 success envelope 超过 1,048,576 bytes | `knowledge.search.result_too_large.v1` |

Failed primary 组成下列封闭 union：

| cause | code |
|---|---|
| 初始 root gate 成功后，mandatory checkpoint 不能继续证明同一安全 root | `knowledge.search.data_root_integrity_lost.v1` |
| SQLite/Registry 结构、完整性或声明的全局不变量损坏 | `knowledge.search.registry_corrupt.v1` |
| 任一 FTS branch、active filter、branch-rank 或 snapshot query 在运行中失败 | `knowledge.search.retrieval_query_failed.v1` |
| 参与融合或最终入选 Candidate 的 identity、governance、payload/hash 不能完整物化 | `knowledge.search.retrieval_materialization_failed.v1` |

### knowledge.show

Blocked primary 按 gate 顺序组成下列封闭 union：

| cause | code |
|---|---|
| Selector 不完整匹配 `cand_[0-9a-f]{24}` | `knowledge.show.invalid_candidate_id.v1` |
| Configuration source/schema/final cross-field 无效 | `knowledge.show.configuration_invalid.v1` |
| Configuration generation 不受支持或不兼容 | `knowledge.show.configuration_incompatible.v1` |
| Knowledge Data Root 缺失、不可访问或不是目录 | `knowledge.show.data_root_unavailable.v1` |
| Knowledge Data Root namespace、reparse、alias、重合或物理边界不安全 | `knowledge.show.data_root_unsafe.v1` |
| safe-open 后不能取得合法 File ID/physical identity | `knowledge.show.data_root_identity_unavailable.v1` |
| `registry.sqlite3` 缺失、不可只读打开或暂时不能取得 read snapshot | `knowledge.show.registry_unavailable.v1` |
| Registry generation 不受支持 | `knowledge.show.registry_incompatible.v1` |
| 合法 Candidate ID 在当前 snapshot 中不存在 | `knowledge.show.candidate_not_found.v1` |
| 完整合法 success envelope 超过 1,048,576 bytes | `knowledge.show.result_too_large.v1` |

Failed primary 组成下列封闭 union：

| cause | code |
|---|---|
| 初始 root gate 成功后，mandatory checkpoint 不能继续证明同一安全 root | `knowledge.show.data_root_integrity_lost.v1` |
| SQLite/Registry 结构、完整性或声明的全局不变量损坏 | `knowledge.show.registry_corrupt.v1` |
| 已开始的 lookup/read transaction 因非损坏性运行故障不能完成 | `knowledge.show.registry_read_failed.v1` |
| 命中的 Candidate identity、payload、hash 或 revision 不一致 | `knowledge.show.candidate_corrupt.v1` |
| content/status import、Citation、Descriptor、Evidence union、hash 或 provenance 缺失/不一致 | `knowledge.show.evidence_corrupt.v1` |

“暂时不能取得 snapshot”只覆盖在读取业务 row 前明确观察到的 absent/access/busy/locked 前置条件；transaction 已开始后的查询故障不能倒退为 blocked。Unknown Schema 是 incompatible，不是 corrupt；声明受支持却缺表、缺索引、破坏 hash/identity 或不能满足声明不变量才是 corrupt。Selected Candidate 的局部 payload 问题使用 materialization/candidate code，不把可定位的局部问题泛化成整个 Registry corrupt。

Gate 顺序是唯一仲裁顺序；一旦 root gate 成功，后续 root trust loss 优先于尚未发布的领域错误。实现不得按异常到达时间选择 code、把多个 primary 放进数组、回显 path/ID/query/异常文本，或用 `unexpected_error`、`internal_error` 等通用 fallback 补洞。未列出的内部不变量或无法证明安全 completion 的路径不在正常 handled matrix 内，不能伪造一个本合同 envelope。

## Human 中文表示

Human mode 与 JSON mode 必须消费同一个已经验证的 command report，拥有相同 outcome、result cap 与领域排序；即使选择 Human，也先以 would-be canonical success envelope 判定 1,048,576-byte cap。成功只写 stdout，blocked/failed 只把一条固定中文说明和一个末尾 LF 写 stderr 并保持 stdout empty；完整 Human success 同样恰好以一个 LF 结束。两种模式都不输出 prompt、progress、spinner、日志、traceback、ANSI 或旧 PaperBot JSON。

Human search success 的前四行依次为 `Knowledge 候选搜索`、下列固定治理说明、`查询：<quoted normalized_text>` 与 `结果：N 条`。随后按 rank 对每项使用固定标签 `候选`、`状态`、`陈述`、`来源`、`证据指针`，呈现 Candidate ID/type、`accepted / active / not_promoted`、规范陈述、Work/Source identity 与全部 Evidence Pointer；只显示 final rank，不显示 atoms、BM25、branch rank、RRF 或 Registry provenance。零结果在 count 后输出 `没有匹配的 active Candidate。`。固定治理说明精确为：

```text
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
```

Human show success 按以下固定 section 顺序呈现：标题 `Knowledge 候选详情`、同一治理说明、`候选` 与 `类型`、`状态`、陈述与 source identity、Citation、`内容交接`、`当前交接`、Descriptor snapshots、Evidence snapshots；每个 machine result 字段都必须在对应 section 可见，不生成额外推断。Withdrawn 结果必须在 governance 后额外输出：

```text
注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。
```

所有外部或人类文本（Query、陈述、source term、title、author、DOI、Descriptor label、block ID、excerpt）均以 Python 3.11 `json.dumps(value, ensure_ascii=False)` 的单个 JSON string token 显示，使 LF/TAB/引号不能伪造 section；ID、enum、hash、integer 可按已验证 ASCII/十进制规范值直接显示，null 固定显示 `未知`。Human renderer 不裁剪、改写、翻译、摘要或生成 URL。

非成功 primary 的固定中文行如下；相同 cause 在 search/show 复用同一句：

| code suffix | fixed Human stderr line |
|---|---|
| `invalid_query.v1` | `搜索内容无效；请提供包含可检索文字的查询。` |
| `query_too_large.v1` | `搜索内容过长；请缩短查询后重试。` |
| `query_too_complex.v1` | `搜索内容过于复杂；请减少不同检索词后重试。` |
| `invalid_candidate_id.v1` | `Candidate ID 格式无效；请提供完整的小写 cand_ 标识。` |
| `candidate_not_found.v1` | `没有找到该 Candidate。` |
| `configuration_invalid.v1` | `格致配置无效；请修正项目配置后重试。` |
| `configuration_incompatible.v1` | `格致配置版本不兼容；请使用项目支持的配置版本。` |
| `data_root_unavailable.v1` | `Knowledge 数据目录不可用；请确认目录已经存在且可读取。` |
| `data_root_unsafe.v1` | `Knowledge 数据目录不满足安全边界；请改用本机独立目录。` |
| `data_root_identity_unavailable.v1` | `无法验证 Knowledge 数据目录身份；请检查磁盘与目录状态。` |
| `data_root_integrity_lost.v1` | `读取期间 Knowledge 数据目录身份发生异常；本次结果未发布。` |
| `registry_unavailable.v1` | `Candidate Registry 暂时不可用；请确认 Registry 已初始化且未被占用。` |
| `registry_incompatible.v1` | `Candidate Registry 版本不兼容；本项目不会自动迁移。` |
| `fts5_unavailable.v1` | `当前 SQLite 缺少所需的 FTS5 检索能力。` |
| `registry_corrupt.v1` | `Candidate Registry 已损坏或不满足完整性约束；本次结果未发布。` |
| `registry_read_failed.v1` | `读取 Candidate Registry 失败；本次结果未发布。` |
| `retrieval_query_failed.v1` | `Candidate 检索执行失败；本次结果未发布。` |
| `retrieval_materialization_failed.v1` | `检索结果无法完整验证；本次结果未发布。` |
| `candidate_corrupt.v1` | `Candidate 内容无法通过身份与哈希验证；本次结果未发布。` |
| `evidence_corrupt.v1` | `Candidate 的交接证据无法完整验证；本次结果未发布。` |
| `result_too_large.v1` | `结果超过本命令的输出上限；本次结果未截断。` |

## Process exit

完整 JSON 或 Human receipt 成功写完并沿正常 handled-return 返回时，process exit 固定为：

| outcome | exit |
|---|---:|
| `succeeded` | `0` |
| `blocked` | `2` |
| `failed` | `1` |

参数/grammar、raw argv resource、typed bootstrap 与入口前失败继续服从 CLI Command v1，不产生本合同 outcome。JSON/Human presentation failure 返回 `1`，但它不是 `failed` outcome、没有新 diagnostic，也不能用第二次写入补发 receipt。两个命令没有正常应用级 `130`。

## 可执行验收矩阵

T19 实现至少必须覆盖：

- Query normalization、空/纯符号/单 Han、2000/8192 边界、双路各 128 atom 边界与 FTS syntax injection；
- 两个 tokenizer 的实际 SQLite probe、每路 48、精确 RRF `k=12`、Candidate ID tie-break、最多 12、单路无 atoms、双路零匹配；
- active/withdrawn 混合数据、withdraw 后 search 排除、重新 accept 后恢复、show withdrawn 仍成功；
- search result 只含完整 Candidate/治理/rank，show result 的 Candidate/Citation/Descriptor/Evidence/import 交叉约束；
- invalid ID、missing ID、unknown Registry generation、缺 FTS、数据库损坏、branch failure、Candidate hash mismatch、import/hash/evidence 缺失与 root identity loss；
- read-only connection 与副作用断言：Registry logical state、main database pages、immutable imports 与 answer tree 不变且不新增业务文件；已存在 WAL/SHM 中只服务 read snapshot 的 SQLite lock/read-coordination metadata 不算业务 mutation，但不得执行 DML/DDL、checkpoint、migration 或 vacuum；
- 1,048,576/1,048,577-byte presentation 边界、canonical JSON LF、Human 固定中文、stdout/stderr 隔离与 `0/2/1` exit；
- 同一 synthetic Registry snapshot 与 Query 至少两次独立进程运行得到相同 JSON bytes；show 对同一 Candidate/import bytes 同样复验；
- 缺失 Codex、OCR、embedding/vector/model runtime 时两个命令仍可成功，且没有 provider、网络或 child-process probe。

所有公共行为必须分别从以下两个真实 Windows subprocess launcher 验收，并断言相同 suffix/外部状态得到相同 application stdout、stderr 与 exit：

```text
E:\Gezhi\.venv\Scripts\gezhi.exe ARGS...
E:\Gezhi\.venv\Scripts\python.exe -m gezhi ARGS...
```

测试只使用临时 Knowledge Data Root 与合成 Registry/Handoff fixtures，不读取生产数据，不安装/同步依赖，不调用 WSL、旧 `knowledgebot`、PowerShell wrapper 或内部 Python service 代替 public seam。只有 SQLite corruption、short-write 或精确内部不变量无法从 launcher 穷举时，才补充窄 internal seam 测试；这些测试不能替代真实 launcher acceptance。

## 明确排除与演进

V1 不增加 `--limit`、filter、work/source scope、score/debug/audit flag、prefix/alias selector、list command、stdin/file query、interactive prompt、conversation、URL、附件、embedding、vector、model rerank、自动 repair/migration、promote/demote/deprecate，也不定义未来 Bot 的业务字段。公开命令仍只有 ADR 0024 的八条；静态 extension 位置保留在 Context composition，而不是当前 CLI surface。

改变 Query/ID 领域、FTS 字段或 tokenizer、branch/RRF/tie-break/上限、result key/type、governance/import 交叉矩阵、diagnostic code/context/outcome、Human 固定语义、exit、持久化副作用或 JSON cap/writer，必须引入新的 command-owned generation 或明确 replacing decision。仅重构私有 SQLite schema、module/file 名或 selector 内部拆分，在保持全部可观察合同与既有 Registry migration 责任时不要求升级本 Schema。
