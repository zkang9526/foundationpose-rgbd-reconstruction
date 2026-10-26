# 杯子位姿复现：固定桌面 ArUco、移动相机的误差实验

本期实现入口 `setup/run_cup_live_fast.sh`，Ubuntu 根目录 `/data/ZJC/foundationPos`。沿用官方预训练权重、同一米制候选杯子网格，初始化5次、跟踪2次细化；不训练新网络。原实时入口保留。当前网格仍有杯口/接触侧孔洞，几何精确QA未通过。

## 能测到的精度范围

杯子和码必须同时固定，只有相机移动。ArUco不参与FoundationPose的位姿优化；从推理所用的同一份原始RGB和实际RGB内参独立求解，时间戳与保存输入可追溯。

- `anchored_object_translation_mm / rotation_deg`：首个有效配对帧对齐后的杯子模型原点漂移，适合观察移动相机时跟踪是否保持一致。初始杯子位姿的固定偏差会被消除；不能据此声称绝对定位精度。
- `relative_translation_mm / rotation_deg`：两套估计得到的相机相对首帧的运动变换差异。其平移是在首帧相机原点处比较，和杯子原点漂移不是同一个数值。
- `absolute_translation_mm / rotation_deg`：只有提供独立标定的 `T_marker_from_original_mesh` 时才计算。不能用本次FoundationPose输出或整段测试拟合该变换后称为真值。
- 无码、重复ID、码过小、平面解歧义、重投影误差过大或跟踪深度不一致：误差留空，仍保存该帧及失败原因。首帧相对误差按定义为零，统计排除这一帧；重新初始化也不重置首帧参考。

矩阵采用列向量，`p_camera = T_camera_from_mesh @ p_mesh`，平移单位米。记杯子估计为 `E_t`、码估计为 `M_t`：相机运动比较 `E_t @ inv(E_0)` 和 `M_t @ inv(M_0)`；首帧对齐的杯子参考为 `M_t @ inv(M_0) @ E_0`。绝对参考为 `M_t @ T_marker_from_original_mesh`。旋转误差用SO(3)测地角，平移用欧氏距离。

## 贴码和实验条件

初跑使用 `DICT_4X4_50`、ID 0。Windows可打印模板在：

`E:\foundationPos_data\calibration\aruco_reference_v4_20261014_2320\aruco_DICT_4X4_50_id0_black60mm.svg`

模板总宽80mm，黑色正方形名义边长60mm，外围白边10mm。打印选择100%/实际大小，不缩放到纸张；用尺或卡尺测量黑色外边长，命令中填写实测米值（不是包含白边的80mm）。打印尺寸误差会直接影响PnP的米制尺度。PNG只供预览，优先打印SVG。码平整、哑光、固定牢固，四角完整可见，不贴弯曲表面，不被杯子遮挡。不要给不同位置贴相同ID。

单个平面码的PnP参考仍有尺寸、内参、角点和视角误差。当前门限（边长至少25像素、重投影RMS至多1.5像素、IPPE歧义检查）只用于剔除明显不可靠帧，不等价于毫米精度保证。建议实际画面里码明显大于最低门限。若目标为几毫米或论文级绝对精度，下一阶段采用实测多码板/ChArUco和独立参考标定，再验证参考的不确定度；当前入口支持的是单码。

一次实验分为：

1. 相机、杯子、码全部静止约30秒，记录静态抖动；若有系统尺度/方向异常先处理。
2. 只缓慢移动相机约30秒，杯子、杯把和码保持完整可见，观察投影与误差。
3. 中等/较快移动相机约30秒，记录误差、帧率、延迟、参考可见率和深度一致性拒绝率；不要只挑成功帧报告精度。
4. 相机回到初始位置并停稳约10秒，观察残余漂移。把各段实际开始/结束时间和运动条件写入运行备注或另存实验笔记。

冻结、框选Mask、初始化期间相机和杯子都保持停稳，等状态进入跟踪再移动。快速运动还可能造成RGB运动模糊、参考码丢失与跟踪失败，提速不会消除这些限制。深度门限仅判断粗一致性，不能发现所有错误杯把朝向或背景假匹配。

