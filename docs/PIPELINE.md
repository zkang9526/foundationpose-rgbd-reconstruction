# 重建、神经表示与WSL

## 几何重建

采集时固定相机，逐次转动物体并停稳保存。RGB与深度通过RealSense SDK对齐，保存内参、毫米深度和时间戳。人工输入的5°计划步长用于采集提示，重建从几何观测估计姿态。

`manual_mask_editor.py` 支持逐帧矩形框和前景/背景点，SAM2生成草稿后可继续人工修正。其本机SAM运行目录需要 `sam2/` 源码及 `sam2/checkpoints/installation.json` 和权重。

```bash
python setup/manual_mask_editor.py \
  --scene /path/to/capture --output /path/to/reviewed_masks \
  --sam-runtime /path/to/native_runtime --port 8768
```

页面中检查杯身、杯把和孔洞，保存确认。杯底平面及杯把方向提供粗姿态，再以点到面ICP微调，供TSDF融合使用。当前脚本针对72张倒扣杯采集，ROI及杯把遮挡区间需要从本批RGB确认。

```bash
python setup/reconstruct_cup_geometric_tsdf.py --help
python setup/export_cup_icp_clouds.py --help
python setup/filter_cup_icp_cloud.py --help
python setup/fuse_filtered_cup_tsdf.py --help
```

四个入口依次完成重建、按保存的配准矩阵导出观测点云、滤波及基于滤波约束的重新融合。输入参数与产物格式见各入口帮助。处理依赖Open3D、NumPy、OpenCV与SciPy。`refine_cup_handle_mesh.py` 提供杯把局部处理，`clean_and_measure_cup_mesh.py` 用于清理与尺寸检查。平滑和几何先验的输出需要与实际尺寸、观测轮廓对照。

## 神经对象表示

当前流程固定使用ICP估计的相机位姿，拟合上游FoundationPose神经对象场中的SDF与颜色MLP。位姿推理阶段从拟合结果导出表面与颜色，再使用网格渲染。训练入口需要上游 `bundlesdf/run_nerf.py` 及其CUDA扩展环境。

```bash
python setup/train_cup_neural_field.py \
  --repo /path/to/FoundationPose --scene /path/to/rgbd_scene \
  --poses /path/to/estimated_camera_to_model --output /path/to/new_fit \
  --steps 1500 --rays 256 --netchunk 8192

python setup/prepare_cup_neural_pose_model.py \
  --field /path/to/new_fit --field-repo /path/to/FoundationPose \
  --output /path/to/new_model

python setup/run_cup_neural_pose.py --help
```

训练输入为 `rgb/`、`depth/`、`masks/`、`K.txt` 及相机到模型的4×4矩阵。`prepare_local_neural_rgbd.py` 可由现有重建结果整理输入。估计矩阵的误差会影响神经场，单圈采集的未观测区域仍需补充数据。

## WSL原生推理

GPU worker支持 `--worker-backend native`，并提供warp临时批量、渲染批量及CPU直径计算的低显存适配。相机与推理可使用独立Python环境。WSL需要Windows NVIDIA驱动支持、USB/IP相机接入，以及已构建的FoundationPose与SAM2环境。

原生运行目录包含 `env/bin/python`、`FoundationPose/`、`sam2/`、`source_sha256.json`，并沿用 `foundationpose_data/` 保存数据。源码校验文件应记录当前已验证上游源码的SHA256。先按实际机器设置CUDA动态库路径，再运行。

```bash
python setup/run_cup_live_fast.py \
  --root /path/to/project --worker-backend native \
  --native-runtime /path/to/native_runtime --mesh-profile cup_smoothed_20261112 \
  --mask-backend sam2 --auto-reacquire --warp-batch-limit 1 \
  --duration-seconds 600 --max-frames 300
```

该命令需要与profile对应的本地模型。不同GPU的初始化、连续跟踪耗时分别测量，README中的3090结果有其独立测试条件。

## 评测

`cup_add_metrics.py` 实现ADD、ADD-S及平移/旋转误差。`evaluate_cup_relative_add.py` 利用固定物体与固定ArUco码的相对关系计算首帧参考下的相对ADD，调用前确认测试中两者相对位置固定。

```bash
python setup/evaluate_cup_relative_add.py --help
python setup/verify_cup_add_metrics.py --output /path/to/new_checks
```

相对指标可用于分析重复性和跟踪漂移。与论文绝对ADD比较需要独立真值位姿、统一模型坐标和尺度。评测结果和原始记录保存在运行数据目录。
