# 分离版本化源码、持久业务数据与可重建本机状态

V1 的 filesystem threat model 假设没有恶意或高权限本机进程在检查与使用之间并发替换目录组件。系统必须在 Data Root preflight、创建本次 staging 直接子目录之前，以及任何正式或 recovery 目录改名之前复核冻结 root identity、handle-derived canonical root、目标父链与 reparse 状态；检测到漂移即停止，但不宣称消除了最后一次检查与实际操作之间的 hostile TOCTOU。V1 不要求所有 descendant I/O 都通过 handle-relative Win32/NT API。本文“路径仍被根包含”“拒绝 reparse”与“值不得漂移”均指词法派生规则和这些强制 checkpoint 观察到的状态，不是对两次观察之间 namespace 不变的持续保证。

Context runtime 只验证并持有自己消费的 Data Root，不打开其他 Context roots，也不因无关 root 缺失或不可访问而阻塞。允许的路径等价仅限大小写、separator、`.` / `..` 归一与普通/local-extended DOS 前缀；8.3 short name、SUBST、额外盘符、volume mount 等隐藏 filesystem alias 一经发现即不属于受支持的数据边界。

所有 Context Data Root 的规范化 Windows path namespace 必须两两不同且互不构成祖先/后代。任一 root 都不得等于项目根 `E:\Gezhi`，也不得包含该项目根；位于项目根内部时，它必须是共享容器 `E:\Gezhi\data` 的严格后代，不能直接使用 `E:\Gezhi\data`。项目外的本机 root 仍允许。未来 Context 通过新 configuration generation 增加显式 root 时，也必须继续满足这项 pairwise isolation rule。

格致默认以 `E:\Gezhi` 为项目总目录：Git 管理源码和规范，`E:\Gezhi\data\literature` 与 `E:\Gezhi\data\knowledge` 保存不入 Git、必须备份的正式业务数据，`E:\Gezhi\.local` 保存可通过锁文件、模型下载或重跑恢复的环境、模型、缓存和临时状态。未完成结果在同一数据卷内 staging 后原子发布；每个上下文只能写自己的数据根，所有正式路径必须解析后仍被其根目录包含，并拒绝路径穿越、符号链接、junction 与 reparse point。ADR 0029 后续把两个可变部署事实冻结为 `gezhi.config.v1` 的 `literature.data_root` 与 `knowledge.data_root`，完整内置默认值即上述两个目录；运行中必须使用 preflight 后冻结的值，不得漂移。V1 只支持本机 non-remote Windows volume 上的 drive-absolute 或等价 local extended DOS root；项目目录外的本地根允许，relative/UNC/WSL UNC/remote mapping/device/Volume GUID/ADS 等 namespace 拒绝，Context command 不自动创建缺失 root。未来 Context 通过新 generation 增加自己的显式 table，不进入动态 root map。

本 ADR 中的“持久业务数据”是数据分类：它表示权威、不可随意重建、脱离 Git 且需要备份，不等同于每次写入都请求 write-through，也不自行承诺突然断电后最新提交一定存续。每个 Context 的写入、原子可见性与 power-loss durability 由自己的版本化合同决定；Knowledge Answer v1 的具体否定保证见 ADR 0088，这不替 Literature、SQLite 或未来 Bot 作同一选择。
