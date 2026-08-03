# 每个上下文只保留一个权威状态载体

Literature 以文件系统中的不可变、带哈希资产包作为业务事实源，SQLite 仅保存可从资产重建的索引、任务状态和查询投影；Knowledge 以 SQLite Candidate Registry 作为治理事实源，并把 Reviewed Handoff 作为不可变导入证据保留。两个上下文不得共享数据库表或直接修改对方状态，只能通过版本化 Handoff 协作，从而避免文件与数据库形成相互矛盾的双重事实源。
