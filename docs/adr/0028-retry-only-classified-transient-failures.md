# 只重试已分类的瞬时故障

`knowledge_answerer_v1` 首版把该政策具体化为独立角色配置：每个 attempt 30 分钟，最多两次重试，退避 10 秒与 30 秒，最多三个全新进程，Codex attempt window 最长 95 分钟；同类与混合瞬时故障沿用 Reader 的稳定 exhausted code，而无效 JSON、Schema/Candidate/引用错误和未知非零退出都不自动重试。Knowledge 与 Reader 的首版数值相同但配置所有权分离，任何一方以后调整都不得隐式改变另一方或改写历史运行。

格致只在参数和输入哈希完全不变时有限重试明确的瞬时故障：MinerU 子进程意外退出或临时超时最多重试一次，Codex 网络中断、429、5xx 或超时最多重试两次并退避，SQLite 短暂锁定只做少量短重试；所有 attempt 都独立记录且不得复用部分输出。CUDA/模型缺失、登录或 CLI 不兼容记为 blocked，输入、Schema、证据、Descriptor、哈希、身份、预算或审核修订错误记为 failed，均不自动重试；未知 Codex 非零退出也不冒充瞬时故障。后续 ADR 0093 对 `knowledge.ask` 尚未形成 committed Answer 的领域输入作更具体窄化：进入 Knowledge adapter 后的 invalid/too-large/too-complex Question 使用 `blocked`，仍不重试；parser 级 argument failure 与其他 Context 不受该窄化影响。系统禁止 GPU→CPU、其他 OCR、其他模型、Ollama、下载模型或不匹配旧缓存等静默回退；达到上限后以按同类或混合瞬时故障区分的稳定 blocked code 终止，只能由显式 `resume` 或人工处理继续。
