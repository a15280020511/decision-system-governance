# OpenRouter 付费旗舰模型严格筛选结果

状态：`TEST_ONLY_NOT_PRODUCTION`

- Workflow Run：`30966648889`
- 测试提交：`7b03011b70e6ffec1810e4aa423ede385702c9ab`
- 工作流结论：`success`
- OpenRouter Key：认证成功，密钥值未暴露
- 实时目录请求：2 次
- 模型调用：0
- 模型费用：0 美元
- OpenRouter 模型目录：338
- Artificial Analysis 三项基准可用模型：109
- 付费、稳定、全尺寸、纯文本且可比较模型：78
- 全球高等级模型：46
- 最终严格旗舰模型：19

## 最终价格第 1 名

```text
nex-agi/nex-n2-pro
```

- 公司：Nex AGI
- 旗舰依据：严格产品层 `Pro`；同系列存在 `Mini`，`Pro` 为较高产品层
- OpenRouter 价格排序位置：115
- 输入价格：0.25 美元/M tokens
- 输出价格：1.00 美元/M tokens
- Intelligence Index：41.0
- Coding Index：59.1
- Agentic Index：31.0
- 三项几何平均综合分：42.1934

## 价格从低到高的前 10 个严格旗舰候选

| 名次 | 模型 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 综合分 | 旗舰依据 |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `nex-agi/nex-n2-pro` | $0.25 | $1.00 | 41.0 | 59.1 | 31.0 | 42.19 | `Pro` 产品层 |
| 2 | `kwaipilot/kat-coder-pro-v2` | $0.30 | $1.20 | 33.7 | 59.5 | 15.5 | 31.44 | `Pro` 产品层 |
| 3 | `deepseek/deepseek-v4-pro` | $0.435 | $0.87 | 44.3 | 59.4 | 36.4 | 45.75 | `Pro` 产品层 |
| 4 | `xiaomi/mimo-v2.5-pro` | $0.435 | $0.87 | 42.2 | 60.2 | 29.1 | 41.97 | `Pro` 产品层、公司自然最高层 |
| 5 | `nvidia/nemotron-3-ultra-550b-a55b` | $0.60 | $3.60 | 37.8 | 49.3 | 27.4 | 37.10 | `Ultra` 产品层 |
| 6 | `z-ai/glm-5.2` | $0.76 | $2.42 | 51.1 | 68.8 | 43.1 | 53.31 | 公司自然最高层 |
| 7 | `qwen/qwen3.7-max` | $1.475 | $4.425 | 46.0 | 66.0 | 30.6 | 45.29 | `Max` 产品层 |
| 8 | `qwen/qwen3.8-max` | $2.00 | $6.00 | 53.4 | 68.9 | 49.9 | 56.84 | `Max` 产品层、公司自然最高层 |
| 9 | `moonshotai/kimi-k3` | $3.00 | $15.00 | 57.1 | 76.2 | 50.1 | 60.18 | 公司自然最高层 |
| 10 | `openai/gpt-5.6-luna` | $0.10 | $0.60 | 51.2 | 71.4 | 45.6 | 55.04 | 公司自然最高层；其 OpenRouter 综合价格顺序位于前述候选之后 |

说明：名次严格沿 OpenRouter `pricing-low-to-high` 的官方返回顺序，不以单独输入价重新排序。因此某模型输入单价更低，不代表其综合价格顺序更靠前。

## 关键纠错

- `deepseek/deepseek-v4-flash-0731`：排除，因为 `Flash` 是效率/速度产品层，不是旗舰层。
- `xiaomi/mimo-v2.5`：排除；“Pro-level performance”属于能力描述，OpenRouter 官方把 `mimo-v2.5-pro` 明确列为小米旗舰。
- `inclusionai/ring-2.6-1t`：排除；公司在可比较集合中只有单个普通候选，且无严格旗舰产品层证据。
- `meta/muse-spark-1.1`：排除；`Spark` 属于速度/紧凑产品层，且缺少严格旗舰证据。
- `deepseek/deepseek-v4-pro`：正常进入旗舰池，排名第 3。

## 严格筛选规则

1. 只保留付费、未过期、非 Preview/Beta/Experimental 的通用文本模型；
2. 排除 Flash、Mini、Nano、Micro、Small、Lite、Fast、Spark 等经济或速度层；
3. 使用 OpenRouter Artificial Analysis 的 Intelligence、Coding、Agentic 三项数据形成平衡能力分；
4. `Pro / Max / Opus / Ultra / Premier` 作为严格旗舰产品层证据；
5. 没有上述命名的模型，必须进入其公司模型分布中的自然最高能力层；
6. `frontier / top-tier / state-of-the-art / Pro-level` 等泛能力描述不能单独证明旗舰身份；
7. 合并所有公司的旗舰模型后，保持 OpenRouter 官方 `pricing-low-to-high` 顺序，选择第一个。

本次仅测试目录筛选能力，没有调用候选模型执行代码维护、红队、逻辑、路由或仓库管理任务，尚未进入 `main` 或 `production`。
