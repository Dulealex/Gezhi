# 记录封闭且不含秘密的 Answer provenance

Knowledge v1 的 terminal manifest 顶层保存封闭 `provenance`，严格绑定 `knowledge_answerer_v1`、请求 selector `gpt-5.6-sol`、`high` reasoning 与项目锁定 Codex CLI `0.146.0`，并以嵌套 Git `state=clean|dirty|unborn` 和相应 40-character lowercase HEAD revision 或 `null` 记录代码来源。绑定值不声明 Codex 实际启动或远端模型 build，零 Candidate 与调用前终止也照常记录；dirty 包含 staged、未暂存和非 ignored 未跟踪项，unborn 仅表示没有首个 commit，Git 无法查询时在 Answer 身份生成前外部阻塞而不伪装。provenance 不记录或散列秘密、登录/账户、环境、机器、路径、argv、Git branch/remote/diff、问题内容或动态 prompt，也不以占位符、长度或存在标记间接披露；dirty/unborn 允许但明确不具备仅凭 revision 重现代码的能力。该选择以放弃远端模型 fingerprint 和脏工作树内容指纹为代价，提供首版所需的稳定、可验证且不会吸入本机机密的运行来源收据。

ADR 0083 将 `provenance` 固定为四种终态下都 required、顶层自身非 `null` 的十一字段闭包成员；只有其既有 `git.revision` 在 `state=unborn` 时可以按本 ADR 为嵌套 `null`，这不违反“顶层仅 `error` 可为 `null`”的边界。
