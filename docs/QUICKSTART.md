# 快速使用与环境准备

本仓库提供复现脚本与实验记录，尚不是跨机器的一键安装包。以下区分已部署机器的命令与新机器需要准备的资源。

## 环境与资产

| 用途 | 本次已验证配置 |
| --- | --- |
| Windows 采集 | Python 3.11 x64、独立 `.windows-camera-venv`、pyrealsense2 2.55.1.6486、NumPy 1.26.4、OpenCV、Pillow |
| Ubuntu 推理 | Ubuntu 20.04、RTX 3090 24 GB、Docker GPU 容器 `foundationpose` |
| FoundationPose | 上游提交 `a1b694b83e633c2cb6115b9063d940a687759392`；容器 PyTorch 2.0.0+cu118 |
| SAM2.1 | 独立环境；Hiera Tiny；上游提交 `2b90b9f5ceec907a1c18123530e92e794ad901a4` |
| 几何处理 | 宿主独立环境 Open3D 0.19.0，与推理容器分开 |

完整实测版本见 [Ubuntu 环境记录](../Ubuntu_environment.md)。宿主驱动支持的 CUDA 与容器 PyTorch 的 CUDA 构建版本是不同概念。

新机器需准备：

1. 按 [FoundationPose 固定版本官方说明](https://github.com/NVlabs/FoundationPose/tree/a1b694b83e633c2cb6115b9063d940a687759392) 准备源码、预训练权重及 GPU 容器；本仓库不重新分发这些资源。
2. 为 Windows 相机、Ubuntu 相机、FoundationPose、SAM2 保留独立环境，不直接升级现有可用的 FoundationPose PyTorch。
3. 检查脚本中的 `/data/ZJC/foundationPos`、`/home/ni/anaconda3/envs/foundationpose`、容器名及 Python 路径。SSH 编排脚本带原实验机器设置，不可直接用于新机器。
4. 准备米制 Mesh、对应内参、深度单位及人工确认的初始分割。`setup/cup_mesh_selection.py` 固定两个实验杯子的路径及 SHA256；自己的模型需定义对应 profile，不应绕过哈希检查。

`setup/prepare_d435i_windows.ps1` 是离线 wheel 缓存安装器，要求 `.assets_download/` 已有指定文件及 SHA256，不会自动下载。`setup/provision_cup_sam2.py` 带原机器路径，应先核对再通过记录器运行。

## Windows 采集

当前项目在 `E:\foundationPos`，默认数据根为 `E:\foundationPos_data`。配置见 `setup/windows_capture_storage.json`、`setup/windows_storage_policy.json`。

```powershell
cd E:\foundationPos
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5
```

固定相机，旋转杯子，停稳、手退出后按回车，等待 `Saved`。计划角度不是实测外参；采集和格式检查自动留档。先检查目标局部深度与视角覆盖，不能用整图有效比例代替杯把/杯口质量。

`-RecordBag` 可录制原始流；`-FilteredDepth` 保存独立派生深度，原始 `depth/` 不变。默认保留当前相机设置；显式选择预设/自动曝光前阅读 [照片采集说明](../CUP_MANUAL_PHOTOS.md)。

## Mask 与重建

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_manual_mask_editor.ps1 -Scene 'E:\foundationPos_data\windows_captures\YOUR_CAPTURE' -Output 'E:\foundationPos_data\manual_masks\YOUR_MASKS'
```

默认页面 `http://127.0.0.1:8767`。标完整杯身、杯把与可见内壁，杯把内孔属于背景。相同输出目录可继续编辑。草稿与人工复核见 [Mask 说明](../MANUAL_CUP_MASKS.md)。

`setup/reconstruct_cup_geometric_tsdf.py` 依赖固定 72 帧、杯底几何、颜色与 ROI。新批次需检查假设、调整数据选择并验证配准，不能照抄旧编排脚本的数据路径。
原始数据、Mask、派生深度、估计姿态、插值标记和候选 Mesh 分开保存。参数和失败对照见 [Mesh 报告](../reports/RED_CUP_REVIEWED72_MESH_RESULT_20261017.md)。

## 实时跟踪

环境与红杯 Mesh 已准备、D435i 连接 Ubuntu 后：

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

此入口启用红杯 Mesh、SAM2 首帧、自动找回、杯把 yaw 初始化检查及固定杯子/ID6 参考评测。

不使用 ArUco 时显式调用通用入口：

```bash
bash setup/run_cup_live_fast.sh \
  --mesh-profile redcup72 --mask-backend sam2 --auto-reacquire --cup-yaw-init \
  --duration-seconds 600 --max-frames 3000
```

通用入口不传这些参数时默认仍是旧 `legacy` 模型与 SAM ViT-B；历史 `run_cup_live.sh` 使用 GrabCut。

Ubuntu 浏览器访问 `http://127.0.0.1:8765`。首次冻结、框选杯身和杯把、修正 Mask 并确认，保持静止直到跟踪。失跟后隐藏旧姿态，SAM2 全图搜索，候选重新注册，连续 3 个新帧通过后恢复显示。

SAM2 仅从 RGB 生成候选；深度由外层筛选目标尺度。目标再次入镜后短暂停稳，避免搜索期间 Mask 过期。颜色/尺寸相似的其他物体仍可能混淆。

## 相对漂移评测

红杯入口默认 `DICT_5X5_50`、ID 6、黑色外边长 30 mm。换码时需修改参数。固定杯子与码，只移动相机；二者相对移动时追加 `--no-aruco-fixed-scene`，不能按固定场景解释误差。

会话位于 `foundationpose_data/live_sessions/`，包含 RGB-D、K、时间戳、矩阵、Mask 尝试、恢复事件、ArUco CSV 与汇总。
首帧对齐后的数值是相对漂移，单码参考本身可能跳变。见 [协议](../reports/CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md)、[最新结果](../reports/CUP_RECOVERED_ACCURACY_20261018_172656.md)。

## 留档

现有采集与实时 wrapper 已接入记录器。其他处理通过：

```powershell
.\.windows-camera-venv\Scripts\python.exe -B setup/run_logged.py --root E:\foundationPos --label YOUR_LABEL -- COMMAND ARGUMENTS
```

```bash
bash setup/run_logged.sh --label YOUR_LABEL -- COMMAND ARGUMENTS
```

补充材质、尺寸、光照与运动条件；不要将密码/令牌放进参数、备注和终端输出。失败保留，新尝试用新目录。
