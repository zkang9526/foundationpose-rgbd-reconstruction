# FoundationPose 复现记录（Ubuntu 20.04 / RTX 3090 / 自有 RGB-D 相机）

> 归档说明（2026-10-26）：这是原 README，保留早期配置假设、探索步骤与当时状态。部分示例脚本/压缩包未实际存在，不作为当前可用入口。请先阅读 [项目首页](README.md) 和 [快速指南](docs/QUICKSTART.md)。

> 项目主页：https://github.com/NVlabs/FoundationPose
> 本文档是**个人复现操作手册，不是 NVIDIA 官方 README**。以你实际克隆的仓库版本、其官方 README 和代码接口为准。
> 适用配置：Ubuntu 20.04、NVIDIA RTX 3090（24 GB）、宿主机显示 CUDA 12.4、RGB-D 相机。
> 复现目标：**先跑通官方 Demo → 再处理自己的 RGB-D 数据 → 无 CAD 时重建物体几何 → 估计与跟踪 6D 位姿**。

> 2026-10-14实际进度：Windows侧面与斜俯视各36张参考、5张完整独立测试及Mask已在Ubuntu校验导入。独立BundleSDF环境已实际运行，保存两个默认网格与冻结神经位姿学习率的实验网格及算法参考矩阵；三网格形状QA均未通过，重建退出清理139未解决。官方FoundationPose权重已完成5张独立初始化并退出0，但首选有杯把朝向错误，当前只能称流程试跑。当前结果、可重跑命令和限制见 [CUP_POSE_PILOT_RESULTS_20261014.md](reports/CUP_POSE_PILOT_RESULTS_20261014.md)。下文starter.zip和make_init_mask.py在工作区不存在，实际分割是 `setup/make_cup_masks_grabcut.py`；原图、失败及各版本保留，没有GT或杯子位姿网络重训。

## 0. 先了解两种复现路线

- **有 CAD / 三维网格**：RGB + 对齐深度图 + 相机内参 `K` + 首帧目标 Mask + OBJ/PLY 网格 → FoundationPose 位姿初始化与跟踪。
- **没有 CAD（当前优先考虑）**：先采集目标物体**多视角 RGB-D**，提供相应目标分割数据，采用适用的无模型初始化/重建流程（例如官方文档对应的 BundleSDF 工作流）获得物体几何表示，再进行位姿估计与跟踪。**没有 CAD ≠ 直接丢入单张 RGB 图就能获得可靠的任意新物体 6D 位姿。**

> 下文提供的自定义数据脚本 `run_rgbd_folder.py` **需要网格模型**：如果当前没有 CAD 文件，请先完成「第 8 节」的三维重建，不能跳过这一步直接运行该脚本。论文中的 model-free 工作流和“先重建网格，再按 model-based 路线推理”并不完全等同。

### 本次验收标准

- [x] Ubuntu宿主机的 `nvidia-smi` 已显示RTX3090，见实际运行档案。
- [x] Docker GPU与PyTorch CUDA已实际用于官方Demo/杯子试跑。
- [x] 官方预训练权重加载、Demo前3帧位姿与可视化已验证。
- [x] D435i已保存对齐RGB、16-bit毫米深度及内参。
- [ ] 无 CAD 时获得可用、尺度正确的物体网格或运行官方无模型流程。
- [x] 自有杯子5张独立图已输出估计矩阵与叠图；可靠性未通过，真实连续跟踪/精度评测未完成。

---

## 1. 检查机器和 NVIDIA 驱动（宿主机执行）

```bash
lsb_release -a
nvidia-smi
nvcc --version || true
```

- `nvidia-smi` 必须能看到 RTX 3090；若驱动尚未工作，先修复宿主机驱动再继续。
- `nvidia-smi` 中的 `CUDA Version: 12.4` 是**驱动支持的 CUDA 版本**，不一定表示安装了 CUDA 12.4 Toolkit；`nvcc --version` 才是编译器版本。
- RTX 3090 的 CUDA compute capability 为 **8.6**，源码编译时可以设置 `TORCH_CUDA_ARCH_LIST=8.6`。
- 推荐 **Docker**：宿主机不需要为 FoundationPose 强制安装同版本的 PyTorch/CUDA Toolkit。容器 CUDA 版本可以与宿主机显示的 12.4 不完全相同，但必须与驱动兼容。

