# Domain Docs

## Before exploring

1. 先阅读根目录 `CONTEXT-MAP.md`。
2. 根据任务读取相关上下文：
   - `docs/contexts/literature/CONTEXT.md`
   - `docs/contexts/knowledge/CONTEXT.md`
3. 阅读 `docs/adr/` 中影响当前工作的系统决策。
4. 阅读 `docs/contracts/` 中相关的版本化交接、资产、CLI 和诊断合同。
5. 若未来新增 Bot，先在 `CONTEXT-MAP.md` 明确其业务语言、职责和状态所有权。

## Layout

格致采用单一 Python 包中的多领域上下文结构：

- `CONTEXT-MAP.md`：系统上下文地图
- `docs/contexts/<context>/CONTEXT.md`：上下文语言和边界
- `docs/adr/`：系统级架构决策
- `docs/contracts/`：跨上下文与公开接口合同
- `src/gezhi/`：静态组合后的实现

## Vocabulary and ADRs

Issue 标题、规格、tickets、测试和代码使用 Context 文档定义的领域词汇。不得用近义词漂移概念。

如果计划与既有 ADR 冲突，必须明确指出冲突并先重新决策，不能在实现中静默覆盖。
