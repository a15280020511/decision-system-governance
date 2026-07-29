# 三中心决策系统总体架构

```text
GPTs 总控使用台
├── Evidence & Data Center
├── Computation & Simulation Center
└── Expert Assessment Center
```

治理仓库只保存合同、版本、恢复和安全边界，不参与业务运行。三个业务中心平行、并列、隔离，全部只与 GPTs 单线联系。GPTs 可按任务调用任意单中心、任意子集或串行 Pipeline，但不得伪造中心输出。

## 核心闭环

```text
证据 → 假设 → 先验 → 校准 → 约束 → 仿真 → 不确定性
→ 留出验证 → 真实结果 → 重新校准 → 模型升降级
```