记录初始环境：

```bash
mkdir -p ~/foundationpose_data
nvidia-smi | tee ~/foundationpose_data/nvidia-smi.txt
```

## 2. 安装 Git、Docker（宿主机执行）

```bash
sudo apt update
sudo apt install -y git git-lfs curl wget ca-certificates gnupg \
  lsb-release build-essential cmake ninja-build python3-venv unzip
```

如果尚未安装 Docker，请添加 Docker 的 Ubuntu 软件源并安装：

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin
sudo systemctl enable --now docker
sudo docker --version
```

已有可用 Docker 的机器可跳过安装步骤。随后安装 NVIDIA Container Toolkit，让 Docker 使用显卡：

```bash
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
  | sudo gpg --dearmor --yes \
  -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L \
  https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
  | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
  | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt update
sudo apt install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

**测试 GPU 容器**（首次需拉取镜像，网络不通则先解决镜像源访问问题）：

```bash
sudo docker run --rm --gpus all \
  nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

> 这里的 CUDA 12.4 镜像仅用于**GPU 访问测试**，不是指定 FoundationPose 必须使用的基础镜像。

## 3. 下载项目源码、记录版本（宿主机执行）

```bash
cd ~
git lfs install
git clone --recursive https://github.com/NVlabs/FoundationPose.git
cd ~/FoundationPose
git submodule update --init --recursive
git rev-parse HEAD | tee ~/foundationpose_data/foundationpose_commit.txt
ls -lah
```

**不要直接覆盖官方仓库的 `README.md`**。建议把本复现文档复制进项目后命名为 `README_reproduce_zh.md`，保留官方的 `README.md` 用于核对依赖和权重链接。

## 4. 构建 Docker 环境（宿主机执行）

不同提交的镜像名、Dockerfile 路径和启动方式可能变化。**先阅读仓库根目录 `README.md` 中的 Installation / Docker 部分**。如果当前版本提供了 Dockerfile，可按下列命令尝试本地构建：

```bash
cd ~/FoundationPose
find . -maxdepth 3 -name Dockerfile

if [ -f docker/Dockerfile ]; then
  DOCKERFILE=docker/Dockerfile
elif [ -f Dockerfile ]; then
  DOCKERFILE=Dockerfile
else
  DOCKERFILE=''
  echo '未找到常见的 Dockerfile 路径：请采用当前官方 README 的 Docker 方案。'
fi

if [ -n "$DOCKERFILE" ]; then
  sudo docker build --network host -t foundationpose:local -f "$DOCKERFILE" .
fi
```

> 若官方构建说明要求额外参数、预构建镜像或特定构建上下文，以官方说明为准；不要随意升级镜像内的 PyTorch。

首次启动容器（已下载的权重、数据、编译产物最好放在挂载目录）：

```bash
mkdir -p ~/foundationpose_data
cd ~/FoundationPose
sudo docker run --rm -it \
  --gpus all --ipc=host --network host \
  -v "$PWD":/workspace/FoundationPose \
  -v "$HOME/foundationpose_data":/data \
  -w /workspace/FoundationPose \
  foundationpose:local bash
```

**从此处到第 6 节的模型命令在容器中执行**，看到类似 `root@...:/workspace/FoundationPose#` 的提示符才开始运行。

## 5. CUDA、PyTorch 和原生扩展（容器内执行）

```bash
nvidia-smi
python - <<'PY'
import torch
print('PyTorch:', torch.__version__)
print('PyTorch CUDA:', torch.version.cuda)
print('CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('GPU:', torch.cuda.get_device_name(0))
    print('Compute capability:', torch.cuda.get_device_capability(0))
PY
```

