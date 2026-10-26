# Ubuntu 环境与目录交付记录

> 2026-10-14 OBJ环境复验：Windows采集，Ubuntu在现有`/home/ni/anaconda3/envs/foundationpose`运行Open3D0.19.0。依赖检查、实际ICP/位姿图/TSDF/OBJ往返与RTX3090 CUDA运算通过；沿用原有包版本，无Ubuntu依赖重装。新增`setup/run_obj_environment_check.sh`自动留档入口。版本和证据见 [OBJ环境配置说明](reports/OBJ_ENVIRONMENT_SETUP_20261014.md)，范围是合成环境测试，实物几何QA仍需执行。

配置日期：2026-10-10。目标机器：`USER@UBUNTU_HOST`。

## 目录

本地 `foundationPos` 文件夹已完整同步到 **`/data/ZJC/foundationPos`**，本地副本保留。

```text
/data/ZJC/foundationPos/
├── README.md                 # 原个人复现文档
├── Ubuntu_environment.md     # 本次实际配置与使用说明
├── FoundationPose/           # 官方代码、预训练权重、mustard0 数据
├── FoundationPose-conda/     # 独立的原生 Conda 备用代码目录
├── foundationpose_data/      # 日志、环境记录、推理输出
├── setup/                    # 本次安装、启动、验证脚本
├── reports/                  # 本地保留的验证报告与示例图片
├── .assets_download/         # 下载缓存
└── transfer_manifest.json    # 本地原文件的 SHA256 清单
```

先前建立的 `~/FoundationPose`、`~/FoundationPose-conda` 和 `~/foundationpose_data` 已改为指向上述目录的兼容符号链接。Conda 环境由 Conda 管理，位于 `/home/ni/anaconda3/envs/foundationpose`。

## 已完成的主要环境

