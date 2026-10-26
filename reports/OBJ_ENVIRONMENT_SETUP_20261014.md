# Windows采集、Ubuntu OBJ重建环境（2026-10-14）

**2026-10-14 16:02更新**：下述早期入口默认High Accuracy已取消。当前杯子实测该预设深度约27–30%；High Density+深度自动曝光约92%。`start_obj_photos.ps1`现默认保留设置，正式命令使用`-DepthPreset high-density -DepthAutoExposure`。显式变更会备份及验证恢复完整参数；早期“原预设0成功恢复”仅证明Custom标签读回，不能当高级参数恢复验收。新真实取帧/录包/恢复复验通过，证据见 [深度设置诊断](OBJ_DEPTH_DENSITY_DIAGNOSIS_20261014.md)。

Viewer后续已于2026-10-14完成本机便携应用配置及桌面/开始菜单快捷方式，程序路径为`tools/realsense-viewer/2.55.1/realsense-viewer.exe`；已启动窗口，GUI内检查被Computer Use自动审批限制，详见 [Viewer安装记录](WINDOWS_VIEWER_INSTALL_EXPERIMENT_20261014.md)。下方“未打开GUI”属于此前环境配置时的状态。

按 `D435i_to_OBJ_FoundationPose_Reconstruction_Guide_Optimized.md` 准备：**D435i接当前Windows；采集完成后批次上传USER@UBUNTU_HOST，在Ubuntu重建**。Windows项目为 `C:\Users\YOUR_USER\Desktop\foundationPos`；Ubuntu项目为 `/data/ZJC/foundationPos`。采集时无需保持SSH连接。

## 环境与本次实测

| 位置 | 配置 | 验证 |
| --- | --- | --- |
| Windows | `.windows-camera-venv`；Python 3.11.8；pyrealsense2 2.55.1.6486；NumPy 1.26.4；Pillow 12.3.0；OpenCV 4.11.0.86 | D435i 238222071455、USB3.2；60对640×480@30对齐RGB-D取帧通过；pip check通过 |
| Windows采集选项 | High Accuracy、原生bag、Spatial/Temporal/Hole Filling派生深度 | 一张自动检查照片保存成功；原始/滤波uint16深度可读；bag可回放RGB和depth；采集结束原预设0成功恢复 |
| Windows Viewer | `.assets_download/Intel.RealSense.Viewer.2.55.1.exe` | 官方便携版已下载，Authenticode签名Valid；本次未打开GUI |
| Ubuntu | `/home/ni/anaconda3/envs/foundationpose`；Python 3.11.14；Open3D 0.19.0；NumPy 2.1.3；OpenCV 4.11.0.86；trimesh 5.1.1 | SSH、pip check、ICP、位姿图、TSDF、PLY/OBJ导出和OBJ再读取通过 |
| Ubuntu GPU/模型 | RTX3090 24GB；驱动535.230.02；PyTorch2.4.1+cu121 | 实际CUDA运算通过；官方scorer/refiner权重存在，沿用此前验收的FoundationPose环境 |

本次Windows只补装OpenCV；安装包已缓存并校验SHA256，`prepare_d435i_windows.ps1`已加入该固定版本和哈希。Ubuntu重建依赖沿用现有安装，没有重装或修改版本。Windows venv不传入Ubuntu运行。

