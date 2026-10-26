# D435i 连接与 Ubuntu 环境检查

Windows Viewer于2026-10-14配置为官方2.55.1便携版：`tools/realsense-viewer/2.55.1/realsense-viewer.exe`；桌面/开始菜单快捷方式名“Intel RealSense Viewer 2.55.1”。Intel数字签名和快捷方式目标校验通过，窗口已启动；界面状态检查受Computer Use授权限制，未验证GUI内相机/流。安装与限制见 [安装留档](reports/WINDOWS_VIEWER_INSTALL_EXPERIMENT_20261014.md)。拍照脚本和Viewer应分开使用，以免相机被同时占用。

RGB-depth对齐检查可用新增`setup/run_rgbd_alignment_check.ps1`读取已保存原始对齐深度，生成透明叠图和RGB上的绿色深度突变边缘；静态目标摆放、命令与判据见 [Windows叠图检查](reports/RGBD_ALIGNMENT_CHECK_GUIDE_20261014.md)。脚本运行成功不等于物理标定精度验收。

> 2026-10-14：相机接Windows，USB3.2、60对640×480@30对齐RGB-D再次取帧通过；Windows补齐OpenCV和官方便携Viewer，新照片入口支持High Accuracy、bag及独立滤波深度并已验证预设恢复/回放。Ubuntu用于离线重建，SSH及Open3D检查通过。详见 [当前OBJ环境配置](reports/OBJ_ENVIRONMENT_SETUP_20261014.md)；下文Ubuntu直连相机结果属于历史。

检查日期：2026-10-13。Ubuntu 主机：`USER@UBUNTU_HOST`。

后续操作与留档规则见 [REPRODUCTION_GUIDE.md](REPRODUCTION_GUIDE.md)，执行结果和问题持续写入 `EXPERIMENT_LOG.md`、`ISSUES.md`。

## 实测状态

| 项目 | 检查结果 |
| --- | --- |
| 操作系统 | Ubuntu 20.04，内核 5.15.0-139-generic |
| GPU | RTX 3090 24 GB，驱动 535.230.02 |
| 原生 FoundationPose 环境 | Python 3.11.14、PyTorch 2.4.1+cu121，实际 CUDA 运算通过 |
| Docker FoundationPose 环境 | Python 3.8.18、PyTorch 2.0.0+cu118，实际 CUDA 运算通过；容器运行中 |
| Ubuntu USB 设备 | 已识别 Intel RealSense D435i，ID `8086:0b3a`，连接速度 5000 Mbps |
| 相机固件 | 5.17.0.10 |
| Python RealSense SDK | 独立 `.camera-venv`：Python 3.11.14、pyrealsense2 2.55.1.6486、NumPy 1.26.4、Pillow 12.3.0 |
| USB 权限规则 | 已配置 `/etc/udev/rules.d/99-foundationpose-d435i.rules`，普通用户 ni 可访问 |
| 相机检查脚本 | `setup/verify_d435i.py`，启动脚本 `setup/run_d435i_check.sh` |
| Docker 相机访问 | 当前容器没有映射 USB 相机设备，只挂载代码与数据目录 |

已在普通用户 ni 下完成 SDK 枚举与真实 RGB-D 取帧：RGB8 和 Z16 均为 640×480 @30，深度对齐到彩色图；预热 30 帧后采集 60 组，实际约 29.98 FPS，彩色和深度均有 60 个不同帧编号，脚本成功结束并释放相机。此检查验证相机采集能力；物体位姿推理、几何重建、IMU 与长期取帧稳定性尚未在本次相机检查中验收。

相机采集环境位于 `/data/ZJC/foundationPos/.camera-venv`，与 FoundationPose 的两套模型环境分开。USB 规则仅针对 D435i，设置为 `0660`、组 `plugdev`，ni 已属于该组；规则使用 Ubuntu 20.04 udev 245 兼容语法。

本次深度原始单位换算为米的比例为约 `0.001`。报告保留 SDK 返回的实际比例，使用时应读取 `depth_scale.txt`。彩色相机内参为：

```text
608.04510498    0             328.438232422
0              608.036132812 243.226287842
0              0             1
```

本次画面包含显示器、键盘与线缆，约 40% 像素有非零深度。报告中的此比例只按深度值非零计算，不能直接视为精度或重建质量指标。正式采集物体前，需要检查目标区域的深度空洞、离群值与视角覆盖。

## 两种连接方式

**推荐：D435i 直接接 Ubuntu 主机的 USB 3.x 接口，使用支持 USB 3.x 的数据线。** 采集程序在 Ubuntu 上运行，后续接入同一台机器上的位姿推理流程。Windows 电脑可以通过 SSH 控制 Ubuntu。

