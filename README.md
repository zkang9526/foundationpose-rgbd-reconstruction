# D435i RGB-D Reconstruction & FoundationPose Tracking

使用 D435i 采集多视角 RGB-D，通过 ICP/TSDF 重建杯子 Mesh，再用 FoundationPose 实现 6D 位姿估计与跟踪。

## 功能

- **重建**：交互式 Mask 复核、杯子几何初始化、ICP 配准与 TSDF 融合。
- **跟踪**：FoundationPose 预训练模型，GPU 网格投影与深度一致性检查。
- **自动找回**：SAM2.1 Hiera Tiny 全图分割，结合外观、深度尺度及连续帧验证重新定位。
- **评估**：ArUco 固定场景相对漂移评测。

## 实测结果

RTX 3090 + D435i；以下为不同测试的统计，不能直接互相比较。

| 指标 | 结果 |
| --- | --- |
| 实机连续跟踪 | 约 **18 FPS**，不含搜索与初始化 |
| GPU 投影优化后的单帧处理 | **56.94 → 37.19 ms**，相同保存输入的 worker 对照 |
| ArUco 相对漂移中位数 | **7.66 mm / 4.16°**，1237 个有效配对，包含参考误差 |

## 使用

已准备环境、权重和红杯 Mesh 后，在 Ubuntu 执行：

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

打开 `http://127.0.0.1:8765`，冻结画面、框选杯身和杯把、确认 Mask 后初始化。失跟后让目标重新入镜并短暂停稳。

该入口默认使用固定的 30 mm ID6 ArUco 码；无参考码的命令、环境要求和采集流程见 [使用指南](docs/QUICKSTART.md)。

## 目录

```text
setup/          采集、分割、重建、跟踪与评测代码
docs/           使用指南
third_party/    第三方许可
```

本项目是基于官方预训练模型的工程复现。当前 Mesh 的杯把及接触面仍有缺陷，相对漂移不代表绝对位姿精度；重建含杯子专用假设和固定路径。原始数据、Mesh、权重与运行日志不包含在仓库中。

上游：[FoundationPose](https://github.com/NVlabs/FoundationPose) · [SAM2](https://github.com/facebookresearch/sam2) · [Open3D](https://github.com/isl-org/Open3D) · [RealSense SDK](https://github.com/realsenseai/librealsense)。许可见 [第三方说明](THIRD_PARTY_NOTICES.md)。
