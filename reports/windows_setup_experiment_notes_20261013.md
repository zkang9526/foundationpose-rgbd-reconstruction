## 2026-10-13：Windows 采集、Ubuntu 后处理路线准备

- 用户希望将 D435i 采集放在 Windows，后续重建及位姿估计放在 Ubuntu。
- Windows 10 x64，现有 Python 3.11.8；新建项目内独立 `.windows-camera-venv`，安装 SHA256 验证过的官方 pyrealsense2 2.55.1.6486、NumPy 1.26.4、Pillow 12.3.0，SDK 导入与 pip check 通过。
- 新建三个 PowerShell 相机入口，并适配 Windows 命令记录、环境信息、追加锁和中断处理；Linux 的现有格式检查再次通过。
- 将此前 Ubuntu 的 30 对 RGB-D 样本传到 Windows，成对文件、uint16 毫米深度、内参和比例读取检查通过。此验证只针对保存格式，不代替 Windows 实际取帧。
- 本次 SDK 查询 Windows 相机列表为空；相机仍在 Ubuntu。因此 Windows 真实采集验收状态为“待移接相机后进行”，不是已经通过。
- Windows 执行档案已复制到 Ubuntu `foundationpose_data/runs/`，按唯一编号导入总记录，保留服务器原有记录。
- 证据：Windows 环境摘要（原始附件未随公开快照提供）、跨平台文件检查（原始附件未随公开快照提供）、Windows 采集与传输说明（原始附件未随公开快照提供）。
- 下一步：D435i 移到 Windows USB 3.x 接口，先运行 60 帧检查；目标深度合格后录制多视角序列，上传 Ubuntu 并验证格式/SHA256。
