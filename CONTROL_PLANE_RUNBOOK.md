# GPTs 三中心治理控制平面

## 正式接口

GPTs 使用六个动作：

```text
checkGovernanceGatewayPublic
checkGitHubAuthentication
submitDecisionTask
findDecisionTaskByClientRequestId
getDecisionTaskStatus
getDecisionTaskReceipts
```

前两个动作诊断传输和 Bearer 认证；`submitDecisionTask` 是唯一写操作；后三个动作负责找回、查询状态和读取可信回执。

## 网页 GPT 会话锁

每个 GPT 会话只允许一个未终态逻辑任务：

```text
无当前任务 → 允许一次提交
当前任务未终态 → 只允许查询同一 Issue
当前任务可信终态 → 才可接受下一逻辑任务
```

用户在任务执行期间提出第二个任务时，GPTs 返回当前任务状态卡，不创建新的治理 Issue。会话锁由 GPT 指令执行；治理中心的全局槽继续提供后端串行保证。

## 全局单任务执行槽

治理仓库只有一个全局执行槽：

```text
最早开放治理 Issue → 占用执行槽 → 异步派发与对账
当前任务终态关闭 → 自动领取最早的下一任务
```

规则：

- 同一时刻只允许一个任务进入三中心派发和监控链路；
- 不同路由共用同一个执行槽；
- 工作流采用固定全局并发组，`cancel-in-progress=false`；
- 当前任务关闭后自动唤醒下一任务；
- 主队列每 15 分钟执行恢复扫描；
- 子中心终态由独立工作流每 5 分钟异步轮询；
- 单个任务最多自动恢复 3 次；
- 不建立后台服务、数据库、Redis、Celery 或常驻进程。

## 提交前连接预检

新会话、Action 配置变更或异常后必须按顺序执行：

1. `checkGovernanceGatewayPublic`
2. `checkGitHubAuthentication`

两项均为 HTTP 200 后才允许一次 POST。任一失败都停止，不请求写操作授权。

## 禁止重复提交

治理层同时使用两种身份：

```text
client_request_id
SHA-256(schema_version + route + ticket)
```

规则：

- `client_request_id` 必须在 POST 前生成；
- 每个逻辑任务最多调用一次 `submitDecisionTask`；
- 每个逻辑任务最多向用户申请一次写授权；
- POST 无返回、超时或非 201 时禁止第二次 POST；
- 必须按原请求号调用 `findDecisionTaskByClientRequestId`；
- 同请求号、同正文复用权威 Issue；
- 同请求号、不同正文返回 `REQUEST_ID_CONFLICT`；
- 规范化重复业务任务返回原治理 Issue，不触发第二次业务调用。

`wait_seconds` 是兼容字段，不参与业务身份，不能用于绕过去重。

## 真异步执行

提交成功只代表治理 Issue 已创建。治理派发后立即释放 Runner：

1. `CONTROL_RECEIVED` 证明 Issue 创建和回读；
2. `CONTROL_DISPATCHED` 的开放 Issue 作为全局槽锁；
3. 独立对账工作流查询子中心可信终态；
4. 五分钟计划轮询是目标间隔，不是严格实时 SLA；
5. 情报和计算期限为两小时，专家期限为三小时；
6. 超时后仍保留迟到可信终态对账。

不存在永久 socket、现场长连接或无限循环。

## 查询窗口与执行进度

网页 GPTs 不能创建常驻浏览器窗口。查询窗口实现为对话中的状态卡与稳定查询句柄：

```text
client_request_id
issue_number
task_id
route
state
phase
last_updated_at
retryable
error_code
next_action
issue_url
```

推荐同一回复内最多四次有限读取：

```text
0 秒：提交后立即回读
15 秒：查询状态
45 秒：查询状态和回执
90 秒：最后一次自动查询
```

90 秒仍未终态时停止自动轮询，向用户返回查询句柄。后续用户通过：

```text
查询当前任务
查询任务 #<issue_number>
继续查看执行进度
```

继续读取同一 Issue。

只展示离散阶段，不伪造百分比或队列名次：

```text
RECEIVED            已接收
QUEUED              等待执行槽
CONTROL_RUNNING     治理校验中
CONTROL_DISPATCHED  已派发子中心
CHILD_ACCEPTED      子中心执行中
CONTROL_COMPLETED   已完成并验证证据
```

## 状态读取

```text
state=open
```

表示排队或运行：

- 尚无治理状态区：FIFO 队列中等待；
- `CONTROL_RUNNING`：治理校验中；
- `CONTROL_DISPATCHED`：已派发并等待子中心终态。

```text
state=closed
state_reason=completed
```

只有可信机器人终态、Task ID 和 Artifact 合同均通过时才表示成功。

```text
state=closed
state_reason=duplicate
```

表示规范化重复提交，正文指向原始 Issue。

```text
state=closed
state_reason=not_planned
```

表示无效票据、派发失败、子中心失败、超时或恢复次数耗尽。具体语义读取 `control-plane/status-dictionary.json`。

## 成功证据

GPTs 只能信任 `github-actions[bot]`。完成必须同时满足：

- 治理 Task ID 匹配；
- 路由匹配；
- 子中心可信终态存在；
- 路由对应 Artifact 合同通过。

Issue 创建、`CONTROL_RECEIVED`、子中心受理、等待窗口结束或监控错误均不等于业务成功。

## 故障恢复

- 工作流中断后重新选择同一最早 Issue；
- 复用已有子 Issue，不重复派发；
- 自动恢复最多 3 次；
- 监控错误和超时不触发新任务；
- 只有可信终态标记 `retryable=true` 且用户决定重试时，才生成新请求号建立新逻辑任务；
- 禁止快速无限 Agent 循环。

## 权限

GPT Action Token：

```text
decision-system-governance
Metadata: Read
Issues: Read and write
```

治理仓库：

```text
GITHUB_TOKEN
  Issues: write
  Actions: write
  Contents: read

CONTROL_PLANE_TOKEN
  三个业务仓库 Issues: read and write
```

GPTs 禁止直接访问三个业务仓库、Contents、Actions、Secrets、工作流或分支。

## 工具与依赖

治理运行时不增加第三方 Python 包。继续使用：

- Python 3.12 标准库；
- GitHub Actions 原生 `concurrency`；
- GitHub CLI；
- Issue、评论和 Artifact；
- UUID 与 SHA-256。

不安装 Celery、Redis、RQ、数据库、状态机框架、消息队列、常驻 Worker 或 Agent 框架。当前 GitHub 原语已经覆盖单槽、异步、幂等、查询和证据链；额外依赖只会扩大故障面和维护成本。

静态维护工具如 CodeQL、Dependabot 和 actionlint 可以用于 CI，但不进入任务运行链路。

## 正式规范

- `GPTS_WEB_SESSION_PROTOCOL.md`
- `contracts/gpts-web-session-protocol.json`
- `gpts-knowledge/GPTS_CONTROL_PLANE.md`
- `control-plane/status-dictionary.json`

## Server酱

Server酱不参与任务队列、状态所有权、去重或自动恢复，只能作为可选辅助通知渠道。
