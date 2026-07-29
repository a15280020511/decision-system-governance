# Decision System Governance

本仓库是三中心决策系统的治理仓库，不是第四个业务中心；不运行任务、不调用外部 API、不调用模型、不保存业务 Artifact。

## 业务仓库

- `a15280020511/evidence-data-center`
- `a15280020511/compute-simulation-center`
- `a15280020511/expert-assessment-center`

GPTs（Orchestration Console）是三中心唯一中继。业务中心之间禁止直接通信、跨仓库运行时读取、共享业务 Secret、共享业务工作流和互取 Artifact。

## 权威文件

- `ARCHITECTURE.md`
- `THREE_CENTER_CONTRACT.md`
- `MASTER_OPERATIONS_RUNBOOK.md`
- `GPTS_REBUILD_GUIDE.md`
- `GLOBAL_RECOVERY_CHECKLIST.md`
- `SECURITY_BOUNDARIES.md`
- `INTERFACE_VERSION_MATRIX.json`
- `contracts/`
