# 使用最小且受控的 Candidate Draft

`CandidateDraftV1` 只包含五类 `candidate_type`、一个 `EvidenceStatementV1`、可为空且必须解析到同一 Reading Result 的受控 Descriptor Reference，以及只对 Relevance Candidate 必填、对其他类型禁止的 `research_interest_id`；Codex 不生成 candidate ID、Work/Source 身份或任何哈希，这些由 Python 在完整校验后补充。首版不保留通用 subtype、自由结构 attributes、标题、推荐理由、重要性分数、自由标签或重复摘要；Comparison 用 Claim 正文和 `comparative_claim` Review Risk Flag 表达，未来只有在真实查询需求出现后才通过新 Schema 版本增加专门结构。本决策完善 ADR 0017 与 0018，以降低首版实现、内容寻址和人工审核复杂度。
