# Unattended Control Plane Design — LearnMind-English

> Agent-neutral 多 Agent 无人值守控制平面设计

## 一、设计原则

本方案以**任何符合规范的 Agent Runner + Reviewer Agent** 为目标平台，主要支持：

1. **OpenCode**
2. **Antigravity**
3. **其他 Agent 通过 Adapter 接入**

Claude Code 仅作为可选兼容层。

---

## 二、四层职责边界

### 2.1 GitHub main — 代码与内容权威

- 唯一保存实施代码、契约、决策记录正文。
- Pull Request 是合并变更的唯一合法入口。
- main 分支的 SHA 是事实唯一来源（source of truth）。

### 2.2 Linear — 规划与状态投影

Linear **不是实施授权的来源**，仅承担：

- Issue 列表与编号
- 状态分类（Triage / In Progress / Blocked / Done）
- 依赖关系
- 简短规划摘要

Linear **不保存**：

- 实施指令正文（见 §2.3）
- 决策记录正文
- 授权记录

**Linear 状态变更不等于实施授权。**

### 2.3 Agent Relay / Unattended Control Plane — 可重建的运行时投影

职责：

- 唤醒与轮询调度
- 状态投影（读 Linear、读 main、读本地证据）
- 消息传递（Builder ↔ Reviewer）
- 等待与重试（带诊断）
- 证据记录（写到磁盘，可重建）
- 触发下一轮但不替任何主体做授权决定

**本质：Agent Relay 是随时可重建的运行时投影，不是项目权威。**

可重建意味着：

- 删除本地 `.agent-bridge/` 不会丢失项目代码或 Linear issue。
- 重启 Agent Runner 不需要重做 Linear 工作。
- Control Plane 任何崩溃都不能阻塞 main 上的真相。

### 2.4 Product Owner — 唯一授权主体

**Product Owner 是唯一可以授权实施、创建 PR、合并、部署的主体。**

授权规则：

- 授权必须来自独立的、明确的结构化授权记录（见 §四）。
- 不得从 Reviewer Agent 的自然语言回复中推断权限。
- 不得从 Linear 状态推断权限。
- 不得从定时器触发推断权限。
- 不得从 CI 绿灯推断权限。
- 不得从 Agent Runner 自报"完成"推断权限。

---

## 三、什么是 NOT 授权

下表列出**任何**容易被误认为授权的信号，明确它们都不产生权限：

| 信号 | 是否授权 | 理由 |
|------|---------|------|
| 定时器触发轮询 | ❌ | 仅表示时间到了，不含主体意图 |
| Reviewer Agent 回复 `PASS` | ❌ | 仅是审核意见，不是授权 |
| Reviewer Agent 回复 `merge` / `合并` / `authorize merge` | ❌ | Reviewer 不具备授权能力，禁止基于关键词授权 |
| Linear issue 状态变 `Done` | ❌ | Linear 不保存授权正文 |
| CI 流水线绿灯 | ❌ | CI 不具备决策能力 |
| Agent Runner 自报"任务完成" | ❌ | 自报 ≠ 真实完成，无证据视为未完成 |
| Product Owner 在聊天中口头同意 | ❌ | 必须落到 §四 的结构化授权记录 |
| 任何自然语言中提到"开 PR" | ❌ | 禁止从自然语言推断权限 |

---

## 四、Product Owner Authorization — 结构化授权记录

Product Owner 的所有授权必须落到一份 JSON 文件，签名或人工放置均可。最低字段：

```json
{
  "schema_version": "owner_authorization_v1",
  "authorization_id": "unique-id",
  "authorization_type": "IMPLEMENTATION | PR_CREATE | READY | MERGE | DEPLOY",
  "repository": "owner/repository",
  "issue_id": "LEA-xx",
  "pr_number": 221,
  "exact_head_sha": "full-40-character-sha",
  "exact_base_sha": "full-40-character-sha",
  "allowed_scope": [
    "exact/file/path"
  ],
  "allowed_operations": [
    "edit",
    "commit",
    "push"
  ],
  "merge_method": null,
  "issued_by": "Product Owner",
  "issued_at": "ISO-8601 timestamp"
}
```

字段约束：

