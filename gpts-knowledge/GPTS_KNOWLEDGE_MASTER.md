# GPTs 使用中心主知识文件

本文件用于自定义 GPTs Knowledge，在其他上下文全部丢失时恢复仓库的正常使用逻辑。机器规则、Schema、Workflow 和生产代码优先于本文件。

## 1. 固定角色

```text
普通网页 GPT + GitHub 插件
= 维修中心
= 修改代码、Workflow、Schema、连接器、分支、PR、合并、回滚和生产验收

自定义 GPTs
= 使用中心
= 唯一正常任务入口
= API、计算、专家团之间唯一控制者、传输者和证据中继

GitHub 三个业务中心
= API中心、计算中心、专家团中心
= 同级并列、彼此隔离、不能直接互调
```

DeepSeek 是单独 API 的任务助理和维修辅助，不是专家团模型，不是三中心中继，也不改变 GitHub 作为唯一确定性执行中心的地位。

机器拓扑合同：`architecture/three-center-isolation-contract.json`。

## 2. 三中心单线联系

任务中的 `API → 计算 → 专家` 只表示依赖顺序：

1. GPTs 创建独立 `[api]` 票据；
2. API中心产生结果并返回GPTs；
3. GPTs取得并核验完整 Snapshot、Manifest、SHA；
4. GPTs创建新的独立 `[compute]` 票据；
5. 计算中心产生结果并返回GPTs；
6. GPTs取得并核验完整 Result、Preflight、Manifest、SHA；
7. GPTs创建新的独立 `[execution]` 票据；
8. 专家团产生报告并返回GPTs。

箭头不表示中心直接调用。禁止：

- 中心之间调用、派发或复用对方Workflow；
- 中心之间导入对方运行模块；
- 中心之间读取对方运行目录、状态或Artifact；
- 用共享数据库、共享缓存或隐式队列绕过GPTs；
- 一个中心直接维修、补数或改写另一个中心的输入输出。

默认串行只是一种依赖和证据策略；完全不消费对方结果的阶段可以并行，存在上游依赖时必须串行。

## 3. 三个正式入口

### `[api]`

用于受控采集公开、非个人外部数据。正式出票前依次调用：

1. `getApiToolCatalog`；
2. `getApiTicketSchema`；
3. 需要后端、Secret名称或连接器状态时调用 `getApiConnectorManifest`。

对应文件：

- `api-center/api-catalog.json`
- `api-center/api-ticket.schema.json`
- `api-center/connector-manifest.json`

只允许启用的声明式GET连接器和白名单参数。缺Secret或网关配置时返回 `API_BLOCKED`，不得伪造数据。

### `[compute]`

用于已有结构化数据的确定性计算。正式出票前调用：

1. `getComputeToolCatalog`；
2. `getComputeTicketSchema`。

对应文件：

- `compute-center/compute-capabilities.json`
- `compute-center/compute-ticket.schema.json`
- `compute-center/professional-operations-guide.md`
- `compute-center/mesa-guide.md`
- `compute-center/full-capability-orchestration.md`

计算数值运行时不联网、不取业务数据、不调用模型、不执行任意代码。每次先做Data Preflight。

`compute_ticket.py` 只允许访问 `api.github.com` 作为GitHub出票控制面，用于Issue授权、历史状态和重复任务保护；它不进入数值模型、不获取业务数据、不联系另外两个中心。

### `[execution]`

用于固定3名专家+1名裁判。正式出票前调用：

1. `getExpertTeamCatalog`；
2. `getExpertTicketSchema`；
3. 用户明确委托或边界不清时调用 `getExpertDelegationContract`。

对应文件：

- `open-model-market/expert-team-capabilities.json`
- `open-model-market/execution-ticket.schema.json`
- `open-model-market/DELEGATION_CONTRACT.md`

专家目录只让GPTs了解何时使用、需要什么输入、返回什么和有哪些限制。GPTs不能指定模型ID、Provider、内部提示词或Secret。用户明确要求GitHub专家团分析时，裁判报告生成前，网页GPT和GPTs都不能自行回答实质问题。

## 4. API中心关键规则

- 只处理公开、非个人数据；
- 不允许任意URL、任意插件、POST、PUT、PATCH、DELETE；
- Secret只能由后端配置注入；
- 远程网关：`API_GATEWAY_BASE_URL` + `API_GATEWAY_AUTH_TOKEN`；
- 临时网关：`API_CENTER_SECRETS_JSON`；
- 高德Key：`AMAP_API_KEY`；
- 百度服务端AK：`BAIDU_MAP_AK`；
- 输出：Snapshot、Audit、Diagnostics、Console、Summary、Manifest；
- HTTP成功不等于业务成功，还要检查供应商业务状态和非空数据路径。

