# GPTs Knowledge 上传与同步清单

## A. 最小恢复集

平台文件数量受限时，至少上传：

1. `recovery/gpts-knowledge/GPTS_KNOWLEDGE_MASTER.md`
2. `api-center/api-catalog.json`
3. `api-center/api-ticket.schema.json`
4. `compute-center/compute-capabilities.json`
5. `compute-center/compute-ticket.schema.json`
6. `compute-center/professional-operations-guide.md`
7. `compute-center/mesa-guide.md`
8. `open-model-market/expert-team-capabilities.json`
9. `open-model-market/execution-ticket.schema.json`
10. `open-model-market/DELEGATION_CONTRACT.md`
11. `gpts-orchestration-policy.json`

Knowledge 只是恢复副本。正式出票前，GPTs 必须优先调用当前生产专用动作：

- API：`getApiToolCatalog`、`getApiTicketSchema`、必要时 `getApiConnectorManifest`；
- 计算：`getComputeToolCatalog`、`getComputeTicketSchema`；
- 专家团：`getExpertTeamCatalog`、`getExpertTicketSchema`、必要时 `getExpertDelegationContract`。

## B. 完整推荐集

在最小集基础上增加：

- `THREE_CENTERS.md`
- `GPTS_USAGE_ORCHESTRATION.md`
- `GPTS_USAGE_CENTER_CONTRACT.md`
- `api-center/api-catalog.md`
- `api-center/catalog-metadata.json`
- `api-center/connector-manifest.json`
- `compute-center/README.md`
- `compute-center/data-readiness-playbook.md`
- `README.md`
- `recovery/README.md`
- `recovery/ARCHITECTURE_AND_DECISIONS.md`
- `recovery/GPTS_REBUILD_GUIDE.md`
- `recovery/CONFIGURATION_AND_SECRETS.md`
- `recovery/MAINTENANCE_RUNBOOK.md`
- `recovery/FULL_RECOVERY_CHECKLIST.md`

## C. 权威优先级

GPTs 遇到冲突时按以下顺序：

1. 当前生产 Schema、Workflow 和执行代码；
2. 三个机器可读能力目录与策略 JSON；
3. 恢复包；
4. README 和说明文件；
5. 历史 Issue、聊天和旧导出。

Knowledge 是帮助使用的副本，不取代实时仓库内容。

## D. 必须重新同步的变更

| 仓库变化 | GPTs 需要更新 |
|---|---|
| API 连接器或目录变化 | API catalog、Schema、manifest、主知识和 Action Schema |
| 百度/高德 Secret 名称变化 | 配置与 Secret 清单、manifest、主知识 |
| 计算 operation、输入或限制变化 | capabilities、Schema、对应指南、主知识 |
| Mesa 版本、模式或限制变化 | `requirements-mesa.txt`、capabilities、Mesa 指南、Action Schema |
| 专家能力、票据或选模策略变化 | expert catalog、execution Schema、委托合同、README、主知识 |
| 三中心编排变化 | orchestration policy、THREE_CENTERS、Instructions |
| 权限合同变化 | Instructions、Action Schema、重新签发 Token |
| 恢复流程变化 | recovery 文件和主知识 |
| Action API 变化 | 重新导入 OpenAPI Schema 并验收 |

## E. 上传后检查

- GPTs 能准确说出三个中心是并列模块；
- GPTs 能解释默认串行与独立并行；
- GPTs 不声称中心直接互调；
- GPTs 能调用 API 目录动作并区分高德、百度连接器及坐标顺序；
- GPTs 知道 `AMAP_API_KEY` 和 `BAIDU_MAP_AK` 只暴露名称，不暴露值；
- GPTs 能调用 `getComputeToolCatalog` 并列出 19 个计算 operation；
- GPTs 能区分聚合 `agent_evolution` 与个体级 `agent_based_simulation`；
- GPTs 知道 Mesa 只允许三个固定模式，不能提交任意 Agent 代码；
- GPTs 能读取专家团能力目录，但不指定专家模型 ID 或 Provider；
- GPTs 不把 accepted、Workflow success 或 Artifact 元数据当完成；
- GPTs 能列出跨中心证据字段；
- GPTs 能指出恢复和维护入口。

## F. 版本记录

每次重新上传后，在维护记录中保存：

```text
GPT名称
更新时间
仓库commit SHA
Instructions版本
Action Schema版本
Knowledge文件清单
测试Issue编号
验收Run ID
操作者
```

不要依赖 GPT 平台显示的“最近更新”代替仓库 commit 和验收证据。