- `exact_head_sha` 与 `exact_base_sha` 必须是完整 40 字符 SHA，**禁止缩写**。
- `allowed_scope` 必须列出确切路径，**禁止通配符或目录别名**。
- `allowed_operations` 必须是显式操作列表，不是描述。
- `merge_method` 留 `null` 时表示"等待 owner 在 gh PR 页面手工合并"。
- 没有此记录 → Agent Runner 不得执行任何 `IMPLEMENTATION` / `PR_CREATE` / `MERGE` / `DEPLOY` 操作。

存储位置：

- `.agent-bridge/owner-authorizations/<authorization_id>.json`（默认）
- 或 Product Owner 指定的任意受控位置

---

## 五、Reviewer Agent 输出集

Reviewer Agent 只能输出以下结构化审核结果（**均不产生任何授权**）：

| 结果 | 含义 | 后续动作 |
|------|------|---------|
| `PASS` | 审核通过 | 等待 Architect Review 与 Product Owner 决定下一步 |
| `CHANGES_REQUESTED` | 需要变更 | Builder Agent 提取变更清单 → 修复 → 重提 |
| `BLOCKED` | 阻塞无法推进 | 等待 Product Owner 决策 |
| `NEEDS_OWNER_DECISION` | 需要 owner 裁决 | 等待 Product Owner 决策 |
| `WAIT` | 当前无需评审 | 保持空闲轮询 |
| `PARSE_ERROR` | 解析失败 | 重试或通知 Product Owner |

**任何 `PASS` 都不自动触发合并、部署或开 PR。**

`PASS` 是 review verdict，不是 execution permit。

---

## 六、架构与执行

### 6.1 组件划分

```
┌─────────────────────────────────────────────────────┐
│  Product Owner (人)                                  │
│  ↓ 写结构化 owner-authorization                       │
├─────────────────────────────────────────────────────┤
│  Agent Relay / Unattended Control Plane              │
│  · 唤醒与轮询                                         │
│  · 状态投影（Linear / GitHub main / 本地证据）          │
│  · 消息传递（Builder ↔ Reviewer）                      │
│  · 等待 / 重试 / 诊断                                  │
│  · 证据记录（可重建）                                   │
├─────────────────────────────────────────────────────┤
│  Builder Agent                                       │
│  · 实现变更                                           │
│  · 跑验证                                             │
│  · 汇报证据（commit SHA / 测试结果）                   │
│  · 必须检查 owner-authorization 后才执行授权动作       │
├─────────────────────────────────────────────────────┤
│  Reviewer Agent                                      │
│  · 接收汇报                                           │
│  · 输出 §五 中的结构化审核结果                          │
│  · 不输出任何授权决策                                   │
├─────────────────────────────────────────────────────┤
│  Architect Review (可选)                              │
│  · 系统级架构决策                                      │
│  · 仍不输出合并授权                                    │
└─────────────────────────────────────────────────────┘
```

### 6.2 Agent Runner Adapter 接口

Adapter 必须实现最小接口契约（任何宿主 Agent 都能满足）：

| 命令 | 用途 |
|------|------|
| `agent_run --task <task-id>` | 跑一轮受限任务 |
| `agent_report --task <task-id>` | 生成结构化汇报（含 SHA、变更、测试） |
| `agent_state` | 输出当前目标状态摘要 |
| `agent_check_owner_authorization <authorization_id>` | 校验授权存在且未过期 |

提供现成 Adapter：

- `OpenCode Adapter`（主目标平台）
- `Antigravity Adapter`（主目标平台）
- `Optional Claude Code Adapter`（可选，向后兼容）
- 自定义 Adapter 接入点

### 6.3 Agent Relay 提供的工具（运行时，非实现文档）

仅描述能力边界，不在本 PR 中实现：

| 工具 | 职责 |
|------|------|
| `relay send` | 将 Builder Agent 汇报送到 Reviewer Agent |
| `relay wait` | 等待 Reviewer 回复（带超时、mainLen 轮询、诊断） |
| `relay read` | 读取 Reviewer 最新回复 |
| `relay status` | 检查 Reviewer 状态（busy/idle/timeout） |
| `parse review_reply` | 把 Reviewer 回复解析为 §五 的结构化结果 |
| `loop run --goal <goal-id> --max-rounds N` | 串起汇报→等待→解析→判断下一步 |

---

