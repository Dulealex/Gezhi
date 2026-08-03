# Literature

Literature 负责论文及强相关科研资料从来源进入到可审核知识候选的业务语义。它拥有资料身份、来源、阅读资产与候选知识，但不拥有长期知识晋升。

## 语言

**Work**:
一个独立的科研成果实体，可以对应多个来源、版本或物理资产。
_Avoid_: Paper, PDF, File

**Identity Alias**:
用于识别同一 Work 的 DOI、arXiv ID 或规范化书目信息；它可以补充和修正，但不是稳定内部身份。
_Avoid_: Work ID, Path Name

**Identity Review**:
当弱书目信息不足以安全判断两个输入是否属于同一 Work 时，由用户作出的合并或分离决定。
_Avoid_: Automatic Merge, Candidate Review

**Source**:
一个 Work 的具体来源、版本和内容快照，是来源证据与阅读选择的最小业务单位。
_Avoid_: File, URL

**Source Asset**:
保存某个 Source 原始内容的物理资产，具有完整内容哈希但不拥有独立业务身份。
_Avoid_: File Entity, Work

**Active Source**:
当前被选择用于生成 Canonical Reading Asset 的唯一 Source；其他 Source 只能作为证据或后备来源共存。
_Avoid_: Active File, Best PDF

**Canonical Reading Asset**:
由一个 Active Source 生成的稳定、来源无关且可按证据块寻址的规范阅读包。
_Avoid_: Summary, Mixed Source, MinerU Output

**Evidence Block**:
Canonical Reading Asset 中具有稳定标识、内容和来源位置的最小证据单元。
_Avoid_: Line Number, Free-form Quote

**Evidence Pointer**:
Candidate Knowledge 使用 Canonical 内容身份与 Evidence Block ID 构成的可验证内容寻址引用；它不是物理 run locator、页码或摘录文本。
_Avoid_: File Path, Canonical Run ID, Citation Text

**Evidence Support**:
语义陈述与所引 Evidence Block 之间的支持关系，只能是 direct、synthesized 或 interpretive；它描述证据关系，不代表真伪或审核结论。
_Avoid_: Confidence Score, Proof, Review Status

**Review Risk Flag**:
提示 Candidate Knowledge 需要额外人工注意的受控标记，不等同于模型置信度、拒绝理由或审核状态。
_Avoid_: Confidence, Rejection Reason, Review Status

**Research Interest**:
带稳定身份的已配置研究方向，用作判断 Relevance Candidate 的明确参照；它不是一次检索问题或 Work 优先级。
_Avoid_: Search Query, Paper Priority, Candidate Type

**Study Descriptor**:
Reading Result 中用于说明研究语境的 Object、Dataset、Experiment 或 Metric；它提供结构化上下文，但不是 Candidate 类型。
_Avoid_: Candidate, Free-form Tag, Attribute Bag

**Descriptor Reference**:
Candidate Knowledge 对同一 Reading Result 中 Method 或 Study Descriptor 的受控内容寻址引用。
_Avoid_: Array Position, Free-form Attribute, Tag, Copied Description

**Reading Result**:
从一个 Canonical Reading Asset 得到、围绕研究问题、方法、发现、局限、相关性、开放问题和研究描述符组织的论文级结构化阅读结果；它不具备长期知识地位。
_Avoid_: Candidate Registry, Promoted Knowledge, Section-by-section Report

**Candidate Draft**:
语义模型从 Reading Result 与可追溯证据中提出、值得跨 Work 检索和审核但尚未通过确定性合同与证据校验的候选草稿。
_Avoid_: Candidate Knowledge, Model Fact, Reading Item

**Candidate Knowledge**:
从可追溯阅读证据中提取、已通过本地合同校验但尚未通过长期知识晋升的结构化候选。
_Avoid_: Knowledge, Fact, Candidate Draft

**Review Queue**:
等待用户异步作出接受、拒绝或暂缓决定的 Candidate Knowledge 集合。
_Avoid_: Promotion Queue, Blocking Prompt

**Candidate Review**:
用户对 Candidate Knowledge 是否可以进入 Reviewed Handoff 作出的显式业务决定；它不授予长期知识地位。
_Avoid_: Code Approval, Promotion

**Review Status**:
Candidate Review 的当前结论，只能是 pending、accepted、rejected 或 deferred。
_Avoid_: Promotion Status

**Review Decision**:
用户针对一个确定 Candidate payload 作出的不可变审核记录；后续改变决定必须追加新记录。
_Avoid_: Mutable Flag, Model Approval

**Reviewed Handoff**:
只携带已审核 Candidate Knowledge 及其身份、Evidence Support、Review Risk Flag、证据和状态的跨上下文交接。
_Avoid_: Archive Export, Promoted Knowledge

**Literature Stage**:
本地资料从进入到 Knowledge 接收之间的一个固定业务职责位置；V1 依次为 ingest、ocr、canonicalize、read、review、handoff 与 knowledge_import。
_Avoid_: Generic Job, Plugin Step, DAG Node

**Continuation Point**:
一个 Work 在当前权威资产下最早尚未被满足的 Literature Stage 或已授权交接义务，是显式 resume 的起点。
_Avoid_: Last Log Line, Staging Guess, Current Command

## Candidate 类型

**Method Candidate**:
描述 Work 提出或采用的方法以及其关键机制。
_Avoid_: Experiment Candidate

**Claim Candidate**:
描述 Work 在明确证据下给出的事实性结论，可包含实验、指标或比较属性。
_Avoid_: Proven Fact, Comparison Candidate

**Limitation Candidate**:
描述方法、实验或结论的明确局限、适用边界或证据缺口。
_Avoid_: Generic Criticism

**Relevance Candidate**:
描述 Work 与已配置研究方向之间可说明依据的关系。
_Avoid_: Paper Priority

**Open Question Candidate**:
描述由现有证据引出、值得继续研究或验证但尚无确定答案的问题。
_Avoid_: Claim Candidate
