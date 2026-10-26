# Ubuntu直连D435i：杯子实时位姿初跑与留档

2026-10-14用户要求相机接Ubuntu后实时估计杯子位姿并保留记录。实时入口已部署，实际官方GPU推理、HTTP初始化/暂停/重新初始化/停止及完整记录验证通过。**当前SDK探测设备数0，相机现场取帧、真实处理FPS和6D准确度仍待验证**。所有GPU验证都明确是重复播放独立保存照片，不冒充现场采集。

## 连接与启动

把D435i插到Ubuntu机器的USB3接口，使用USB3数据线。Ubuntu已有相机SDK、D435i udev规则及ni访问权限，现有FoundationPose容器继续使用。主机采集SDK对齐RGB-D，经共享数据目录交给容器推理，无需USB转发到容器。

从Windows PowerShell启动并转发查看端口：

```powershell
ssh -L 8765:127.0.0.1:8765 USER@UBUNTU_HOST "cd /data/ZJC/foundationPos && bash setup/run_cup_live.sh"
```

保持此终端打开，在Windows浏览器打开 `http://127.0.0.1:8765`。也可以在Ubuntu终端执行：

```bash
cd /data/ZJC/foundationPos
FP_RUN_NOTE='Cup; candidate mesh; direct D435i; record actual placement and illumination here.' \
  bash setup/run_cup_live.sh
```

Ubuntu本机浏览器同样打开 `http://127.0.0.1:8765`。默认监听本机地址，Windows通过SSH转发访问。先完成模型加载，终端会打印实际输出目录与URL。启动时没有相机会明确退出并留下失败/条件记录；接机后重跑使用全新目录。

若要先做相机取帧检查，在Ubuntu运行现有自动留档入口：

```bash
cd /data/ZJC/foundationPos
bash setup/run_d435i_check.sh \
  --output "foundationpose_data/camera_checks/direct_live_$(date +%Y%m%d_%H%M%S)" \
  --frames 60 --warmup 30
```

相机检查正常退出后再运行实时入口，不同时占用相机。SDK按640×480 RGB8/Z16、30FPS取帧并对齐深度到RGB；使用当次实际内参和深度尺度，不复用Windows测试K。检查USB3、时间戳域、RGB/depth时间差及对齐内参；这些是数据一致性检查，不代替物理标定验收。

## 首次初始化与跟踪

1. 把完整杯身和杯把放进画面，停稳、手退出；建议沿用已试过的距离/视角，先少量缓慢运动。
2. 点击“1 冻结画面”，在左侧拖框包含完整杯身及杯把，并留少量背景。
3. 点击“2 生成框内 Mask”，检查黄色轮廓是否包含完整杯子并排除背景。Mask是ROI+GrabCut候选，细节不满意可重新拖框；不自动当精确分割或GT。
4. 点击“3 确认 Mask 并初始化”。该Mask严格绑定冻结的同一RGB-D帧，官方`register(iteration=5)`执行，成功后调用`track_one(iteration=2)`。
5. 检查右侧紫色完整网格轮廓，特别看杯把是否同侧并重合，再缓慢移动。轴/绿框是OBB显示坐标，原始OBJ姿态单独保存。
6. 方向不对或遮挡/出画面后，暂停并重新冻结、框选、初始化。数值失败或跟踪处理帧间隔超过2秒会要求重初始化；程序没有校准的可靠性置信度，错误旋转仍可能数值合法。
7. 点击“停止并保存记录”，或终端Ctrl+C正常停止。停止时若GPU正在处理，会完成并登记最后一帧，再退出。