期望：`CUDA available: True`，设备名包含 `RTX 3090`，计算能力 `(8, 6)`。

测试关键 GPU 渲染依赖：

```bash
python -c "import nvdiffrast.torch; print('nvdiffrast OK')"
```

如果仓库版本还要求编译 C++/CUDA 扩展：

```bash
find . -maxdepth 3 \( -name 'build_all.sh' -o -name 'setup.py' \)
```

**仅当官方 README 指示并且项目根目录确实存在 `build_all.sh` 时**，执行：

```bash
export TORCH_CUDA_ARCH_LIST='8.6'
export MAX_JOBS=8
bash build_all.sh
```

不要因为 `nvcc --version` 与宿主机 `nvidia-smi` 显示的 CUDA 版本不同，就修改一个已经能正常运行的容器。首先检查**容器内**的 `nvcc`、PyTorch CUDA、编译日志是否互相兼容。

## 6. 下载预训练权重并运行官方 Demo（容器内执行）

权重、Demo 数据下载地址会随仓库版本调整；**不要凭空猜测权重 URL 和文件名**。从你克隆的官方 README 获取对应链接：

```bash
cd /workspace/FoundationPose
grep -nEi 'weight|checkpoint|pretrain|download|demo[_ -]?data' README.md
# 查看各网络的实际权重加载位置
grep -R -n --exclude-dir=.git --include='*.py' \
  -E 'weights/|ckpt_dir|model_best\.pth' . | head -n 80
```

按官方链接下载**位姿评分网络（ScorePredictor）和位姿细化网络（PoseRefinePredictor）**所需权重，解压到源码实际读取的目录（通常涉及 `weights/`）；Demo 数据也按官方说明准备。验证下载文件是否存在：

```bash
find weights -type f \( -name '*.pth' -o -name '*.pt' \) -print 2>/dev/null
python run_demo.py --help
```

运行官方 Demo：

```bash
python run_demo.py
```

如果该版本 README 要求显式指定 `--mesh_file`、`--test_scene_dir` 等参数，就采用**当前 README** 的示例路径与命令；不要假设每个提交都有相同的示例目录。此阶段先确认**权重加载、扩展编译、渲染、pose 输出**全部正常，再接自己的相机。

## 7. 采集自己的 RGB-D 数据（宿主机执行）

推荐统一存成以下结构（颜色图和深度图必须对齐，文件名必须一一对应）：

```text
~/foundationpose_data/my_object/
├── color/
│   ├── 000000.png
│   └── 000001.png
├── depth/
│   ├── 000000.png
│   └── 000001.png
├── mask/
│   └── 000000.png
├── mesh/
│   └── model.obj         # 无 CAD 时：三维重建完成后放入
├── K.txt                 # 3×3 相机内参
└── depth_scale.txt       # 原始 depth 数值换算为“米”的比例
```

数据要求：

1. `color/`：普通彩色 PNG，脚本会使用 OpenCV 读取。
2. `depth/`：**单通道 uint16 PNG**，和 RGB 具有相同分辨率、对应视角。
3. `K.txt`：用于当前**对齐到彩色图**的 `fx, fy, cx, cy`，如果图像做了缩放或去畸变，应使用对应的新内参。
4. `depth_scale.txt`：一行数值，如 `0.001` 表示原始整数深度单位为毫米。计算关系：`depth_m = depth_raw * depth_scale`。
5. `mask/000000.png`：首帧目标的二值分割掩码；无模型三维重建通常需要多帧准确掩码，具体依据重建方法而定。
6. RGB 和 Depth 尽可能做到时间同步，避免运动目标产生跨模态错位。

### 7.1 Intel RealSense 相机示例（如 D435 / D455）

如果你使用 RealSense，可以使用之前提供的辅助脚本包 `foundationpose_rgbd_starter.zip`（该工具包**不是官方仓库的一部分**）。把 ZIP 放在 `~/Downloads/`，解压：

```bash
cd ~
unzip ~/Downloads/foundationpose_rgbd_starter.zip -d ~
```

