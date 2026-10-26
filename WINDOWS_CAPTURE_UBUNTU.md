# Windows 采集 D435i，Ubuntu 重建与位姿估计

2026-10-14 16:17最新存储：新Windows采集默认在`E:\foundationPos_data\windows_captures`，C盘保存代码/venv及run_id日志。三次刚采OBJ已按用户要求删除原图/录包，元数据/日志保留；重采已在E盘启动。旧项目内打包脚本不会自动包含E盘外部数据，正式上传时须明确纳入E盘源与C盘档案并验证SHA256。详情见 [E盘迁移记录](reports/WINDOWS_E_DRIVE_CAPTURE_20261014.md)。

> 2026-10-14：Ubuntu SSH已可用，继续采用Windows先采集、批次上传；早期“主动断开”仅说明历史阶段。新增`setup/start_obj_photos.ps1`；High Accuracy、bag回放及独立滤波深度已实测，Ubuntu Open3D/TSDF/OBJ通过合成环境验证。最新命令及范围见 [OBJ环境配置说明](reports/OBJ_ENVIRONMENT_SETUP_20261014.md)。

可以将采集与后续处理分开：D435i 接 Windows，采集对齐 RGB-D；数据传到 Ubuntu 的 `/data/ZJC/foundationPos`，再做分割、无 CAD 重建和位姿估计/跟踪。

**当前执行方式（用户于 2026-10-13 确认）：先在 Windows 完成全部采集并保存执行证据，再统一打包发送 Ubuntu。Ubuntu 当前由用户主动断开，不影响 Windows 取帧。采集期间不需要 SSH；下文上传步骤等采集完成且 Ubuntu 恢复连接后再执行。最终包需包含各采集目录的 RGB/深度、内参、单位、时间戳、报告、SHA256清单，以及本机执行档案与操作/问题说明；`.windows-camera-venv` 不作为 Ubuntu 运行环境打包。当前尚未开始正式多视角序列，因此没有生成最终数据包。**

## 已准备好的环境

- Windows 项目：`C:\Users\YOUR_USER\Desktop\foundationPos`。
- 独立采集环境：`.windows-camera-venv`，Python 3.11.8、pyrealsense2 2.55.1.6486、NumPy 1.26.4、Pillow 12.3.0。
- SDK 导入、依赖检查、采集入口参数和已有 RGB-D 样本在 Windows 上的格式读取均通过。
- Windows 已于 2026-10-13 实际识别并取帧 D435i（序列号 238222071455、USB3.2）；杯子首次检查及改善光照后复拍均保存到 `foundationpose_data/windows_captures/`。最新光线与局部深度检查见 [CUP_LIGHT_RECHECK_20261013.md](CUP_LIGHT_RECHECK_20261013.md)。