Viewer来源：[官方SDK2.55.1发布](https://github.com/realsenseai/librealsense/releases/tag/v2.55.1)。SHA256为 `ced0bd623f2df2e86f074ff8ee0fd89637c92f25f44fbf2d24262a325a8990c0`。

## 下一次正式采集

先把不透明刚性目标完整放入画面，距离约40–60cm，记录实际物体尺寸、材质、摆放、光照和旋转方式。本次检查画面是墙面，不作为杯子参考/测试，也不验收物理标定误差或实物几何。

Windows PowerShell执行：

```powershell
cd C:\Users\YOUR_USER\Desktop\foundationPos
$env:FP_RUN_NOTE = '填写物体/实测尺寸/材质/距离/光照；相机固定，手转物体，停稳且手退出后保存'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5 -DepthPreset high-density -DepthAutoExposure -RecordBag -FilteredDepth
```

预热90对后，每次小幅旋转、停稳且手退出，按回车保存；程序再等待约1秒并读取新帧，等`Saved`后再转动。5°是计划备注，不是实测转角、配准外参或GT。旧`start_cup_photos.ps1`仍可用，旧默认设置保留。

侧面一圈后调整观察高度，分别用`-Ring top`和`-Ring low`建立俯视/低角度序列；独立测试用`-Ring test`。少量补拍可改`-Views`。各圈及物体翻转后的序列分别保存，跨圈需实际估计并检查配准；桌面遮住的底面仍需补采。

每次创建 `foundationpose_data/windows_captures/obj_<ring>_<时间戳>/`，不覆盖旧采集：

- `rgb/`与`depth/`：停稳选出的同名PNG；原始未滤波的对齐深度为uint16毫米值，0缺失，乘0.001得到米。
- `depth_filtered/`：仅在`-FilteredDepth`时保存的派生空间/时间/补洞深度，不替换`depth/`。补洞并非新的真实测量，几何QA保留原始数据。
- `raw_streams.bag`：仅在`-RecordBag`时录制原生未对齐流，包含预热、等待与手转过程；回放后仍需对齐和筛选静止帧。
- 内参、深度比例、metadata/report、timestamps：包含SDK depth-to-color外参、每对帧号/时间戳、计划角度、预设应用和恢复结果。

bag在等待期间也持续录制，空间占用大于选出的PNG，本次短时检查约139MB。不需要原生录包时省略`-RecordBag`，RGB-D PNG/内参/时间戳仍保存。Viewer与采集脚本应分开使用，拍照前退出Viewer，避免占用相机。

需要重建Windows环境时，执行自动留档且校验缓存安装包哈希的 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\prepare_d435i_windows.ps1`。

## 配准与传输条件

固定相机、旋转物体时，应逐张生成只含目标的Mask，排除手、桌面和背景，再估计物体相对刚体变换。静止背景可能让整场景配准收敛到恒等变换；**相机固定不表示物体位姿固定，不能直接拼深度，也不能用计划转角代替配准**。

Open3D的`depth_scale`表示每米对应多少保存值，毫米PNG传`1000`，不是文本中的0.001m/值。TSDF接收模型/世界到当前相机的变换；若保存相机到模型的矩阵，应取逆后融合。[官方RGB-D融合示例](https://www.open3d.org/docs/release/tutorial/pipelines/rgbd_integration.html)

ICP需要足够重叠与合理初值；杯子等近对称/弱纹理目标仍可能错误收敛。逐对配准、闭环和跨圈一致性需检查，不能仅凭退出0验收网格。[官方多视角配准](https://www.open3d.org/docs/release/tutorial/pipelines/multiway_registration.html)

采好后统一打包原图/录包、内参、时间戳、SHA256与成功/失败/中断档案；上传新暂存目录后核验整包及逐文件SHA256，按唯一run_id追加Ubuntu索引。Windows总日志不能覆盖Ubuntu记录，venv不复制过去。参见 [Windows传输说明](../WINDOWS_CAPTURE_UBUNTU.md) 与 [复现指南](../REPRODUCTION_GUIDE.md)。

本次只完成环境和采集选项验证。正式物体Mask、可靠配准、完整实物OBJ及尺寸/法向/完整性QA仍需在正式数据上执行。现有BundleSDF容器和旧结果保留，杯子几何变形与退出139仍未解决；没有新的位姿训练或GT评测。

## 重复验证Ubuntu环境及证据

```bash
ssh USER@UBUNTU_HOST
cd /data/ZJC/foundationPos
bash setup/run_obj_environment_check.sh --output /data/ZJC/foundationPos/foundationpose_data/obj_environment_checks/open3d_新的时间戳
```

输出目录必须是新的。该入口使用合成点云和盒子，不下载数据、不打开GUI。输出包括依赖锁定、ICP/位姿图、合成毫米深度、米制PLY/OBJ及报告；`synthetic_box.obj`不是用户杯子的模型。

本次通过测试：12视角、3mm体素、7808顶点和15580三角面，表面距离95分位约2.69mm。盒子设定0.10×0.12×0.08m，提取包围框约0.11717×0.12662×0.09443m；TSDF边缘伪影如实保留。验收采用两体素表面距离和截断带内量纲检查，不能当毫米级实物精度验收。OBJ再读与导出网格尺寸差小于1e-6m。

- Windows60对：`foundationpose_data/windows_captures/obj_env_check_20261014_132150_762/report.json`。
- 最终录包/预设/滤波：`foundationpose_data/windows_captures/obj_options_final_20261014_133130_611/report.json`。
- Ubuntu：`foundationpose_data/obj_environment_checks/open3d_20261014_1333_surface/report.json`；Windows副本：report.json（原始附件未随公开快照提供）。
- Ubuntu通过run：`20261014_133110_132279_obj_open3d_environment_check_54ba3cfc`；失败和诊断目录保留。
- 本次问题事实与复验：[问题留档](OBJ_SETUP_SESSION_ISSUES_20261014.md)；两端持续追加`EXPERIMENT_LOG.md`和`ISSUES.md`。
