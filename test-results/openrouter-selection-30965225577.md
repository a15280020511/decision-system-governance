# OpenRouter 治理模型目录测试结果

状态：`TEST_ONLY_NOT_PRODUCTION`

- Workflow Run：`30965225577`
- 测试提交：`56b13ac1eed2289ec20f79e14c739f844527dcbf`
- OpenRouter Key：认证成功，密钥值未暴露
- 实时目录请求：2 次
- 模型调用：0
- 模型费用：0 美元
- 智力排序目录模型数：338
- 价格排序目录模型数：338
- 两榜交集：338

## 字面规则的选中结果

当前测试把“出现在 `intelligence-high-to-low` 目录”定义为高等级。由于该目录返回全部 338 个文本模型，按 `pricing-low-to-high` 选择时，字面结果为：

```text
cohere/north-mini-code:free
```

- 公司：Cohere
- 智力榜位置：76
- 输入价格：0 美元/M tokens
- 输出价格：0 美元/M tokens
- 上下文：256,000

## 价格最低的候选

| 价格顺序 | 模型 | 智力榜位置 | 输入价/M | 输出价/M |
|---:|---|---:|---:|---:|
| 1 | `cohere/north-mini-code:free` | 76 | $0 | $0 |
| 2 | `google/gemma-4-26b-a4b-it:free` | 65 | $0 | $0 |
| 3 | `google/gemma-4-31b-it:free` | 60 | $0 | $0 |
| 4 | `google/lyria-3-clip-preview` | 172 | $0 | $0 |
| 5 | `google/lyria-3-pro-preview` | 173 | $0 | $0 |
| 6 | `inclusionai/ling-3.0-flash:free` | 178 | $0 | $0 |
| 7 | `nvidia/nemotron-3-nano-30b-a3b:free` | 94 | $0 | $0 |
| 8 | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 215 | $0 | $0 |
| 9 | `nvidia/nemotron-3-super-120b-a12b:free` | 67 | $0 | $0 |
| 10 | `nvidia/nemotron-3-ultra-550b-a55b:free` | 39 | $0 | $0 |
| 11 | `nvidia/nemotron-3.5-content-safety:free` | 216 | $0 | $0 |
| 12 | `nvidia/nemotron-nano-12b-v2-vl:free` | 217 | $0 | $0 |
| 13 | `nvidia/nemotron-nano-9b-v2:free` | 218 | $0 | $0 |
| 14 | `openai/gpt-oss-20b:free` | 88 | $0 | $0 |
| 15 | `poolside/laguna-s-2.1:free` | 276 | $0 | $0 |
| 16 | `poolside/laguna-xs-2.1:free` | 278 | $0 | $0 |
| 17 | `inclusionai/ling-2.6-flash` | 95 | $0.01 | $0.03 |
| 18 | `mistralai/mistral-nemo` | 199 | $0.019 | $0.03 |
| 19 | `ibm-granite/granite-4.0-h-micro` | 175 | $0.017 | $0.112 |
| 20 | `nex-agi/nex-n2-mini` | 210 | $0.025 | $0.10 |

## 结论

本次测试证明治理仓能够使用 `OPENROUTER_API_KEY` 读取实时模型目录并完成价格排序。

但 OpenRouter 当前没有返回一个可直接使用的“高等级模型=true”分类字段；`intelligence-high-to-low` 只是排序，不是高等级集合。若把整张智力榜视为高等级集合，全部 338 个模型都会进入候选，最终会选中免费但智力排名第 76 的 `cohere/north-mini-code:free`。

因此，本结果只证明目录连接和字面算法可运行，不代表该模型已经通过治理维护、代码、红队、逻辑和路由实测，也未进入 `main` 或 `production`。