Windows 采集保存 RGB PNG、对齐的 uint16 毫米深度 PNG、彩色相机内参、时间戳和 SDK 原生深度比例。Ubuntu 使用同一份数据格式。[官方 Python SDK](https://github.com/realsenseai/librealsense/blob/v2.55.1/wrappers/python/readme.md)、[BundleSDF 数据格式](https://github.com/NVlabs/BundleSDF#run-on-your-custom-data)

## 1. 先连接 Windows 并试拍

把 D435i 从 Ubuntu 拔下，使用 USB 3.x 数据线连接当前 Windows 电脑。相机使用 Windows 上的采集程序；Windows 电脑可继续通过 SSH 控制 Ubuntu。

打开 Windows PowerShell，执行：

```powershell
cd C:\Users\YOUR_USER\Desktop\foundationPos
$env:FP_RUN_NOTE = 'Windows试拍；物体名称/尺寸/材质/距离/光照请填写实际情况'
$previewDir = Join-Path $PWD.Path ('foundationpose_data\windows_captures\preview_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_d435i_check.ps1 --output $previewDir --frames 60 --warmup 30
```

检查终端的 `passed`、帧数和报告；在 Windows 文件管理器中打开 `$previewDir` 对应的目录，查看 `rgb.png` 和 `depth_preview_color.png`。重点检查目标物体是否完整、清楚，以及目标区域是否有大块深度空洞。

需要重新建立本机采集环境时，使用已经缓存并验证 SHA256 的官方安装包：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\prepare_d435i_windows.ps1
```

上述执行策略只对本次 PowerShell 进程生效。三个相机入口自动生成运行记录，不需要在全局 Python 安装采集依赖。

## 2. 在 Windows 录制多视角序列

**用户当前选择固定相机、手动旋转杯子、停稳后保存照片。优先使用 [CUP_MANUAL_PHOTOS.md](CUP_MANUAL_PHOTOS.md) 和 `setup/start_cup_photos.ps1`；下文保留连续采集方式作为备选。两种方式都保存配对RGB/depth PNG。**

当前杯子目标可按 [CUP_TRIAL_STEPS.md](CUP_TRIAL_STEPS.md) 做首轮30秒多视角试采。新增入口 `setup/start_cup_trial.ps1` 采用预热90对、倒计时10秒、新时间戳目录，并在成功采集后自动检查格式；执行时由用户准备并移动相机。

目标深度合格后，保持物体不动，准备缓慢移动相机。在同一个 PowerShell 窗口执行：

```powershell
$env:FP_RUN_NOTE = 'Windows多视角采集；物体固定；相机缓慢绕拍；补充物体与光照条件'
$captureDir = Join-Path $PWD.Path ('foundationpose_data\windows_captures\my_object_' + (Get-Date -Format 'yyyyMMdd_HHmmss'))

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_d435i_capture.ps1 --output $captureDir --seconds 30 --save-fps 10 --countdown 5

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_d435i_format_check.ps1 $captureDir
```

出现 `Capturing` 后再开始绕拍正面、侧面、背面及另一侧，保持充分重叠，始终让整个目标在画面中。预计约 300 对图片，以实际报告为准。摆放与移动细节见 [D435i_capture_steps.md](D435i_capture_steps.md)。

## 3. 传到 Ubuntu

Ubuntu 接收目录已准备为 `/data/ZJC/foundationPos/foundationpose_data/windows_captures/`。在保留 `$captureDir` 变量的 Windows PowerShell 中执行：

```powershell
# 为这次序列生成 SHA256 清单，随后上传整段数据。
.\.windows-camera-venv\Scripts\python.exe -u .\setup\run_logged.py --root . --label windows_capture_manifest --note '生成本次采集数据的SHA256清单' -- .\.windows-camera-venv\Scripts\python.exe .\setup\finalize_transfer.py --root $captureDir --write-manifest

# 只接受脚本生成的安全目录名，并确认服务器上没有同名序列。
$sceneName = Split-Path -Leaf $captureDir
if ($sceneName -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') { throw '请使用字母、数字、下划线组成的采集目录名' }
$destinationCheck = 'test ! -e /data/ZJC/foundationPos/foundationpose_data/windows_captures/' + $sceneName
.\.windows-camera-venv\Scripts\python.exe -u .\setup\run_logged.py --root . --label windows_destination_check -- C:\Windows\System32\OpenSSH\ssh.exe -o BatchMode=yes -o UpdateHostKeys=no USER@UBUNTU_HOST $destinationCheck
if ($LASTEXITCODE -ne 0) { throw '服务器目录已存在或连接失败，请保留日志并排查，不要继续覆盖上传' }

.\.windows-camera-venv\Scripts\python.exe -u .\setup\run_logged.py --root . --label windows_capture_upload --note '将Windows采集序列传到Ubuntu' -- C:\Windows\System32\OpenSSH\scp.exe -o BatchMode=yes -o UpdateHostKeys=no -r $captureDir USER@UBUNTU_HOST:/data/ZJC/foundationPos/foundationpose_data/windows_captures/

# 保存已完成的Windows执行档案到同一项目；总日志导入时保留已有Ubuntu记录。
.\.windows-camera-venv\Scripts\python.exe -u .\setup\run_logged.py --root . --label windows_logs_upload --note '同步Windows执行档案' -- C:\Windows\System32\OpenSSH\scp.exe -o BatchMode=yes -o UpdateHostKeys=no -r .\foundationpose_data\runs USER@UBUNTU_HOST:/data/ZJC/foundationPos/foundationpose_data/
```

每次采集使用新的时间戳目录；正式数据上传前确认 Ubuntu 没有同名序列，避免对已有数据合并覆盖。也可以完成采集后告诉我具体目录，由我完成传输、校验和留档。

SSH 使用此前已经可用的密钥认证。如果在你自行打开的终端中密钥不可用，保留报错并让我排查；不要将密码写入命令或日志。

## 4. Ubuntu 校验与处理

登录 Ubuntu，将下列示例目录替换为本次实际上传的序列名称：

```bash
ssh USER@UBUNTU_HOST
scene_dir=/data/ZJC/foundationPos/foundationpose_data/windows_captures/my_object_YYYYMMDD_HHMMSS

bash /data/ZJC/foundationPos/setup/run_d435i_format_check.sh "$scene_dir"
bash /data/ZJC/foundationPos/setup/run_logged.sh --label windows_capture_sha256_check -- \
  python3 /data/ZJC/foundationPos/setup/finalize_transfer.py --root "$scene_dir"

python3 /data/ZJC/foundationPos/setup/import_windows_run_records.py
```

数据格式和 SHA256 校验通过后，继续生成目标 Mask、进行几何重建、确认模型尺度，再接入 FoundationPose 位姿估计与跟踪。这些步骤仍需使用实际目标数据完成；仅上传 RGB-D 序列不代表重建或推理已经完成。

本机采集元数据中的 `C:\...` 路径保留原始采集来源；Ubuntu 处理脚本应使用实际上传目录，读取相对文件名及 `cam_K.txt`。不要删除或改写原始内参、深度比例和时间戳。

## 5. 后续“检测”有两种方式

| 目标 | 相机连接与数据流 |
| --- | --- |
| 离线处理 Windows 采集的数据 | 相机接 Windows；采集完传文件，Ubuntu 读取序列进行位姿估计与跟踪 |
| Ubuntu 实时位姿跟踪 | 在完成目标重建后，将相机接回 Ubuntu，使用已配置的 Ubuntu SDK；实时推理程序仍需接入目标模型与 Mask |

如果相机一直留在 Windows，又要求 Ubuntu 实时处理画面，需要额外实现 RGB-D 网络传输和接收程序；当前没有部署这条实时网络链路。

无 CAD 时，重建参考序列与后续测试/跟踪序列分别保存，清楚标记用途。[FoundationPose 官方说明](https://github.com/NVlabs/FoundationPose/blob/a1b694b83e633c2cb6115b9063d940a687759392/readme.md)

## 6. 留档规则

本机档案保存在 `foundationpose_data\runs\`，操作与问题持续追加到本机 `EXPERIMENT_LOG.md` 和 `ISSUES.md`。传到 Ubuntu 后，由导入脚本按唯一运行编号追加记录，保留原有服务器日志；未完成的运行暂不导入，待结束后再次同步。

每次仍需补充物体、距离、光照和相机移动方式。失败、中断与重试均保留。Windows 的实际取帧验证将在相机移到本机后记录，不能用 Ubuntu 的取帧报告代替。

## 7. 2026-10-13当前离线数据批次

Windows取帧已经真实验证，侧面/斜俯视共72张参考的Mask与试运行派生深度已准备。现阶段仍按用户决定不尝试SSH；最新状态和独立测试补拍命令见 [CUP_NEXT_STEPS_20261013.md](CUP_NEXT_STEPS_20261013.md)。

本地快照脚本 `setup/package_cup_offline.py` 生成新的 `foundationpose_data/exports/cup_reference_batch_20261013/`，内含ZIP、逐文件manifest、整包SHA256和打包报告。脚本会复读源文件并重新读取ZIP所有条目校验SHA，不把“压缩结束”当作校验通过。成功/失败/中断旧运行与旧分割也包含；当前尚未结束的打包run在ZIP中排除，它结束后的run和外层报告另存，后续一并传输。

服务器恢复后先上传到一个新的暂存目录，核验整包及manifest后再导入。包内 `windows_notes/` 是根MD的Windows快照，不覆盖Ubuntu总日志。新增run按唯一run_id追加；本次人工总结用 `append_manual_records.py` 追加，event-id为 `CUP-REFERENCE-MASK-DEPTH-20261013`，summary文件在 `reports/CUP_REFERENCE_SESSION_EXPERIMENT_20261013.md` 和对应 `...ISSUES...md`。独立测试补拍完成后重新生成新目录批次，保留当前快照。
