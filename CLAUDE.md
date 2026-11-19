# FTEC5510 Group 20 Middle Office

本仓库实现数字资产模拟交易中台。服务使用 Python 3.10+ 标准库、SQLite 和 HTTP/JSON。C++/Qt 与 AI 示例通过 HTTP 接入。默认监听 `127.0.0.1:8200`。

## 三人分工

| 维护角色 | 负责范围 |
| --- | --- |
| 中台（ALLE77-maker） | `middle_office/` 中除 `market.py`、`client.py` 外的 Python 文件，负责 HTTP API、账本、订单、风控和数据校验。`docs/API.md` 和 `docs/RULES.md` 由中台维护。 |
| 行情与 Qt 接入（XU Fangzhou） | `middle_office/market.py`、`middle_office/client.py`、`examples/qt/`，负责行情接入、HTTP 客户端与 Qt 示例。 |
| AI 联调（杨昊岳） | `examples/ai/`、`scripts/check_ai_integration.py`、`docs/AI_NUMBER_CONSISTENCY.md` 和 `对接杨昊岳.md`，负责只读接口接入及数据一致性检查。 |

`tests/` 按被测功能归属。`README.md`、`docs/INTEGRATION.md` 和协作配置由三人共同维护。开始前在任务或 PR 中写清改动范围。需要改其他人的文件时，先协调并请对应维护者审查。外部对接分工见 [联调文档](docs/INTEGRATION.md)。

## 代码与接口

- Python 用 4 空格缩进。函数、模块和变量用 `snake_case`，类用 `PascalCase`，常量用 `UPPER_SNAKE_CASE`。新增代码沿用相邻文件的风格。
- 行情、金额和数量沿用 `validation.py` 的校验。用 `Decimal` 计算，按已有接口用十进制字符串传输。报价保留原采集时间，时间字段使用带时区的 RFC 3339 格式。
- 写入账本沿用 SQLite 事务，保留账户隔离、订单请求去重和预留资金语义。变更 HTTP 字段、状态码或权限时，同步更新接口文档和相关测试，并确认调用方兼容。
- AI 凭证仅用于读取行情、账户和分析快照。AI 解释账户估值和风险时，使用 `analysis_snapshot` 提供的同批数据和报价依据。

```python
from middle_office.validation import amount, number

quantity = number(payload["quantity"], "quantity", positive=True)
serialized_quantity = amount(quantity)
```

## 常用命令

在仓库根目录运行。macOS 可用 `python3`。

```sh
python -m middle_office
python -m middle_office.demo
python -B -m unittest discover -s tests -v
python -B scripts/check_ai_integration.py --ai-source ../crypto-ai-mvp
```

服务与演示分别在两个终端运行。最后一条命令用于 AI 联调，需要本地已有同级的 `crypto-ai-mvp`，只用模拟数据和临时数据库。

## 本地配置

- [`.env.example`](.env.example) 只记录配置项。程序从进程环境读取变量。真实 Token 留在本机，AI 只读 Token 和业务写入 Token 必须不同。
- 本地 `.env*`、账本数据库、私钥和个人 AI 配置不可提交。涉及数据的测试与演示使用虚构账户和报价。
- AI 在任务约定的范围内改动文件。业务阈值、接口权限及其他成员负责的代码，需要对应维护者确认。

## 分支与审查

- `main` 保持可运行。每人从最新的 `main` 开自己的 `feat/名字/任务名` 分支，提交前确认 diff。提交消息统一用 `type: 变更摘要`。
- 提 PR 前 rebase 到 `origin/main` 并验证。可用 AI 协助解冲突，由作者逐处核对合并意图并重跑相关测试。
- 作者先运行 `/middle-office-review`，再请至少一位其他成员审查。PR 附上改动范围、验证结果和 AI 发现的处理情况。人工批准并通过检查后合并，随后删除功能分支。
- `CLAUDE.md`、`AGENTS.md` 和共享 `.claude/` 的变更须提交并走 PR，请其余两位成员审查。操作步骤见 [三人协作指南](docs/COLLABORATION.md)。
