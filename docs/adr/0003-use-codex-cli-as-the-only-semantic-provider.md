# 仅使用 Codex CLI 承担语义任务

格致首版只通过原生 Windows Codex CLI 执行论文理解、候选知识提取和语义质量检查，不建设模型路由器，也不接入 Ollama、本地小模型或 OpenAI Python SDK。该选择减少模型分支、配置面和静默降级风险，使 RTX 4090 专用于 MinerU；代价是 Codex 不可用时相关语义阶段必须明确阻塞。
