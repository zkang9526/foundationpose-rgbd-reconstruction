# RGB-D Reconstruction & FoundationPose Tracking

面向机器人预抓取，使用D435i采集多视角RGB-D，重建米制Mesh，并通过FoundationPose估计、跟踪目标6D位姿。

- **重建**　SAM2框选分割与人工复核，几何粗对齐、点到面ICP、TSDF融合，支持点云滤波及杯把局部处理。
- **分割与重定位**　SAM/SAM2获取Mask，结合深度、外观和多帧一致性检查，在目标重新入镜后尝试恢复跟踪。
- **推理优化**　GPU网格投影、临时批量限制和低显存适配，支持Ubuntu容器与本机WSL原生worker。
- **神经表示**　由RGB-D及估计相机位姿拟合SDF与颜色场，导出带颜色的表面供同一位姿流程使用。
- **预抓取**　多帧稳定位姿聚合、杯轴垂直约束、多方向候选、多初值逆解及完整路径检查的数值模块。

## 运行

准备官方源码、权重、相机环境及自己的米制Mesh后，在Ubuntu运行。

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh \
  --mesh-profile redcup72 --mask-backend sam2 --auto-reacquire \
  --duration-seconds 600 --max-frames 3000
```

打开 `http://127.0.0.1:8765`，冻结画面、框选目标、修正Mask并初始化。模型profile绑定文件路径和SHA256，使用自己的Mesh前需更新配置。

[采集与跟踪指南](docs/QUICKSTART.md) · [重建、神经表示与WSL](docs/PIPELINE.md) · [预抓取模块](robotics/README.md)

## 已有验证

RTX 3090与D435i实机连续跟踪约 **18.23 FPS**。同一保存输入、同样2次细化的离线worker对照中，单帧处理中位耗时 **56.94 → 37.19 ms**，降低约 **34.7%**，吞吐提升约 **53%**。搜索、初始化和显示耗时另计。

已有目标返回后自动恢复跟踪的现场记录。精度评测提供相对漂移及相对ADD/ADD-S工具，绝对位姿精度需要独立参考位姿。几何重建包含杯子专用假设，需根据新目标调整ROI、轴线及几何约束。

## 目录

```text
setup/        采集、分割、重建、推理与评测
robotics/     预抓取几何、逆解搜索和轨迹检查
docs/         操作指南
third_party/  第三方许可
```

依赖来源与使用条款见[第三方说明](THIRD_PARTY_NOTICES.md)。运行数据、Mesh、权重、环境、标定结果及日志保存在本地。
