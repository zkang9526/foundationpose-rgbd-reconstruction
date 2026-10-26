# 第三方来源与许可说明

本仓库是复现脚本和实验记录，不代表下列项目的官方实现或性能结论。预训练权重、数据与完整上游检出不随仓库分发。

| 依赖 | 使用位置 / 固定版本 |
| --- | --- |
| [FoundationPose](https://github.com/NVlabs/FoundationPose/tree/a1b694b83e633c2cb6115b9063d940a687759392) | 官方初始化、跟踪和渲染接口；提交 `a1b694b83e633c2cb6115b9063d940a687759392` |
| [SAM2](https://github.com/facebookresearch/sam2/tree/2b90b9f5ceec907a1c18123530e92e794ad901a4) | SAM2.1 Hiera Tiny；提交 `2b90b9f5ceec907a1c18123530e92e794ad901a4` |
| [Segment Anything](https://github.com/facebookresearch/segment-anything) | SAM ViT-B 首帧分割对照 |
| [Open3D](https://github.com/isl-org/Open3D) | 点云、ICP、TSDF、网格处理 |
| [RealSense SDK](https://github.com/realsenseai/librealsense) | D435i 采集、软件对齐与设备访问规则 |
| [NVDiffRast](https://github.com/NVlabs/nvdiffrast)、[PyTorch](https://github.com/pytorch/pytorch)、[OpenCV](https://github.com/opencv/opencv)、[NumPy](https://github.com/numpy/numpy)、[Pillow](https://github.com/python-pillow/Pillow) | 渲染、推理、图像和数值处理 |

代码、模型和数据的使用分别以对应上游版本的条款为准。本仓库未为第三方内容重新授予许可证，也未为全部内容另行指定统一开源许可证。


模型和数据请从对应上游官方渠道获取，使用前核对代码、权重与数据的许可。

RealSense SDK 的 Apache-2.0 许可副本见 `third_party/licenses/librealsense-LICENSE.txt`。
