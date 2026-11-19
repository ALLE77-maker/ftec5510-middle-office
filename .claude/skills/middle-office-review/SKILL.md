---
name: middle-office-review
description: 审查 FTEC5510 中台分支，检查业务回归、接口兼容、凭证和测试，起草提交消息和 PR 描述。
disable-model-invocation: true
---

1. 阅读 `CLAUDE.md`。用 `git status --short` 查看工作区，用 `git diff origin/main...HEAD` 看已提交的分支差异。另查 `git diff HEAD` 和新增的未跟踪文件，把尚未提交的发现单独标明。找不到 `origin/main` 时先提示运行 `git fetch origin`。
2. 根据改动核对调用方与测试。重点检查金额精度、订单去重和预留、SQLite 事务、报价时效、账户隔离、AI 只读权限和凭证泄露。发现接口变化时，检查文档和消费方是否同步。
3. 按严重程度报告发现，每条给出文件和行号、触发条件、影响以及修复建议。根据改动确定相关验证命令，记录实际执行的结果和仍需验证的场景。没有可证实的问题时，报告审查范围和剩余验证缺口。
4. 起草 `type: 变更摘要` 格式的提交消息，并按 `.github/pull_request_template.md` 起草 PR 描述。把审查与草稿返回给作者，由作者决定如何修改和提交。
