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

Human mode 与 JSON mode 必须消费同一个已经验证的 command report，拥有相同 outcome、result cap 与领域排序；即使选择 Human，也先以 would-be canonical success envelope 判定 1,048,576-byte cap。成功只写 stdout，blocked/failed 只把一条固定中文说明和一个末尾 LF 写 stderr 并保持 stdout empty。两种模式都不输出 prompt、progress、spinner、日志、traceback、ANSI 或旧 PaperBot JSON。

### HumanTreeV1 逐行语法

成功 Human stdout 由命令前导行加同一个 machine `result` 的完整 `HumanTreeV1` 投影组成。`knowledge search` 前导恰好是下列两行，`knowledge show` 只把第一行替换为 `Knowledge 候选详情`：

```text
Knowledge 候选搜索
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
```

令 `I(d)` 为恰好 `2*d` 个 ASCII SPACE，根 result object 的字段深度为 `d=0`。renderer 必须先验证完整 typed result，再按下列规则逐行生成；这里的 `LF` 是单个 byte `0x0A`，`LABEL(k)` 来自后文封闭表：

- 非空 object 的 field 按 machine key 的 Python 3.11 string 升序输出；根 object 不输出 `{` 或 `}`，nested object 由其 field label 建立边界。Array 保持合同已经冻结的领域顺序，不排序。
- scalar field 是 `I(d) + LABEL(k) + ": " + SCALAR(v)`；empty array field 用同一前缀加字面量 `[]`，empty object field 加字面量 `{}`。
- nonempty array/object field 是 `I(d) + LABEL(k) + ":" + LF`，随后以 `d+1` 渲染 container body；冒号后不得有 SPACE。
- array 中每个 scalar item 是 `I(d) + "- " + SCALAR(v)`；empty array/object item 分别是 `I(d) + "- []"` 与 `I(d) + "- {}"`；nonempty array/object item 是 `I(d) + "-" + LF`，随后以 `d+1` 渲染其 body。重复项相邻输出，每项各有一个同深度 `-`，项间没有空行或其他分隔符。
- `SCALAR(null)` 是 ASCII `null`；boolean 必须先于 integer 分派并精确为 `true` 或 `false`；integer 是无 `+`、无多余前导零的 ASCII 十进制（零为 `0`）；string 是 Python 3.11 `json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))` 产生的单个 JSON string token。Float、未知 key、未知类型或未经验证的值不能进入 renderer。
- 所有逻辑行只用一个 LF 连接，无物理 CR、空行、尾随 SPACE、BOM 或 ANSI；完整 stdout 在最后一行后追加恰好一个 LF。每个 machine field 恰好生成一个带 `[machine_key]` 的 field label；不得省略、合并、摘要或另行推断字段。

`LABEL(k)` 的封闭映射如下；square brackets 是输出字符，不是本文元语法：

