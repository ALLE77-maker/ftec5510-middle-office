# 三人协作指南

每人克隆同一个仓库，在自己的分支里使用 AI。[CLAUDE.md](../CLAUDE.md) 记录三人的文件分工、项目命令和合并规则。使用 Claude Code 时从仓库根目录启动。使用 Codex 时由 [AGENTS.md](../AGENTS.md) 指向同一份规范。

## 第一次开始

```sh
git clone https://github.com/ALLE77-maker/ftec5510-middle-office.git
cd ftec5510-middle-office
python -B -m unittest discover -s tests -v
```

已克隆的成员从下一节开始。macOS 可用 `python3`。需要连接 AI 或上游行情时，对照 [`.env.example`](../.env.example) 设置进程环境，操作见 [README](../README.md)。

## 从分支到 PR

1. 认领任务，说明涉及的文件。需要跨维护范围时，先和对应成员确认由谁改。
2. 从最新的 `main` 开个人分支。将下面的 `your-name` 和 `task-name` 换成自己的名字和任务名。

   ```sh
   git switch main
   git pull --ff-only origin main
   git switch -c feat/your-name/task-name
   ```

3. 写完后运行相关验证，请 AI 起草提交消息并检查变更。用 `git add` 只暂存本任务的文件，用 `git diff --cached` 核对后提交。提交标题使用 `type: 变更摘要`，如 `fix: retain quote timestamps on retry`。
4. 本地提交后同步主分支。遇到冲突，可以请 AI 提出解决方案。作者核对两边的意图，用 `git add` 标记已解决文件，再运行 `git rebase --continue`。解决方案有疑问时，可用 `git rebase --abort` 退出本次 rebase。

   ```sh
   git fetch origin
   git rebase origin/main
   python -B -m unittest discover -s tests -v
   ```

5. 推送前用 Claude Code 的 `/middle-office-review` 审查最终差异。使用其他 AI 的成员可让它按 [共享审查步骤](../.claude/skills/middle-office-review/SKILL.md) 检查。修复发现后重新验证，再推送并在 GitHub 创建指向 `main` 的 PR。

   ```sh
   git push -u origin feat/your-name/task-name
   ```

   如果已推送的个人分支因 rebase 需要更新历史，确认只有自己在维护该分支后用 `git push --force-with-lease`。多人共用的分支先与其他作者协调更新方式。
6. 按 PR 模板填写范围、验证和 AI 审查结果，请至少一位其他组员审核。跨模块请受影响的维护者参与。修改共享 AI 规范时，由其余两人审查。人工批准且检查通过后合并，随后用 GitHub 的 **Delete branch** 清理远端功能分支。