本入口是首次目标Mask初始化后的位姿跟踪，不是无需首次选择的通用杯子自动检测器。沿用官方预训练scorer/refiner，[官方示例](https://github.com/NVlabs/FoundationPose/blob/main/run_demo.py)也是首次register、随后track。

## 帧率与记录

相机请求30FPS，实际处理FPS在页面显示，**当前没有现场FPS测量**。桥接只传最新帧、最多一个待处理请求，避免积压；保留每个实际参与推理的原RGB、毫米深度及SDK时间戳，跳过的相机帧不保存。默认不录bag。右侧叠图属于实际被推理的帧，左侧可能更新更快，页面显示结果距今时间。

默认最多10分钟或2000个处理帧，也可以调整，例如：

```bash
bash setup/run_cup_live.sh --duration-seconds 1200 --max-frames 4000
```

数据默认保存到Ubuntu新目录：

```text
/data/ZJC/foundationPos/foundationpose_data/live_sessions/cup_<日期时间>_<唯一后缀>/
  session.json                      SDK、相机参数/内参、单位、版本、模型哈希、结束结果
  K.txt                             当次真实相机内参（现场模式）
  frames/000000/rgb.png              本次推理所用原始RGB
  frames/000000/depth.png            uint16毫米深度，0为无效；不补洞
  frames/000000/capture.json         SDK时间戳/帧号、主机收到时间、首次框选条件
  frames/000000/mask.png             初始化帧保存Mask
  frames/000000/pose_camera_from_mesh.txt
  frames/000000/pose_camera_from_display_obb.txt
  frames/000000/overlay.png
  frames/000000/result.json
  requests/, processing/, responses/
  frame_events.jsonl, worker_events.jsonl, controls.jsonl
  worker_report.json, worker_stdout.log, worker_code/
```

输入、位姿、叠图及请求SHA记录在结果中；官方源码、权重配置与模型哈希也保存。主进程与GPU worker均通过统一记录器，档案在`foundationpose_data/runs/`，正常/失败/中断保留。主机收到帧到结果的时间与SDK帧时间分开记录，未把两个时钟无标定地相减。空间少于1GiB时停止并保留证据，不覆盖旧会话。

位姿定义：`p_camera_m = R @ p_original_mesh_m + t_m`，是原始候选OBJ→OpenCV相机，平移单位米，相机x右/y下/z前。不是机器人或世界外参，不是GT。

## 当前模型限制

当前使用`cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj`，SHA256 `5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de`，原米制/原坐标不变。杯口/接触侧孔洞与噪声保留，5张独立测试中的第2/3张杯把朝向存疑，见[模型初跑](CUP_NEW72_FOUNDATIONPOSE_PILOT_20261014.md)。实时输出仅作流程试验；不能因能跟踪就当准确6D标签。没有新训练、补造几何或把计划角度当GT。BundleSDF退出139仍未解决，本实时入口使用另一现有推理容器。

## 已完成验证与证据

- 独立Ubuntu `.camera-venv`仅新增`opencv-python-headless==4.11.0.86`；NumPy1.26.4、pyrealsense2 2.55.1.6486、Pillow12.3.0保持。pip check退出0，GPU/模型环境未修改。
- V1离线GPU启动因快照漏`verify_demo.py`失败，0推理帧；失败目录保留。V2补齐传递依赖，1次register+4次track、5帧全部通过且退出0。
- GPU/HTTP集成验证包括拒绝无Mask初始化、冻结/ROI+GrabCut、register/track、暂停后不被旧响应重启、重新初始化、推理中停止；共5帧、2次register/3次track，最后一帧停止后仍写入帧索引，与GPU数目一致，端口退出后关闭。使用重复独立照片000004，非连续真实视频评测。
- 实际HTTP返回的JavaScript经Windows Node语法检查退出0；REST流程已测，未宣称实相机浏览器点击/显示性能已验收。
- 两次成功回放共10帧已下载E盘，原RGB/depth/Mask、请求、响应、位姿及叠图逐项SHA复验通过。

Ubuntu证据：`foundationpose_data/live_sessions/cup_live_replay_v1_20261014_2103`（失败）、`cup_live_replay_v2_20261014_2107`（通过）、`cup_live_http_gpu_smoke_v1_20261014_2113`（通过）。Windows对应副本在`E:\foundationPos_data\reviews\`。

报告：`reports/CUP_LIVE_GPU_HTTP_SMOKE_20261014.json`、`reports/CUP_LIVE_VERIFICATION_20261014.json`；控制验证服务器run `20261014_211031_727102_cup_live_gpu_http_control_smoke_d135bb4f`。下一步在接机后做60对取帧检查及短现场跟踪，保存当次真实FPS、SDK条件和杯把叠图，精度仍需独立验证。
