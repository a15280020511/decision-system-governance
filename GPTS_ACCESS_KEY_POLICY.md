# GPTs 最小权限与密钥边界

## 结论

网页 GPTs 不得持有任何能够访问三个业务仓库的密钥。必须使用两层凭证：

```text
网页 GPTs
  └─ GPTS_GOVERNANCE_TOKEN
       └─ 仅访问 decision-system-governance
            └─ 仅创建和读取 [control] Issue

治理仓库 GitHub Actions
  └─ CONTROL_PLANE_TOKEN
       └─ 仅访问三个业务仓库
            └─ 仅创建任务 Issue、写入必要命令、读取终态回执
```

网页 GPTs 不能直接访问：

- `a15280020511/evidence-data-center`
- `a15280020511/compute-simulation-center`
- `a15280020511/expert-assessment-center`

它也不能修改治理仓库或三个业务仓库的代码、分支、标签、Release、Pull Request、工作流、Secrets、Variables、Environments、Webhook 或仓库设置。

## 密钥一：GPTS_GOVERNANCE_TOKEN

类型：GitHub fine-grained personal access token。

Repository access：

```text
Only select repositories
  - a15280020511/decision-system-governance
```

Repository permissions：

```text
Metadata: Read-only            # GitHub 强制的基础权限
Issues: Read and write         # 创建 [control] Issue，并读取同一 Issue 状态
```

其余所有 Repository permissions 均设为：

```text
No access
```

特别确认以下权限不是 Write：

```text
Actions
Administration
Contents
Deployments
Environments
Pull requests
Secrets
Variables
Webhooks
Workflows
```

该密钥只配置在网页 GPT 的 Action 认证中，不写入仓库，不作为 Actions Secret，不提供给任何子仓库。

### GitHub 权限模型限制

GitHub 没有“只允许创建 Issue、禁止编辑 Issue”的独立权限。`Issues: Read and write` 同时覆盖创建和修改 Issue。这里通过两层约束缩小风险：

1. GPT Action OpenAPI 只暴露 `POST /issues` 和 `GET /issues/{issue_number}`；
2. 该密钥只绑定治理仓库，完全不能访问三个业务仓库，也没有代码写权限。

因此这里的“只有使用权”准确含义是：可以提交任务和读取结果，但不能修改任何仓库代码或配置。

## 密钥二：CONTROL_PLANE_TOKEN

类型：GitHub fine-grained personal access token。该密钥只保存为治理仓库 Actions Secret：

```text
CONTROL_PLANE_TOKEN
```

Repository access：

```text
Only select repositories
  - a15280020511/evidence-data-center
  - a15280020511/compute-simulation-center
  - a15280020511/expert-assessment-center
```

Repository permissions：

```text
Metadata: Read-only
Issues: Read and write
```

其余所有权限均为 `No access`，特别禁止：

```text
Actions
Administration
Contents
Deployments
Environments
Pull requests
Secrets
Variables
Webhooks
Workflows
```

该密钥可以创建和读取子仓库任务 Issue，但不能提交代码、修改分支、创建或合并 PR、修改工作流或仓库设置。

## 治理工作流自身权限

治理工作流继续使用仓库自动生成的 `GITHUB_TOKEN`，权限固定为：

```yaml
permissions:
  contents: read
  issues: write
  actions: write
```

用途：

- `contents: read`：读取治理代码；
- `issues: write`：更新治理 Issue 的状态和最终回执；
- `actions: write`：当前任务完成后唤醒下一次 FIFO worker。

禁止增加 `contents: write`、`pull-requests: write`、`workflows: write` 或 `administration: write`。

## GPT Action 允许的唯一接口

```text
POST /repos/a15280020511/decision-system-governance/issues
GET  /repos/a15280020511/decision-system-governance/issues/{issue_number}
```

不允许在 OpenAPI 中出现三个业务仓库的路径，也不允许出现 `PATCH`、`PUT`、`DELETE`、Pull Request、Contents、Git refs、Actions、Workflows、Secrets 或 Administration 接口。

## 配置与轮换

- 两个密钥不得相同；
- 两个密钥不得写入 Issue、日志、Artifact、代码或知识库；
- 令牌过期时间优先设置为 90 天；若维护成本优先，可设置更长期限，但仍需在到期前轮换；
- 轮换时先创建新令牌并验证，再撤销旧令牌；
- 一旦怀疑泄露，立即撤销，不等待到期。
