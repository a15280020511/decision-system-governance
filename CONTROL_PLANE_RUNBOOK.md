# GPTs 三中心治理控制平面

## 结论

`decision-system-governance` 现在承担控制平面，不承担业务计算、数据请求或专家研判。GPTs 只向治理仓库提交控制票据；治理仓库使用受限凭证，把原始业务票据送入对应中心已有的正式 Issue 入口，并轮询受信任的最终回执。

```text
Custom GPT
  └─ GitHub REST Action（仅治理仓库 Issues）
       └─ [control] Issue + /dispatch-control
            └─ Governance Control Plane
                 ├─ [api] Issue → 情报中心
                 ├─ [compute] Issue → 计算中心
                 └─ [execution] Issue + /run-expert-team → 专家团
```

三个业务中心之间仍然没有直接通信。

## 必需 Secret

只在 `decision-system-governance` → Settings → Secrets and variables → Actions 添加：

| Secret | 权限与用途 |
|---|---|
| `CONTROL_PLANE_TOKEN` | 仓库所有者签发的 fine-grained PAT；仅授权三个业务仓库；Issues 读写。可选增加 Actions 只读。不得授权 Contents 写入。 |
| `SERVERCHAN_SENDKEY` | Server酱 SendKey；只用于最终状态或拒绝摘要通知。 |

不要把 SendKey、PAT、业务 API Key、模型 Key 写进 Issue、代码、日志或 Artifact。

GPT Action 自己还需要一个独立的 fine-grained PAT，权限仅限治理仓库 Issues 读写。该 Token 填在 GPT Action 的 Bearer Authentication，不放入仓库。

## GPT Action 配置

1. 在 GPT 编辑器中选择 Actions，不要同时启用 Apps。
2. 导入 `gpts-action/openapi.yaml`。
3. Authentication 选择 API Key → Bearer。
4. 使用只授权 `decision-system-governance` 的 fine-grained PAT。
5. GPT 只能调用四个操作：
   - `createGovernanceIssue`
   - `commentGovernanceIssue`
   - `getGovernanceIssue`
   - `listGovernanceIssueComments`

GPT Action Token 不应能访问三个业务仓库。跨仓库权限只存在于治理仓库的 `CONTROL_PLANE_TOKEN`。

## 控制票据

治理 Issue 标题必须以 `[control]` 开头。正文必须是：

```json
{
  "schema_version": "governance-control-ticket-v1",
  "task_id": "compute-20260802-001",
  "route": "compute",
  "notify": true,
  "wait_seconds": 2400,
  "ticket": {
    "task_id": "compute-20260802-001",
    "operation": "descriptive_statistics",
    "inputs": {
      "values": [1, 2, 3]
    }
  }
}
```

`route` 只允许：

- `intelligence`：转为情报中心 `[api]` Issue；
- `compute`：转为计算中心 `[compute]` Issue；
- `expert`：转为专家团 `[execution]` Issue，并自动评论 `/run-expert-team <task_id>`。

`ticket` 必须是目标中心当时有效 Schema 对应的完整原始票据。`task_id` 必须与外层完全一致。任何名称疑似 Secret、Token、密码、API Key、Private Key 或 SendKey 的字段都会被中央入口拒绝。

创建 Issue 后，GPT 必须再评论：

```text
/dispatch-control compute-20260802-001
```

## 回执判定

治理工作流只信任子仓库中 `github-actions[bot]` 发布的正式终态：

- 情报中心：`API_COMPLETED`、`API_PARTIAL`、`API_BLOCKED`、`API_FAILED`、`API_REJECTED`；
- 计算中心：`COMPUTE_COMPLETED`、`COMPUTE_FAILED`、`COMPUTE_REJECTED`；
- 专家团：`EXECUTION_COMPLETED`、`EXECUTION_FAILED`、`EXECUTION_DEGRADED`、`EXECUTION_REJECTED`。

治理 Issue 会得到：

- `CONTROL_DISPATCHED`：已创建子 Issue；
- `CONTROL_COMPLETED`：子中心可信终态成功；
- `CONTROL_FAILED`：子中心失败、拒绝或超时。

治理层不会把 Workflow success 当成业务成功，也不会下载或修改三个中心的业务 Artifact。完整业务结果仍以子中心正式评论、Manifest 和 Artifact 为准。

## Server酱通知策略

每个控制任务最多推送一条最终摘要；票据在进入子中心前被拒绝时推送一条拒绝摘要。不对每个步骤推送，避免免费额度被噪声耗尽。

通知失败不会改变业务任务的审计结论；通知步骤独立 `continue-on-error`。业务失败也不会被通知成功掩盖。

## 验收顺序

1. 合并本控制平面 PR。
2. 添加 `CONTROL_PLANE_TOKEN`。
3. 添加 `SERVERCHAN_SENDKEY`。
4. 在 GPT 中导入 OpenAPI Action。
5. 先提交一个最小计算票据，确认：
   - GPT Action 只能写治理仓库；
   - 治理仓库创建计算中心 Issue；
   - 计算中心 actor 仍为仓库所有者并正常触发；
   - 治理 Issue 收到 `CONTROL_COMPLETED`；
   - 微信收到一条 Server酱摘要。
6. 再分别做情报中心与专家团最小票据验收。
