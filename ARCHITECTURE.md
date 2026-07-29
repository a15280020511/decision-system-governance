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

## 计算中心内部控制面

计算中心使用轻量、确定性的系统论计算矩阵：

```text
问题类型 × 系统层级 × 反馈结构 × 证据成熟度 × 风险等级
→ 必须通过的质量门 → 固定 operation / mode → 独立依赖矩阵
```

该矩阵只负责正确组合现有受管能力，不执行跨中心调用，不安装票据指定依赖，不替代 GPTs 总控，也不要求所有任务进入同一条重型流水线。正式规则见 `SYSTEMS_COMPUTATION_MATRIX_POLICY.md`。