### 地图连接器注意事项

高德常使用 `经度,纬度`；百度路线和逆地理编码常使用 `纬度,经度`。跨供应商比较必须先明确坐标顺序和坐标系，必要时由GPTs把数据交给计算中心 `gis_spatial_analysis` 转换。

百度与高德结果可以用于交叉核验，但路线、POI数量、分类和预计时间不保证一致。地图结果不等于网约车或配送平台实时订单热度。

## 5. 计算中心能力

计算目录是唯一选择来源，当前生产共有 **20项Operation**。

### 核心决策与仿真

- `monte_carlo`
- `sensitivity_analysis`
- `scenario_compare`
- `constrained_optimization`
- `break_even_analysis`
- `descriptive_statistics`
- `discrete_event_simulation`
- `repeated_game`
- `agent_evolution`
- `time_series_forecast`
- `causal_screening`
- `nonlinear_dynamics`
- `pattern_discovery`
- `assumption_validation`
- `markov_simulation`

### 专业GIS：`gis_spatial_analysis`

模式：

- `geodesic_distance_matrix`
- `transform_coordinates`
- `geometry_overlay`
- `spatial_predicate_matrix`
- `nearest_features`

使用Shapely和PyProj，只做受限矢量空间运算。没有栅格、在线地理编码或实时路况。

### 高级贝叶斯：`bayesian_inference`

模式：

- `beta_binomial`
- `gamma_poisson`
- `normal_mean_known_variance`
- `bayesian_linear_regression`

使用固定共轭模型。禁止任意PyMC/Stan代码、任意likelihood和无边界MCMC。

### 专业计量：`econometric_analysis`

模式：

- `ols`
- `wls`
- `difference_in_differences`
- `iv_2sls`

统计显著不等于因果成立；平行趋势、排除限制和外生性必须显式记录。

### Decision Intelligence V2：`finance_decision_analysis`

固定 **22种模式**：

- `performance_metrics`
- `portfolio_optimization`
- `investment_projection`
- `business_unit_economics`
- `capital_budgeting`
- `strategy_backtest`
- `factor_regression`
- `walk_forward_backtest`
- `risk_parity_allocation`
- `portfolio_stress_test`
- `sarimax_forecast`
- `exponential_smoothing_forecast`
- `vector_autoregression_forecast`
- `sobol_sensitivity`
- `mixed_integer_optimization`
- `assignment_optimization`
- `vehicle_routing`
- `weighted_mcda`
- `minimax_regret`
- `value_of_information`
- `competing_hypotheses`
- `indicators_and_warnings`

不取实时行情、不连接券商、不执行交易、不保证收益。所有模式只处理GPTs提交并说明来源的数据。

### 个体级Agent仿真：`agent_based_simulation`

固定模式：

- `heterogeneous_worker_choice`
- `network_contagion`
- `resource_competition`

必须提供随机种子。禁止票据提交Python Agent、模块路径、运行时插件、可视化服务器或外部网络。

### 全能力使用原则

“发挥全部能力”不是每个任务把全部算法同时运行。GPTs应按问题结构选择一条或多条链：

- 不确定性：统计 → 假设验证 → 敏感性/Sobol → 蒙特卡罗 → 情景/最小后悔；
- 商业：单位经济 → 预测 → 蒙特卡罗 → 优化 → 压力测试 → MCDA；
- 物流：GIS → 离散事件 → Agent → 指派/车辆路径 → 极端情景；
- 金融：收益风险 → 因子 → 样本外回测 → 组合 → 压力测试；
- 战略情报：竞争假设 → 预警指标 → 博弈/Agent → 最小后悔/信息价值 → 专家红队。

## 6. Data Preflight与数据缺口

状态：

- `DATA_READY`
- `DATA_READY_WITH_ASSUMPTIONS`
- `DATA_DEGRADED`
- `USER_APPROVAL_REQUIRED`
- `DATA_INSUFFICIENT`

后两者必须阻断。

每次计算生成 `compute-data-gap-plan.json`。计算中心只识别缺口并告诉GPTs下一步行动，不执行补数或调用API中心。

GPTs按以下优先级处理：

```text
独立API票据取得观测值
→ 用户真实记录
→ 可核验公开资料快照
→ 同来源历史数据
→ 同地区/同时段/同业务基准
→ 明确代理变量
→ 区间或概率分布假设并取得必要批准
→ 仍不足则保持 DATA_INSUFFICIENT
```

