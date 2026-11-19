# 组员联调与职责交接

## 本次代码审查基准

杨昊岳仓库为 https://github.com/phillipyang62/crypto-ai-mvp ，审查基准为提交 `bcfd2220e3c3ab1f47deb983fb3869fa692542f3`（2026-11-18）。已阅读 `providers.py`、`profiles.py`、`risk.py`、`simulation.py`、`assistant.py`、`server.py` 和接口联调文档。

本项目覆盖六个中控模块。AI 只读兼容入口是其中一部分。采用独立 Python HTTP 服务和 SQLite 保存业务状态，便于网页、原有 C++/Qt 连接器和 AI 分别接入。Qt 示例为接线参考，尚未在 Qt 环境编译。

## 与其他组员需要协调的内容

| 对接方 | 提供给中控 | 从中控读取 | 需要确定 |
| --- | --- | --- | --- |
| 前端 LIU Yibo | 用户设置、创建模拟账户、买卖和撤单请求 | 比价、订单状态、持仓、盈亏、余额、预警 | 前端或业务后端根据登录会话确定 user_id。按钮在返回 filled 后刷新，不凭本地乐观状态改持仓。真实登录另行对接。 |
| 行情及连接器 XU Fangzhou | 报价的交易对、来源、采集时间、price/bid/ask，模拟费率 | 订单处理结果或账户快照 | 使用推送或轮询。保留报价真实时间。原交易网关当前未提供完成的成交链路，本次由中控生成模拟成交。 |
| 问卷 Peng Jun | 已计算的五维分数、RAI、C1-C5、R1-R5、限制和版本 | 可回读已接收结果 | 问卷组为评分权威。同一个派生数据包同步给中控与 AI，核对版本与内容。 |
| AI 杨昊岳 | 查询报价和账户快照的请求 | 币种数量、挂单方向数量、报价计价币和来源 | 用只读 Token。配置见下。账户数据不反向改写账本。 |

前端对接建议顺序为建账户、推报价、保存偏好和问卷、提交订单、查 portfolio、查 orders、查 alerts。撤单后重新查询可用资金。所有开发组都使用同一 user_id。

## 原 C++/Qt dev.zip 的接入位置

- `BusinessEngine::_handle_md` 在保留 UI 更新的同时，将 `ExtMD` 转成行情 JSON，POST `/api/quotes`。
- `ExtMD.symbol` 转 symbol，exchange 转 source，datetime 转带时区 RFC 3339，last_px 转 price，bid_px/ask_px 转 bid/ask。采集时间不能在重试时改成当前时间。
- `BusinessEngine::OnPlaceOrder` 将用户请求提交 `/api/accounts/{id}/orders`，解析返回状态。中控已完成风控和模拟成交，旧版 `OnReqOrderApproval` 的“始终批准”演示应从实际链路退出。
- `BusinessEngine::OnCancelOrder` 使用中控返回的 `order_id` 发起撤单。
- 原 `Common.h` 的整数数量不能表示 `0.01 BTC`。传输时采用十进制字符串，UI 与原 C++ 数据结构需一起调整。
- 原 `OrderType` 的 Gfd/Fak/Fok 与本服务的 market/limit 不是同一维度。首次联调仅映射 market/limit，生命周期参数另定。
- 参考 `examples/qt/MiddleOfficeClient.h`，CMake 增加 Qt6 Network。所有 Qt 网络对象在 BusinessEngine 所在线程创建。
- 每笔订单与成交由中控维护。未来如果交易模拟器提供执行回报，再定义单独的入账协议，避免两边同时生成成交。

## 与 AI 重合的地方及建议分工