## 七、当前痛点（从实践得出）

1. **relay.py --send 几乎永远 timeout**：Reviewer Agent 回复常需 60-180s，但 `--timeout` 是硬上限
2. **发送 + 等待是两步**：冗余且易出错
3. **没有解析层**：Reviewer 回复全文塞进上下文，需要逐行识别 `PASS`/`BLOCKED`
4. **汇报手写**：每次手工拼格式，容易遗漏 SHA / ahead-behind / changed files 等字段
5. **没有自动循环**：成功 → 汇报 → FAIL → 修复 → 再汇报，每一轮都需手动触发
6. **relay 内部等待逻辑不可靠**：DOM 按钮检测易受页面结构变化影响

---

## 八、优化目标

**一条命令完成「汇报 → 等 → 读 → 解析 → 写入 evidence」，决策权仍归 Product Owner。**

---

## 九、设计阶段

### 阶段 1：合并发送 + 等待

新建 `auto_relay.py`：

```
python3 auto_relay.py --send --wait-timeout 600
```

- 内部调用 relay 的发送逻辑（粘贴+发送）
- 发送后**立即用 mainLen 轮询**，不再依赖 DOM 按钮
- 检测完成条件：连续 N 次 mainLen 相同 且 无「停止生成」文本
- 完成后写出 review_reply.txt，exit 0
- 超时则 exit 1 + 写出最后 partial 文本

### 阶段 2：结构化汇报模板

创建 `report_template.py`，Builder Agent 只需提供数据，自动生成 Reviewer 格式报告：

```python
data = {
    'title': 'PR-7 P0 修复 — 幂等键残留',
    'head_sha': 'ecd4d76...full40',
    'parent': '419d63f...full40',
    'branch': 'worktree/pr-7-migration-rpcs',
    'ahead': 2, 'behind': 0,
    'changed_files': ['0016_...sql', 'verify_pr7_...py'],
    'verifier': {'label': 'PR-7', 'run1': '93/0', 'run2': '93/0'},
    'regression': {'PR-5': '200/2', 'PR-4': '138/4'},
    'notes': '未创建 PR、未合并...',
}
```

输出标准格式到 `report.md` + stdout，确保不遗漏汇报字段。

### 阶段 3：Reviewer 回复解析

新建 `parse_review_reply.py`，读取 `review_reply.txt`，识别 §五 中的结构化结果：

| 结果 | 动作 |
|------|------|
| `PASS` | 写 evidence，等待 Architect Review + Product Owner 决策 |
| `CHANGES_REQUESTED` | 提取变更清单 |
| `BLOCKED` | 提取 BLOCKED 原因 |
| `NEEDS_OWNER_DECISION` | 通知 Product Owner |
| `WAIT` | 进入空闲轮询 |
| `PARSE_ERROR` | 重试或通知 Product Owner |

输出结构化 evidence JSON，写入磁盘供下一轮读取。

### 阶段 4：自动循环引擎

新建 `auto_loop.py`：

```
python3 auto_loop.py --goal <goal-id> --max-rounds 10
```

循环逻辑：

```
while round < max_rounds:
    1. 自动生成汇报（根据 git 状态 + 测试结果）
    2. auto_relay.py --send --wait → review_reply.txt
    3. parse_review_reply.py → evidence JSON
    4. 根据 evidence 决策：
       - "PASS"                          → 写 evidence，break，等待 Product Owner
       - "CHANGES_REQUESTED"             → 提取变更清单 → 修复 → commit/push → continue
       - "BLOCKED"                       → 通知 Product Owner，break
       - "NEEDS_OWNER_DECISION"          → 通知 Product Owner，break
       - "WAIT"                          → 进入空闲轮询模式
    5. 写 evidence log
    6. 无新任务 → 进入空闲轮询模式
```

**重要：循环引擎只执行以下操作**

- ✅ 写 evidence（到磁盘）
- ✅ 切换 worktree
- ✅ git commit / push（修复循环）
- ✅ 跑测试 / verifier
- ✅ 发送汇报给 Reviewer Agent
- ✅ 通知 Product Owner（结构化）

**禁止执行：**

