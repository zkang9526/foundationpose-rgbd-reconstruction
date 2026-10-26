# 使用指南

## 1. 环境准备

| 环节 | 已验证配置 |
| --- | --- |
| Windows 采集 | Python 3.11、pyrealsense2 2.55.1.6486、NumPy、OpenCV、Pillow |
| Ubuntu 推理 | Ubuntu 20.04、RTX 3090、Docker GPU 容器 `foundationpose` |
| FoundationPose | 提交 `a1b694b83e633c2cb6115b9063d940a687759392`；PyTorch 2.0.0+cu118 |
| SAM2.1 | Hiera Tiny，独立环境；提交 `2b90b9f5ceec907a1c18123530e92e794ad901a4` |
| 重建 | 独立 Open3D 0.19.0 环境 |

按 [FoundationPose 官方说明](https://github.com/NVlabs/FoundationPose/tree/a1b694b83e633c2cb6115b9063d940a687759392) 准备源码、权重和容器。SAM/SAM2 分别通过 `setup/provision_cup_sam.py`、`setup/provision_cup_sam2.py` 准备；先核对脚本中的环境和目录。

这些脚本沿用实验机器布局：项目 `/data/ZJC/foundationPos`，相机 Python `.camera-venv/bin/python`，容器内 Python `/opt/conda/envs/my/bin/python`。SAM2 还引用原宿主 Conda 环境。换机器需适配路径，不能直接视为一键安装包。

Windows 默认项目 `E:\foundationPos`、数据 `E:\foundationPos_data`；配置在 `setup/windows_capture_storage.json` 和 `setup/windows_storage_policy.json`。`prepare_d435i_windows.ps1` 依赖已缓存并匹配 SHA256 的官方 wheel，不自动下载。

## 2. RGB-D 采集

```powershell
cd E:\foundationPos
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5
```

固定相机，旋转杯子，停稳、手退出后按回车，等待 `Saved`。计划角度只是备注，不是外参真值。先检查杯把和杯口的原始深度质量。`-RecordBag` 可额外录制，`-FilteredDepth` 另存派生深度。

## 3. Mask 与 Mesh

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_manual_mask_editor.ps1 -Scene 'E:\foundationPos_data\windows_captures\YOUR_CAPTURE' -Output 'E:\foundationPos_data\manual_masks\YOUR_MASKS'
```

页面默认 `http://127.0.0.1:8767`。Mask 包含杯身、杯把和可见内壁；杯把内孔是背景。相同输出目录可继续编辑。`sam_offline_drafts.py` 生成草稿，`prepare_sam_assisted_masks.py` 将草稿接入人工复核。

重建实现为 `setup/reconstruct_cup_geometric_tsdf.py`，清理导出为 `setup/audit_geometric_cup_mesh.py`。两者依赖 72 帧；前者还带杯子颜色、杯底 ROI 等假设，新批次必须调整并验证。使用各自 `--help` 查看参数。计划角度不能替代实际配准，平滑/补洞不能恢复未观测表面。

## 4. 实时跟踪

Mesh 使用米制，目标 profile 和 SHA256 在 `setup/cup_mesh_selection.py`。自己的模型需配置对应 profile；本仓库不提供实验杯子的 Mesh 或模型权重。

有固定参考码时：

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

此入口使用红杯 profile、SAM2、自动找回和杯把 yaw 检查，默认 ArUco `DICT_5X5_50` / ID6 / 黑色外边长 30 mm。杯子与码保持固定，只移动相机。二者相对移动时加 `--no-aruco-fixed-scene`。

不使用参考码时：

```bash
bash setup/run_cup_live_fast.sh \
  --mesh-profile redcup72 --mask-backend sam2 --auto-reacquire --cup-yaw-init \
  --duration-seconds 600 --max-frames 3000
```

页面 `http://127.0.0.1:8765`：冻结 → 框选 → 生成/修正 Mask → 确认初始化。保持静止直到跟踪；失跟后重新入镜并停稳，候选注册后连续 3 个新帧通过才恢复显示。

通用入口默认仍是旧 `legacy` profile 与 SAM ViT-B，必须显式选上述参数。SAM2 用 RGB 生成候选，外层用颜色和深度尺度筛选；同色同尺寸目标可能混淆。

## 5. 输出与评测

运行输出位于 `foundationpose_data/`，不进入 Git。相机会话保存 RGB-D、内参、时间戳、位姿和恢复事件；正常结束自动汇总 ArUco 相对漂移。首帧对齐消除了初始偏差，单码参考还可能跳变，不能作为绝对精度真值。

采集和实时 wrapper 自动接入记录器。独立处理命令使用 `setup/run_logged.py` 或 `setup/run_logged.sh`；计算过程中产生的记录留本地。
