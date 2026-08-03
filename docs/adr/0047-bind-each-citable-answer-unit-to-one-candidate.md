# 将每个可引用回答单元绑定到一个 Candidate

Knowledge v1 的每个 `CitableAnswerUnitV1` 与 `CitableQualificationUnitV1` 都只允许一个 `candidate_id`，跨来源回答通过多个有序单元组合，而不是把多个 Candidate ID 堆在同一段新结论之后；`answer_units` 在 `answered` 时允许 1–12 项，`qualification_units` 允许 0–4 项，而 `insufficient_evidence` 时两者都固定为空，每种数组内 Candidate 唯一，每项复用 NFC、去首尾空白后的 1–400 code point 单行纯文本合同。首版因此不生成跨 Candidate 联合结论，除非某个已审核 Candidate 本身已经表达该综合语义；Python 保留语义顺序并能验证一对一成员资格，但不能证明语义蕴含，所以结果保持 Candidate-backed 标签。以后如需真正的跨 Candidate synthesis，必须使用新 Schema 和逐分句支持映射，而不能放宽本版本合同。
