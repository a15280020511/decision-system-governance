# Repository Protection Policy

状态：生产要求；管理员设置待启用

## 目标

`main` 是治理仓唯一生产分支。代码、工作流、治理合同和发布清单必须通过 Pull Request 与正式门禁进入 `main`，不得依赖人员记忆或口头约定。

## 必须启用的 GitHub Ruleset

目标分支：

```text
main
```

要求：

1. 禁止删除分支；
2. 禁止强制推送；
3. 所有变更必须通过 Pull Request；
4. 合并前必须解决全部审阅对话；
5. 合并前要求分支与 `main` 保持最新；
6. 要求正式状态检查成功；
7. 不允许普通直接推送；
8. 管理员绕过仅保留真实事故恢复用途，不作为日常路径。

单人仓库可将最低批准数设为 `0`，但仍必须通过 Pull Request 和全部状态检查。

## 必须选择的状态检查

至少要求：

```text
Governance Validate
Control Plane Validate
GPTs Access Contract
Validate OpenRouter Selector Security
Validate OpenRouter Governance Selector Resilience
Validate Main Provenance and Repository Protection
```

GitHub 界面显示的具体检查名称可能是工作流名称或 Job 名称，应选择当前 `main` 最近一次成功运行产生的对应检查。

## 代码侧检测

`.github/workflows/main-provenance-and-repository-protection.yml` 提供两层检测：

- `main` 每次推送都必须能关联到一个已合并、目标为 `main` 的 Pull Request；
- 每周读取一次实时分支保护和 Ruleset 状态。

来源检测失败会使主分支检查失败。仓库保护检查在 Ruleset 尚未由管理员启用前只产生明确警告，不会伪报已经受保护。

## 权限边界

审计工作流只拥有：

```yaml
contents: read
pull-requests: read
```

禁止仓库写权限、Actions 写权限、Issue 写权限和身份令牌写权限。审计不得自动修改 Ruleset、分支、代码、Secret 或业务中心。

## 临时与测试分支

已合并测试分支不得继续出现在生产工作流触发器中。连接器无法删除分支时，应先将分支快进到当前 `main`，确保不再保留未合并差异，再由仓库管理员在 GitHub 页面删除。

## 失败处理

检测到直接推送、无关联 PR、分支未保护、Ruleset 缺失或保护接口不可读时：

- 不声明长期治理保护已经完成；
- 不自动扩大权限进行修复；
- 保持业务系统和三个中心不受影响；
- 在 Actions 回执中保留明确状态；
- 由仓库管理员完成 Ruleset 设置后重新运行审计。
