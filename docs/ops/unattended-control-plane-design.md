# Unattended Control Plane Design — AgentOps

> Agent-neutral 多 Agent 无人值守控制平面设计

AgentOps 是独立仓库和独立控制平面。本文件仅适用于 `liangzhipengdamon-maker/Agent-Ops` 项目范围。

---

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

- Issue 列表与编号（`AGE-NN` 格式）
- 状态分类（Triage / In Progress / Blocked / Done）
- 依赖关系
- 简短规划摘要
- 授权摘要或证据链接（可选，辅助追踪）

Linear **不保存**：

- 实施指令正文（见 §2.3）
- 决策记录正文
- 原始授权记录

**Linear 状态变更不等于实施授权。**

**Linear Done 不等于 Merge。**

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

### 2.4 Product Owner — 权限主体

**Product Owner 是权限主体，可以授权实施、创建 PR、Ready、合并、部署。**

Product Owner 的明确指令本身就是权限来源。系统需将其**可信捕获**并转换为结构化授权投影（见 §四），以此作为执行门禁。

授权规则：

- 授权来源必须是 Product Owner 的明确指令，经结构化绑定后方可执行。
- 不得从 Reviewer Agent 的自然语言回复中推断权限。
- 不得从 Linear 状态推断权限。
- 不得从定时器触发推断权限。
- 不得从 CI 绿灯推断权限。
- 不得从 transport success（push 成功）推断权限。
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
| transport success（push 成功） | ❌ | 执行通道成功不等于授权 |
| Agent Runner 自报"任务完成" | ❌ | 自报 ≠ 真实完成，无证据视为未完成 |
| 任何自然语言中提到"开 PR" | ❌ | 禁止从自然语言推断权限 |

---

## 四、Product Owner Authorization — 结构化授权绑定

Product Owner 的授权必须绑定到一份结构化记录，经校验后才能执行对应操作。最低字段：

```json
{
  "schema_version": "owner_authorization_v1",
  "authorization_id": "unique-id",
  "request_id": "immutable-request-id",
  "task_id": "AGE-1-or-runtime-task-id",
  "authorization_type": "IMPLEMENTATION | PR_CREATE | READY | MERGE | DEPLOY | FORCE_PUSH",
  "authorization_status": "PENDING | CONSUMED | REVOKED | EXPIRED",
  "repository": "owner/repository",
  "issue_id": "AGE-xx",
  "pr_number": null,
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
  "issued_at": "ISO-8601 timestamp",
  "source_evidence_ref": "immutable-reference-to-owner-instruction",
  "expires_at": "ISO-8601 timestamp or null",
  "consumed_at": "ISO-8601 timestamp or null",
  "execution_result": {
    "status": "SUCCEEDED | FAILED | DRIFTED | CANCELLED",
    "completed_at": null,
    "result_sha": null,
    "evidence_ref": null
  }
}
```

字段约束（执行门禁）：

- `authorization_id`：这份授权记录自身的唯一 ID。
- `request_id`：原始 Product Owner 授权请求的不可变关联 ID。
- `task_id`：被授权执行的具体任务或运行单元。
- `issue_id`：Linear 规划对象，不可替代 `task_id`，三者不得相互推断。

- `exact_head_sha` 与 `exact_base_sha` 必须是完整 40 字符 SHA，**禁止缩写**。
- 必须是一次性消费（成功、失败或远程状态漂移后不得复用）。
- 必须支持 Owner 撤销以及过期失效（`expires_at`）。
- `allowed_scope` 必须列出确切路径，**禁止通配符或目录别名**。
- `allowed_operations` 必须是显式操作列表，不是描述。
- `merge_method` 留 `null` 时表示"等待 owner 在 GitHub PR 页面手工合并"。
- 投影不完整或不匹配实时远程状态 → Agent Runner 不得执行任何 `IMPLEMENTATION` / `PR_CREATE` / `READY` / `MERGE` / `DEPLOY` 操作。

存储位置：

- `.agent-bridge/owner-authorizations/<authorization_id>.json`（默认）
- 或 Product Owner 指定的任意受控位置

**request_id、task_id、base SHA、head SHA、allowed paths、allowed operations** 均为授权绑定的必要组成，缺一不可。

---

## 五、Reviewer Agent 输出集

Reviewer Agent 只能输出以下结构化审核结果（**均不产生任何授权**）：

| 结果 | 含义 | 后续动作 |
|------|------|---------|
| `PASS` | 审核通过 | 等待 Product Owner 决定下一步 |
| `CHANGES_REQUESTED` | 需要变更 | Builder Agent 提取变更清单 → 修复 → 重提 |
| `BLOCKED` | 阻塞无法推进 | 等待 Product Owner 决策 |
| `NEEDS_OWNER_DECISION` | 需要 owner 裁决 | 等待 Product Owner 决策 |
| `WAIT` | 当前无需评审 | 保持空闲等待，不得主动询问或编造下一任务 |
| `PARSE_ERROR` | 解析失败 | 重试或通知 Product Owner |

