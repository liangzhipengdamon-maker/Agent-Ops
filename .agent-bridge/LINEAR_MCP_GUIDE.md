# Linear MCP 使用指南 — AgentOps

> Agent-neutral Linear 操作参考

你是 **AgentOps** 项目的 **Builder Agent**，通过 Linear 管理 issue。Linear **不**保存授权记录，**不**充当 Product Owner 授权的来源。

---

## 一、配置信息

Linear 通过具备 Linear API 能力的执行通道（MCP、HTTP API、CLI 等）接入。Token 在宿主环境的配置中，**不得提交到仓库**：

```
LINEAR_ACCESS_TOKEN: <由宿主环境提供，此处仅为占位>
```

> ⚠️ 不要将真实 Token 写入任何仓库文件。`lin_api_...` 仅为格式占位符示例。

支持的接入方式（capability-based，不绑定单一实现）：

- 任何具备 Linear MCP 能力的 Agent 环境
- 任何可调用 Linear REST/GraphQL API 的执行通道
- 参考 `linear` 官方文档接入

---

## 二、Linear 在 AgentOps 中的定位

| Linear 承担 | Linear 不承担 |
|------------|-------------|
| Issue 列表与编号（`AGE-NN`） | 实施指令正文 |
| 状态分类（Triage / In Progress / Blocked / Done） | 授权记录 |
| 依赖关系 | 合并 / 部署 / 创建 PR 决策 |
| 简短规划摘要 | Reviewer Agent 输出正文 |
| 授权摘要或证据链接（可选，辅助追踪） | 原始权限来源 |

**Linear 状态变更不等于实施授权。** 任何合并 / 部署 / 开 PR / Ready 必须由 Product Owner 出具结构化授权记录（见主方案 §三）。

**Linear Done 不等于 Merge。**

**Linear MCP 不是唯一执行通道。** 根据宿主环境能力选择合适的通道，授权要求不因通道而改变。

---

## 三、常用操作

以下为 capability-based 描述，具体调用方式依宿主环境和接入实现而定：

### 1. 查看当前用户和团队

```
get_viewer        # 当前登录用户信息
get_teams         # 项目中的团队列表（AgentOps Team Key: AGE）
```

### 2. Issue 操作

```
# 搜索 issue
search_issues --query "<关键词>" --team "AGE"

# 获取单个 issue 详情（identifier 格式如 AGE-1）
get_issue --identifier "AGE-1"

# 创建 issue
create_issue
  --team "AGE"
  --title "<标题>"
  --description "<描述>"
  --priority "High"

# 更新 issue 状态
update_issue
  --identifier "AGE-1"
  --state "In Progress"

# 添加评论（汇报进展、记录证据链接）
add_comment
  --identifier "AGE-1"
  --body "<内容>"
```

### 3. 项目和状态

```
get_projects
get_workflow_states --team "AGE"
```

---

## 四、AgentOps 团队对应关系

| Linear 团队 | 项目缩写 |
|------------|---------|
| AgentOps | AGE |

Issue 编号示例：`AGE-1`、`AGE-2`、`AGE-3` 等。

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
   → add_comment(最终汇报: HEAD SHA, 变更列表, 测试结果, 证据链接)
   → 写 evidence 到本地磁盘（不是 Linear）
   → update_issue(状态 → "Done") 仅在完成条件已满足并获得相应授权时执行
```

> **注意**：不允许 Agent 自行把 Issue 状态改为 `Done`，除非 Issue 的完成条件已满足并获得相应授权。

---

## 六、注意

- issue identifier 格式为 `TEAM-NUMBER`（如 `AGE-1`），不是 UUID
- 搜索时用关键词搜索，并限定团队 `AGE`
- 更新状态前先查出该团队的有效状态名
- **不要在 issue 里放 token、密钥、生产 URL、私人会话 URL、本地绝对路径**
- **不要在 issue 评论里写授权决策**——授权必须落到 `.agent-bridge/owner-authorizations/*.json`
- Linear 状态变 `Done` **不**意味着可以合并 / 部署 / 开 PR，仍需 Product Owner 出具结构化授权
- Linear 中可以记录授权摘要或证据链接，但不能成为原始权限来源

---

## 七、与其他系统的关系

```
Product Owner (人)
  ↓ 明确指令 → 转换为结构化授权绑定
  .agent-bridge/owner-authorizations/*.json  ← 运行时校验的授权投影
  ↓ 触发（仅在授权范围内）
  Agent Runner (Builder Agent)               ← 仅当读到有效授权绑定才执行授权操作
  ↓ 状态投影
  Linear (issue 列表 / 状态)                  ← 仅作规划与状态投影

执行通道（MCP / gh CLI / git / HTTP API）    ← 通道不决定授权，授权决定通道是否可用
```

Linear 改动只是状态投影的一部分；任何实际授权操作必须通过结构化授权绑定校验后才能执行。