采用 [FoundationPose 官方安装说明](https://github.com/NVlabs/FoundationPose/blob/main/readme.md) 的 Docker 路线。容器名为 `foundationpose`，设置为 `unless-stopped` 自动重启，并已保存配置后的镜像 `foundationpose:ready-20261010`。

| 项目 | 实测版本 |
| --- | --- |
| 宿主系统 | Ubuntu 20.04 / Linux 5.15 |
| GPU | NVIDIA RTX 3090，24 GB |
| 宿主驱动 | 535.230.02 |
| 宿主 CUDA Toolkit | 12.1 |
| Docker | 28.1.1 |
| NVIDIA Container Toolkit | 1.20.1 |
| 容器 Python | 3.8.18 |
| 容器 PyTorch / CUDA 构建版本 | 2.0.0+cu118 / 11.8 |
| 容器 PyTorch3D / NVDiffRast | 0.7.5 / 0.3.1 |
| 容器 Warp / Open3D / Kaolin | 1.0.0 / 0.18.0 / 0.15.0 |

官方代码固定在提交 `a1b694b83e633c2cb6115b9063d940a687759392`。基础镜像 digest 为 `wenbowen123/foundationpose@sha256:22837f81c0cfc1906b96daa344f8e80919c7619b816fcab487a024f1f566c215`。容器中已编译 `mycpp` 并安装 Kaolin。

原 README 中“宿主机 CUDA 12.4”是预设值；这台机器的 `nvidia-smi` 实际显示驱动支持 CUDA 12.2，`nvcc` 是 12.1。实际容器 CUDA 运算与推理已验证成功。

## 直接使用

在你的终端执行：

```bash
ssh USER@UBUNTU_HOST
bash /data/ZJC/foundationPos/setup/enter_foundationpose.sh
```

进入后工作目录为 `/workspace/FoundationPose`，Python 环境为容器中的 `my`。运行完整官方 mustard0 序列：

```bash
python run_demo.py --debug 0 --debug_dir /data/demo_full
```

这里使用 `--debug 0` 适合 SSH 无图形界面运行。完整序列有 737 帧；其输出将保存在宿主机 `/data/ZJC/foundationPos/foundationpose_data/demo_full`。完整 737 帧运行由你后续启动，本次已验收前 3 帧。

若要重复本次 3 帧验证，在 Ubuntu 宿主机执行：

```bash
docker exec foundationpose /opt/conda/envs/my/bin/python \
  /data/setup/verify_demo.py --output /data/demo_smoke --frames 3
```

## 验证结果与输出

- 官方 `check_env.py --demo-data` 通过，权重和示例数据齐全。
- 8 项实际环境测试全部通过：GPU 矩阵计算、NumPy/PyTorch 数据往返、CUDA 光栅化、PyTorch3D CUDA KNN、mycpp、FoundationPose 导入、Warp 深度处理及代码目录检查。
- 官方 scorer/refiner 权重实际加载到 GPU；mustard0 首帧初始化和后续两帧跟踪成功，3 个位姿矩阵通过合法性检查。
- 已检查首帧输出图片，3D 包围框与坐标轴覆盖目标 mustard 瓶。

Ubuntu 上的结果：

```text
foundationpose_data/environment_verification.json
foundationpose_data/demo_smoke/report.json
foundationpose_data/demo_smoke/poses/
foundationpose_data/demo_smoke/visualizations/
foundationpose_data/packages_after_build.txt
foundationpose_data/official_assets_manifest.json
foundationpose_data/setup_logs/
foundationpose_data/foundationpose_ready_image_id.txt
```

容器路径 `/workspace/FoundationPose` 对应宿主机 `FoundationPose/`；容器路径 `/data` 对应宿主机 `foundationpose_data/`。权重、数据与推理结果均保存于挂载目录中。

## 原生 Conda 备用环境

原生环境也已完成安装，8 项环境检查、官方两模型权重加载和前 3 帧初始化/跟踪全部通过；`pip check` 显示依赖无冲突。

| 项目 | 实测版本 |
| --- | --- |
| Python | 3.11.14 |
| PyTorch / CUDA 构建版本 | 2.4.1+cu121 / 12.1 |
| NumPy | 2.1.3 |
| PyTorch3D / NVDiffRast | 0.7.8 / 0.3.3 |
| Warp / Open3D | 1.6.2 / 0.19.0 |

环境前缀为 `/home/ni/anaconda3/envs/foundationpose`，代码目录为 `/data/ZJC/foundationPos/FoundationPose-conda`。权重和示例数据共享主代码目录中的同一份文件。

无需 Docker 时，在 Ubuntu 宿主机执行下列命令运行完整官方序列：

```bash
bash /data/ZJC/foundationPos/setup/conda_run.sh
```

脚本会激活专用 Conda 环境、设置 CUDA 12.1 和 RTX 3090 编译参数，并默认以 `--debug 0` 运行，输出到 `foundationpose_data/demo_full_conda/`。也可传入自定义命令：

```bash
bash /data/ZJC/foundationPos/setup/conda_run.sh \
  python /data/ZJC/foundationPos/setup/verify_demo.py \
  --repo /data/ZJC/foundationPos/FoundationPose-conda \
  --output /data/ZJC/foundationPos/foundationpose_data/demo_smoke_conda --frames 3
```

备用环境的记录保存在 `foundationpose_data/conda_verification.json`、`foundationpose_data/demo_smoke_conda/` 和 `foundationpose_data/conda_setup/`，其中包含完整包版本与安装日志。此备用环境验收范围为有网格的位姿推理。

2026-10-13 已接入 D435i，并建立独立 `.camera-venv`；普通用户下的 SDK 枚举、60 组 640×480 RGB-D 取帧及深度对齐检查通过，约 30 FPS。详细说明见 `D435i_connection.md`。

模型验收范围是官方有网格 Demo 的位姿初始化和跟踪。自有物体的正式多视角采集、无 CAD 的 BundleSDF 重建与位姿推理需继续配置和验证。

<!-- CUP-LIVE-SETUP-20261014 -->
2026-10-14：独立Ubuntu `.camera-venv`新增 `opencv-python-headless==4.11.0.86`，NumPy1.26.4、SDK2.55.1.6486、Pillow12.3.0保持；pip check及实际CPU/GPU导入通过。主机USB采集+现有FoundationPose容器文件桥接，不改GPU/模型环境或容器USB权限。GPU/HTTP回放验证通过；现场相机、实时FPS与位姿精度尚未验证。说明见[Ubuntu实时杯子位姿初跑](reports/CUP_LIVE_POSE_20261014.md)。

<!-- CUP-AUTO-REACQUISITION-SAM2-20261015 -->

## 自动找回目标实验分支（2026-10-15）

分支 `fix/reacquisition-sam2-eval`，不合并main。Ubuntu启动：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000 --auto-reacquire
```
首次仍需冻结、框选、确认目标Mask；后续意外失跟自动全图搜索，无需再次人工框选。目标重新进入画面时请短暂停稳，供新RGB-D注册和连续3帧验证。
首帧对照默认 `--mask-backend sam`；试SAM2首帧追加 `--mask-backend sam2`；禁用自动找回追加 `--no-auto-reacquire`。
SAM2.1 Hiera Tiny在独立 `foundationpose_data/environments/sam2` 环境，源码与权重分别位于 `foundationpose_data/tools/sam2` 和 `foundationpose_data/checkpoints/sam2`；不升级FoundationPose容器或相机环境。
恢复流程：深度/初始目标颜色检查失败→隐藏无效位姿→SAM2全图候选→初始外观与深度尺度筛选→新帧检查→FoundationPose全局注册→Mask/深度检查→连续3新帧确认。
没有匹配或存在多个分离的相似候选时继续等待。该外观与尺度匹配不是语义杯子检测器，也不保证区分同色同尺寸的另一只杯子。
每次全图搜索保留RGB、深度、SDK/主机时间戳、候选Mask、目标筛选、SHA和失败日志。每次注册另存官方top1、前8候选及自定义几何选择，不能冒称所有输出都是未修改的官方top1。
当前连续跟踪FPS按分段统计，搜索/暂停/重新初始化耗时单列，不再混入跟踪FPS。原始事件仍保留，完整运行吞吐需另算。
首帧可用SAM2，但更换首帧分割器本身不构成自动重获。模型几何缺陷、真实移动相机的恢复成功率与6D精度需继续现场/ArUco评测，不把回放或合成消失测试当物理GT。
# 2026-10-18 RealSense Viewer用户目录安装

已安装官方focal/amd64 SDK工具`2.55.1-0~realsense.12473`到`foundationpose_data/tools/realsense_viewer_20261018_v2/root`，Ubuntu桌面入口为“RealSense Viewer (FoundationPos)”。终端运行`bash setup/run_realsense_viewer_ubuntu.sh`，通过项目记录器启动。无sudo、系统包/内核/固件或现有Python环境变更；具体签名、SHA、失败与复验见[安装记录](reports/UBUNTU_REALSENSE_VIEWER_20261018.md)。使用Viewer预览后先关闭所有流/窗口，再启动位姿程序。
