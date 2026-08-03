# Knowledge

Knowledge 负责接收经过审核、可追溯的知识候选，并提供跨来源治理、检索和引用能力。它不拥有上游全文处理，也不自动授予候选长期知识地位。

## 语言

**Evidence Pointer**:
Candidate Knowledge 中由 Canonical 内容身份与 Evidence Block ID 构成、可返回原始来源证据的验证引用；它不是摘录文本、页码或物理 run locator。
_Avoid_: Citation Text, File Path, Canonical Run ID

**Candidate Registry**:
保存候选身份、来源、状态和冲突关系的治理集合。
_Avoid_: Knowledge Base

**Intake Status**:
一个已交接 Candidate 当前是否允许参与 Knowledge 检索，只能是 active 或 withdrawn。
_Avoid_: Review Status, Promotion Status

**Candidate Withdrawal**:
由较新的 rejected 或 deferred 审核决定使既有 accepted Candidate 停止参与检索、但不删除其导入历史和证据的动作；pending 审核不产生 Handoff，也不创建或更新 Registry 状态。
_Avoid_: Delete, Demotion

**Candidate Search Result**:
为一次搜索返回的、按当前治理资格排序且保留 Candidate 内容身份与 Evidence Pointer 的发现结果；它不包含证据摘录，也不授予 Candidate 长期知识地位。
_Avoid_: Retrieval View, Search Index, Promoted Knowledge

**Candidate Detail**:
一个 Candidate 的内容、来源证据、交接 provenance 与当前治理状态的只读审计视图；withdrawn Candidate 仍可有 Detail。
_Avoid_: Promoted Knowledge, Retrieval View, Mutable Record

**Retrieval View**:
为一次查询确定性选择、过滤和排序合规 Candidate Knowledge 的可重建视图。
_Avoid_: Source of Truth, Vector Store

**Promotion Gate**:
决定 Candidate Knowledge 是否可以成为 Promoted Knowledge 的显式治理边界。
_Avoid_: Import

**Promoted Knowledge**:
通过 Promotion Gate、可作为长期治理知识使用的资产。
_Avoid_: Candidate Knowledge, Accepted Candidate

**Citable Answer**:
所有事实性结论都能追溯到本次 Retrieval View 中 Evidence-bearing Candidate 的回答。
_Avoid_: Verified Fact, Entailed Answer

**Citable Answer Unit**:
Candidate-backed Answer 中最小的模型生成事实性陈述单元，恰好绑定本次 Retrieval View 中一个 Candidate；它不是已验证事实，也不是 Candidate 类型中的 Claim。
_Avoid_: Fact, Claim, Multi-source Conclusion

**Citable Qualification Unit**:
Candidate-backed Answer 中披露适用范围、证据缺口或审核风险的模型生成边界说明，恰好绑定本次 Retrieval View 中一个 Candidate；它不是 Limitation Candidate，也不是无引用备注。
_Avoid_: Uncited Caveat, Confidence Note, Limitation Candidate

**Candidate-backed Answer**:
由已审核但尚未晋升的 Candidate Knowledge 支持，并明确披露该治理状态的 Citable Answer。
_Avoid_: Promoted Answer, Verified Answer

**Answer Status**:
Candidate-backed Answer 对本次 Retrieval View 是否足以支持事实性回答的语义结论，只能是 answered 或 insufficient_evidence；它不表示运行是否成功。
_Avoid_: Run Status, Terminal State, Confidence

**Insufficiency Reason**:
Answer Status 为 insufficient_evidence 时说明证据为何不足的受控语义分类；它不是自由解释，也不是运行失败或错误码。
_Avoid_: Failure Reason, Error Code, Model Explanation
