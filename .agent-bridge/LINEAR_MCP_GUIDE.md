# Linear MCP 使用指南 — LearnMind-English

> Agent-neutral Linear 操作参考

你是 LearnMind-English 项目的 **Builder Agent**，通过 Linear MCP 管理 issue。Linear **不**保存授权记录，**不**充当 Product Owner 授权的来源。

---

## 一、配置信息

Linear MCP 通过 `mcp-server-linear`（npx）接入，Token 在宿主环境的 MCP 配置中：

```json
{
  "linear": {
    "command": "npx",
    "args": ["-y", "mcp-server-linear"],
    "env": {
      "LINEAR_ACCESS_TOKEN": "lin_api_..."
    }
  }
}
```

支持宿主环境：

- Claude Desktop（已配置）
- 其他 MCP 兼容 Agent（参考 `mcp-server-linear` 接入文档）

---

## 二、Linear 在本项目中的定位

| Linear 承担 | Linear 不承担 |
|------------|-------------|
| Issue 列表与编号（`LEA-NN`） | 实施指令正文 |
| 状态分类（Triage / In Progress / Blocked / Done） | 授权记录 |
| 依赖关系 | 合并 / 部署 / 创建 PR 决策 |
| 简短规划摘要 | Reviewer Agent 输出正文 |

**Linear 状态变更不等于实施授权。** 任何合并 / 部署 / 开 PR 必须由 Product Owner 出具结构化授权记录（见主方案 §四）。

---

## 三、常用操作

### 1. 查看当前用户和团队

```
mcp__linear__get_viewer        # 当前登录用户信息
mcp__linear__get_teams         # 项目中的团队列表
```

### 2. Issue 操作

```
# 搜索 issue
mcp__linear__search_issues --query "decision tool PR-8" --team "LEA"

# 获取单个 issue 详情（identifier 格式如 LEA-29）
mcp__linear__get_issue --identifier "LEA-29"

# 创建 issue
mcp__linear__create_issue
  --team "LEA"
  --title "PR-8: 前端基线导入"
  --description "..."
  --priority "High"

# 更新 issue 状态
mcp__linear__update_issue
  --identifier "LEA-29"
  --state "In Progress"

# 添加评论
mcp__linear__add_comment
  --identifier "LEA-29"
  --body "..."
```

### 3. 项目和状态

```
mcp__linear__get_projects
mcp__linear__get_workflow_states --team "LEA"
```

---

## 四、LearnMind-English 项目对应关系

| Linear 团队 | 项目缩写 |
|------------|---------|
| LearnMind-English | LEA |

常见 issue 编号示例：`LEA-29`、`LEA-30`、`LEA-32` 等。

---

## 五、典型工作流

```
1. 接到新任务
   → search_issues 确认是否已有对应 issue
   → 若无则 create_issue（仅记录规划，不构成实施授权）

2. 开始工作
   → update_issue(状态 → "In Progress")

3. 阶段性汇报
   → add_comment(更新进展)

4. 遇到阻塞
   → add_comment(标注 BLOCKED + 原因)
   → update_issue(状态 → "Blocked")

5. 完成
   → add_comment(最终汇报: HEAD SHA, 变更列表, 测试结果)
   → update_issue(状态 → "Done")
   → 写 evidence 到本地磁盘（不是 Linear）
```

---

## 六、注意

- issue identifier 格式为 `TEAM-NUMBER`（如 `LEA-29`），不是 UUID
- 搜索时用 `--query` 做关键词搜索，用 `--team` 限定团队
- 更新状态前先用 `get_workflow_states` 查出该团队的有效状态名
- **不要在 issue 里放 token、密钥、生产 URL**
- **不要在 issue 评论里写授权决策**——授权必须落到 `.agent-bridge/owner-authorizations/*.json`
- Linear 状态变 `Done` **不**意味着可以合并 / 部署 / 开 PR，仍需 Product Owner 出具结构化授权

---

## 七、与其他系统的关系

```
Product Owner (人)
  ↓ 写结构化授权 JSON
  .agent-bridge/owner-authorizations/*.json  ← 唯一授权来源
  ↓ 触发
  Agent Runner (Builder Agent)               ← 仅当读到授权才执行授权操作
  ↓ 状态投影
  Linear (issue 列表 / 状态)                  ← 仅作规划投影
```

Linear 改动只是状态投影的一部分；任何实际操作必须回到授权文件来校验。