| machine key | exact `LABEL(k)` |
|---|---|
| `action` | `动作 [action]` |
| `arxiv_id` | `arXiv ID [arxiv_id]` |
| `author_count` | `作者总数 [author_count]` |
| `block_id` | `Block ID [block_id]` |
| `candidate` | `Candidate [candidate]` |
| `candidate_count` | `Candidate 数量 [candidate_count]` |
| `candidate_id` | `Candidate ID [candidate_id]` |
| `candidate_type` | `Candidate 类型 [candidate_type]` |
| `candidates_sha256` | `candidates.jsonl SHA-256 [candidates_sha256]` |
| `canonical_content_sha256` | `Canonical 内容 SHA-256 [canonical_content_sha256]` |
| `citation` | `引用快照 [citation]` |
| `content_import` | `内容交接 [content_import]` |
| `descriptor_id` | `Descriptor ID [descriptor_id]` |
| `descriptor_refs` | `Descriptor 引用 [descriptor_refs]` |
| `descriptor_snapshots` | `Descriptor 快照 [descriptor_snapshots]` |
| `doi` | `DOI [doi]` |
| `evidence_pointers` | `证据指针 [evidence_pointers]` |
| `evidence_snapshots` | `证据快照 [evidence_snapshots]` |
| `excerpt` | `摘录 [excerpt]` |
| `governance` | `治理 [governance]` |
| `handoff_id` | `Handoff ID [handoff_id]` |
| `intake_status` | `接收状态 [intake_status]` |
| `items` | `候选项 [items]` |
| `kind` | `类型 [kind]` |
| `label` | `名称 [label]` |
| `manifest_sha256` | `manifest.json SHA-256 [manifest_sha256]` |
| `page_index` | `页索引 [page_index]` |
| `payload` | `Payload [payload]` |
| `payload_sha256` | `Payload SHA-256 [payload_sha256]` |
| `pointer` | `证据指针 [pointer]` |
| `primary_authors` | `主要作者 [primary_authors]` |
| `promotion_status` | `晋升状态 [promotion_status]` |
| `query` | `规范查询 [query]` |
| `rank` | `排名 [rank]` |
| `reference` | `Descriptor 引用 [reference]` |
| `research_interest_id` | `Research Interest ID [research_interest_id]` |
| `result_kind` | `结果种类 [result_kind]` |
| `review_revision` | `审核修订 [review_revision]` |
| `review_status` | `审核状态 [review_status]` |
| `risk_flags` | `审核风险标记 [risk_flags]` |
| `schema_version` | `架构版本 [schema_version]` |
| `source_id` | `Source ID [source_id]` |
| `source_sha256` | `Source SHA-256 [source_sha256]` |
| `source_terms` | `来源术语 [source_terms]` |
| `statement` | `陈述 [statement]` |
| `status_import` | `当前交接 [status_import]` |
| `support_kind` | `支持类型 [support_kind]` |
| `text` | `文本 [text]` |
| `title` | `标题 [title]` |
| `value` | `值 [value]` |
| `work_id` | `Work ID [work_id]` |
| `year` | `年份 [year]` |

上述 union 覆盖 `KnowledgeSearchResultV1`、`KnowledgeShowResultV1`、`CandidateKnowledgeV1`、Citation/Descriptor/Evidence snapshots、Descriptor payload 的两个 `value` variant、governance 与 import object 的全部允许 key。首个切片不会产生 `research_interest_id`；保留其 label 不授权 Relevance Candidate。由于 `search` machine result 只有完整 Candidate、治理和 final rank，Human search 同样不泄露 Citation/Descriptor snapshot、excerpt/page、Handoff/import、atoms、BM25、branch rank、RRF 或 Registry provenance。`show` 则按同一语法完整呈现全部治理与审计字段。

若且仅若 show result 的 `governance.intake_status="withdrawn"`，renderer 在完整 `governance` subtree 后、下一个根 field 前插入下列 depth-0 固定行；active 时禁止该行。Withdrawn 的 `review_status` 只能是 `rejected|deferred`，pending 不产生 Handoff 或 Registry 状态，因而没有 Human withdrawn 表示。

```text
注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。
```

### Redirected success fixture bytes

下列四个 fence 各自是完整 UTF-8 文件 bytes：无 BOM、无 CR，closing fence 前的换行是唯一 final LF。它们只固定本节 exact-output witness 的可复制输入与哈希，不替代未来独立版本化的生产 Reviewed Handoff Schema。Accept Candidate payload/hash、两次 T04 Handoff identity、accept 的 self-contained snapshots、withdraw tombstone、manifest→`candidates.jsonl` 哈希与 revision 关系均须按现有合同复验。

Accept `candidates.jsonl`：

```json
{"action":"accept","candidate":{"candidate_id":"cand_3a421e895f79e2c167e2ef4b","payload":{"candidate_type":"claim","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","descriptor_refs":[],"schema_version":"gezhi.candidate_payload.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","statement":{"evidence_pointers":[{"block_id":"block-001","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"gezhi.evidence_pointer.v1"}],"risk_flags":[],"source_terms":["source term"],"support_kind":"direct","text":"示例结论"},"work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"},"payload_sha256":"3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1","schema_version":"gezhi.candidate_knowledge.v1"},"citation":{"arxiv_id":null,"author_count":1,"doi":null,"primary_authors":["张三"],"source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","title":"示例论文","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000","year":2024},"descriptor_snapshots":[],"evidence_snapshots":[{"excerpt":"Example evidence.","page_index":null,"pointer":{"block_id":"block-001","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","schema_version":"gezhi.evidence_pointer.v1"}}],"review_receipt":{"review_revision":1,"review_status":"accepted","reviewer_kind":"local_human_cli"},"schema_version":"gezhi.reviewed_candidate_action.v1"}
```

