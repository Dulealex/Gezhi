# ADR 0135：把 Candidate 物化发布为不可变 successor

状态：已接受

T14 的 `semantic/current.json` 与 `semantic/runs/<semrun_id>/` 继续只拥有 Reader bundle。T15 不修改该 run，也不再次调用 Codex；它以当前有效 Reader manifest 为唯一上游，完成 Candidate Draft 的确定性规范化、Evidence Pointer、Descriptor Payload/Reference、内容身份、碰撞、完全相同项去重、逐类型预算和 pending Review Queue 投影。

T15 使用独立 sibling namespace：

```text
semantic/materializations/
├── current.json
├── .current.next.json
├── .staging/<matrun_uuidv4>/
└── runs/<matrun_uuidv4>/
    ├── input.json
    ├── manifest.json
    └── result/
        ├── descriptor_payloads.jsonl
        ├── candidate_knowledge.jsonl
        └── review_queue.json
```

`matrun_<lowercase UUIDv4>` 是物理运行定位，不进入 Candidate 或 Descriptor 内容身份。`input.json` 以实际文件 SHA-256 绑定 Reader 的 `reading_result.json`、`candidate_drafts.json`、Reader run/manifest、Work/Source/Canonical 内容身份及冻结 materializer profile。Success manifest 记录该 input 哈希、profile 哈希、上游身份、候选/描述符计数、Git revision、完成时间和除 manifest 外的完整资产清单。Successor 不复制 Reading Result 或 Candidate Draft；`descriptor_payloads.jsonl` 保存 Candidate 正式引用所需的完整 Descriptor Payload authority，使后续 Reviewed Handoff 可以按引用验证并形成自包含快照。

`materializations/current.json` 只含 `schema_version、run_id、manifest_sha256`。Reader 身份只存在于 input/manifest，避免把 current 变成第二份 manifest。正式队列升级为 `gezhi.review_queue.v2`，每项同时绑定 Candidate ID、完整 payload hash、`pending` 状态和 item Schema；它只是当前 successor 的待审核投影，不是 Review Decision authority，不写 `catalog.sqlite3`、Candidate Registry、Handoff 或 Promoted Knowledge。

Materializer 在创建 staging 前完成全部纯计算和整集合校验；任何 Draft、Evidence、Descriptor、预算、重复项或内容身份冲突都以 `candidate_validation_failed` 结束且不发布部分结果。提交只允许完整 success run：先在同卷 staging 写入并 readback，最后写 manifest，再原子改名到 `runs/`，最后以 `.current.next.json` 原子替换 current。确定的写入失败映射 `commit_failed`；rename、replace 或 namespace 的最终状态无法证明时保留现场并进入 recovery uncertainty，不伪造 handled success 或删除证据。

恢复顺序固定为：先处理唯一 `.current.next.json`，再处理 staging，然后验证 current，最后扫描 committed success。完整且唯一的 success staging 只能完成 rename/current；partial result、坏 manifest、foreign entry、reparse、多个 staging 或 target conflict 均原位 fail-stop。有效且绑定当前 Reader 的 current 直接复用；current 缺失或只指向有效历史 Reader 时，恰有一个匹配 committed success 可只修复 current；多个匹配 success 为歧义。修复 success pointer 与新发布 success 都把 `read` 记入本次 `advanced_stages`，单独发布或复用 T14 Reader bundle不算完成 `read`。

非零 Candidate 成功后，Resume 停在 `review/awaiting_review`，按 Candidate 文件顺序返回 `1..12` 个 pending ID，且不创建任何人工决定。零 Candidate 仍必须发布合法 successor；两个 JSONL 精确零字节、Queue 为空，此时 review、handoff 与 knowledge_import 的空集合义务自动满足，Resume 返回 `pipeline_complete=true`。这些空义务不伪造 Decision、Handoff、Registry receipt，也不把三个阶段加入 `advanced_stages`。

这一额外 publication 增加一次本地磁盘验证和一个 current，但换取 T14 run 永不改写、恢复边界局部化、Descriptor 正文可审计、T16 不必从临时数组位置猜测引用，以及 materializer 版本可以在不污染 Reader/Codex seam 的情况下演进。