**任何 `PASS` 都不自动触发 Ready、合并、部署或开 PR。**

`PASS` 是 review verdict，不是 execution permit。

---

## 六、架构与执行

### 6.1 组件划分

```
┌─────────────────────────────────────────────────────┐
│  Product Owner (人) — 权限主体                        │
│  ↓ 明确指令 → 转换为结构化授权绑定                     │
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
│  · 必须校验授权绑定后才执行授权动作                     │
│  · 每次唤醒仅执行一个有界动作（one bounded action）     │
├─────────────────────────────────────────────────────┤
│  Reviewer Agent                                      │
│  · 接收汇报                                           │
│  · 输出 §五 中的结构化审核结果                          │
│  · 不输出任何授权决策                                   │
└─────────────────────────────────────────────────────┘
```

### 6.2 执行通道

MCP、gh CLI、git push、HTTP API 均为**执行通道**，不是授权来源。

- 选择哪个通道不改变授权要求
- 不绑定单一通道实现，根据宿主环境能力选择合适通道
- 任何通道的 transport success 都不等于授权

### 6.3 Agent Runner Adapter 接口

Adapter 必须实现最小接口契约（任何宿主 Agent 都能满足）：

| 命令 | 用途 |
|------|------|
| `agent_run --task <task-id>` | 跑一轮受限任务 |
| `agent_report --task <task-id>` | 生成结构化汇报（含 SHA、变更、测试） |
| `agent_state` | 输出当前目标状态摘要 |
| `agent_check_owner_authorization <authorization_id>` | 校验授权绑定存在且未过期 |

提供现成 Adapter：

- `OpenCode Adapter`（主目标平台，拟议接口）
- `Antigravity Adapter`（主目标平台，拟议接口）
- `Optional Claude Code Adapter`（可选，向后兼容）
- 自定义 Adapter 接入点

### 6.4 Agent Relay 提供的工具（运行时，非实现文档）

仅描述能力边界，不在 AGE-1 中实现，为后续拟议契约：

| 工具 | 职责 |
|------|------|
| `relay send` | 将 Builder Agent 汇报送到 Reviewer Agent |
| `relay wait` | 等待 Reviewer 回复（带超时、轮询、诊断） |
| `relay read` | 读取 Reviewer 最新回复 |
| `relay status` | 检查 Reviewer 状态（busy/idle/timeout） |
| `parse review_reply` | 把 Reviewer 回复解析为 §五 的结构化结果 |
| `loop run --goal <goal-id> --max-rounds N` | 串起汇报→等待→解析→判断下一步 |

---

## 七、受保护仓库与操作范围

以下仓库默认受保护，AgentOps 默认无操作权限：

| 仓库 | 保护级别 |
|------|---------|
| `liangzhipengdamon-maker/LearnMind-English` | 默认受保护，禁止操作 |
| `liangzhipengdamon-maker/AI-Investment-Lab` | 默认受保护，禁止操作 |
| 任何生产 Supabase 资源 | 默认受保护，禁止操作 |

AgentOps 只能在任务授权明确包含目标仓库时，才能操作其他项目。授权绑定中的 `repository` 字段必须明确指定目标仓库。

---

## 八、高风险动作单独授权

以下每项操作都需要独立的、单独的 Product Owner 授权绑定：

| 操作 | 授权类型 | 说明 |
|------|---------|------|
| PR Ready for Review | `READY` | 不得基于 review PASS 自动触发 |
| Merge to main | `MERGE` | 不得基于 CI 绿灯、review PASS 自动触发 |
| Deploy to production | `DEPLOY` | 不得基于 merge 自动触发 |
| force push | `FORCE_PUSH` | 默认禁止；只有 Product Owner 针对目标仓库、目标分支、exact SHA 和操作范围单独明确授权时才可执行 |
| 直接提交到 main | 禁止 | 无论任何情况均禁止 |
| main 历史重写 | 需明确授权 | 同 force push 规则 |
| 访问生产资源 | `IMPLEMENTATION`（scope 限定） | 需明确 scope |

**Fail-closed 原则**：授权绑定缺失或不完整时，默认拒绝执行，不得推断或降级执行。

---

## 九、当前痛点（从实践得出）

1. **relay 发送等待常 timeout**：Reviewer Agent 回复常需 60-180s
2. **发送 + 等待是两步**：冗余且易出错
3. **没有解析层**：Reviewer 回复全文塞进上下文，需逐行识别结构化结果
4. **汇报手写**：每次手工拼格式，容易遗漏 SHA / ahead-behind / changed files 等字段
5. **没有自动循环**：成功 → 汇报 → FAIL → 修复 → 再汇报，每一轮都需手动触发
6. **无诊断层**：Reviewer 不回复时不知原因