```text
D435i --USB--> Ubuntu：采集 RGB-D、重建、位姿推理
Windows --SSH--> Ubuntu：执行命令、查看或取回结果
```

**如果相机只能接在 Windows 电脑上，也可以先在 Windows 采集，再传到 Ubuntu 处理。** 导出对齐的彩色图、深度图、内参和深度单位，或使用 SDK 录制并回放，再做重建与推理。录播文件应使用兼容的 SDK 版本解析。[官方录播说明](https://github.com/realsenseai/librealsense/blob/v2.55.1/doc/record-and-playback.md)

普通 SSH 连接不会自动把 Windows 的 USB 设备映射到 Ubuntu。Windows 采集、Ubuntu 实时推理需要额外实现网络传输和推理接收程序，目前尚未部署。

## 下一步

1. 将目标物体放入画面，检查目标区域的彩色图和有效深度是否清楚完整。
2. 使用已部署的 `setup/run_d435i_capture.sh` 保存连续 RGB-D 序列、内参和深度单位。具体摆放、试拍和录制命令见 `D435i_capture_steps.md`；`run_d435i_check.sh` 保留最后一组图片与每帧统计，适合连接检查。
3. 为目标准备 Mask，执行多视角几何重建，再接入自有物体位姿估计与跟踪。
4. 采集数据可保存到 `/data/ZJC/foundationPos/foundationpose_data/my_object/`。该目录已挂载到 FoundationPose 容器中的 `/data/my_object/`，适合先做离线数据处理。

已有 `run_demo.py` 读取官方示例文件。接上相机后，还需要采集与自有数据推理脚本才能使用 D435i 的实时画面。

可重复执行实际相机检查（在 Ubuntu 宿主机运行）：

```bash
ssh USER@UBUNTU_HOST
bash /data/ZJC/foundationPos/setup/run_d435i_check.sh \
  --output /data/ZJC/foundationPos/foundationpose_data/d435i_check_$(date +%Y%m%d_%H%M%S) \
  --frames 60 --warmup 30
```

本次报告与最后一帧输出位于 `/data/ZJC/foundationPos/foundationpose_data/d435i_check_20261013/`，包含 `report.json`、`rgb.png`、原生单位的 16-bit `depth.png`、米制 `depth_meters.npy`、深度预览、`K.txt` 和 `depth_scale.txt`。本地 `reports/d435i_check_20261013/` 也保留同一份结果。

安装日志及锁定版本位于 `foundationpose_data/camera_setup/`。参考：[官方 Linux 安装说明](https://github.com/realsenseai/librealsense/blob/v2.55.1/doc/installation.md)、[官方对齐示例](https://github.com/realsenseai/librealsense/blob/v2.55.1/wrappers/python/examples/align-depth2color.py)。

<!-- CUP-LIVE-SETUP-20261014 -->
2026-10-14新增Ubuntu直连实时入口：`bash setup/run_cup_live.sh`，需D435i接Ubuntu USB3；本次探测设备0，现场硬件验证待接机。浏览器首次冻结/框选Mask，官方register后track；自动记录实际推理RGB-D/K/SDK时间戳/姿态/叠图。离线GPU/HTTP测试通过，不能当相机对齐或6D精度验收。说明见[Ubuntu实时杯子位姿初跑](reports/CUP_LIVE_POSE_20261014.md)。

<!-- CUP-LIVE-DRIFT-20261014 -->
2026-10-14实际Ubuntu直连D435i USB3.2会话399帧已验证输入与保存、约10FPS；用户确认移动相机。冻结帧到首跟踪帧24.39秒、杯身图像位置跳约182像素，旧姿态从首跟踪帧即失跟；初始Mask有效深度36.7%。同模型/权重在当前帧+检查过的新Mask重新初始化，独立120帧诊断重放的抽查投影明显改善（非GT）。正式实时入口仍需补初始化变化检查与失跟判定，本期没有改生产跟踪行为；见[漂移分析](reports/CUP_LIVE_DRIFT_ANALYSIS_20261014.md)。

<!-- CUP-FAST-ARUCO-20261014 -->
2026-10-14已部署可选 `bash setup/run_cup_live_fast.sh --aruco-marker-length-m 实测米值 --aruco-id 0 --aruco-fixed-scene`。固定杯子/码，只移动相机；同帧RGB参考、无损NPY原图/毫米深度/SDK时间戳/估计矩阵/误差CSV/源码和权重证据均留档；正常结束自动汇总。保留官方2次细化与原入口。回放端到端约27.49FPS，真实新版移动相机帧率与物理精度未实测；首帧对齐误差消除初始偏差，绝对误差需要独立码→原始OBJ变换。初步网格孔洞/杯把问题与部分失跟漏检仍未解决。见[操作说明](reports/CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md)及[验证结果](reports/CUP_FAST_ARUCO_RESULT_20261014.md)。

<!-- CUP-NO-ARUCO-FPS-START-20261015 -->
2026-10-15用户先测试FPS、暂不贴ArUco。可用 `bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000`，不传任何ArUco参数，仍自动留档；Ubuntu打开 `http://127.0.0.1:8765`，相机对准完整杯子，停稳、冻结、框选并检查Mask、初始化后再移动。当前会话已启动时直接打开页面，避免重复占用端口/相机。初次检查镜头朝天花板，等待目标入镜，尚无本次杯子跟踪FPS；问题待现场复验，不标记已解决。见[启动与记录](reports/CUP_NO_ARUCO_FPS_START_20261015.md)和[问题处理](reports/CUP_NO_ARUCO_FPS_ISSUES_20261015.md)。

<!-- WINDOWS-ALL-E-STORAGE-20261015 -->

## 2026-10-15 Windows统一E盘存储（当前规则）

- 用户本次明确要求后续保存文件统一E盘；本条替代此前“代码/venv/小日志仍在C盘”的安排。
- 项目真实根目录是 `E:\foundationPos`；原 `C:\Users\YOUR_USER\Desktop\foundationPos` 仅为指向E盘的NTFS目录联接。两条路径是同一份文件，原命令保持可用，禁止再复制一份项目回C盘。
- 本机新增代码、文档、报告、运行档案、导出包和下载文件写到 `E:\foundationPos` 或 `E:\foundationPos_data`；采集根目录仍为 `E:\foundationPos_data\windows_captures`。优先使用E盘真实路径。
- 记录器读取 `setup/windows_storage_policy.json`，为Windows子进程设置E盘TEMP/TMP、pip/HuggingFace/Torch/通用/Matplotlib/Numba/CUDA缓存。后续操作继续通过记录器；不要绕过E盘策略下载/生成大文件到C盘。
- pip缓存实际位于 `E:\foundationPos_data\cache\pip`；旧AppData缓存目录也是联接，兼容既有pip使用方式。
- Ubuntu根目录仍为 `/data/ZJC/foundationPos`，不能把Windows venv或Windows磁盘配置用于Linux执行。
- 迁移采用逐文件SHA256验证，验证成功才删除C盘原件。所有旧数据、成功/失败/中断档案及源代码快照保留；迁移证据位于 `E:\foundationPos_storage_ops\20261015`。


<!-- CUP-SAM-INITIALIZATION-20261015 -->

## SAM 初始化分割（2026-10-15）

Ubuntu `/data/ZJC/foundationPos` 执行：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000
```
页面 `http://127.0.0.1:8765`，重新启动入口并刷新页面后生效。
默认 `--mask-backend sam`，官方 SAM ViT-B；旧 `run_cup_live.sh` 仍是 GrabCut。
冻结 → 拖框包含杯身和杯把 → 生成 SAM Mask → 按需要加前景点/背景点 → 再生成 → 确认初始化。
绿色点表示杯子前景，红色点表示背景。把手空隙属于背景；可见杯子内壁属于物体，不能为了深度缺失而全部删掉。
改点/改框后确认按钮禁用，重新生成后才能初始化。Mask 黄色半透明显示；需人工检查，没有可靠GT。
保持相机和杯子不动，直到初始化结束并开始跟踪。SAM仅在生成/修正Mask时运行，进程结束释放GPU，不逐跟踪帧运行。
每次尝试保留在会话 `mask_attempts/`：原始RGB NPY、框和提示点、二值Mask PNG、SHA、SAM预测IoU、耗时和失败日志。
SAM预测IoU不是实际分割或6D精度。位姿输入仍使用同一冻结RGB-D；原始深度、网格缺陷与失跟问题仍需分别检查。
SAM源码 `/data/ZJC/foundationPos/foundationpose_data/tools/segment-anything`；权重 `checkpoints/sam/sam_vit_b_01ec64.pth`；来源与SHA见同目录 `installation.json`。
没有升级FoundationPose的PyTorch/torchvision或Windows相机环境。Ubuntu产物保存在Ubuntu数据盘；传回Windows的产物统一E盘。
显式GrabCut对照：在快速入口追加 `--mask-backend grabcut`；SAM失败不会静默回退。