在宿主机新建**相机采集专用** Python 环境（不要破坏 FoundationPose 容器依赖）：

```bash
python3 -m venv ~/fp-camera-env
source ~/fp-camera-env/bin/activate
python -m pip install -U pip
python -m pip install numpy opencv-python pyrealsense2
```

运行采集：

```bash
python ~/foundationpose_rgbd_starter/capture_realsense.py \
  --output ~/foundationpose_data/my_object \
  --frames 120
```

脚本将对齐深度至 RGB，并保存 `color/`、`depth/`、`K.txt`、`depth_scale.txt`。如果 Ubuntu 20.04 自带 Python 3.8 无法安装当前 `pyrealsense2` wheel，请使用受支持的 Python 环境或对应版本的 librealsense SDK；不要在已有 FoundationPose 容器中盲目升级 Python。

如果你使用的是**非 RealSense 相机**，应通过该相机的 SDK 实现同样的数据格式，不要直接运行上述 `pyrealsense2` 脚本。

### 7.2 制作第一帧 Mask

在有桌面环境的宿主机中（可以继续使用上述 venv）：

```bash
python ~/foundationpose_rgbd_starter/make_init_mask.py \
  --scene ~/foundationpose_data/my_object
```

这会通过框选 + GrabCut 生成 `mask/000000.png`，仅适合初步调试；正式实验建议逐帧检查或采用高质量分割结果。

## 8. 没有 CAD 模型：先准备可用的物体几何

你现在**没有 CAD 模型**，建议按照下列路线执行：

1. **先跑通官方 Demo**：排除 CUDA、PyTorch、权重和推理代码本身的问题。
2. **多视角采集**：让相机从不同方向观察物体（或以受控方式转动物体），尽量覆盖前后左右、顶部；保持 RGB-D 标定稳定。透明、镜面反光、纯黑表面会增加重建难度。
3. **分割与清洗深度**：为重建序列提供高质量物体 Mask，去除离群深度和背景。单张首帧 Mask 往往不足以完成稳定重建。
4. **执行三维重建**：优先检查 FoundationPose 官方 README / model-free 说明中对应的 **BundleSDF** 等流程（如需要，另行安装其依赖）。如果采用其他 RGB-D 重建工具，也要保证输出是尺度正确、拓扑可用的 OBJ/PLY 网格。
5. **检查模型坐标系与单位**：建议使用米；如果 OBJ 使用毫米，推理时须做单位转换。确定模型原点、姿态定义、相机坐标系一致。
6. **进入第 9 节**，通过重建网格完成后续初始化与跟踪。

> **重要区分**：如果你计划严格复现论文的 *model-free* 实验，而不是先重建再按模型方式推理，必须使用该版本官方定义的 model-free 数据及评估流程。这里无法在离线状态核验该流程对应的精确脚本和命令，因此不提供未经核对的 BundleSDF 启动命令。

## 9. 用自己的 RGB-D 数据进行位姿估计（容器内执行）

**前提：第 6 节 Demo 已成功 + 第 8 节已获得可用网格。** 下面使用辅助包中的 `run_rgbd_folder.py`；该脚本根据公开版 `estimater.py` API 编写，**不保证与所有 FoundationPose 提交完全兼容**，需要按当前源码核对 `FoundationPose`、`ScorePredictor`、`PoseRefinePredictor` 的接口与坐标系约定。

退出旧容器（若仍在），在**宿主机**重新启动并挂载辅助工具目录：

```bash
cd ~/FoundationPose
sudo docker run --rm -it \
  --gpus all --ipc=host --network host \
  -v "$PWD":/workspace/FoundationPose \
  -v "$HOME/foundationpose_data":/data \
  -v "$HOME/foundationpose_rgbd_starter":/tools:ro \
  -w /workspace/FoundationPose \
  foundationpose:local bash
```

在**容器内**执行：

```bash
python /tools/run_rgbd_folder.py \
  --scene /data/my_object \
  --mesh /data/my_object/mesh/model.obj \
  --mesh-unit m \
  --output /data/my_object/results
```

