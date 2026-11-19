# 中台记账、风控与 AI 数字一致性

## 检查结论

中台的核心业务和 HTTP 服务使用 Python，账本由 SQLite 保存。仓库中的 C++/Qt 文件只是上游连接示例。

本次检查前已有：

| 职责 | 实际代码 | 检查结果 |
| --- | --- | --- |
| 记账、成本与盈亏 | `MiddleOffice._try_fill`、`_portfolio`，`Store.transaction` | 已有。成交、余额、持仓、成本、交易记录在同一写事务内更新 |
| 交易前风控 | `place_order`、`_check_suitability` | 已有。检查可用资金、可卖数量、订单限额及配置后的产品适当性 |
| 持仓风险监测 | `_monitor` | 已有。集中度和浮亏比例命中阈值后预警，不会因此自动卖出 |
| AI 解释与辅助统计 | 杨昊岳项目的 `Assistant.respond`、`risk.portfolio_risk` | 已有，但在他的仓库里。他的 AI 从中台读取账户，再独立取价计算估值与集中度 |
| 两端使用同一份账户和估值事实 | 原 `/snapshot` 与 `/quotes` 是两次读取 | 原来未完整实现，行情或持仓更新可能使两次读取落在不同版本 |

只统一交易所名称和报价时间仍不够，还要统一持仓版本、计价币、计算公式和小数精度。例如他的旧 `risk.py` 会将现金计入“最大资产集中度”，中台预警则逐项检查交易持仓，二者名称和范围也要明确，不能直接视为同一个指标。

## 本次补上的中台代码

新增只读接口：

```http
GET /api/accounts/{user_id}/analysis_snapshot
Authorization: Bearer <MO_AI_READ_TOKEN>
```

核心入口在 [service.py](../middle_office/service.py) 的 `analysis_snapshot`：

```python
with self.store.transaction() as state:
    as_of = self.clock()
    account = self._account(state, user)
    snapshot = self._snapshot(state, user, as_of=as_of)
    portfolio = self._portfolio(state, user, as_of=as_of)
    # 使用同一份账本、同一个估值时刻，生成官方风险指标及快照编号。
```

接口返回：

| 字段 | 含义 |
| --- | --- |
| `snapshot_id` | 本次返回内容的 SHA-256 编号，用来判断双方是否引用同一份报告；不是数字签名或访问凭证 |
| `as_of` | 本次冻结的账本读取及估值时刻 |
| `account` | 持仓币种数量和未成交挂单，保留原快照的 50 行上限与 `truncated` 标记 |
| `portfolio` | 中台已计算的总资产、已实现/未实现盈亏、成本、余额、手续费及各项持仓估值 |
| `portfolio.valuation_quotes` | 本次估值实际使用的报价，含交易对、价格、来源、报价时间 |
| `portfolio.positions[].market_price/source/as_of` | 每项持仓的估值价格及其依据 |
| `risk.position_metrics` | 中台持仓预警使用的同一套集中度、浮亏比例、阈值及是否命中 |
| `basis` | 估值选择规则、计价及舍入口径 |
| `state/reasons` | 完整状态或缺失原因；缺失报价、过期报价或账户截断会明确标记 |

实现要点：

1. 一个数据库读取事务取得同一份账户、订单和行情状态。
2. 只读取一次估值时刻，避免计算中途跨过 120 秒报价过期边界而出现部分新鲜、部分过期的判定。
3. 每个交易对采用最新的有效报价；相同时间按来源名称稳定选择，与中台估值保持一致。
4. 数量和金额保持十进制字符串，金额统一最多 8 位小数，显式使用 `ROUND_HALF_EVEN`。
5. `_position_risk_values` 被预警模块和本报告共用，避免二者各写一套公式。命中判断使用未舍入比率，输出值再按约定舍入。
6. 数据不完整时完整总资产、未实现盈亏为 `null`，不会把缺失估值当成零。`observed_assets` 仅代表已估值部分。

集中度公式为 `持仓市值 / 含现金的总资产 × 100`。浮亏比例为 `-未实现盈亏 / 成本 × 100`；盈利时该值可为负数。预警记录保留最初命中时的证据，本报告的风险值则是本次快照时点的计算结果。

