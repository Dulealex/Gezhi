# Knowledge Intake v1 合同

状态：已冻结。本合同为 [T18 / Issue #19](https://github.com/Dulealex/Gezhi/issues/19) 冻结 Reviewed Handoff 到 Knowledge Candidate Registry 的 owned write seam、SQLite migration baseline、revision 规则、不可变 import evidence 与 typed verdict。它实现 [ADR 0010](../adr/0010-use-one-authoritative-store-per-context.md)、[ADR 0025](../adr/0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md)、[ADR 0031](../adr/0031-use-a-flat-auditable-knowledge-asset-tree.md)、[ADR 0121](../adr/0121-classify-continuation-failures-by-recoverability-and-certainty.md)、[ADR 0137](../adr/0137-commit-knowledge-import-evidence-before-registry-state.md) 与 [ADR 0138](../adr/0138-own-the-rebuildable-candidate-search-projection-in-knowledge-intake.md)，输入 bytes 必须逐项满足 [Reviewed Handoff v1](./reviewed-handoff-v1.md)。

## 1. 唯一写入 seam

唯一跨 Context 写入 interface 是：

```python
KnowledgeIntake.apply(
    ReviewedHandoffBytesV1(
        manifest_bytes=<完整 manifest.json bytes>,
        candidates_bytes=<完整 candidates.jsonl bytes>,
    )
)
```

值只携带两个 immutable buffers。Knowledge 不接收 Literature path、Data Root capability、SQLite connection、Review current 或可写 callback；Literature 不读取或写入 Registry。Knowledge 必须从 bytes 独立重验 closed Schema、CanonicalJsonV1、文件 hash、Handoff identity、Candidate identity、Citation/Descriptor/Evidence snapshot、provenance、action 与 revision。

明确成功只返回 `IntakeAppliedV1(intake_status, disposition)`：`accept → active`、`withdraw → withdrawn`；首次提交该 Handoff 为 `applied`，逐 byte 相同且已经明确提交的重放为 `unchanged`。Unknown、异常或 commit completion 不确定不形成 handled verdict。

## 2. Knowledge 资产与提交顺序

Knowledge Data Root 的 T18 正式资产为：

```text
registry.sqlite3
imports/
├── .staging/
│   ├── .files/
│   └── <handoff_id>/
└── <handoff_id>/
    ├── candidates.jsonl
    └── manifest.json
```

正式 import 目录是普通本机目录且恰含两个普通文件；两个文件与 `KnowledgeIntake.apply` 输入逐 byte 相同。相同 Handoff ID 与相同 bytes 幂等复用；同 ID 不同 bytes、partial/foreign/reparse target、坏 hash 或歧义明确失败，不覆盖、删除、修复或 last-write-wins。Private staging 不属于治理 authority。

单次 apply 固定按下列顺序执行：

1. 在内存中完整验证两个输入 buffer；
2. 打开并持续证明 Knowledge Data Root，取得 Registry 单写者 ownership；
3. non-replacing 提交或复用正式 import evidence，并 readback 验证；
4. 打开或创建 `registry.sqlite3`，只允许第 3 节 migration；
5. `BEGIN IMMEDIATE`，验证 Registry schema、完整性、既有 Handoff 绑定与 revision；
6. 同一 transaction 内追加 Handoff revision、安装首次 accept content，并从 revision history 重建该 Candidate 的 current projection；
7. commit 后重新只读核验本次 Handoff 与 current projection，才返回 acknowledgement。

Evidence 已明确提交而 Registry transaction 未提交时，evidence 是无治理权威 orphan；相同 apply 可以复用并完成 transaction。Registry commit 已发生但调用方未收到 acknowledgement 时，相同 apply 必须核验已有 row 与 evidence 后返回 `unchanged`。任何 completion 不确定状态不得猜测为 applied、unchanged 或 failed。

## 3. SQLite migration baseline

Registry 固定 `PRAGMA application_id=0x475A4831`、`PRAGMA user_version=1`、foreign keys enabled。V1 只允许两种启动状态：

- `registry.sqlite3` 不存在，或 `user_version=0` 且数据库没有任何 user object：在单一 transaction 中创建 V1；
- `application_id=0x475A4831、user_version=1`：逐项验证 V1 schema、约束、foreign keys 与完整性后使用。

`user_version=0` 但已有 user object、错误 application ID、未知/未来 version、缺表/多表、列/约束漂移、foreign-key failure 或 integrity failure 都是 Registry conflict；不得自动猜测、导入旧 PaperBot schema、删除表、降级、就地修补或创建空 fallback。

V1 的逻辑表恰为：

- `registry_meta`：唯一 row，保存 schema identity 与单调 `generation`；每个首次提交的 Handoff 增加 1，unchanged 重放不增加；
- `candidate_content`：每个 Candidate 恰一行 immutable accepted content，保存完整 Candidate、Citation、Descriptor snapshots、Evidence snapshots 的 canonical JSON bytes及其 Work/Source/Canonical identity；`promotion_status` 只能是 `not_promoted`；
- `handoff_revisions`：每个已提交 Handoff 恰一行 append-only history，保存 action、review status/revision、两个文件 hash、Handoff/Work/Source/Canonical/provenance identity；同一 Candidate 与 review revision 唯一；
- `candidate_current`：从该 Candidate 最大已提交 Handoff revision 确定性重建的 current projection，保存 current review status、Intake Status 与 status Handoff binding。

数据库内部表名、列名与索引不是 CLI 或跨 Context interface；T19 及以后必须通过 Knowledge deep module 读取，不让调用方拼 SQL。

T19 依据 ADR 0138 在同一 SQLite 文件内增加独立版本化的搜索派生投影；FTS virtual/shadow table 与 `registry_search_meta` 不增加第五张治理逻辑表，也不成为新的事实源。首次 applied accept/withdraw 必须在同一 transaction 更新该投影并绑定新的 Registry generation。只有已知、完整且通过验证的 T18 四表基线可在 exact Handoff replay 时补建投影；该补建保持治理 generation 与 `unchanged` disposition 不变。未知或损坏 schema 继续 fail closed，读取命令不得承担迁移。

`candidate_content` 的 Candidate、Citation、Descriptor 与 Evidence canonical bytes 在同一 Candidate ID 下仍不可变；其中 content import provenance 是由 revision history 重建的读取投影，必须指向最近合法 accepted revision。较新的 withdraw 只改变 status binding；较新的 re-accept 同时成为 content/status binding。历史 exact replay 不得把任一 binding 回退到较早 revision。

## 4. Revision、重复与冲突

- 新 Candidate 的首个 Knowledge action 只能是 `accept`；其 review revision 可以大于 1，因为较早 non-accepted Decision 可能只在 Literature 形成 no-action receipt。
- 已存在 Candidate 的新 Handoff revision 必须严格大于 Registry current revision，不要求连续。
- `withdraw` 必须绑定已存在且 payload identity 相同的 Candidate，并严格晚于至少一个已提交 accept。
- 更高 `withdraw` 令 current Intake Status 为 `withdrawn`；更高 `accept` 令其恢复为 `active`。
- 相同 Handoff ID、Candidate、revision、action、全部 identity、两个文件 hash 与正式 evidence 完全相同的重放返回 `unchanged`，不得更新 current 或 generation。
- 已记录的 `(candidate_id, review_revision)` 对应不同 Handoff/bytes，未记录的倒序 revision，withdraw 未知 Candidate，Candidate ID/full hash/Canonical bytes碰撞，或相同 Candidate 的 immutable accepted content/snapshots漂移，都是明确冲突，不猜测意图。
- 历史 Handoff 的 exact replay 不回退 current projection；acknowledgement 表示该历史 action 已明确提交，不表示它仍是 Candidate 的 current revision。

`candidate_current` 只能从 transaction 内的 `handoff_revisions` 最大 revision重建。Import evidence 是逐 byte 审计 witness，不可代替 Registry 重建治理状态；Registry 也不得脱离其绑定 evidence 返回成功。

## 5. Typed failure mapping

KnowledgeIntake 只使用 Reviewed Handoff v1 已批准的 closed verdict：

- `data_root_unsafe|data_root_unavailable`：Knowledge root 初始 physical gate；
- `data_root_integrity_lost`：已打开 root 的 identity/proof 漂移；
- `registry_unavailable`：Registry 不能安全打开或创建；
- `registry_busy`：在冻结的短等待内不能取得单写者或 `BEGIN IMMEDIATE`；
- `revision_conflict`：倒序、同 revision 不同 Handoff/bytes、withdraw 无合法前序 accept；
- `registry_conflict`：Candidate identity/content、Registry schema/integrity、已提交 DB row 与绑定 evidence 冲突；
- `commit_failed`：能够确定本次 Registry 未提交的本地提交失败；
- `import_failed`：确定性的 Handoff Schema/hash/identity/snapshot/provenance 或 immutable evidence失败；
- `import_blocked`：仅保留给其他已批准、可恢复且不属于上述 specific reason 的 prerequisite。

Specific reason 优先于 generic reason。SQLite commit、directory rename 或 readback completion 不确定，unknown exception 与未列出的 verdict 位于 handled matrix 外。

## 6. 非目标与验收

T18 原始验收不实现 FTS、`knowledge search/show/ask`、Retrieval View、Answer、Promotion Gate、Promoted Knowledge、batch import、dynamic plugin、旧数据库迁移或 repair command。T19 只按 ADR 0138 把搜索投影的原子维护加入现有 Intake writer；它不改变 T18 的治理事实、typed verdict 或 Promotion 禁令。

最低验收覆盖：两个真实 launcher 的 accept/withdraw/import receipt；相同 Handoff 重放；accept→withdraw→re-accept；revision skip、倒序和同 revision冲突；Candidate/content/snapshot冲突；Registry migration/schema/integrity/busy；evidence orphan恢复、正式 evidence冲突、transaction rollback与commit-uncertain重放；current projection重建；withdrawn不再是active；任何路径均不创建 Promoted Knowledge。
