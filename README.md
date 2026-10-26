# D435i RGB-D Reconstruction & FoundationPose Tracking

基于 Intel RealSense D435i 的无 CAD 杯子重建、6D 位姿估计与实时跟踪复现项目。包含 Windows RGB-D 采集、Mask 标注、ICP/TSDF 重建、SAM2.1 自动找回及 ArUco 相对漂移评测。

本项目是个人实验与工程复现，不是 NVIDIA 官方仓库；使用官方预训练权重，没有针对杯子重新训练位姿网络。

```text
多视角 RGB-D → SAM2 草稿 / 人工复核 Mask → 几何初始化 + ICP + TSDF → 米制 Mesh
                                                                         ↓
实时 RGB-D → 首帧分割 → FoundationPose 初始化 / 跟踪 → 深度与外观检查 → 有效位姿
                                 ↑                       ↓ 失跟
                                 └── SAM2 全图候选 + 筛选 + 重新注册 + 连续验证
```

## 功能

- **采集与留档**：保存对齐 RGB、原始毫米深度、内参、时间戳、文件 SHA256 和成功/失败记录。
- **重建**：针对当前杯子，以杯底平面、杯把方向建立初始配准，再做有界 ICP 与 TSDF 融合；保留估计及插值标记。
- **位姿与跟踪**：FoundationPose 官方预训练模型；GPU 网格投影用于深度/轮廓一致性检查。
- **自动找回**：SAM2.1 Hiera Tiny 全图候选，结合初始颜色和深度尺度筛选，重新注册后连续 3 个新跟踪帧确认。
- **评估**：固定杯子与 ArUco 码、移动相机，记录相对漂移、参考覆盖率及逐帧结果。

## 已配置环境的启动入口

以下适用于已部署的 Ubuntu 环境。**新克隆不包含相机环境、权重、原始数据或杯子 Mesh**，需要先完成[环境与资产准备](docs/QUICKSTART.md)。部分脚本仍使用实验机器的固定目录，需要按实际机器适配。

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

Ubuntu 浏览器打开 `http://127.0.0.1:8765`：冻结画面 → 框选完整杯身和杯把 → 生成/修正 Mask → 确认初始化。保持静止直到开始跟踪；目标失跟后重新入镜时短暂停稳，系统会自动搜索。

该入口使用红色杯口版本 Mesh、SAM2 首帧、自动找回及 **DICT_5X5_50 / ID 6 / 黑色外边长 30 mm** 的固定场景评测。杯子与码相对移动时追加 `--no-aruco-fixed-scene`；无参考码的命令见[快速指南](docs/QUICKSTART.md)。

## 已有实验结果

数值来自不同目的的实验，统计范围分别列出。

| 实验 | 结果 | 范围与证据 |
| --- | --- | --- |
| 真实 D435i 连续跟踪 | **18.23 FPS** | RTX 3090；分段统计，不含搜索/初始化；[现场报告](reports/CUP_RECOVERED_ACCURACY_20261018_172656.md) |
| 现场输入接收 → 结果返回 | 中位 **71.77 ms**，P95 **88.99 ms** | 不含浏览器真正显示延迟；同上 |
| GPU 投影优化对照 | 处理中位 **56.94 → 37.19 ms** | 同一保存 RGB-D、相同 2 次细化；worker 范围；[计时报告](reports/CUP_FAST_ARUCO_RESULT_20261014.md) |
| 轮廓自一致性 | 平均 IoU **0.8655** | 72 个重建参考视图、估计/插值姿态；不是独立几何或 6D 精度；[重建报告](reports/RED_CUP_REVIEWED72_MESH_RESULT_20261017.md) |
| ArUco 相对漂移 | 中位 **7.66 mm / 4.16°** | 1237 个有效非锚点配对；P95 19.73 mm / 10.45°；混合参考噪声；[评测报告](reports/CUP_RECOVERED_ACCURACY_20261018_172656.md) |
| 现场自动找回 | 记录到一次成功恢复 | 恢复后 337 个确认帧；单次不代表总体成功率；同上 |

## 当前限制

- 杯把接头、杯口/接触侧仍有毛刺、孔洞和缺失；Mesh 尚未通过精确几何验收。
- 重建脚本包含 72 帧、颜色、杯底 ROI 等杯子专用假设；计划转角不作为外参或真值。
- SAM2 当前做图像分割候选，不在正常跟踪时逐帧运行；颜色/尺寸匹配不能保证区分同色同尺寸的另一目标。
- 单 ArUco 平面参考存在朝向跳变；没有独立码到 OBJ 外参标定，不能把相对漂移当绝对位姿精度。
- 官方 BundleSDF 失败尝试与退出 139 分开留档；当前模型来自独立 ICP/TSDF 流程。
- 尚未完成机器人实物抓取与抓取成功率评测。

## 文档与目录

- [快速使用与资产要求](docs/QUICKSTART.md)
- [模块与文档索引](docs/PROJECT_MAP.md)
- [Git 与发布流程](GIT_WORKFLOW.md)
- [完整历史操作记录](REPRODUCTION_GUIDE.md)、[早期搭建手册](README_LEGACY.md)
- [第三方来源与许可说明](THIRD_PARTY_NOTICES.md)

`setup/` 保存采集、分割、重建、跟踪、评测和留档脚本；`camera_calibration/` 保存独立相机检查工具；`reports/` 保存阶段结论。
原始 RGB-D、权重、Mesh、视频、虚拟环境、缓存、逐次运行档案与原本地 Git 历史不随公开快照上传。

## 上游项目

[FoundationPose](https://github.com/NVlabs/FoundationPose)、[SAM2](https://github.com/facebookresearch/sam2)、[Open3D](https://www.open3d.org/)、[RealSense SDK](https://github.com/realsenseai/librealsense)。