各资产的实际报价时间可以不同；“同一时点”指两端共同使用同一份报告中已经选定的报价，不能把报告顶层的 `as_of` 当成所有交易所的报价时间。

成交报价与持仓估值也有不同用途：模拟成交按买入 ask / 卖出 bid 及费用规则执行；报告使用选定的估值 price。当前市值与历史成交价不同是正常情况。

## AI 侧 Python 调用示例

完整示例见 [examples/ai/consistent_analysis.py](../examples/ai/consistent_analysis.py)，仅使用 Python 标准库。

```python
from examples.ai.consistent_analysis import fetch_analysis, build_explanation_context

report = fetch_analysis(
    "http://127.0.0.1:8200/api",
    "demo_user",
    "replace-with-read-only-token",
)

# 前端展示中台数字；AI 从同一个 report 构建解释上下文。
frontend_numbers = report["portfolio"]
ai_context = build_explanation_context(report)

assert frontend_numbers["total_assets"] == ai_context["official_numbers"]["total_assets"]
assert report["snapshot_id"] == ai_context["snapshot_id"]
```

该示例把中台已经计算好的资产、盈亏、风险结果直接传入上下文，AI 侧仅附加已返回挂单的买入/卖出数量统计，不再次取价计算官方数字，也不下单或修改账本。若挂单被截断，辅助统计明确标为不完整。

模型负责生成文字。前端金额应直接展示 `official_numbers` 中的值，避免模型自行生成或舍入金额；提示词本身不能保证模型永远准确复述数字。

运行示例（中台已经启动，并已有 `demo_user` 账户）：

```bash
export MO_AI_READ_TOKEN='replace-with-read-only-token'
python3 examples/ai/consistent_analysis.py --user demo_user
```

跨电脑时增加 `--base-url http://中台实际IPv4:8200/api`。

## 与杨昊岳如何落地

他的现有 `/snapshot` 读取方式继续兼容，但不会自动切换到新报告。仅设置旧的 `AI_MVP_TRADING_URL` 仍会使用旧路径。

需要他在 AI 后端引入上述读取与上下文构建逻辑：

- 一轮涉及账户数字的回答，获取一次报告，并将 `build_explanation_context(report)` 加入模型上下文。
- 如果前端也显示同一轮报告的资产数字，前端与 AI 后端共享这一个报告对象及 `snapshot_id`，不要各自重新查询“最新”报告后要求完全相同。
- 对总资产、盈亏、集中度与阈值，采用报告的官方字段。保留旧 `risk.py` 做独立分析时，需明确其统计名称与范围；不能把不同口径的结果当成中台同一指标。
- 使用本报告的 `portfolio.valuation_quotes` 作本轮估值依据，不再另外查询更新后的 `/quotes`；其他独立行情问答可继续查询实时行情。
- 不完整报告按 `state/reasons` 明确说明；不能通过更换为更新报价或缓存报价，悄悄补齐这一份旧报告。

目前已经完成并测试的是：中台的新接口、共享预警公式和 Python 调用示例。**本次没有修改他的仓库，也没有将新路径自动接进他现有的聊天或风险路由。** 双方仍需按以上规则完成接线。

`snapshot_id` 是报告内容编号，当前没有按编号重新下载历史报告的接口。若要复用旧报告，应由调用方保留该 JSON；事后再次 GET 得到的可能是新报告。旧报告仍可作为该历史时点的事实，不能宣称其一定代表现在的行情。

## 验证

```text
python -B -W error::ResourceWarning -m unittest discover -s tests -v
```

当前 38 项测试通过，其中 9 项新增测试覆盖：来源和官方数字传递、统一估值时钟、缺失报价保留未知值、后续报价/成交不改写旧报告、读取期间并发写入、风险值与相同时点预警公式一致、内容混改检测、舍入规则及只读 HTTP 调用。

原有杨昊岳 AI 联调脚本也重新通过；它验证的是原有兼容路径，不能据此声称他的 AI 已经采用新增的一致性报告。新示例没有调用真实模型。
