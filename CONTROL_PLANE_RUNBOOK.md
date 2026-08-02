# GPTs 三中心治理控制平面

## 最终接口

GPTs 与治理仓库之间采用“提交一次、查询同一个 Issue”的固定接口：

```text
GPTs
  ├─ submitDecisionTask       创建一次 [control] Issue
  └─ getDecisionTaskStatus   查询状态、结果摘要和 Artifact 信息
```

GPTs 不读取评论，不访问三个业务仓库，不发送 `/dispatch-control`，也不生成 `task_id`。治理仓库根据新 Issue 编号自动生成唯一任务 ID，并负责票据验证、路由、派发、监控、失败处理、结果汇总、状态写回和自动关闭。

评论仍保留为人工审计证据，但不暴露为 GPT Action。

## 最小连接配置

在 GPT 编辑器中：

1. 选择 Actions。
2. 导入 `gpts-action/openapi.yaml`。
3. Authentication 选择 API Key → Bearer。
4. 填入只授权 `decision-system-governance` 仓库、`Issues: Read and write` 的 fine-grained PAT。
5. 在 Preview 中执行一次最小计算票据。

GPT 端只有一个写操作和一个读操作。GPT Action Token 无权访问三个业务仓库。

治理仓库仅需：

```text
CONTROL_PLANE_TOKEN
```

该 Token 只授权三个业务仓库的 Issues 读写，不授权 Contents 写入。

## 提交格式

标题必须完全等于：

```text
[control]
```

正文示例：

```json
{
  "schema_version": "governance-control-ticket-v3",
  "route": "compute",
  "ticket": {
    "operation": "descriptive_statistics",
    "inputs": {
      "data": [1, 2, 3]
    }
  }
}
```

规则：

- `route` 只允许 `intelligence`、`compute`、`expert`；
- `ticket` 不得包含 `task_id`，治理仓库自动注入；
- `wait_seconds` 可省略，默认 2400；
- 不得包含 Secret、Token、API Key、密码、私钥或任意执行代码；
- 创建 Issue 后无需再发表评论。

## 状态读取

GPT 只调用 `getDecisionTaskStatus`。

```text
state=open
```

表示排队或运行。此时 Issue 正文末尾包含治理仓库写入的 `CONTROL_DISPATCHED` 状态、任务 ID、路由和子 Issue。

```text
state=closed
state_reason=completed
```

表示成功。Issue 正文末尾包含 `CONTROL_COMPLETED`、子中心终态、子 Issue、可信终态摘录、Artifact ID、digest 和公开结果摘要。

```text
state=closed
state_reason=not_planned
```

表示拒绝、失败或超时。Issue 正文末尾包含治理仓库集中写入的失败类型和原因。

状态区由以下标记包围：

```text
<!-- governance-status:start -->
...
<!-- governance-status:end -->
```

GPT 不需要读取评论或理解子仓库回执格式。

## 稳定性机制

- GPT 只连接一个仓库、一个 OpenAPI、一个 Token；
- GPT 只有一个写操作和一个读操作；
- 仅 `issues.opened` 触发一次；
- 任务 ID 从治理 Issue 编号确定性生成；
- 子 Issue 创建前检查同名任务，工作流重跑不会重复派发；
- 专家团正式命令在发送前检查是否已存在；
- 只信任目标仓库 `github-actions[bot]` 的终态；
- 监控连续错误会形成 `CONTROL_MONITOR_ERROR`，不会伪报成功；
- 状态和结果统一写回治理 Issue 正文；
- 成功自动关闭为 `completed`；
- 拒绝、失败或超时自动关闭为 `not_planned`；
- 三个中心仍互相隔离，治理仓库不下载或修改业务 Artifact。

## Server酱

Server酱仍仅为禁用安装占位，不参与本接口。
