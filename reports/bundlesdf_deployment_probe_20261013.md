# BundleSDF 部署检查（2026-10-13）

## 已验证的结论

Ubuntu SSH 已恢复。现有 FoundationPose 环境可用于有网格的推理，但不能直接进行未知杯子的联合跟踪/重建：`FoundationPose/bundlesdf` 只有 `run_nerf.py`、`nerf_runner.py`、`mycuda` 等神经场部分，没有 `run_custom.py`、`bundlesdf.py` 或 `BundleTrack` 跟踪器。FoundationPose 两个权重不是 BundleSDF 的 LoFTR 权重。

| 项目 | 只读实测 |
| --- | --- |
| FoundationPose 提交 | `a1b694b83e633c2cb6115b9063d940a687759392` |
| 现有容器 | `foundationpose`，持续运行约 3 天 |
| 可复用镜像 | `foundationpose:ready-20261010`，20.4GB（层会共享，非每容器复制整个镜像） |
| Python / Torch | 3.8.18 / 2.0.0+cu118 |
| 容器 nvcc | **11.3.109**；不能把 PyTorch cu118 当成编译器版本 |
| 已编译 | FoundationPose `mycpp.cpython-38...so`；Kaolin 已安装 |
| BundleSDF CUDA ops | 原 FoundationPose `build_all.sh` 中为可选且注释，不存在已编译 BundleSDF 跟踪器 |
| Eigen | 已源码安装于 `/usr/local/include/eigen3`；`dpkg` 无包名不意味着不存在 |
| 缺少的 C++ 开发包/头文件 | PCL、OpenCV（`dpkg-query` 与常见 include 目录两种检查） |
| 缺少的 Python 包 | `dearpygui`（即使关闭 GUI，源码仍在导入时引用）；PyMCubes 是否真正需要须按固定源码检查 |
| 已有 Python 包 | kornia0.7.1、yacs0.1.8、einops0.7.0、loguru0.7.2、ruamel.yaml0.18.6、h5py3.9.0、pyzmq24.0.1、trimesh4.2.0、pypng |
| /data 磁盘 | 117GB 可用，94% 已使用 |
| 原生备用环境 | `/home/ni/anaconda3/envs/foundationpose`，Python3.11.14；本次不修改 |

## 固定代码版本和部署路线

