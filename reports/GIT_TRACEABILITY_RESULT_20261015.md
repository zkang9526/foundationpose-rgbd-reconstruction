# 项目Git化与运行版本追踪（2026-10-15）

用户要求Git化以定位问题和回溯。Windows `E:\foundationPos` 与Ubuntu `/data/ZJC/foundationPos` 已初始化Git；原C盘Windows入口仍为E盘联接，没有另存C盘项目。

## 基线与两端历史

- Windows `main` 基线提交：`41a0d3979bc0da82817fc9099ef0c278ea0a69c7`；标签 `baseline/sam-windows-20261015`。
- Ubuntu `ubuntu` 基线提交：`be8dce3547ec3eb8d31085ad44d60f89f6a6f21b`；标签 `baseline/sam-ubuntu-20261015`。父提交为上述Windows基线。
- Ubuntu以bundle导入共同历史，仅设置Git索引与分支引用；原有文件未被checkout或reset覆盖。105个服务器原先缺失的基线源码/文档作为新文件补齐；服务器已有文档与部署差异随后独立提交。
- Windows可用 `ubuntu/deployed` 对照服务器已导入的版本，Ubuntu可用 `windows/main` 对照本机版本。没有新建GitHub/Gitee远程或公开上传。
- 基线保存当前SAM/相机/重建/评测代码与已有报告，不伪造本次Git化之前的阶段提交。

## 纳入与排除

初始Windows提交464个文件约15.5MB原始文本；Ubuntu初始提交后487个文件约17.0MB原始文本。Git压缩bundle约1.8MB。
纳入脚本、小配置、udev规则、根目录指南、文本/JSON/CSV/补丁报告及历史基线索引；对选中文件的体积、二进制和常见凭据模式检查通过，检测值不输出到日志。
忽略采集数据、全部 `foundationpose_data/`、权重、网格、视频、图像复核目录、环境、缓存、下载与上游独立仓库。忽略不删除任何现有文件。
`EXPERIMENT_LOG.md` 和 `ISSUES.md` 继续按原规则追加，但不作为每条命令的Git变更；初始化时分别留存可追踪快照到 `history/windows/baseline_20261015/` 与 `history/ubuntu/baseline_20261015/`，原账本不跨端覆盖。后续阶段结论写进可提交的 `reports/`。

## 每次运行关联代码版本

`setup/run_logged.py` 新增非阻断Git检查，保留原有命令、源码快照、依赖版本和SHA。
每次运行的 `project_git.json` 与 `run.json` / `environment.json` 中的 `metadata.project_git` 保存HEAD、分支、dirty标志、状态路径、已跟踪改动SHA；有未提交改动时另存8MiB以内的 `project_worktree.patch`。
新增未跟踪文件只记录路径，选定setup源文件另有源码快照；不声称patch覆盖任意未跟踪内容。不会读取远程认证URL或全量Git配置。

Windows与Ubuntu均已真实验证：
1. 干净工作区运行正确记录提交号和dirty=false。
2. 在 `project_git_state.py` 暂加无行为改变的注释后，运行记录dirty=true，patch包含该注释并通过SHA检查。
3. 测试后恢复原始源码字节，HEAD不变且工作区恢复干净。
4. 数据/模型/环境路径及实时账本均被忽略，未进入已跟踪清单。

证据见 `reports/GIT_WINDOWS_VERIFICATION_20261015.json` 与 `reports/GIT_UBUNTU_VERIFICATION_20261015.json`；完整原始记录保留两端 `foundationpose_data/git_validation/` 与对应唯一run目录。
本次没有改变推理算法，因此没有重复相机/物理精度测试；SAM的60帧集成验证仍按原报告解释。

## 离线恢复与日常使用

初始Windows bundle：`foundationpose_data/exports/git_windows_baseline_20261015.bundle`，SHA256 `ecad3e74932bd947eaf1a7bcdf29f6aca8b558b9365bc83276f4ef81e850121a`，上传Ubuntu后校验一致。
初始Ubuntu bundle：`foundationpose_data/exports/git_ubuntu_baseline_20261015.bundle`，SHA256 `b7ae423ada73142bad673dc1940c19fe87ec5e6c8662bfdbf448c7376abaae43`，下载Windows E盘后校验一致；bundle对象检查与分支fetch通过。
最终Git化收尾提交与两个分支的bundle另以 `git_ready_*_20261015.bundle` 保存在两端数据目录，不能将bundle当原始数据备份。
常用命令、阶段提交、对照和恢复单文件的方法见根目录 `GIT_WORKFLOW.md`。后续改动应先检查diff，完成复验并写入报告，再形成有意义的提交。
