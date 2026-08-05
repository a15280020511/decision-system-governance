# OpenRouter 付费通用旗舰模型筛选结果

状态：`TEST_ONLY_NOT_PRODUCTION`

- Workflow Run：`30967195054`
- 测试提交：`a16f1207d7ae642c22b10adcd47e6cd2aa244ff2`
- OpenRouter Key：认证成功，密钥值未暴露
- OpenRouter 模型目录：338
- Artificial Analysis 可用基准模型：109
- 付费、稳定、完整层级且三项基准完整：78
- 全球高层模型：46
- 最终通用旗舰候选：18
- 模型调用：0
- 模型费用：0 美元

## 最终第 1 名

```text
nex-agi/nex-n2-pro
```

- 公司：Nex AGI
- OpenRouter 价格榜位置：115
- 输入价格：0.25 美元/M tokens
- 输出价格：1.00 美元/M tokens
- Intelligence Index：41.0
- Coding Index：59.1
- Agentic Index：31.0
- 综合分：42.1934
- 旗舰依据：正式 `Pro` 产品层级

## 价格从低到高的通用旗舰候选

| 顺序 | 模型 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 综合分 | 旗舰依据 |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `nex-agi/nex-n2-pro` | $0.25 | $1.00 | 41.0 | 59.1 | 31.0 | 42.19 | Pro 产品层级 |
| 2 | `deepseek/deepseek-v4-pro` | $0.435 | $0.87 | 44.3 | 59.4 | 36.4 | 45.75 | Pro 产品层级 |
| 3 | `xiaomi/mimo-v2.5-pro` | $0.435 | $0.87 | 42.2 | 60.2 | 29.1 | 41.97 | Pro 产品层级 |
| 4 | `nvidia/nemotron-3-ultra-550b-a55b` | $0.60 | $3.60 | 37.8 | 49.3 | 27.4 | 37.10 | Ultra 产品层级 |
| 5 | `z-ai/glm-5.2` | $0.76 | $2.42 | 51.1 | 68.8 | 43.1 | 53.31 | 公司自然最高层 |
| 6 | `qwen/qwen3.7-max` | $1.475 | $4.425 | 46.0 | 66.0 | 30.6 | 45.29 | Max 产品层级 |
| 7 | `qwen/qwen3.8-max` | $2.00 | $6.00 | 53.4 | 68.9 | 49.9 | 56.84 | Max 产品层级 |
| 8 | `moonshotai/kimi-k3` | $3.00 | $15.00 | 57.1 | 76.2 | 50.1 | 60.18 | 公司自然最高层 |
| 9 | `openai/gpt-5.6-luna` | $0.10 | $0.60 | 51.2 | 71.4 | 45.6 | 55.04 | 公司自然最高层；OpenRouter 综合价格榜位置较后 |
| 10 | `openai/gpt-5.6-terra` | $1.00 | $6.00 | 55.0 | 76.7 | 47.4 | 58.48 | 公司自然最高层 |
| 11 | `anthropic/claude-sonnet-5` | $2.00 | $10.00 | 53.4 | 71.5 | 46.7 | 56.28 | 公司自然最高层 |
| 12 | `openai/gpt-5.4` | $2.50 | $15.00 | 51.4 | 71.1 | 41.1 | 53.16 | 公司自然最高层 |
| 13 | `anthropic/claude-opus-4.7` | $5.00 | $25.00 | 53.5 | 73.6 | 44.4 | 55.92 | Opus 产品层级 |
| 14 | `anthropic/claude-opus-4.8` | $5.00 | $25.00 | 55.7 | 74.3 | 47.2 | 58.02 | Opus 产品层级 |
| 15 | `anthropic/claude-opus-5` | $5.00 | $25.00 | 60.7 | 78.0 | 55.3 | 63.97 | Opus 产品层级 |
| 16 | `openai/gpt-5.5` | $5.00 | $30.00 | 54.8 | 74.9 | 44.9 | 56.91 | 公司自然最高层 |
| 17 | `openai/gpt-5.6-sol` | $5.00 | $30.00 | 58.9 | 77.4 | 54.0 | 62.67 | 公司自然最高层 |
| 18 | `anthropic/claude-fable-5` | $10.00 | $50.00 | 59.9 | 76.5 | 52.8 | 62.31 | 公司自然最高层 |

## 准确度修正

本轮额外排除了 `kwaipilot/kat-coder-pro-v2`。虽然名称包含 `Pro`，但它是代码专用型号，不属于通用仓库治理旗舰模型。

筛选规则：

1. 排除免费、已过期、Preview、Beta、Experimental；
2. 排除 Flash、Mini、Nano、Lite 等经济或速度层级；
3. 要求付费、稳定、文本输入输出，并具有 Intelligence、Coding、Agentic 三项基准；
4. 旗舰身份来自正式产品层级（Pro、Max、Opus、Ultra、Premier）或公司内部自然最高能力层；
5. 排除 Coder、Safety、Guard、Embedding、Rerank 等领域专用模型；
6. 保留 OpenRouter `pricing-low-to-high` 的官方顺序，选择第一个剩余模型。

## 结论

按当前 OpenRouter 官方综合价格排序，最便宜的付费通用旗舰模型是 `nex-agi/nex-n2-pro`。`deepseek/deepseek-v4-pro` 排第 2。此测试仅完成目录筛选，尚未调用模型验证真实代码维护、红队、逻辑、路由和仓库管理能力，也未进入 `main` 或 `production`。
