# 冻结 Context-scoped Data Root CLI overrides

本 ADR 是对 [ADR 0094](./0094-freeze-uncommitted-blocked-knowledge-ask-primary-diagnostics.md) 的局部 replacing decision：Windows V1 的 Data Root CLI override 只允许 root scope 的 `--literature-data-root VALUE` 与 `--knowledge-data-root VALUE`，分别形成 `literature.data_root` 与 `knowledge.data_root` 的 raw CLI patch；`--data-root` 与 `--timeout` 都是 parser-unknown token，不进入 Configuration gate。它只 supersede ADR 0094 中尚待 source-specific contract 冻结的 provisional `--data-root` / `--timeout` token witnesses，不改变该 ADR 的 Question → Configuration gate 顺序、blocked cause、diagnostic、exit 或 Data Root policy；role timeout 继续由 immutable role descriptor 拥有，不是用户配置。

Parser 必须保留 recognized option 的空字符串值。规范的重叠 witness 是 `--knowledge-data-root= knowledge ask "" --json`：grammar 成功后，空 Question 先在 Question gate 选择 `invalid_question`，Configuration gate 不运行；把 Question 换成领域合法值而保持 `--knowledge-data-root=` 时，Question gate 通过，随后 Configuration gate 才因 present empty root 选择 `configuration_invalid`。这两个 witness 固定既有 gate order，而不是让 parser 校验领域值。

采用 Context-scoped 名称可以在同一 invocation 中无歧义地覆盖两个独立 ownership roots，并为以后经新 configuration generation 显式加入的 Context 保留同样的命名规则。恢复无 Context 的 `--data-root`、暴露 `--timeout`，或增加其他 root configuration option，都需要新的 replacing decision 与 CLI/configuration contract revision。