---

## 十、优化目标

**一条命令完成「汇报 → 等 → 读 → 解析 → 写入 evidence」，决策权仍归 Product Owner。**

---

## 十一、设计阶段

### 阶段 1：合并发送 + 等待

新建 `auto_relay.py`（拟议）：

```bash
python3 auto_relay.py --send --wait-timeout 600
```

- 内部调用 relay 的发送逻辑
- 发送后立即用轮询等待，不依赖 DOM 按钮
- 检测完成条件：连续 N 次响应相同且无"停止生成"文本
- 完成后写出 review_reply.txt，exit 0
- 超时则 exit 1 + 写出最后 partial 文本

### 阶段 2：结构化汇报模板

创建 `report_template.py`，Builder Agent 只需提供数据，自动生成结构化报告：

```python
data = {
    'title': 'AGE-1 文档适配',
    'head_sha': '<full-40-character-sha>',
    'parent': '<full-40-character-sha>',
    'branch': 'docs/unattended-control-plane-design',
    'ahead': 1, 'behind': 0,
    'changed_files': [
        '.agent-bridge/AGENT_RUNNER_PROMPT.md',
        '.agent-bridge/LINEAR_MCP_GUIDE.md',
        'docs/ops/unattended-control-plane-design.md'
    ],
    'notes': '未创建 PR、未合并、未部署...',
}
```

输出标准格式到 `report.md` + stdout，确保不遗漏汇报字段。

### 阶段 3：Reviewer 回复解析

新建 `parse_review_reply.py`，读取 `review_reply.txt`，识别 §五 中的结构化结果：

| 结果 | 动作 |
|------|------|
| `PASS` | 写 evidence，等待 Product Owner 决策 |
| `CHANGES_REQUESTED` | 提取变更清单 |
| `BLOCKED` | 提取 BLOCKED 原因 |
| `NEEDS_OWNER_DECISION` | 通知 Product Owner |
| `WAIT` | 进入空闲等待（不主动询问） |
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
       - "WAIT"                          → 进入空闲等待模式
    5. 写 evidence log
    6. 无新任务 → 进入空闲等待模式
```

**重要：循环引擎只执行以下操作**

- ✅ 写 evidence（到磁盘）
- ✅ 切换 worktree
- ✅ git commit / push（在授权范围内）
- ✅ 跑测试 / verifier
- ✅ 发送汇报给 Reviewer Agent
- ✅ 通知 Product Owner（结构化）

**禁止执行（需独立授权绑定）：**

- ❌ Ready PR（需 READY 授权）
- ❌ 合并到 main（需 MERGE 授权）
- ❌ 部署到生产（需 DEPLOY 授权）
- ❌ 创建 PR（需 PR_CREATE 授权）
- ❌ 任何基于关键词推断出来的"授权"
- ❌ force push（默认禁止，需单独明确授权）

### 阶段 4.5：空闲等待模式

当 auto_loop 进入空闲状态：

```
IDLE → 等待外部调度策略指定时间（如 10 分钟，仅为示例） → 仅在调度策略明确要求时向 Reviewer 发送询问
                                  → 等待回复 → 解析 evidence
                                            ↓
                                  Reviewer 未回复（timeout/离线）
                                            ↓
                                  诊断排查 → 修复 → 再重试
                                  ↓
                           仍失败 → 通知 Product Owner