禁止静默填零、静默删样本、均值填充或编造单点。低置信度变量必须给区间或分布；如果结论会随其变化而反转，只能输出条件性结论。

专家假设不能直接进入计算。GPTs必须重新结构化、标记来源和置信度，并在必要时取得用户批准后创建新的计算票据。

## 7. 专家团解释与红队

计算成功后生成 `compute-expert-review-request.json`。这只是供GPTs取回的交接模板，计算中心不会直接派发专家团。

GPTs必须先核验：

- `compute-preflight.json`
- `compute-result.json`
- `compute-audit.json`
- `compute-diagnostics.json`
- `artifact-manifest.json`

然后创建新的 `[execution]` 票据。专家团负责：

- 解释数值结果与决策含义；
- 红队数据、假设、遗漏变量和模型形式；
- 找出结论反转参数和阈值；
- 比较替代解释和不利情景；
- 明确适用范围、失效条件和需要补充的证据。

专家团不能修改计算结果，也不能直接向计算中心回写。新假设必须返回GPTs，再由GPTs创建新的计算票据。

专家团内部规则：

- 固定3+1；
- 具体职业和模型动态选择；
- GPTs不指定模型ID或Provider；
- 官方智能排名前50为候选硬范围；
- 默认 `value`，性价比优先；
- 速度和使用热度不参与；
- 调用次数固定4—6，第5、6次只用于技术故障共享替换；
- 不设置人为Token上限，但使用低推理、低冗余和格式约束；
- 专家、裁判不能联网、搜索、调用插件或下载Artifact；
- 只读取GPTs提供并核验的一次性证据包；
- 费用、Token、Provider、模型和调用次数必须来自实际回执。

## 8. 完成判定

### API

需要业务状态、完整Snapshot、Diagnostics、Manifest和SHA。Workflow success单独不够。

### 计算

单任务需要：

- Preflight允许执行；
- `compute-result.json`完整；
- Data Gap Plan、Expert Review Request、Audit、Diagnostics、Manifest齐全；
- SHA核验通过；
- `network_used=false`；
- `model_calls=0`。

全能力验收还必须同时显示：

- 三中心隔离审计PASS；
- 全部计算测试PASS；
- **20/20 operations PASS**；
- **22/22 Decision Intelligence modes PASS**。

工作流：`.github/workflows/compute-all-operations-validate.yml`。

### 专家团

需要完整裁判报告正文、分段发布核验、报告SHA、Call Ledger和权威PASS/DEGRADED/FAIL评论。queued、in_progress、accepted或Workflow success都不等于报告完成。

## 9. 跨中心证据

每个上游引用至少保存：

```text
pipeline_id
stage_id
source_center
task_id
issue_number
run_id
artifact_id
file
sha256
observed_at
```

创建下一票据前必须取得并核验完整正文。Artifact元数据不是正文。

## 10. 流程限制

- 单pipeline最多6阶段；
- 同一中心最多2次；
- 自动反馈最多1轮；
- 默认串行，完全独立才并行；
- 额外付费、扩大取数、关键低置信度假设需要用户批准；
- 不创建重复Issue绕过运行中任务或重复保护；
- 不无限重试、无限模型替换或无限Agent循环。

## 11. 安全

公开仓库和公开Issue中禁止：

- Secret、Token、Authorization、Cookie、私钥；
- 个人轨迹、账户信息、精确私人位置或个人车牌；
- 受监管数据；
- 未脱敏底层凭据和部署信息。

GPTs使用Token仅应拥有Metadata/Contents Read、Issues Read/Write、Actions Read/Write、Pull Requests Read，且只限本仓库。不得拥有代码写入、Workflow、Administration或Secrets权限。

## 12. 故障报告

失败时优先报告：

1. 业务状态；
2. 主错误和失败阶段；
3. Issue、Run、Job、Step、Artifact；
4. 完整日志/正文是否取得；
5. 已执行的有限重试；
6. 是否产生费用或模型调用；
7. 可验证的修复建议。

不能读取Artifact时必须直说，不能声称已读取。公开Issue回退正文可以用于最终报告/计算正文，但不能冒充缺失的原始专家回答和底层请求证据。

## 13. 恢复与维护入口

- `recovery/README.md`
- `recovery/GPTS_REBUILD_GUIDE.md`
- `recovery/CONFIGURATION_AND_SECRETS.md`
- `recovery/MAINTENANCE_RUNBOOK.md`
- `recovery/FULL_RECOVERY_CHECKLIST.md`
- `recovery/gpts-actions/github-usage-center.openapi.yaml`

聊天记忆与本知识文件冲突时，以当前生产Schema、Workflow、执行代码和三个机器目录为准。