Accept `manifest.json`：

```json
{"candidates_sha256":"9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","canonical_run_id":"canonical_fixture_001","handoff_id":"hnd_a90bf219d563804b283af452","provenance":{"canonical_run_id":"canonical_fixture_001","semantic_run_id":"semantic_fixture_001"},"record_count":1,"schema_version":"gezhi.reviewed_handoff_manifest.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"}
```

Withdraw `candidates.jsonl`：

```json
{"action":"withdraw","candidate_id":"cand_3a421e895f79e2c167e2ef4b","payload_sha256":"3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1","review_receipt":{"review_revision":2,"review_status":"rejected","reviewer_kind":"local_human_cli"},"schema_version":"gezhi.reviewed_candidate_action.v1"}
```

Withdraw `manifest.json`：

```json
{"candidates_sha256":"0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e","canonical_content_sha256":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","canonical_run_id":"canonical_fixture_001","handoff_id":"hnd_39cf03ad1f8fd432e3b83a5b","provenance":{"canonical_run_id":"canonical_fixture_001","semantic_run_id":"semantic_fixture_001"},"record_count":1,"schema_version":"gezhi.reviewed_handoff_manifest.v1","source_id":"src_bbbbbbbbbbbbbbbbbbbbbbbb","source_sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","work_id":"wrk_123e4567-e89b-42d3-a456-426614174000"}
```

对应完整文件 SHA-256 固定为：Accept candidates `9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507`、Accept manifest `8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930`、Withdraw candidates `0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e`、Withdraw manifest `a6c2da28a7e542197222fe646305023178606b1febff6954b3f09f8b9eec5f47`。

### Redirected success exact-byte witnesses

下列四个 fence 内从首字符到末字符是 redirected stdout 的完整 UTF-8 文本；closing fence 前的换行就是唯一 final LF。四项 stderr 都是 zero bytes、process exit 都是 `0`；stdout 无 BOM、CR、ANSI、console wrapping 或 fence 字符。示例 Candidate 的 `payload_sha256` 是所示 payload 的真实 CanonicalJsonV1 SHA-256，`candidate_id` 与其前 24 位一致。

#### search：0 项

```text
Knowledge 候选搜索
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
Candidate 数量 [candidate_count]: 0
候选项 [items]: []
规范查询 [query]: "没有结果"
结果种类 [result_kind]: "candidate_backed"
架构版本 [schema_version]: "gezhi.knowledge_search_result.v1"
```

#### search：1 项

```text
Knowledge 候选搜索
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
Candidate 数量 [candidate_count]: 1
候选项 [items]:
  -
    Candidate [candidate]:
      Candidate ID [candidate_id]: "cand_3a421e895f79e2c167e2ef4b"
      Payload [payload]:
        Candidate 类型 [candidate_type]: "claim"
        Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
        Descriptor 引用 [descriptor_refs]: []
        架构版本 [schema_version]: "gezhi.candidate_payload.v1"
        Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"
        Source SHA-256 [source_sha256]: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        陈述 [statement]:
          证据指针 [evidence_pointers]:
            -
              Block ID [block_id]: "block-001"
              Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
              架构版本 [schema_version]: "gezhi.evidence_pointer.v1"
          审核风险标记 [risk_flags]: []
          来源术语 [source_terms]:
            - "source term"
          支持类型 [support_kind]: "direct"
          文本 [text]: "示例结论"
        Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"
      Payload SHA-256 [payload_sha256]: "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
      架构版本 [schema_version]: "gezhi.candidate_knowledge.v1"
    治理 [governance]:
      接收状态 [intake_status]: "active"
      晋升状态 [promotion_status]: "not_promoted"
      审核状态 [review_status]: "accepted"
    排名 [rank]: 1
规范查询 [query]: "source term"
结果种类 [result_kind]: "candidate_backed"
架构版本 [schema_version]: "gezhi.knowledge_search_result.v1"
```