- ❌ 合并到 main（需 §四 的 MERGE 授权）
- ❌ 部署到生产（需 §四 的 DEPLOY 授权）
- ❌ 操作远程 Supabase（需 §四 的 IMPLEMENTATION 授权且 scope 允许）
- ❌ 创建 PR（需 §四 的 PR_CREATE 授权）
- ❌ 任何基于关键词推断出来的"授权"

### 阶段 4.5：空闲轮询模式

当 auto_loop 进入空闲状态：

```
IDLE → 等 10 分钟 → 主动发送询问消息给 Reviewer Agent → 等待回复 → 解析 evidence
                                                  ↓
                                          Reviewer 未回复（timeout/离线）
                                                  ↓
                                          诊断排查 → 修复 → 再重试
                                          ↓
                                   仍失败 → 通知 Product Owner
```

**Reviewer 未回复时的诊断排查**（不直接无脑重试）：

| 排查项 | 检测方式 | 自动修复 |
|--------|----------|----------|
| Relay 进程存活 | 健康检查端点 | 重启 Relay |
| Reviewer 会话连接 | 探测会话 URL | 重连 |
| 页面存活 | 检查 tab URL 仍含 Reviewer 会话标识 | reload |
| 页面弹层/错误覆盖 | 检测常见错误弹层 | 关闭/reload |
| 消息送达确认 | 检查汇报片段是否在 Reviewer 会话中出现 | 未送达则重发 |
| Reviewer 长时间思考 | mainLen > 0 且持续变化 | 延长等待（非故障） |
| 登录态过期 | 页面出现登录/验证界面 | 通知 Product Owner |

- 重试策略：诊断+修复后重发，最多 3 次修复循环，仍失败通知 Product Owner
- 退出条件：Reviewer 回复 `WAIT`、收到 Product Owner 结构化授权、Product Owner 手工中断

### 阶段 5：独立工作区隔离

- 每个目标在独立 git worktree 中执行
- auto_loop 自动管理 worktree 创建/切换
- 不同目标的自动化互不干扰

---

## 十、实现优先级

| 优先级 | 阶段 | 理由 |
|--------|------|------|
| **P0** | 阶段 1: 合并发送+等待 | 消除最高频的手动两步操作 |
| **P0** | 阶段 2: 结构化汇报模板 | 减少手写误差 |
| **P1** | 阶段 3: Reviewer 回复解析 | 加速决策但授权权仍归 Product Owner |
| **P1** | 阶段 4: 自动循环引擎 | 实现"发了就等、失败就修、自动推进" |
| **P1** | 阶段 4.5: 空闲轮询 + 诊断 | 避免 Reviewer 不回复时无限重试 |
| **P2** | 阶段 5: 工作区隔离 | 多目标并行时有用 |

---

## 十一、文件规划（仅命名约定，不在本 PR 实现）

```
.agent-bridge/
├── relay.py                 # 现有：发送 + 简单等待（保留）
├── auto_relay.py            # 新：发送 + mainLen 轮询等待 + 超时处理
├── report_template.py       # 新：结构化汇报生成
├── parse_review_reply.py    # 新：Reviewer 回复解析为 evidence JSON
├── auto_loop.py             # 新：自动循环引擎
├── report.md                # 新：Builder Agent 汇报
├── review_reply.txt         # 新：Reviewer Agent 回复全文
├── evidence.json            # 新：结构化 evidence（含 review verdict）
├── loop-state.json          # 新：循环状态持久化
├── owner-authorizations/    # 新：Product Owner 结构化授权记录
└── loop-log/                # 新：每轮日志
```

---

## 十二、不做的（保持现有实现不动）

- 不碰现有 relay.py 的发送逻辑（已验证可靠）
- 不引入新的运行时依赖
- 不创建 CI / Hook / 定时任务文件
- 不修改 GitHub Actions
- 不创建任何远程状态变更
- 不实现 §六 中描述的工具——本 PR 仅文档，不含代码

---

## 十三、与 Linear 的关系

Linear 在本方案中只承担：

- Issue 列表与编号（`LEA-NN` 格式）
- 状态分类
- 依赖关系

Linear **不**：

- 保存实施指令
- 保存授权记录
- 充当 Product Owner 授权的来源
- 充当 Reviewer Agent 输出正文

任何 Linear 操作必须用 §四 的结构化授权记录来触发，**不允许** Agent Runner 仅基于 Linear 状态变更执行合并或部署。