```

**无变化时不调用模型。**

**Reviewer 未回复时的诊断排查**（不直接无脑重试）：

| 排查项 | 检测方式 | 自动修复 |
|--------|----------|----------|
| Relay 进程存活 | 健康检查端点 | 重启 Relay |
| Reviewer 会话连接 | 探测会话 URL | 重连 |
| 消息送达确认 | 检查汇报片段是否在 Reviewer 会话中 | 未送达则重发 |
| Reviewer 长时间思考 | 响应流持续变化 | 延长等待（非故障） |
| 登录态过期 | 页面出现登录/验证界面 | 通知 Product Owner |

- 重试策略：诊断+修复后重发，最多 3 次修复循环，仍失败通知 Product Owner
- 退出条件：Reviewer 回复 `WAIT`、收到 Product Owner 结构化授权、Product Owner 手工中断

### 阶段 5：独立工作区隔离

- 每个目标在独立 git worktree 中执行
- auto_loop 自动管理 worktree 创建/切换
- 不同目标的自动化互不干扰

---

## 十二、实现优先级

| 优先级 | 阶段 | 理由 |
|--------|------|------|
| **P0** | 阶段 1: 合并发送+等待 | 消除最高频的手动两步操作 |
| **P0** | 阶段 2: 结构化汇报模板 | 减少手写误差 |
| **P1** | 阶段 3: Reviewer 回复解析 | 加速决策但授权权仍归 Product Owner |
| **P1** | 阶段 4: 自动循环引擎 | 实现"发了就等、失败就修、自动推进" |
| **P1** | 阶段 4.5: 空闲等待 + 诊断 | 避免 Reviewer 不回复时无限重试 |
| **P2** | 阶段 5: 工作区隔离 | 多目标并行时有用 |

---

## 十三、文件规划（仅命名约定，不在本 PR 实现）

```
.agent-bridge/
├── relay.py                 # 现有：发送 + 简单等待（保留）
├── auto_relay.py            # 新：发送 + 轮询等待 + 超时处理
├── report_template.py       # 新：结构化汇报生成
├── parse_review_reply.py    # 新：Reviewer 回复解析为 evidence JSON
├── auto_loop.py             # 新：自动循环引擎
├── report.md                # 新：Builder Agent 汇报
├── review_reply.txt         # 新：Reviewer Agent 回复全文
├── evidence.json            # 新：结构化 evidence（含 review verdict）
├── loop-state.json          # 新：循环状态持久化（claim/lease/restart recovery）
├── owner-authorizations/    # 新：Product Owner 结构化授权绑定记录
└── loop-log/                # 新：每轮日志
```

---

## 十四、不做的（保持现有实现不动）

- 不碰现有 relay.py 的发送逻辑（已验证可靠）
- 不引入新的运行时依赖
- 不创建 CI / Hook / 定时任务文件
- 不修改 GitHub Actions
- 不创建任何远程状态变更
- 不实现 §六 中描述的工具——本 PR 仅文档，不含代码

---

## 十五、与 Linear 的关系及 Builder/Reviewer 职责

Linear 在本方案中只承担规划和状态投影：

- Issue 列表与编号（`AGE-NN` 格式）
- 状态分类（Triage / In Progress / Blocked / Done 等）
- 依赖关系
- 授权摘要或证据链接（可选，辅助追踪）

Linear **不**：

- 保存实施指令
- 保存原始授权记录
- 充当 Product Owner 授权的来源
- 充当 Reviewer Agent 输出正文

任何实际授权操作必须通过结构化授权绑定校验后才能执行，**不允许** Agent Runner 仅基于 Linear 状态变更执行 Ready、合并或部署。

### 15.1 Builder 默认职责（Linear 生命周期维护）

将 Linear 生命周期管理正式纳入 Builder 的默认职责：

1. **工作认领与创建**：接到新的 AgentOps 工作时，必须先检查是否已有对应 AGE Issue。如果已有，使用现有 Issue，不重复创建；如果没有，在 AgentOps Team 创建新的 AGE Issue，关联正确的 AgentOps Project。
2. **生命周期维护**：Builder 需在整个工作生命周期自行维护 Linear 状态。包括但不限于：
   - 任务开始时标记 In Progress
   - Draft PR 创建后更新 PR URL、exact HEAD 和 CI 状态
   - 更新 Independent Review 状态
   - 遇到阻碍或需要授权时流转至 CHANGES_REQUESTED / BLOCKED / WAITING_PO_AUTH
   - Merge 后回读 GitHub
   - 最终完成时标记为 Done
3. **真相与修正冲突**：GitHub main 始终是 canonical repository truth。当 GitHub 与 Linear 不一致时，以 GitHub 为准；Builder 有责任修正 Linear 以反映 GitHub 的真实状态，**绝对不得反向修改 GitHub 来迁就 Linear**。
4. **禁止自我授权**：Builder 不得通过修改 Linear 状态来给自己生成 Implementation / Ready / Merge / Deploy 等执行权限。

### 15.2 Reviewer 职责（状态校验）

1. 独立审核 GitHub 上的实现代码与逻辑。
2. 同时核验 Linear 是否准确反映 GitHub 当前事实。
3. 如果发现 Linear 状态漂移（drift），要求 Builder 修正；Reviewer 原则上不替 Builder 日常维护 Linear。

### 15.3 到达治理停点的汇报规范

到达治理停点后（如 WAITING_PO_AUTH, BLOCKED），必须：
1. Builder 更新 Linear 到对应管理状态。
2. 使用 Status Report 自动向当前外部 ChatGPT Reviewer 汇报最终状态。
3. STOP。

---

## 十六、安全与隐私约束

**禁止提交到仓库的内容：**

- 真实 Token、Secret、Password
- 私人会话 URL（如 ChatGPT 页面 URL、私人 AI 会话 URL）
- 本地绝对路径
- 生产凭据
- Supabase 生产访问信息

**禁止的操作模式：**

- 无授权自动 push 循环（需授权绑定）
- 无授权自动修复循环（需授权绑定）
- 基于自然语言关键词推断执行权限