官方当前 `master` 在 2025-07-10 升级为 CUDA12.6/PyTorch2.6；其 Dockerfile 使用 DeepStream7.1，`mycuda/setup.py` 要求 `torch>=2.6.0`。直接在已验收的 FoundationPose 容器执行最新源码的 `pip install -e` 会改变 Torch 依赖，不宜采用。[官方升级历史](https://github.com/NVlabs/BundleSDF/commits/master/)、[最新 mycuda/setup.py](https://github.com/NVlabs/BundleSDF/blob/master/mycuda/setup.py)

采用升级前的官方提交 **`cf0610e3636bc42535c996f129161f44beeadc56`**（2024-12-25）。已通过 Ubuntu 网络读取该提交的 Dockerfile：原基础镜像 CUDA11.3.1/Ubuntu20.04，原方案 Python3.8、Torch1.11+cu113。已有 FoundationPose 镜像的系统和编译器与此接近，但 Torch2.0 兼容性仍需实际编译和导入验证，不能仅凭接近就宣称通过。[固定提交 Dockerfile](https://github.com/NVlabs/BundleSDF/blob/cf0610e3636bc42535c996f129161f44beeadc56/docker/dockerfile)

部署只新增独立代码目录、`foundationpose-bundlesdf` 容器和后续快照镜像。以已存在的 FoundationPose ready 镜像为基础，在新容器补齐 PCL/OpenCV 开发包、必要 Python 包，编译 `mycuda` 与 `BundleTrack`。保留原容器和原 Conda 环境。旧构建文件的 Python/CUDA/C++ 路径和标准须检查，必要适配保存 `git diff`，不能直接运行会清除 build 目录的官方 `build.sh`。

## 权重、输入与安全输出约束

- 使用已经逐帧验收的离线掩码，启动时 `--use_segmenter 0 --use_gui 0`。因此无需新增 XMem 代码或下载其分割权重。
- LoFTR 的 `outdoor_ds.ckpt` 仍必须下载并保存来源、大小、SHA256，再 CPU 加载核对 `state_dict`，路径为 `BundleTrack/LoFTR/weights/outdoor_ds.ckpt`。[官方权重目录](https://drive.google.com/drive/folders/1xu2Pq6mZT5hmFgiYMBT9Zt8h1yO-3SIp)、[官方 LoFTR 包装器](https://github.com/NVlabs/BundleSDF/blob/master/loftr_wrapper.py)
- 离线照片按相邻视角顺序可作为 RGB-D 序列尝试，但相机改俯仰后的两圈不能直接当作有已知外参的一条序列；先单圈试跑，检验跟踪，再考虑第二圈合并。
- 输入 `rgb/`、`depth/`、`masks/` 同名 PNG，深度 uint16 毫米，`cam_K.txt` 为 3×3 内参。输出 `ob_in_cam/` 是估计位姿，不是 GT。[官方自有数据入口](https://github.com/NVlabs/BundleSDF#run-on-your-custom-data)
- 固定 `run_custom.py` 的入口会递归清理 `out_folder`，每次必须使用新的、预先确认不存在且位于专用 runs 目录的输出路径。绝不能把原始采集目录、项目根目录或成功结果目录作为输出。
- 首轮小序列命令模板：`python run_custom.py --mode run_video --video_dir <单圈派生输入目录> --out_folder <新结果目录> --use_segmenter 0 --use_gui 0 --stride 1 --debug_level 2`。只有环境和资产复验通过后才启动，由主任务统一调度 GPU。

## 运行证据与问题

本地 `foundationpose_data/runs/` 中保留：

| run_id | 结果/范围 |
| --- | --- |
| `20261013_205257_000854_bundlesdf_remote_readonly_inventory_19ee6b62` | exit0；代码、资产、容器和磁盘 |
| `20261013_205321_695288_bundlesdf_remote_readonly_container_ecaa1daf` | exit0；已有扩展、Torch/CV 包、构建脚本 |
| `20261013_205414_495453_bundlesdf_remote_readonly_native_dependencies_ccf19e07` | exit1；缺包导致 `&&` 后续未运行，证据保留 |
| `20261013_205435_505340_bundlesdf_remote_readonly_python_packages_445bfa4a` | exit0；补做 Python/nvcc 检查 |
| `20261013_205722_028269_bundlesdf_remote_readonly_include_paths_3cf74c0c` | exit1；显式列出的不存在路径，证实 Eigen 源码安装与 OpenCV/PCL 缺失 |
| `20261013_205544_514254_bundlesdf_official_history_remote_a6837332` | exit0；官方公开 commit API 完整响应 |
| `20261013_205652_274982_bundlesdf_official_oldpin_sources_cf65153b` | exit1；7 份中 5 份读取成功，2 份 read timeout；结果另存 JSON |
| `20261013_205903_730712_bundlesdf_official_oldpin_api_sources_99232f15` | exit1；contents API 响应超时，原失败记录保留 |

本机 curl 首次命中沙箱拒绝代理端口9，按权限规则升级重试后仍 Schannel TLS失败（分别 `205452...653415a9` 和 `205510...27ede6cb`）。Ubuntu 网络可读取官方 GitHubAPI 和部分 raw 文件，但存在间歇超时；不能标为已解决。SSH 首次尝试自动更新 Windows known_hosts 因沙箱权限失败，但认证与命令成功；后续添加 `UpdateHostKeys=no` 后警告未再出现，不打印或留存密码。

本文件是部署探查记录；**截至本段写入时，尚未完成 BundleSDF 安装/编译、杯子网格或位姿推理**。后续实际部署结果按新运行记录追加。