#### show：active

```text
Knowledge 候选详情
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
Candidate [candidate]:
  Candidate ID [candidate_id]: "cand_3a421e895f79e2c167e2ef4b"
  Payload [payload]:
    Candidate 类型 [candidate_type]: "claim"
    Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    Descriptor 引用 [descriptor_refs]: []
    架构版本 [schema_version]: "gezhi.candidate_payload.v1"
    Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"
    Source SHA-256 [source_sha256]: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    陈述 [statement]:
      证据指针 [evidence_pointers]:
        -
          Block ID [block_id]: "block-001"
          Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
          架构版本 [schema_version]: "gezhi.evidence_pointer.v1"
      审核风险标记 [risk_flags]: []
      来源术语 [source_terms]:
        - "source term"
      支持类型 [support_kind]: "direct"
      文本 [text]: "示例结论"
    Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"
  Payload SHA-256 [payload_sha256]: "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
  架构版本 [schema_version]: "gezhi.candidate_knowledge.v1"
引用快照 [citation]:
  arXiv ID [arxiv_id]: null
  作者总数 [author_count]: 1
  DOI [doi]: null
  主要作者 [primary_authors]:
    - "张三"
  Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"
  Source SHA-256 [source_sha256]: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  标题 [title]: "示例论文"
  Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"
  年份 [year]: 2024
内容交接 [content_import]:
  动作 [action]: "accept"
  candidates.jsonl SHA-256 [candidates_sha256]: "9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507"
  Handoff ID [handoff_id]: "hnd_a90bf219d563804b283af452"
  manifest.json SHA-256 [manifest_sha256]: "8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930"
  审核修订 [review_revision]: 1
Descriptor 快照 [descriptor_snapshots]: []
证据快照 [evidence_snapshots]:
  -
    摘录 [excerpt]: "Example evidence."
    页索引 [page_index]: null
    证据指针 [pointer]:
      Block ID [block_id]: "block-001"
      Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      架构版本 [schema_version]: "gezhi.evidence_pointer.v1"
治理 [governance]:
  接收状态 [intake_status]: "active"
  晋升状态 [promotion_status]: "not_promoted"
  审核状态 [review_status]: "accepted"
结果种类 [result_kind]: "candidate_backed"
架构版本 [schema_version]: "gezhi.knowledge_show_result.v1"
当前交接 [status_import]:
  动作 [action]: "accept"
  candidates.jsonl SHA-256 [candidates_sha256]: "9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507"
  Handoff ID [handoff_id]: "hnd_a90bf219d563804b283af452"
  manifest.json SHA-256 [manifest_sha256]: "8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930"
  审核修订 [review_revision]: 1
```

#### show：withdrawn/rejected

