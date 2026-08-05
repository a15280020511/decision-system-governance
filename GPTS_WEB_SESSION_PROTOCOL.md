# 网页 GPTs 对接治理中心规范

## 目标

网页 GPTs 只连接 `decision-system-governance`。治理中心负责幂等、单任务锁、异步派发、状态归一化、证据核验和故障恢复。GPTs 不直接连接三个业务中心。

## 一、单任务纪律

1. 每个 GPT 会话最多绑定一个未终态逻辑任务。
2. 三个业务路由共用一个全局执行槽。
3. 当前任务未进入可信终态前，GPTs 不得提交第二个任务。
4. 用户在当前任务未完成时提出新任务，GPTs 只能返回当前任务查询卡，不得调用 `submitDecisionTask`。
5. 不声明无法可靠计算的队列名次或完成百分比。

这一区分两层锁：

- 会话锁：阻止同一 GPT 会话重复提交或切换任务；
- 全局槽：阻止治理中心跨路由并发执行。

## 二、连接预检

新会话、Action 配置变更或异常后，按固定顺序执行：

1. `checkGovernanceGatewayPublic`
2. `checkGitHubAuthentication`

只有两项均返回 HTTP 200，才允许进入写操作。任一项失败都必须停止，不得弹出任务写入确认。

## 三、一次提交与幂等

1. GPTs 在 POST 前生成 UUID 格式 `client_request_id`。
2. 每个逻辑任务最多调用一次 `submitDecisionTask`。
3. 每个逻辑任务最多向用户请求一次写操作授权。
4. POST 返回非 201、超时、无结果或结果不明确时，禁止第二次 POST。
5. 只能使用原 `client_request_id` 调用 `findDecisionTaskByClientRequestId` 找回任务。
6. 同一请求号和相同正文复用权威 Issue；同一请求号对应不同正文返回 `REQUEST_ID_CONFLICT`。
7. 重新执行必须是新的逻辑任务、得到用户决定，并生成新的请求号。

## 四、异步执行

提交成功只代表治理 Issue 已创建。业务执行继续异步进行：

1. `CONTROL_RECEIVED` 证明入口创建和回读成功；
2. 治理派发工作流不等待子中心完成；
3. 开放治理 Issue 作为唯一全局槽锁；
4. 独立对账工作流以 5 分钟为目标间隔查询子中心终态；
5. 15 分钟恢复扫描处理遗漏唤醒和中断；
6. 情报、计算期限为 2 小时，专家期限为 3 小时；
7. 超时后仍允许可信迟到终态完成对账。

GitHub cron 可能延迟，因此这些间隔不是严格实时 SLA。

## 五、查询窗口

网页 GPTs 不能建立常驻浏览器窗口。所谓“查询窗口”应实现为对话中的状态卡和稳定查询句柄。

状态卡必须包含：

```text
任务请求号：client_request_id
治理 Issue：issue_number
任务 ID：task_id
路由：route
当前状态：state
当前阶段：phase
最后更新时间：last_updated_at
是否可重试：retryable
错误码：error_code
下一步：next_action
查询链接：issue_url
```

推荐同一回复中的有限查询节奏：

```text
提交后立即回读
15 秒后查询一次
45 秒后查询一次
90 秒后查询一次
```

90 秒后仍未完成，停止自动轮询并返回查询句柄。后续由用户发送：

```text
查询当前任务
查询任务 #<issue_number>
继续查看执行进度
```

GPTs 只能调用：

- `getDecisionTaskStatus`
- `getDecisionTaskReceipts`

查询操作不得触发新的 POST，也不应再次要求写操作确认。

## 六、执行进度表达

只使用离散阶段，不使用虚构百分比：

| 顺序 | 状态 | 用户显示 |
|---:|---|---|
| 1 | `RECEIVED` | 已接收 |
| 2 | `QUEUED` | 等待执行槽 |
| 3 | `CONTROL_RUNNING` | 治理校验中 |
| 4 | `CONTROL_DISPATCHED` | 已派发子中心 |
| 5 | `CHILD_ACCEPTED` | 子中心执行中 |
| 6 | `CONTROL_COMPLETED` | 已完成并验证证据 |

失败、拒绝、超时和监控异常使用状态字典中的独立状态，不得强行映射为完成百分比。

## 七、成功判定

只有以下证据同时满足，GPTs 才能报告完成：

1. 回执作者为 `github-actions[bot]`；
2. Task ID 与治理任务一致；
3. 路由一致；
4. 子中心可信终态存在；
5. 路由对应 Artifact 合同通过。

以下均不代表业务成功：

- Issue 已创建；
- `CONTROL_RECEIVED`；
- 子中心已受理；
- 等待窗口结束；
- 监控工作流暂时失败。

## 八、失败与恢复

1. 治理中心最多自动恢复同一任务 3 次；
2. 自动恢复复用原治理 Issue 和子 Issue；
3. GPTs 不得因监控错误、超时或页面无返回而重新提交；
4. 只有终态明确标记 `retryable=true`，且用户决定重新执行时，才建立新逻辑任务；
5. 新任务必须使用新的 `client_request_id`。

## 九、安全边界

- GPTs 只访问治理仓库；
- 禁止直接访问三个业务仓库；
- 票据中禁止密钥、个人数据、任意代码和 Shell 命令；
- GPT Action Token 仅授予治理仓库 `Metadata: Read` 与 `Issues: Read and write`；
- 只读 GET 显式标记为非 consequential；
- `submitDecisionTask` 是唯一 consequential 操作。

## 十、依赖策略

本链路不引入第三方 Python 运行包。现有 GitHub 原语已经覆盖所需能力：

- GitHub Actions `concurrency`：单全局执行槽；
- GitHub Issue：任务句柄与状态存储；
- 评论：可信回执；
- Artifact：证据交付；
- Python 3.12 标准库：JSON、UUID、哈希、HTTP 和状态处理；
- GitHub CLI：工作流唤醒与有限恢复。

不引入 Celery、Redis、RQ、数据库、常驻 Worker 或 Agent 循环框架。它们需要额外服务器和维护，并会增加鉴权、状态一致性和故障面。

机器可读合同：`contracts/gpts-web-session-protocol.json`。
