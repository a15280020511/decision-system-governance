# GPTs 三中心治理控制平面

## 最终接口

GPTs 只使用两个动作：

```text
submitDecisionTask
getDecisionTaskStatus
```

提交与内部执行现在都是真异步。GPTs 创建一次 `[control]` Issue 后立即保存 Issue 编号；治理 worker 派发子任务后立即释放 Runner，独立对账工作流每5分钟读取同一个任务的可信终态。禁止通过再次创建 Issue 重试。

## 全局单任务队列

治理仓库只有一个全局执行槽：

```text
新任务 → 打开治理 Issue → FIFO 排队
当前任务终态关闭 → 自动领取最早的下一任务
```

规则：

- 同一时刻只允许一个任务进入三中心派发和监控链路；
- 不同路由也共用同一个执行槽；
- 排队顺序按治理 Issue 编号从小到大；
- GitHub Actions 采用固定全局并发组，`cancel-in-progress=false`；
- 当前任务关闭后，工作流自动唤醒下一名；
- 主队列每15分钟执行恢复扫描；子中心终态由独立工作流每5分钟异步轮询；
- 单个任务最多自动恢复 3 次，达到上限后关闭为 `CONTROL_RETRY_EXHAUSTED`；
- 不建立后台服务、数据库、Redis、Celery 或常驻进程。

## 内部异步轮询

- 派发工作流不再现场等待子中心，不维持长连接，也不执行30秒循环轮询；
- `CONTROL_DISPATCHED` 的开放 Issue 本身就是全局槽锁，下一任务不能越过它；
- 独立对账工作流以5分钟为目标间隔运行；GitHub cron 可能延迟，因此不是严格实时 SLA；
- cron 延迟只增加最终回执的送达时间，不改变子中心已经独立执行的模型、计算或采集质量；
- 情报和计算路由期限为2小时，专家路由为3小时；超期后仍保留迟到可信终态对账。

## 禁止重复提交

治理仓库对请求进行规范化 SHA-256：

```text
schema_version + route + ticket
```

`wait_seconds` 为旧接口兼容字段，不再用于占用 Runner 等待；它仍不参与业务身份，因此不能用于绕过去重。

发现更早的相同请求时：

```text
state=closed
state_reason=duplicate
```

Issue 正文写入 `CONTROL_DUPLICATE` 和原始 Issue。重复任务不会进入队列，不会创建子 Issue，不会触发模型、API 或计算调用。

GPTs 必须保存首次返回的 Issue 编号。网络超时或暂时未看到状态时，只能查询原 Issue，不得再次提交。

## 状态读取

```text
state=open
```

表示排队或运行：

- 尚无治理状态区：FIFO 队列中等待；
- `CONTROL_RUNNING`：已占用全局执行槽；
- `CONTROL_DISPATCHED`：已派发并等待子中心终态。

```text
state=closed
state_reason=completed
```

表示成功，正文包含 `CONTROL_COMPLETED`、子中心终态和 Artifact 元数据。

```text
state=closed
state_reason=duplicate
```

表示规范化重复提交，正文指向原始 Issue。

```text
state=closed
state_reason=not_planned
```

表示无效票据、派发失败、子中心失败、超时或恢复次数耗尽。

## 稳定性机制

- GPT 只连接一个仓库、一个 OpenAPI 和一个 Token；
- 一个全局执行槽，禁止跨路由并发；
- FIFO 扫描以开放的、仓库所有者创建的 `[control]` Issue 为唯一队列；
- 规范化哈希阻止重复排队和重复派发；
- 子 Issue 标题和专家命令仍保持幂等；
- 只信任 `github-actions[bot]` 的子中心终态；
- 工作流中断后重新选择同一最早 Issue，并复用已有子 Issue；
- 快速连续自恢复被禁止；只有已成功关闭当前任务时才立即唤醒下一任务；
- 未正常关闭的任务由 15 分钟恢复扫描处理；
- 自动恢复最多 3 次，不形成无限循环；
- 所有状态继续写回同一个治理 Issue。

## 权限

GPT Action Token：

```text
decision-system-governance
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

`Actions: write` 只用于在当前任务完成后唤醒下一次治理工作流，不用于修改工作流或仓库配置。

## 工具与依赖

治理运行时不需要新增第三方 Python 包。继续使用：

- Python 3.12 标准库；
- GitHub Actions 原生 `concurrency`；
- GitHub CLI；
- Issue、评论和 Artifact；
- SHA-256。

不安装 Redis、Celery、消息队列、数据库、Agent 框架或自动代码修改框架。它们会增加常驻服务、权限、故障面和维护成本。

可在独立维护阶段评估 `actionlint`、CodeQL 和 Dependabot，但它们只用于静态检查和依赖维护，不进入任务运行链路。

## Server酱

Server酱仍仅为禁用安装占位，不参与队列、任务状态或自动恢复。
