# 2026-10-26 GitHub 公开快照整理与发布

用户授权将复现项目稍作整理后上传 GitHub，并明确选择公开仓库，名称 `foundationpose-rgbd-reconstruction`，账号 `zkang9526`。

## 整理范围

- 新 README 说明项目目标、工作流、当前入口、实验统计范围与局限；旧 README 保留为 `README_LEGACY.md`。
- 新增 `docs/QUICKSTART.md`、`docs/PROJECT_MAP.md`，标明固定目录、离线 wheel、Mesh/权重等新机器需要另行准备的资源。
- 历史指南加文档定位，保留原状态和失败证据；当前脚本路径不移动，不修改相机/重建/推理算法。
- 调整本地忽略规则，默认不再纳入新 reports 运行子目录；既有 tracked 历史不删除。
- 补充第三方来源；公开版排除原报告中的整段上游源码、原始运行环境档案及私人本地 Git 历史。

## 发布策略

原工作分支 `fix/reacquisition-sam2-eval` 保留。通过 `setup/export_public_snapshot.py` 导出至 `foundationpose_data/publication/github_20261026/repository`，公开副本单独建立 `main`。
只选择脚本、配置、根指南、顶层文字报告及指定计时汇总，不打包原始 RGB-D、Mask 历史、Mesh、权重、venv、缓存或原历史。
导出记录源提交、每文件 SHA256、已知 SSH 主机/Windows 用户目录替换和未公开附件链接，不把公开快照伪装成早期版本历史。

GitHub 认证只调用现有 Git Credential Manager，在内存中供 API 使用；不输出/保存凭据。初次受限凭据查询无可用结果，原生权限复验成功，账号/API 已核验。

第三方许可获取时，raw 端点及一次认证 API 请求遇到 TLS EOF，匿名 API 也达到限额；失败均留档。改从现有官方 pyrealsense2 2.55.1.6486 wheel 提取同版本 LICENSE，先核验 wheel SHA256，再保留许可文本。wheel SHA256 为 `e01939a63bac3e1a4da742f7e1dbc618a4ec03ee0f7b3690ae5d1ad0c983aca8`，许可 SHA256 为 `0656803c0f61036b73ec2c35bd473cb1a095deed5a7247a879f3f51e3298ad24`。

首轮导出预检发现 git NUL 列表末尾空路径处理缺失，已修复并在新目录预检通过：445 文件、199 个 Python AST、4 个 JSON；失败目录保留。最终计数以提交后的正式导出为准。

## 验证与发布状态

- 仓库：[zkang9526/foundationpose-rgbd-reconstruction](https://github.com/zkang9526/foundationpose-rgbd-reconstruction)，GitHub API 核验为 public，默认分支 main。
- 首次公开提交：`c916c07c049ccaa7706d21ae59aa7a878ea56228`；来源本地提交：`2265979b13b408da7261990d8f0811fa02bc85bf`。后续发布文档同步另成提交，不改写这份初始快照。
- 正式导出 447 文件，源内容 2,438,320 字节，199 个 Python 文件 AST、4 个 JSON 解析通过；入口文档链接及逐文件导出 SHA256 核验通过。
- 已知私人 SSH 主机/Windows 用户路径共替换 54 处；37 个未公开原始附件链接明确标注。常见私钥、GitHub/OpenAI/AWS 凭据和硬编码密码模式无命中；不把自动扫描当完整安全保证。
- 仅推送独立公开 main；Git ls-remote 与 GitHub API 两种方式均核验首次提交一致。原分支与原历史未上传、未重置。
- 原生 curl 最初没有沿用 Windows 系统代理，显式使用已有系统代理后创建、上传和 API 核验通过；原 raw 端点的 TLS 故障未另外复验。没有修改全局网络设置或 Git 配置，没有保存/打印 token。
- 原始相机、重建、推理环境未改动；本次验证是文档、导出和发布检查，不冒称重新完成实物精度评测。

关键运行档案：`20261026_111031_437709_github_public_snapshot_export_final_63bc3d88`、`20261026_111143_657144_github_public_snapshot_git_init_b0c2df1c`、`20261026_111238_941188_github_public_repository_create_system_proxy_7c7e6d8f`、`20261026_111328_555271_github_public_snapshot_push_1a2ac17f`、`20261026_111409_279691_github_public_snapshot_api_verification_637f2680`。
完整运行日志、失败记录、预检目录和发布回执位于本机 `foundationpose_data/publication/github_20261026` 及 `foundationpose_data/runs`，不随公开快照上传。