| 功能 | 杨的现有代码 | 本中控代码 | 交接结论 |
| --- | --- | --- | --- |
| 行情检索及校验 | `QuoteBook` 保存报价，`HttpMarketProvider` 查询上游并检查时效 | 多来源行情、费用比较、估值和执行报价 | 中控输出行情事实，AI 继续做输入检查。AI 的缓存可以保留作降级用途。 |
| 交易对与来源 | QuoteBook 按交易对合并，最终一交易对一条价格 | 每个交易对保留多平台来源 | `/api/quotes` 特意按交易对合并以兼容。AI 要回答跨平台费用差，需新增读取 `/api/comparison` 的工具，或由前端传该比较结果。 |
| 风险画像存储 | profiles.py 校验并保存五维派生评分，决定 education/advisory 路线 | 保存同源测评供订单限制使用 | 问卷组计算评分。中控和 AI 各自保存所需副本，两边按同一输入更新。前端核对版本，避免各自重算 RAI。 |
| 持仓估值与集中度 | risk.py 独立按行情和只读快照计算净值、敞口和最大资产比例，挂单只计数 | 计算成本、盈亏、可用余额、持仓集中度和执行预警 | 这里确有计算重合。中控负责交易账本和是否放行。新增 `/analysis_snapshot` 在同次读取中返回官方数字及报价依据；AI 接入后共享该报告作解释和辅助统计。旧路径不自动保证数字一致，见 [具体代码](AI_NUMBER_CONSISTENCY.md)。 |
| 产品风险上限 | simulation.py 根据 R1-R5 和禁止项筛选两类教育模拟场景 | 可配置产品风险等级，限制新增买单 | AI 的“模拟建议”是教育场景选择，中控的“模拟成交”负责改变账本。两边用途清楚分配。 |
| 反洗钱 | 仓库没有 AML 告警案件及人工复核流程 | 成交后大额和频率检测、告警记录与人工复核 | 由中控实现。AI 只读凭证不开放此内部复核接口。 |

产品 R 档与订单限额的演示值需小组确认。当前没有擅自把 BTC 或稳定币判为某个 R 档。配置产品风险文件后，中控才按问卷上限检查该产品。已有 prohibitions 会限制新买入，减仓卖出保留可执行路径。

## 杨的服务如何直接连接

中控侧设置两个不同的凭证，并启动服务。以下全部为示例占位值。

```powershell
$env:MO_API_TOKEN = 'replace-operator-token'
$env:MO_AI_READ_TOKEN = 'replace-read-only-token'
python -m middle_office --port 8200
```

在杨的项目目录设置，下面的两个中控 Token 均使用上面的只读值。

```powershell
$env:AI_MVP_API_TOKEN = 'replace-ai-server-token'
$env:AI_MVP_MARKET_URL = 'http://127.0.0.1:8200/api'
$env:AI_MVP_TRADING_URL = 'http://127.0.0.1:8200/api'
$env:AI_MVP_MARKET_TOKEN = 'replace-read-only-token'
$env:AI_MVP_TRADING_TOKEN = 'replace-read-only-token'
python -m ai_mvp
```

跨机器时，替换为中控机器实际内网 IPv4，并通过 `--host` 监听该地址。AI 自身也需在对外提供服务时设置对应监听地址。用户身份在可信后端确认，服务 Token 不放入浏览器页面。

用户问卷派生数据先 PUT 中控 `/api/accounts/{user_id}/assessment`，将返回的标准化结果 PUT AI `/v1/profiles/{user_id}`。读取持仓只需 AI 当前的 `include_account: true`，无需更改杨的代码。

## 实际已验证和仍需联调

`scripts/check_ai_integration.py` 使用杨仓库的实际 HttpMarketProvider、HttpTradingProvider、Assistant 和 ApiServer。它同时启动两端临时服务，验证有权限的行情查询、账户快照、未成交卖单、风险汇总、问卷提交和模板对话，避免只检查 JSON 外形。

该检查使用离线模板，没有调用他的真实 Ollama 或 DeepSeek 账号。组员仍需在各自电脑验证局域网地址、防火墙、凭证，以及前端真实下单按钮和 Qt 接线。
