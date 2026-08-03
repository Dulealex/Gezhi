# Issue tracker: GitHub

Issues、规格和实施 tickets 位于私有仓库 `Dulealex/Gezhi` 的 GitHub Issues。所有操作使用 `gh` CLI，并从本地 `origin` 推断仓库。

## Conventions

- 创建：`gh issue create --title "..." --body-file "..."`
- 阅读：`gh issue view <number> --comments`
- 列表：`gh issue list --state open --json number,title,body,labels,comments`
- 评论：`gh issue comment <number> --body "..."`
- 标签：`gh issue edit <number> --add-label "..."` 或 `--remove-label "..."`
- 关闭：`gh issue close <number> --comment "..."`
- 当 skill 要求“publish to the issue tracker”时，创建 GitHub Issue。
- 当 skill 要求读取 ticket 时，读取完整 issue body、comments 和 labels。

## Pull requests as a triage surface

**PRs as a request surface: no.**

PR 不作为需求入口；规格和 tickets 统一使用 Issues。

## Blocking relationships

优先使用 GitHub 原生 issue dependencies 表达 `blocked by`。如果当前仓库无法使用原生依赖，则在 issue body 顶部写入：

`Blocked by: #<number>, #<number>`

只有所有 blocker 均已关闭的 ticket 才进入实施 frontier。