如果你的网格坐标单位是**毫米**，把 `--mesh-unit m` 改成 `--mesh-unit mm`。运行正常后，输出类似：

```text
results/
├── pose/
│   ├── 000000.txt           # 每帧 4×4 位姿矩阵
│   └── 000001.txt
├── vis/
│   ├── 000000.png           # 坐标轴/三维包围盒投影
│   └── 000001.png
└── debug/
```

特别提醒：各版本源码对**模型中心化、位姿矩阵是 object→camera 还是其他参考系**可能有额外转换。部署到机器人前，一定用已知物体位置验证变换方向与尺度，不能只凭输出矩阵形状判断正确。

## 10. 排查常见错误

| 现象 | 优先检查 |
|---|---|
| 宿主机 `nvidia-smi` 不可用 | NVIDIA 驱动、Secure Boot、GPU 驱动是否正常加载 |
| Docker 报 `could not select device driver ... gpu` | NVIDIA Container Toolkit、`nvidia-ctk runtime configure`、Docker 服务是否重启 |
| `torch.cuda.is_available() == False` | 是否以 `--gpus all` 启动；镜像 CUDA/驱动是否兼容；GPU 是否分配到容器 |
| `ModuleNotFoundError: nvdiffrast` | 当前镜像是否安装依赖；官方构建脚本是否已执行 |
| 编译时 `nvcc` / `sm_86` 错误 | 容器的 PyTorch CUDA、CUDA Toolkit、编译器及 `TORCH_CUDA_ARCH_LIST=8.6` |
| 模型权重找不到 | `ScorePredictor` / `PoseRefinePredictor` 的实际权重目录、文件名和下载完整性 |
| 运行时 CUDA OOM | 降低图像分辨率或同时运行的 GPU 任务，检查 RTX 3090 显存占用 |
| 位姿明显偏移、物体尺寸异常 | `depth_scale`、网格单位（mm/m）、相机 `K` 和图像缩放是否匹配 |
| 位姿跳动或跟踪失败 | 首帧 Mask、深度噪声、遮挡、物体对称性、运动模糊、网格质量 |
| RealSense 无法采集 | USB 3.x、设备权限、librealsense 与 Python 绑定版本、彩色/深度流模式 |

## 11. 如何判断复现成功

基础验收：

- 官方 Demo 正常生成位姿矩阵和叠加可视化。
- 自己的数据每帧输出一个 4×4 数值矩阵（旋转矩阵和以米为单位的平移）。
- 将模型轮廓/坐标轴投影到 RGB 图像时，位置和朝向与真实物体基本一致。
- 连续帧跟踪时，姿态变化平滑且没有严重漂移。

**注意：视觉上“看起来对”不等于精度达标。** 若要做论文级复现或比较 ADD / ADD-S 等指标，需要有标定好的 6D 真值、统一的模型坐标系和评价协议。

## 12. 建议进度与下一步

| 阶段 | 预计投入 | 结果 |
|---|---|---|
| 环境准备 + Demo | 1–3 天 | 正常加载权重和推理 |
| RGB-D 数据采集与对齐 | 1–2 天 | 可靠的彩色/深度/内参数据 |
| 无 CAD 几何重建 | 3–7 天或更久 | 可用 OBJ/PLY 网格 |
| 自定义位姿估计与调试 | 2–4 天 | 连续 6D 位姿与可视化 |

**建议你现在先执行第 1 节到第 3 节**，记录下面三个输出以便针对你机器做进一步排障：

```bash
nvidia-smi
nvcc --version || true
sudo docker --version
```

### 参考入口

- FoundationPose 官方源码：https://github.com/NVlabs/FoundationPose
- Docker 官方安装文档：https://docs.docker.com/engine/install/ubuntu/
- NVIDIA Container Toolkit 安装文档：https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- NVIDIA CUDA 支持矩阵：https://docs.nvidia.com/deploy/cuda-compatibility/
