# Git版本与运行结果回溯

## 2026-10-26 公开快照发布

用户已授权创建公开仓库 `zkang9526/foundationpose-rgbd-reconstruction`。GitHub 发布使用独立、经过审计的源码快照，不推送本地原有全部 Git 历史；原分支 `fix/reacquisition-sam2-eval`、Ubuntu 分支及实验档案保持原样。

已发布并核验：[GitHub 项目](https://github.com/zkang9526/foundationpose-rgbd-reconstruction)。首次公开提交 `c916c07`，验证记录见 [发布报告](reports/GITHUB_PUBLICATION_20261026.md)。

公开副本在 Windows 项目下 `foundationpose_data/publication/github_20261026/repository`，单独管理 `main` 与 GitHub remote；它位于原项目忽略的数据目录，不是第二份采集环境。不得从原项目执行 `git push --all` 或用公开快照覆盖 Ubuntu 账本。

后续同步：先在原项目修复、验证和提交，再通过 `setup/export_public_snapshot.py --source E:\foundationPos --output <新空目录>` 导出。检查 `PUBLICATION_MANIFEST.json`、脱敏和差异后，只在公开副本提交选定变更并推送 `main`。导出器拒绝已有输出目录，不自动发布或删除内容。

公开仓库不包含原始数据、Mesh、权重、上游源码检出、运行账本、环境和缓存。发布证据保存在本机 `foundationpose_data/publication/` 与运行记录中。下文“未配置 GitHub”是 2026-10-15 基线事实，不表示本次发布后的状态。

## 原本地历史与双机流程（2026-10-15）

Windows真实仓库 `E:\foundationPos`（原C盘入口是联接），Ubuntu仓库 `/data/ZJC/foundationPos`。
Windows `main` 保存本机版本；Ubuntu `ubuntu` 保存服务器实际部署版本，共享Windows基线父提交。
通过本地 `.bundle` 文件交换提交；没有配置GitHub/Gitee或公开上传。

## 范围

纳入：项目 `setup/` 脚本与小配置、`tools/` 源码、根目录指南、`reports/` 文本报告和小JSON/CSV、历史基线索引。
排除：`foundationpose_data/` 全部数据与运行档案、`reviews/` 图片、权重/网格/bag/视频、虚拟环境、缓存、下载目录、上游FoundationPose/BundleSDF独立检出。
忽略规则不删除磁盘文件。原运行资料与逐文件SHA继续保留在原位置。

`EXPERIMENT_LOG.md`、`ISSUES.md` 是持续追加的本机账本，留在磁盘并继续更新；初始化时各存一份到 `history/windows/baseline_20261015/` 和 `history/ubuntu/baseline_20261015/`，后者由Ubuntu本地生成，不能被Windows账本覆盖。
这避免每条执行记录都成为代码改动。阶段结论、故障原因与验证结果写入可提交的 `reports/`。

## 定位问题

```bash
git status --short
git log --oneline --decorate -15
git show <提交号> -- setup/run_cup_live_fast.py
git diff <旧提交> <新提交> -- setup/
git blame setup/cup_sam_mask.py
```

后续记录器自动在每个 `foundationpose_data/runs/<run_id>/` 中保存 `project_git.json`：提交号、分支、dirty标志、修改/新增路径、已跟踪文件差异SHA。
存在未提交改动时保存 `project_worktree.patch`（8MiB内），包含已跟踪文件相对HEAD的暂存/未暂存差异；新增文件只列路径，记录器选定的setup源码另存 `source/` 和逐文件SHA。
该信息也在 `environment.json` 与 `run.json` 的 `metadata.project_git` 中。先用run_id找到提交，再对比当次源码快照和patch。
没有Git或检查失败不会阻止实际相机/推理命令，记录中会说明。

## 后续提交

每次有意义的修改，先复验并更新对应报告，再提交。以下辅助入口会先检查体积、二进制和常见凭据模式，再暂存并提交（自动检测不能替代对 `git diff` 的阅读）：

Windows：
```powershell
cd E:\foundationPos
& .\.windows-camera-venv\Scripts\python.exe -B setup/run_logged.py --root E:\foundationPos --label git_commit -- .\.windows-camera-venv\Scripts\python.exe -B setup/manage_project_git.py --root E:\foundationPos --action commit --message "fix: describe change and validation"
```

Ubuntu：
```bash
cd /data/ZJC/foundationPos
bash setup/run_logged.sh --label git_commit -- python3 -B setup/manage_project_git.py --root /data/ZJC/foundationPos --action commit --message 'fix: describe change and validation'
```

先提交需要保留的当前改动，再按需从历史恢复特定脚本：`git restore --source <提交号> -- setup/某脚本.py`，复验后形成新的提交。
诊断历史源码可使用新分支或独立worktree；执行时仍需明确选择数据/权重/环境与项目root，不能认为Git包含这些资产。

## Windows与Ubuntu同步

```bash
git bundle create <新文件.bundle> --all
git bundle verify <新文件.bundle>
git fetch <对方.bundle> <分支>:refs/remotes/<来源>/<分支>
git diff HEAD refs/remotes/<来源>/<分支> -- setup/
```

bundle只保存Git已提交内容，不是原始数据备份。对方分支先fetch和比较，再按阶段选择代码提交；不能直接用Windows总日志覆盖Ubuntu记录。
现有初始基线反映2026-10-15 SAM已接入时的实际文件，不把先前聊天或报告补造为历史Git提交。