## Ubuntu命令

以下 `.060` 仅代表“实测黑色外边长确为60.0mm”的例子；请替换成自己的实测值。

```bash
cd /data/ZJC/foundationPos
FP_RUN_NOTE='固定杯子和桌面码，只移动相机；DICT_4X4_50 ID0；黑色外边长实测60.0mm；补充光照和实际运动条件' \
bash setup/run_cup_live_fast.sh \
  --aruco-marker-length-m 0.060 --aruco-id 0 --aruco-fixed-scene \
  --duration-seconds 600 --max-frames 2000
```

在Ubuntu浏览器打开 `http://127.0.0.1:8765`，冻结→框完整杯身/杯把→生成并检查Mask→初始化。画面显示首帧对齐后的杯子漂移；码未通过参考检查时不显示虚构的零误差。深度不一致或初始化后画面明显变化时停止跟踪并提示重新框选。初始化期间若两个有效ArUco参考显示相机移动超过5mm或2度，也暂停。这些是运行保护门限，不是测量精度验收线；没有自动全局重新检测。

终端会打印实际 `foundationpose_data/live_sessions/cup_fast_...` 路径。按“停止并保存记录”正常结束；超过时长/帧数会自动结束。2000帧损失无压缩的RGB+深度约3.1GB，加上显示、日志和矩阵，需要预留数GB磁盘空间。

每帧保存 `rgb.npy`（RGB uint8）、`depth.npy`（uint16毫米）、`capture.json`（SDK时间戳/帧号/收到时间）、`aruco.json`（角点、解与参考质量）、原始网格→相机矩阵、显示OBB矩阵、`result.json`（GPU候选）、`host_result.json`（运行保护及参考评估）、`reference_evaluation.json`、显示JPEG。JPEG不用于推理/测量。请求记录包含输入SHA256。所有已处理帧保留；30Hz采集时跳过的帧未保存，不把处理帧数当采集帧数。

会话根目录有 `aruco_errors.csv`、`frame_events.jsonl`、配置/源码快照、GPU权重/官方commit信息、运行记录。正常停止后自动生成 `evaluation_summary/report.json`，包括误差均值/RMSE/P95/最大值、参考配对覆盖率、失跟/失败数量、FPS和延迟；`summary_status.json`记录汇总执行结果。参考原始变化只有在相机静止的片段才可解释成参考抖动。

需要导出误差图时，使用已存在的原生环境（不安装依赖），把SESSION替换为终端打印的实际路径，选择新的输出目录：

```bash
bash setup/run_logged.sh --label aruco_error_plot -- \
  /home/ni/anaconda3/envs/foundationpose/bin/python -B \
  setup/summarize_cup_aruco_session.py \
  --session /data/ZJC/foundationPos/foundationpose_data/live_sessions/cup_fast_实际会话 \
  --output /data/ZJC/foundationPos/foundationpose_data/derived/aruco_eval_新的名称 --plot
```

若以后完成独立标定，可额外传 `--marker-from-mesh /绝对路径/independent_T_marker_from_mesh.txt`（4×4刚体矩阵、米、原始OBJ坐标系）。重建用的计划旋转角与估计/插值矩阵均不是真值。

## 方法依据和现阶段证据

[OpenCV ArUco官方说明](https://docs.opencv.org/4.x/d5/dae/tutorial_aruco_detection.html)给出字典、角点顺序和按markerLength确定平移尺度的方法；[OpenCV PnP说明](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)给出IPPE_SQUARE的规定点序。单码四角几何解不构成无误差真值。[BOP评测定义](https://bop.felk.cvut.cz/tasks/)的绝对6D评测需要模型、相机内参和独立参考姿态等条件；本实验首先评估固定场景下的相对跟踪一致性，不能直接宣称复现BOP精度。

本期合成图/已知变换验证了坐标约定、未知固定码→杯子变换的消去、注入10mm误差、缺码/失败不造误差。约90像素的合成码仍存在数毫米栅格化偏差，测试通过不等于实物毫米精度。真实桌面码还未采集；本报告没有实物准确度结论。
