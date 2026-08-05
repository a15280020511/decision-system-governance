# 治理中心统一日志、诊断与告警

## 分层

1. **业务诊断层**：各中心继续生成自己的结构化诊断、审计、控制台日志和 Artifact Manifest。
2. **Actions 诊断层**：每个仓库的 `Workflow Diagnostic Sweep` 关联 Run、Attempt、Commit、Job、Step、耗时和完整失败日志。
3. **治理审计层**：治理中心执行 OSV、deps.dev、CISA KEV、CodeQL、Dependabot 和 Artifact Attestation。
4. **通知层**：关键治理工作流非成功时通过 Server酱发送最小元数据。
5. **失联检测层**：配置 `HEALTHCHECKS_PING_URL` 后，由外部服务检测治理心跳缺失。

## 错误诊断

统一错误分类：

- `secret_or_auth`
- `rate_limit_or_quota`
- `timeout_or_cancellation`
- `network_dns_tls`
- `dependency_install`
- `schema_or_input`
- `artifact_or_attestation`
- `provider_or_model`
- `test_or_assertion`
- `resource_exhaustion`
- `syntax_or_runtime`
- `unknown`

每个失败记录必须包含失败 Workflow、Run ID、Attempt、Commit SHA、失败 Job/Step、关键错误行、失败指纹、是否可重试、最大重试次数和诊断证据路径。临时性错误只允许有限退避；权限、Secret、Schema、依赖和 Artifact 完整性问题禁止原样重试。

## 诊断包读取顺序

```text
summary.md
→ diagnostic-index.json
→ runs/<run_id>/failure.json
→ runs/<run_id>/key-lines.jsonl
→ runs/<run_id>/jobs.jsonl
→ runs/<run_id>/redacted-logs/
→ manifest.json
→ Artifact Attestation
```

## 告警规则

Server酱只监听明确列出的关键治理工作流，且只在非成功结论或受控手动测试时发送。通知只包含仓库、工作流、结论、Run ID、缩短 Commit SHA 和 Run URL。通知器不得读取 Issue 正文、Artifact 或业务日志，也不得打印 SendKey 或完整发送端点。

## 外部心跳

`Governance External Heartbeat` 每 30 分钟验证治理仓库 GitHub API 可达性并发送 start、success 或 fail 信号。未配置 `HEALTHCHECKS_PING_URL` 时工作流明确输出 `pending_secret`，但不伪报已启用。

## 供应链审计

供应链工作流扫描锁定的 Python 依赖和 GitHub Actions 引用，通过 OSV 查询漏洞、通过 deps.dev 获取依赖元数据、与 CISA KEV 做本地 CVE 关联。默认是报告模式；是否阻断必须单独批准。审计包同样包含 SHA-256 Manifest，并在正式运行时生成 Attestation。

## 脱敏要求

禁止保存或发送完整环境变量、Authorization、Cookie、Set-Cookie、API Key、Token、SendKey、密码、提示词、模型私密输入输出、个人数据和业务私密数据。原始日志 ZIP 解析后必须删除，只允许保存脱敏日志。
