# 三中心决策系统总体架构

```text
GPTs 总控使用台
└── Decision System Governance（控制平面，不是业务中心）
    ├── Evidence & Data Center
    ├── Computation & Simulation Center
    └── Expert Assessment Center
```

治理仓库保存合同、版本、恢复、安全边界和控制入口。它可以代表 GPTs 创建目标中心的正式 Issue、轮询由 `github-actions[bot]` 发布的可信状态并集中通知，但不执行业务请求、不下载业务 Artifact、不调用模型，也不修改中心结果。

三个业务中心平行、并列、隔离；中心之间不得直接通信。GPTs 可按任务调用任意单中心、任意子集或串行 Pipeline，但不得伪造中心输出。控制平面只传递明确票据与状态，不形成自动无限循环。

## 权限分层

```text
GPT Action Token
  └─ 仅治理仓库 Issues 读写

治理仓库 GITHUB_TOKEN
  └─ 仅本仓库内容读取、Issue 回执、Artifact

CONTROL_PLANE_TOKEN
  └─ 仅三个业务仓库 Issues 读写
     不授予 Contents 写入，不持有业务 API/模型 Secret

SERVERCHAN_SENDKEY
  └─ 仅治理仓库最终摘要通知
```

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
