# OpenRouter 付费高等级治理模型筛选结果

状态：`TEST_ONLY_NOT_PRODUCTION`

- Workflow Run：`30965714212`
- 测试提交：`f3131c801c13141122d7ac8ee06b5de083a52d6c`
- OpenRouter Key：认证成功，密钥值未暴露
- 实时目录请求：2 次
- 模型调用：0
- 模型费用：0 美元
- OpenRouter 模型目录：338
- Artificial Analysis 可用基准模型：109
- 付费、稳定、纯文本且三项基准完整的模型：99
- 第一阶段高层模型：56
- 最终高等级付费模型：19

## 最终选中

```text
deepseek/deepseek-v4-flash-0731
```

- 公司：DeepSeek
- 输入价格：0.09 美元/M tokens
- 输出价格：0.18 美元/M tokens
- Intelligence Index：49.9
- Coding Index：69.1
- Agentic Index：45.7
- 三项几何平均综合分：54.0130

## 最便宜的高等级付费候选

| 价格顺序 | 模型 | 输入价/M | 输出价/M | Intelligence | Coding | Agentic | 综合分 |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | `deepseek/deepseek-v4-flash-0731` | $0.09 | $0.18 | 49.9 | 69.1 | 45.7 | 54.01 |
| 2 | `z-ai/glm-5.2` | $0.76 | $2.42 | 51.1 | 68.8 | 43.1 | 53.31 |
| 3 | `qwen/qwen3.8-max` | $2.00 | $6.00 | 53.4 | 68.9 | 49.9 | 56.84 |
| 4 | `meta/muse-spark-1.1` | $1.25 | $4.25 | 50.6 | 71.3 | 37.5 | 51.34 |
| 5 | `moonshotai/kimi-k3` | $3.00 | $15.00 | 57.1 | 76.2 | 50.1 | 60.18 |
| 6 | `openai/gpt-5.6-luna` | $0.10 | $0.60 | 51.2 | 71.4 | 45.6 | 55.04 |
| 7 | `openai/gpt-5.6-terra` | $1.00 | $6.00 | 55.0 | 76.7 | 47.4 | 58.48 |
| 8 | `x-ai/grok-4.5` | $2.00 | $6.00 | 53.8 | 72.4 | 45.7 | 56.25 |
| 9 | `anthropic/claude-sonnet-5` | $2.00 | $10.00 | 53.4 | 71.5 | 46.7 | 56.28 |
| 10 | `openai/gpt-5.4` | $2.50 | $15.00 | 51.4 | 71.1 | 41.1 | 53.16 |
| 11 | `anthropic/claude-sonnet-4.6` | $3.00 | $15.00 | 47.2 | 63.0 | 40.8 | 49.50 |
| 12 | `google/gemini-3.6-flash` | $1.50 | $7.50 | 50.1 | 69.2 | 38.7 | 51.19 |
| 13 | `google/gemini-3.5-flash` | $1.50 | $9.00 | 50.2 | 70.1 | 37.4 | 50.87 |
| 14 | `anthropic/claude-opus-4.7` | $5.00 | $25.00 | 53.5 | 73.6 | 44.4 | 55.92 |
| 15 | `anthropic/claude-opus-4.8` | $5.00 | $25.00 | 55.7 | 74.3 | 47.2 | 58.02 |
| 16 | `anthropic/claude-opus-5` | $5.00 | $25.00 | 60.7 | 78.0 | 55.3 | 63.97 |
| 17 | `openai/gpt-5.5` | $5.00 | $30.00 | 54.8 | 74.9 | 44.9 | 56.91 |
| 18 | `openai/gpt-5.6-sol` | $5.00 | $30.00 | 58.9 | 77.4 | 54.0 | 62.67 |
| 19 | `anthropic/claude-fable-5` | $10.00 | $50.00 | 59.9 | 76.5 | 52.8 | 62.31 |

## 筛选规则

1. 只保留至少一个 OpenRouter 计费字段大于 0 的付费模型；
2. 只保留文本输入、纯文本输出模型；
3. 排除已过期、Preview、Beta、Experimental 模型；
4. 要求 OpenRouter Artificial Analysis 同时提供 Intelligence、Coding、Agentic 三项成绩；
5. 三项成绩使用几何平均值形成平衡能力分；
6. 不设置固定分数线，连续两次按照实时成绩分布提取上层自然分组；
7. 在最终高等级组中沿 OpenRouter `pricing-low-to-high` 顺序选择最便宜者。

本结果仅完成目录筛选，没有调用候选模型执行代码维护、红队、逻辑、路由或仓库管理任务，尚未进入 `main` 或 `production`。
