# ADR 0136：以单入口深 module 提交 Candidate Review

状态：已接受

T16 把 Candidate Review、append-only Review Decision、Reviewed Handoff 与尚未完成的 Knowledge import 续行收进一个 Literature-owned 深 module。它在 T16 只有一个外部 interface：`review_candidate(ReviewCandidateCommandV1(candidate_id, action), ...)`。CLI adapter 只负责完整 public `literature review CANDIDATE_ID (--accept|--reject|--defer)` grammar、配置与 Data Root gate、command 构造、结果呈现和 exit mapping；它不能逐步调用 Candidate 定位、revision 计算、Decision 写入、Handoff 生成或 Registry 修改。Candidate Review 的 Human-only 性质由该 public grammar、module 固定写入 `reviewer_kind=local_human_cli`，以及 Reader 与运行时 Codex 不具有 Literature 写能力共同保证；Reader、Codex、status 与普通 resume 都不能创建 Review Decision。

`review_candidate` 隐藏当前或历史 Candidate successor 定位、Candidate ID/完整 payload hash/canonical bytes/provenance/Evidence/Descriptor 复验、Work writer ownership、Review history 恢复、状态转换、Handoff bytes、原子提交与幂等续行。T17 在出现真实 backlog caller 时可以增加一个只续行既有授权的 Work-level entry point，但该入口不得创建 Review Decision；T16 不预建 batch、通用 workflow、Repository 或 FileStore port。

Review Decision 以 `works/<work_id>/reviews/<candidate_id>/<revision>.json` 追加，首 revision 为 1。Decision 绑定 `candidate_id` 与完整 `payload_sha256`，固定 reviewer kind 为 `local_human_cli`，V1 note 恒 absent；完整 leaf 验证后才切换同 Candidate 的 `current.json`。相同 payload/action 重试为 `unchanged`，不追加 revision、不改 timestamp/current，但继续补同一 revision 的后续义务；不同 action 使用 revision+1。Decision、current 与 no-action receipt 的 closed bytes 由 [Reviewed Handoff v1](../contracts/reviewed-handoff-v1.md) 冻结。

每个 revision 最多形成一个 immutable Reviewed Handoff，正式目录恰含 `manifest.json` 与单记录 `candidates.jsonl`。Accepted 形成携带完整 Candidate、Citation、Descriptor、Evidence snapshot 与审核收据的 `accept`；只有成功 Knowledge import receipt 已证明该 Candidate 曾导入时，后续 rejected/deferred 才形成最小 `withdraw`。从未导入的 rejected/deferred 形成 Literature-owned deterministic no-action receipt，不生成 Handoff ID、空 Handoff 或 Registry row。旧 accept 在尚未成功导入时被更高 non-accepted Decision supersede 后不得再导入。

Literature 与 Knowledge 的唯一 cross-context seam 是 `KnowledgeIntake.apply(ReviewedHandoffBytesV1)`。值只携带已经完整验证的 `manifest.json` 与 `candidates.jsonl` 最终 bytes；Knowledge 不读取 Literature path、current pointer、Review namespace 或 Candidate materialization，Literature 也不直接写 Candidate Registry。T18 提供真实 Knowledge adapter 与测试 adapter；T16 不建立假 Registry、占位 row 或伪造 import receipt。

为跨 Data Root 关闭“Knowledge 已提交、Literature 尚未确认”的进程终止窗口，真实 apply 前必须先提交绑定 Decision、Handoff ID及两文件hash的 Literature-owned immutable import attempt。Typed success 后才追加同 revision import receipt；attempt 无 receipt 时禁止更高 Decision和no-action，并只用相同 Handoff bytes幂等重放或返回 import blocked。Receipt 是对 Knowledge-owned成功事实的本地 acknowledgement，不是第三个 Handoff 文件，也不替代 Knowledge Registry transaction。

T16 未装配 `KnowledgeIntake` 时，required accept/withdraw Handoff 仍先按正式合同提交。随后 command 必须返回 blocked `literature.review.import_blocked.v1`，保留 non-null Review result，精确陈述 `handoff_status=committed`、`import_status=pending`、`intake_status=null`；它不能把 pending 包装成 succeeded 或 `applied`。相同 action 重试复用同一 Decision revision、Handoff ID 与两文件 bytes。No-action revision 不消费 Knowledge seam，可以以 `handoff_action=none`、Handoff/import `not_required` 正常完成。

任何已明确提交的 Decision、no-action receipt、Handoff、import attempt/receipt 或未来 Registry fact 都不因后续失败或 presentation failure 回滚。确定性冲突明确失败；rename/replace或跨根 acknowledgement completion不确定时停止 normal handled receipt并保留恢复证据，不能通过后续 non-accepted action掩盖。Candidate Review 与 Intake Status 仍不跨越 Promotion Gate；T16 不新增 batch、interactive review、note、Promotion 或 Promoted Knowledge。

本决定细化 [ADR 0019](./0019-use-append-only-candidate-review-decisions.md)、[ADR 0020](./0020-use-a-minimal-self-contained-reviewed-handoff.md)、[ADR 0025](./0025-propagate-candidate-review-revisions-as-accept-or-withdraw.md)、[ADR 0026](./0026-continue-review-through-handoff-and-knowledge-import.md)、[ADR 0118](./0118-limit-v1-candidate-review-to-one-candidate-and-action.md)、[ADR 0121](./0121-classify-continuation-failures-by-recoverability-and-certainty.md) 与 [ADR 0135](./0135-publish-candidate-materialization-as-an-immutable-successor.md)，不改变 [Literature Commands v1](../contracts/literature-commands-v1.md) 已冻结的 public interface、result 或 diagnostic union。
