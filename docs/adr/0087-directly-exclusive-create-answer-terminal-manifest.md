# 在 Answer staging 内直接排他创建 terminal manifest

本次新 Answer 的 terminal `manifest.json` canonical buffer/cap、direct `CREATE_NEW` 等价形成、write/completion/close、安全 readback、Schema/canonical byte identity、目录闭合或跨资产复验任一步失败，且 Root trust 仍成立时，使用 `{"code":"knowledge.ask.answer_manifest_failed.v1","context":{}}` 返回 no-commit `failed`、`result=null`、正常 JSON exit `1`。任何 partial、既存或无效 leaf 原样保留在 staging，不删除、修补、重开写入或规范化；历史 orphan 的无效 manifest 继续只作 supplemental。

Knowledge Answer writer 只有在当前 `answers/.staging/<answer_id>/` 中全部非 manifest 资产已经完成、验证并关闭，所有 writer-private spool、tail、临时与备份 entry 已撤销，而且 ADR 0082 的唯一 immutable canonical byte buffer 已通过 ADR 0084 的 `65_536`-byte cap 后，才可开始形成 terminal leaf。此时字面 lowercase `manifest.json` 及其任何 Windows ordinal-ignore-case alias 都必须不存在；预先枚举只用于 fail-closed 检查，真正的不存在性与不覆盖保证来自随后一次 exclusive create。Staging 在整个过程仍不是正式 Answer，所有正式消费者继续忽略它。

Writer 必须在既有安全根包含与 no-reparse 路径边界内，对字面 `manifest.json` 使用一次 Windows `CreateFileW(..., CREATE_NEW)` 等价语义直接取得一个新 binary write handle；write handle 存续期间不得授予 write 或 delete sharing，最简单实现为 `dwShareMode=0`。写入必须使用同步完成语义，或对每次 overlapped completion 明确等待并确认后才推进 offset；只有能同时证明“不存在才创建、存在绝不打开”、sharing 与 completion 语义相同的标准库封装才可替代。任何既存普通文件、目录、大小写别名、hard-link 占位、symlink、junction 或其他 reparse entry 都必须失败；不得打开、跟随、截断、覆盖、删除后重试或改写既存 entry。创建得到的 handle 还必须被验证为预期 staging 根内的普通非 reparse 文件。`CREATE_NEW` 只是不存在性的原子判定，不替代父路径与 leaf 的既有 no-reparse 检查，也不得把之前的 `exists`/枚举结果当成创建授权。

V1 不创建 writer-private manifest temp leaf，不执行 temp-to-final leaf rename，也不使用 backup、marker、sidecar、hard link、`os.replace`、`ReplaceFile`、replace-existing move 或 copy-then-delete。Writer 只能把已经检查过的同一 immutable canonical byte sequence 从 offset `0` 开始写入新 handle；每次正长度 short write 后在同一 handle 上继续写剩余 suffix，直到精确写满全部 bytes，这个 suffix loop 是一次写入的机械进度而不是 semantic retry。Zero-byte write、超出本次请求的 write count、I/O exception、未完成的异步 I/O、用户态 buffer flush 失败或 close 失败都使本次 writer 禁止提交。Exclusive create 一旦成功，本次运行就不得删除、截断、重开写入、重新序列化、覆盖或以第二次 create 修补该 leaf；现场留在 staging。

写 handle 成功关闭后，writer 必须按既有安全路径边界重新打开字面最终 `manifest.json`；该 read handle 在整次验证期间不得授予 write 或 delete sharing。共享 terminal-manifest reader 从头读到 EOF，重新执行 raw cap、framing/strict UTF-8、ADR 0086 parser profile、当前 Schema、canonical byte round-trip、完整目录闭合及全部跨资产验证。Reader 看到的 raw bytes 必须与先前写入的 immutable buffer byte-for-byte 相等。只有重读验证通过、确认没有任何未批准 entry，而且验证过程中打开的全部文件与目录 handle 都已关闭，writer 才可执行既有的一次同卷 staging-directory 原子改名。Leaf 的存在、写满或 close 都不是 Answer commit point；正式可见性的唯一 commit point 仍是整个 staging 目录改名成功。

进程崩溃可以留下缺失、空、partial 或看似完整的字面 `manifest.json`，这是 direct-create 策略允许的 staging 现场，不是正式终态。下一 writer 只有在持有同一数据根 mutex、证明没有活跃 owner，并用共享 reader 与全目录 validator 证明现有 manifest 和全部资产完整有效、目标目录不存在后，才可只补做原定目录改名；缺失或无效 leaf 原样隔离，不能补写、修短、删除、重命名、替换或从其他文件重建。原 writer 因 write/flush/close/readback 失败不得在当前运行提交；以后 recovery 是否能从实际遗留 bytes 独立证明一个完整终态，只由既有恢复合同决定。

本策略利用 staging 对正式消费者不可见以及 recovery fail-closed 的既有边界，省去 manifest temp leaf、leaf rename 和相应的残留状态；它只冻结进程崩溃下的 leaf formation 与目录级原子发布顺序。用户态 flush、close、readback、exclusive create 与目录 rename 都不等价于强制介质持久化；ADR 0088 已冻结 V1 不调用 `FlushFileBuffers`、file/directory/volume flush 或 write-through，也不承诺突然断电或系统崩溃后的 power-loss durability。

本协议只关闭持有同一 Knowledge 数据根 mutex 的合规 Gezhi writer/recovery 之间的竞态；不服从该 mutex 的同用户外部进程或恶意本地篡改不在 v1 威胁模型内。全部验证 handle 关闭到 staging-directory rename 之间仍存在面向这类外部进程的窗口，因此不得把本决策表述为通用抗篡改保证；若以后纳入该威胁，必须另行冻结目录 ACL、身份钉扎与 rename 原语。

`manifest.json` 继续不列入 `assets`，本决策不增加持久资产、字段、配置、marker、sidecar、错误码或第三方依赖，也不改变已经锁存的 Answer terminal cause。阻止本次新 Answer terminal manifest 形成的 leaf failure 已由 ADR 0095 绑定 no-commit `knowledge.ask.answer_manifest_failed.v1`；不得把该失败写进无法提交的 manifest。