```text
Knowledge 候选详情
治理说明：以下结果仅为已审核但尚未晋升的 Candidate Knowledge，不代表已晋升知识、已验证事实或自动蕴含证明。
Candidate [candidate]:
  Candidate ID [candidate_id]: "cand_3a421e895f79e2c167e2ef4b"
  Payload [payload]:
    Candidate 类型 [candidate_type]: "claim"
    Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
    Descriptor 引用 [descriptor_refs]: []
    架构版本 [schema_version]: "gezhi.candidate_payload.v1"
    Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"
    Source SHA-256 [source_sha256]: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    陈述 [statement]:
      证据指针 [evidence_pointers]:
        -
          Block ID [block_id]: "block-001"
          Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
          架构版本 [schema_version]: "gezhi.evidence_pointer.v1"
      审核风险标记 [risk_flags]: []
      来源术语 [source_terms]:
        - "source term"
      支持类型 [support_kind]: "direct"
      文本 [text]: "示例结论"
    Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"
  Payload SHA-256 [payload_sha256]: "3a421e895f79e2c167e2ef4b4f42ece44839ca487c11e6659870904f268eabf1"
  架构版本 [schema_version]: "gezhi.candidate_knowledge.v1"
引用快照 [citation]:
  arXiv ID [arxiv_id]: null
  作者总数 [author_count]: 1
  DOI [doi]: null
  主要作者 [primary_authors]:
    - "张三"
  Source ID [source_id]: "src_bbbbbbbbbbbbbbbbbbbbbbbb"
  Source SHA-256 [source_sha256]: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  标题 [title]: "示例论文"
  Work ID [work_id]: "wrk_123e4567-e89b-42d3-a456-426614174000"
  年份 [year]: 2024
内容交接 [content_import]:
  动作 [action]: "accept"
  candidates.jsonl SHA-256 [candidates_sha256]: "9a9724ea798c15059e06b2bb60aef971ec491af0f43b4a68745b5c0b01e3c507"
  Handoff ID [handoff_id]: "hnd_a90bf219d563804b283af452"
  manifest.json SHA-256 [manifest_sha256]: "8f6635fc1f12a442f396c79147c9b454d5237165014b6e4b0039379b0f394930"
  审核修订 [review_revision]: 1
Descriptor 快照 [descriptor_snapshots]: []
证据快照 [evidence_snapshots]:
  -
    摘录 [excerpt]: "Example evidence."
    页索引 [page_index]: null
    证据指针 [pointer]:
      Block ID [block_id]: "block-001"
      Canonical 内容 SHA-256 [canonical_content_sha256]: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
      架构版本 [schema_version]: "gezhi.evidence_pointer.v1"
治理 [governance]:
  接收状态 [intake_status]: "withdrawn"
  晋升状态 [promotion_status]: "not_promoted"
  审核状态 [review_status]: "rejected"
注意：该 Candidate 已撤回，不参与 search 或 ask 检索；以下内容仅供历史审计。
结果种类 [result_kind]: "candidate_backed"
架构版本 [schema_version]: "gezhi.knowledge_show_result.v1"
当前交接 [status_import]:
  动作 [action]: "withdraw"
  candidates.jsonl SHA-256 [candidates_sha256]: "0eb7acfdbb5b679171ffa4b898393d2d58fe9300a61f509711b5659dd99f0d9e"
  Handoff ID [handoff_id]: "hnd_39cf03ad1f8fd432e3b83a5b"
  manifest.json SHA-256 [manifest_sha256]: "a6c2da28a7e542197222fe646305023178606b1febff6954b3f09f8b9eec5f47"
  审核修订 [review_revision]: 2
```

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
- accepted/active、rejected/withdrawn 与 deferred/withdrawn 混合数据；从未 accepted 的 pending Candidate 不产生 Handoff、不在 Registry 建立状态且 show 为 `candidate_not_found`；既有 active Candidate 在没有后续 Reviewed Handoff 时保持原有 show/search 状态，不同 payload 使用不同 Candidate ID；rejected 或 deferred withdraw 后 search 排除，随后 accept 恢复，show withdrawn 仍成功；
- search result 只含完整 Candidate/治理/rank，show result 的 Candidate/Citation/Descriptor/Evidence/import 交叉约束；
- invalid ID、missing ID、unknown Registry generation、缺 FTS、数据库损坏、branch failure、Candidate hash mismatch、import/hash/evidence 缺失与 root identity loss；
- read-only connection 与副作用断言：Registry logical state、main database pages、immutable imports 与 answer tree 不变且不新增业务文件；已存在 WAL/SHM 中只服务 read snapshot 的 SQLite lock/read-coordination metadata 不算业务 mutation，但不得执行 DML/DDL、checkpoint、migration 或 vacuum；
- 1,048,576/1,048,577-byte presentation 边界、canonical JSON LF、Human 固定中文、stdout/stderr 隔离与 `0/2/1` exit；`HumanTreeV1` 逐项覆盖 null/bool/int/string、empty/nonempty array/object、nested object、多个相邻 array item、全部 label/key 与四个 redirected exact-byte witness；
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
