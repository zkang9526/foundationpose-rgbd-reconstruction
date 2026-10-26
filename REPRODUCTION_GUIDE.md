# FoundationPose 自有物体复现操作与留档指南

> 文档定位（2026-10-26）：以下是按阶段追加的历史操作与留档记录，早期“未完成/未替换”结论仅对应当时状态。当前启动入口、公开仓库资产范围及最新结果请先看 [README](README.md) 和 [快速指南](docs/QUICKSTART.md)；最新现场成功找回见 [2026-10-18 报告](reports/CUP_RECOVERED_ACCURACY_20261018_172656.md)。历史原文保留。

<!-- RED-CUP-REVIEWED72-MESH-20261017 -->
2026-10-17用户完成涂红杯子修正版72张Mask人工检查。72/72确认、源/版本SHA及操作回放通过，已冻结快照、按实测深度分布派生350–520mm输入，并上传Ubuntu校验7437文件、追加44份Windows档案。官方BundleSDF完整72帧输出后退出139，只有1关键帧且最大相对旋转3.33°，网格不验收；独立杯底平面/杯把方向+ICP/TSDF已生成并回传初步OBJ，49方向观测/23插值，未标记精确几何或6D验收通过。Windows路径兼容性校验问题已修复并复验进入完整重建。实际路径、命令及问题见[本轮Mesh结果](reports/RED_CUP_REVIEWED72_MESH_RESULT_20261017.md)。原始照片/Mask/所有失败记录保留，未替换实时位姿入口的现用模型。

<!-- CHECKERBOARD-PAPER-BATCH-20261017 -->
2026-10-17本期off棋盘会话已结束，38次试拍/26组接收，投射器恢复为1且相机释放。用户确认尚未固定硬板；横向中心跨度125.3px未达到本工具160px诊断采样条件，未拟合新内外参。后半段双轴倾角已改善，不能将整批都说成仅桌面内旋转。原始数据和565份文件SHA档案保留；下一轮需纸面固定平整硬板后独立重采。见[最终复核](camera_calibration/REVIEW_PAPER_BATCH_20261017.md)。

<!-- CHECKERBOARD-SCATTER-FIX-20261017 -->
2026-10-17棋盘实拍发现IR投射散斑使当前SB角点检测失败，原会话13组全部保留拒绝。新独立对照关闭投射器后三路66角点均检出，临时开关1→0→1恢复实测通过；当前使用`camera_calibration/run_windows.ps1 -EmitterMode off`采25–35组有效多姿态，生产投射器开启时的深度/边界另验。页面仍8766，新会话`windows_20261017_154720_168`；横竖5格实测100mm用户已确认。详见[处理与限制](camera_calibration/SCATTER_FIX_20261017.md)。

<!-- CAMERA-REVALIDATION-20261017 -->
2026-10-17用户准备涂红杯口后重新采集及重建，先在Windows重新验证相机。已确认棋盘为7×12方格、6×11内角点、20mm格距。使用独立`camera_calibration/`工具，页面`http://127.0.0.1:8766`；新增3秒延时后取新帧及左右红外预览，原静止门限保持不变。出厂参数数值结构/四路取帧/软件对齐通过，物理内外参、实体边缘对齐及涂红后的杯口深度仍需多姿态实测。当前操作说明及证据见 [2026-10-17相机验收阶段记录](camera_calibration/STATUS_20261017.md) 与 [采集说明](camera_calibration/README.md)。旧数据、标定和模型保留。

项目目录：`/data/ZJC/foundationPos`。Ubuntu：`USER@UBUNTU_HOST`。本指南建立于 2026-10-13。

2026-10-14新72张及原E盘72张已按静态RGB-D/参数/掩码/日志方案打包、上传并逐文件SHA256验证，新增51份Windowsrun索引；bag留E盘。官方72帧跟踪未正确估计旋转且退出139，独立几何初始化+ICP/TSDF已导出候选OBJ并回传E盘，孔洞/噪声仍使精确几何QA未通过。模型、复现命令/路径和实跑问题见 [新72张重建结果](reports/CUP_NEW72_UBUNTU_RESULT_20261014.md)。

2026-10-14 E盘新72张侧面参考`obj_side_20261014_161656_953`已完整采集、格式/时序通过，并逐张查看RGB及原始深度；可以保留作侧面分割/重建参考。杯身/黑色下沿样区平均99.88%/99.55%，可见杯底中心仍有空洞需新斜俯视补拍，完整网格QA仍待执行。检查结果保存在E盘reviews，项目留档见 [72张复核](reports/CUP_SIDE72_REVIEW_SESSION_20261014_161656.md)。

2026-10-14 16:17：Windows手动采集默认改到`E:\foundationPos_data\windows_captures`（`setup/windows_capture_storage.json`），代码/venv/小日志仍在C盘项目。用户要求删除的三次近期OBJ原始数据已清理，释放18.17 GiB，元数据及原运行档案保留。E盘写入/回放验证通过，新的72位置采集已启动等待回车；历史原图保留状态和后续外部目录打包要求以 [E盘迁移记录](reports/WINDOWS_E_DRIVE_CAPTURE_20261014.md) 为准。

2026-10-14 16:02：当前杯子30%深度的设置因素已定位，High Density+深度AE的原始整图对比达到92.18%、正式采集脚本复验91.3%。OBJ入口默认改为保留参数，正式新批次明确使用`setup/start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5 -DepthPreset high-density -DepthAutoExposure -RecordBag -FilteredDepth`；完整参数备份/恢复、bag回放和格式检查通过。9张稀疏数据保留作诊断，几何精度/整圈仍待验收。见 [深度下降诊断](reports/OBJ_DEPTH_DENSITY_DIAGNOSIS_20261014.md)。

2026-10-14 15:38侧面8张试采复核：目标完整、时序/格式与杯身局部深度通过，实际视角变化大于5°计划标签，杯底原始深度随视角明显缺失。下一步保持当前条件，新目录72个小步位置采侧面圈，再独立俯视补拍；详情与命令见 [试采复核](reports/CUP_SIDE8_REVIEW_20261014_153854.md)。计划标签不当测量或GT，真实配准/网格QA仍待执行。

2026-10-14 15:33当前倒扣杯子取帧复验通过，可以从侧面8张小步停稳试采开始；杯底中心与杯把接头的缺失需后续补拍和原始深度复验。入口与实测范围见 [当前采集条件](reports/CUP_CAPTURE_READINESS_20261014_153348.md)。单张/局部样区通过不替代整圈配准和实物OBJ QA。

RGB-depth实际边缘检查新增自动留档的Windows离线入口`setup/run_rgbd_alignment_check.ps1`，读取原始对齐深度、不改数据；新拍静态目标及叠图判读见 [对齐检查说明](reports/RGBD_ALIGNMENT_CHECK_GUIDE_20261014.md)。软件执行align、文件格式通过与物理边缘精度需分别判断。

2026-10-14 按优化版OBJ指南完成Windows取帧/录包/High Accuracy/独立滤波深度复验，以及Ubuntu Open3D ICP、位姿图、TSDF、OBJ往返和CUDA环境测试。新手动照片入口为`setup/start_obj_photos.ps1`；命令和物体Mask配准条件见 [OBJ环境配置说明](reports/OBJ_ENVIRONMENT_SETUP_20261014.md)。本次墙面检查图与合成盒子不是实物参考/OBJ；旧杯子几何QA与退出139仍待处理。旧命令保持可用。

现已支持 Windows 采集、Ubuntu 后处理。Windows D435i 已完成真实取帧、连续试采和手动照片验收；用户当前采用固定相机、手动旋转杯子、停稳后按回车。具体步骤见 [CUP_MANUAL_PHOTOS.md](CUP_MANUAL_PHOTOS.md)，已完成36位置的侧面参考检查见 [CUP_PHOTOS_REVIEW_20261013.md](CUP_PHOTOS_REVIEW_20261013.md)。采集期间只在Windows留档，全部数据采好后统一打包，恢复Ubuntu连接后再上传；传输说明见 [WINDOWS_CAPTURE_UBUNTU.md](WINDOWS_CAPTURE_UBUNTU.md)。

后续环境变更、相机检查、数据采集、分割、重建、位姿估计和问题排查都需要留档。成功与失败均保留；每次重试使用新的运行记录和新的数据目录。

## 1. 当前进度与今天要做的事

用户已选定先用官方预训练权重跑通杯子位姿估计；无CAD先重建网格，参考姿态后续由算法估计并留档，本阶段不重新训练位姿网络。位姿/训练与真值要求见 [POSE_AND_TRAINING_GUIDE.md](POSE_AND_TRAINING_GUIDE.md)。2026-10-13继续核查确认：16:58侧面36对与18:53真正斜俯视36对均已采集，可进入第一轮分割和重建尝试。18:36的36对仍属侧视，不误称俯视；数据角色与最新步骤见 [CUP_NEXT_STEPS_20261013.md](CUP_NEXT_STEPS_20261013.md)。

已完成：FoundationPose Docker/Conda环境及官方Demo前3帧；Windows D435i采集、72张参考Mask和5张完整独立测试Mask逐张验收；完整批次上传/校验/追加日志；独立BundleSDF环境实际运行并保存候选网格与估计矩阵；官方预训练FoundationPose对5张独立测试逐张初始化并退出0。原始图、失败与各版本均保留，结果质量另行审核。

尚待完成：可靠的杯子几何、参考配准与预测姿态质量、重建退出清理139根因、连续实物跟踪和有真值的精度评测。已有候选网格及算法矩阵不等于这些工作已完成；当前倒扣采集没有覆盖杯口内壁与支撑接触面。

当前下一步：检查并改善参考配准/几何质量。数据已在Ubuntu；72张侧面/斜俯视参考与5张完整独立测试分开，原始深度保留，参考派生300–800mm输入只是探索性过滤。默认两圈网格明显变形，不能按planned_angle硬拼；官方基线与自定义Mask候选选择均另存。最新进度见 [CUP_UBUNTU_RECONSTRUCTION_20261013.md](CUP_UBUNTU_RECONSTRUCTION_20261013.md)，重跑命令与结果阅读见 [CUP_POSE_PILOT_RESULTS_20261014.md](reports/CUP_POSE_PILOT_RESULTS_20261014.md)。

2026-10-14更新：完整批次及增量脚本/Windows档案已上传并逐文件核验、只追加Ubuntu索引；历史问题单的CRLF变更已恢复并修补索引工具。BundleSDF环境实际GPU运行，保存侧面/俯视候选网格与估计参考矩阵，默认候选网格QA均拒收为可靠重建，退出清理139仍未解决。官方FoundationPose预训练权重已对5张独立图逐张register并退出0，矩阵/图像完整；一个明显杯把朝向错误及其它形状偏差不能当准确结果。掩码一致性候选选择另存诊断，不改官方基线、不当GT评测。当前重点是质量排查，最新步骤与可重跑命令见服务器阶段文档。

## 2. 记录保存在哪里

```text
/data/ZJC/foundationPos/
├── REPRODUCTION_GUIDE.md         # 本操作说明
├── EXPERIMENT_LOG.md             # 实验与操作总记录，按实际执行持续追加
├── ISSUES.md                     # 问题、原因、处理及复验结果
├── AGENTS.md                     # 后续自动化执行的留档规则
├── setup/
│   ├── run_logged.sh             # 通用执行记录器
│   ├── run_d435i_check.sh        # 相机检查，自动留档
│   ├── run_d435i_capture.sh      # 连续采集，自动留档
│   └── run_d435i_format_check.sh # 数据格式检查，自动留档
└── foundationpose_data/
    ├── runs/                    # 每次执行的独立运行档案
    ├── object_preview_时间/     # 试拍图、深度、内参和报告
    └── my_object_时间/          # 正式 RGB-D 序列
```

每次运行的档案包含命令、工作目录、参数、开始/结束时间、退出码、终端输出、环境记录、脚本快照及产物路径。失败还会生成问题记录，并追加到 `ISSUES.md`。终端会显示本次运行档案目录。

相机三个启动脚本已经接入记录器，按下文执行就会自动留档。模型脚本、安装或其他操作需要按第 7 节使用记录器，或补录交互操作。

## 3. 摆放目标物体

1. 选定一个物体，并记录名称、材质、大致尺寸及是否存在透明、反光或变形情况。
2. 首轮建议用不透明、刚性、带纹理或标签的物体，单独放在平整、不反光的桌面。
3. 移开遮挡目标的手、线缆和杂物，保持均匀光照。
4. D435i 初始距目标约 0.4–0.8 米，略微俯拍，确保整个物体清楚地在画面中；最终以目标区域的深度质量为准。

摆好后可以告诉我“物体已摆好，物体是 XXX”，由我远程试拍并检查。人工摆放、相机移动方式和光照条件也要写入运行备注。

## 4. 静止试拍：先验收目标区域

登录 Ubuntu，在宿主机执行：

```bash
ssh USER@UBUNTU_HOST
cd /data/ZJC/foundationPos

# 将备注中的内容替换为实际情况；不填写密码或令牌。
export FP_RUN_NOTE='物体：待填写；尺寸：待填写；距离：待填写；光照：待填写；静止试拍'
preview_dir="/data/ZJC/foundationPos/foundationpose_data/object_preview_$(date +%Y%m%d_%H%M%S)"

bash setup/run_d435i_check.sh \
  --output "$preview_dir" --frames 60 --warmup 30

echo "$preview_dir"
```

检查输出目录中的 `rgb.png`、`depth_preview_color.png` 和 `report.json`：

- 目标完整、清楚，主要表面未被遮挡。
- 目标的深度区域大部分有颜色，没有明显的大块空洞或投影错位。
- 报告中的 `passed` 为 `true`，采集帧数为 60。

`passed=true` 说明取帧程序通过检查；是否适合重建还要检查目标区域。此前桌面场景只有约 40% 的像素有非零深度，不能据此认定目标重建数据合格。

需要在 Windows 看图片时，另开 PowerShell，将下面的 `实际试拍目录` 替换为终端打印的完整目录：

```powershell
scp -r USER@UBUNTU_HOST:实际试拍目录 C:\Users\YOUR_USER\Desktop\foundationPos\reports\
```

记录“目标深度合格”或“哪些区域存在空洞”，不要只写“相机正常”。若调整摆放或参数，每次重新试拍保留新的目录和记录。

## 5. 当前采集入口与历史可选视频流程

当前用户采用Windows固定相机、手转杯子、停稳且手退出后触发RGB-D照片，入口与留档命令见 [CUP_MANUAL_PHOTOS.md](CUP_MANUAL_PHOTOS.md)。本期参考与独立测试已采完，优先处理既有数据；需要新照片时继续用手动入口、新目录，不能默认改回手持相机绕拍。

下面保留的是历史可选的Ubuntu连续视频入口，只有另行选择连续绕拍方式时使用：

```bash
cd /data/ZJC/foundationPos
export FP_RUN_NOTE='物体：待填写；物体固定；相机缓慢绕拍；首轮30秒'
capture_dir="/data/ZJC/foundationPos/foundationpose_data/my_object_$(date +%Y%m%d_%H%M%S)"

bash setup/run_d435i_capture.sh \
  --output "$capture_dir" \
  --seconds 30 --save-fps 10 --countdown 5

echo "$capture_dir"
```

程序会先预热、再倒计时。出现 `Capturing` 后开始缓慢移动相机：

1. 保持物体不动，连续拍摄正面、一侧、背面和另一侧，始终对准目标。
2. 相邻画面保持充分重叠，避免突然移动或丢失目标。
3. 略微俯拍以覆盖顶部；底面被桌面遮住的部分需要后续补采与处理。
4. 等终端输出结束结果后停止。预计约 300 对图片，实际以报告的 `saved_frames` 为准。

相机按 30 FPS 取流，按约 10 FPS 保存。每次正式采集使用新目录，原始数据保留，后续清洗或分割结果另存。

序列目录包含：`rgb/`、毫米单位的 uint16 `depth/`、`cam_K.txt`、`K.txt`、`depth_scale.txt`、`metadata.json`、时间戳及 `report.json`。

## 6. 检查保存格式并登记结果

在保存 `capture_dir` 变量的同一个终端中执行：

```bash
bash /data/ZJC/foundationPos/setup/run_d435i_format_check.sh "$capture_dir"
```

它检查 RGB/Depth 文件配对、帧数、16-bit 深度 PNG、毫米单位和内参，并自动保存执行日志。

随后在该次运行档案的备注中记录：物体名称、拍摄范围、保存帧数、是否有模糊/空洞/遮挡、是否需要重采、准备采用哪一段数据。采集成功与重建成功分开记录。

## 7. 后续其他命令如何留档

使用通用记录器执行任意非交互命令：

```bash
bash /data/ZJC/foundationPos/setup/run_logged.sh \
  --label 步骤名称 --note '本次操作目的与条件' -- 命令 参数
```

例如，在 Docker 中重复已有 3 帧 Demo 验证（这只验证官方数据）：

```bash
bash /data/ZJC/foundationPos/setup/run_logged.sh \
  --label official_demo_3frames --note '官方预训练权重推理复验' -- \
  docker exec -w /workspace/FoundationPose foundationpose \
  /opt/conda/envs/my/bin/python /data/setup/verify_demo.py \
  --repo /workspace/FoundationPose \
  --output /data/demo_recheck_$(date +%Y%m%d_%H%M%S) --frames 3
```

分割、重建及自有物体推理脚本准备好后，也通过记录器执行。它保存实际命令的退出码，不能把“记录器创建成功”当成业务操作成功。

当前三个相机启动脚本已经自动调用记录器，直接运行它们即可；无需再套一层记录器。

需要密码、登录或其他交互输入的安装操作，由执行者另外保存脱敏命令、终端结果、变更文件和验证结果，追加到总日志；密码、令牌及私钥不写入命令、备注或日志。记录器不会记录 stdin。

## 8. 出现问题时怎么记录

命令返回非零时，记录器会保留失败运行档案和问题入口。后续按下面模板补充：

```markdown
### 问题编号 / 简短标题
- 发现时间、步骤、物体/数据集：
- 现象与关键报错原文：
- 失败运行目录、console.log、命令和参数：
- 原因：已确认 / 推测 / 尚未定位（必须区分）：
- 处理方法和改动文件：
- 复验命令、新运行目录和结果：
- 状态：待排查 / 处理中 / 已解决 / 暂缓：
- 剩余影响：
```

只有复验确认后才标记“已解决”。重试记录要关联原问题，失败数据与日志保留；质量不合格但退出码为 0 的情况，也要手动登记到 `ISSUES.md`。

发生断电、进程被强制终止或连接中断时，查看 `run.json` 的状态和结束信息。若只有开始记录，标记为未完成，再排查；不要自动当作通过。

## 9. 采集完成后继续什么

1. 确认正式目标序列的深度、视角覆盖和图像质量。
2. 生成同名逐帧目标 `masks/`。目前公开 BundleSDF 自定义流程逐帧读取掩码，需要完整掩码序列，或另行接入在线分割传播程序。
3. 配置并验证重建依赖，生成几何模型，确认尺寸、单位和坐标系。
4. 使用自有数据进行位姿初始化与跟踪，保存每帧位姿及可视化。
5. 若目标是论文指标复现，再另行明确数据集、真值和评估协议。

阶段2–4已有实际工具和候选结果，但几何与姿态可靠性尚未通过。不能把采集报告、数值合法矩阵或推理退出0当作完整项目复现及准确度验证；继续依据实际QA更新实验总日志和问题记录。

杯子当前几何拒收后的改善顺序见 [配准与重建改善步骤](reports/CUP_REGISTRATION_RECONSTRUCTION_PLAN_20261014.md)：先用现有参考复核深度、对应点/位姿及简单融合，再按证据做单项改动，必要时少量补拍后再扩到整圈。该文是下一轮待执行方案，12/72张采集不能直接送入仍验收36张的旧重建入口。

相机标定与RGB-D对齐区分及补拍前静态验证见 [相机说明](reports/CUP_CAMERA_CALIBRATION_GUIDE_20261014.md)。三批78对内参/对齐元数据及格式已离线复核，但未做硬件物理精度测量；先验证再决定重新标定，保持旧数据及拍摄时K不变。

## 10. 历史记录与维护规则

2026-10-10 至本指南建立前的工作，已按现有 JSON 报告、安装日志、图片及版本文件补写摘要，见 `EXPERIMENT_LOG.md` 和 `ISSUES.md`。早期没有统一记录器，无法追溯的完整命令或输出不会补造。

后续我执行项目操作时，会使用上述留档方式，并在每个阶段后记录执行内容、结果、问题及下一步。你自行执行时也使用这些启动脚本或通用记录器；人工摆放与采集条件通过备注补充。

相关说明：[环境记录](Ubuntu_environment.md)、[相机连接与验收](D435i_connection.md)、[多视角采集说明](D435i_capture_steps.md)。

2026-10-14新72张几何候选已用于官方FoundationPose独立5图初跑，命令、米制位姿定义及E盘叠图见[本轮初跑](reports/CUP_NEW72_FOUNDATIONPOSE_PILOT_20261014.md)。推理退出0，但第2/3图杯把朝向存疑，几何与6D精度未验收；参考插值姿态不作标签。

<!-- CUP-LIVE-SETUP-20261014 -->
Ubuntu直连实时初跑新增 `bash setup/run_cup_live.sh`，自动双层留档；默认10分钟或2000个处理帧。浏览器框选初始化后跟踪，保存每个实际推理帧，丢弃积压相机帧并记录处理节奏。停止/暂停/重初始化回放测试通过，实际相机未连接时不能称现场验证完成。操作见[Ubuntu实时杯子位姿初跑](reports/CUP_LIVE_POSE_20261014.md)。

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

<!-- PROJECT-GIT-TRACEABILITY-20261015 -->

## Git版本与回溯（2026-10-15）

项目根目录已纳入Git。Windows真实路径 `E:\foundationPos` 的main分支与Ubuntu `/data/ZJC/foundationPos` 的ubuntu分支共用基线历史，保留各端真实差异；不公开上传，不覆盖对方实时总日志。
后续代码/配置修改按有意义的阶段提交，并更新对应可提交报告；当前基线不能冒充之前各阶段的Git历史。
记录器自动保存 `project_git.json`（HEAD/分支/dirty/路径/差异SHA），有已跟踪改动时保存patch；继续保存原有源码快照、数据SHA、失败与中断证据。
大数据、模型、虚拟环境、缓存和逐次原始运行档案不进Git；实时 `EXPERIMENT_LOG.md` / `ISSUES.md` 继续在磁盘追加，初始化快照分别在 `history/windows/` 与 `history/ubuntu/`，阶段报告纳入Git。
操作示例、bundle交换与回溯方法见 `GIT_WORKFLOW.md`。代码版本回溯不能替代数据、权重和物理精度验证。

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

<!-- CUP-ARUCO-ID6-30MM-20261015 -->
## 固定杯子/码，只移动相机：ID 6、黑边实测30 mm

现场原始RGB已识别为5×5家族（ID6可由DICT_5X5_50解码；不声称知道打印时选的完整字典大小）。
Ubuntu运行：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_aruco_id6.sh --duration-seconds 1200 --max-frames 6000
```
打开 http://127.0.0.1:8765 ，首次冻结、框选完整杯子及杯把，生成并检查SAM Mask，再初始化。
初始化期间相机停稳；进入跟踪后先静止30秒，再缓慢移动30秒、较快移动30秒，最后返回停稳10秒。
杯子和码全程固定，记录各阶段的实际时间；计划时长本身不代表已执行阶段。
码短边至少25像素才进入参考求解，建议40像素以上；页面初始化前显示码尺寸/有效性。
DICT_5X5_50、ID6、0.030m和fixed-scene由专用入口设置；通用入口默认4×4/ID0保持可用。
所有误差来自同一推理RGB，失跟或参考拒绝时留空，不把缺失数据当零误差。
结束自动生成会话evaluation_summary/report.json和aruco_errors.csv；原始RGB-D、角点、矩阵、时间戳和失败记录保留。
这些是首帧对齐后的相对漂移，不能作为绝对6D精度；绝对值需独立T_marker_from_original_mesh标定。

<!-- D435I-CHECKERBOARD-TOOL-20261015 -->

## D435i棋盘格验证工具（2026-10-15）

独立目录 `camera_calibration/`；棋盘格按用户提供12×7方格、20mm格距，配置11×6内角点。
用户选择之后接Windows实测，本阶段仅工具准备和Ubuntu设备/原始取帧检查，不能宣称内外参或物理RGB-D对齐精度已验收。
Windows双击 `camera_calibration/start_windows.cmd`，或执行
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\camera_calibration\run_windows.ps1`；
相机就绪后浏览器 `http://127.0.0.1:8766`，停稳逐组保存25–35个多姿态视角；完成按钮释放相机并自动分析。
Windows原始/结果均在E盘项目的 `camera_calibration/sessions/` 和 `camera_calibration/results/`；执行仍由项目记录器留档。
保存RGB、原生/对齐深度、双目红外、SDK内外参/深度尺度、时间戳、角点、拒绝记录、代码快照及SHA。
可手工标实体板外轮廓，测逐边深度边界偏移；不得用棋盘黑白格纹理线当深度台阶。
详细操作/限制见 [独立说明](camera_calibration/README.md)，证据/验证见 [阶段报告](camera_calibration/STATUS_20261015.md)。
不修改设备标定或旧数据K；候选只保存到新的分析报告。现有Windows/Ubuntu相机环境没有升级。

<!-- CUP-DASHBOARD-RESTART-20261015 -->
重新启动后，waiting_for_roi表示模型和图像已就绪，需重新冻结、框选、生成Mask并确认初始化。
页面识别新的会话目录后清除旧冻结/框选/提示点/Mask版本；第一次使用更新后刷新一次页面。
本次修改只改善提示和会话切换，不复用上一轮Mask，不改变FoundationPose姿态估计或精度门限。

<!-- CAMERA-RIGID-REVIEW-20261017 -->
## 2026-10-17重新建模前的相机检查状态

**用户后续决定：2026-10-17明确暂停相机参数验证，按当前参数先采涂红杯口的新数据，采后自己逐张标注/修Mask。按该最新决定执行，不再将继续校准作为本轮实验性采集的前置要求；几何问题未解决状态保留。72张已完成，最后一帧单独补拍后使用修正版184953_656_corrected_last_190116；全组图像/深度及来源时序已复核，可保留作倒扣参考圈，但未覆盖内壁或通过完整几何QA。见[本轮复核结果](reports/RED_CUP72_CAPTURE_REVIEW_20261017.md)。用户反馈描轮廓慢后，已用已有Ubuntu SAM2生成72张待确认草稿，8768页接入画笔/橡皮擦修正并保留5张既有人工确认；恢复命令见[Mask说明](MANUAL_CUP_MASKS.md)，失败和复验见[SAM2辅助记录](reports/CUP_SAM2_ASSISTED_MASKS_20261017.md)。以下是该决定之前的检查结论。**

当前用户确认棋盘7×12方格、6×11内角点、20mm格距，固定后横竖5格100mm；已完成29组静态硬板视角。几何采集临时关闭投射器以避免IR散斑干扰：
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\camera_calibration\run_windows.ps1 -EmitterMode off`。
结束恢复原开关并留档；生产开启投射器的深度与实体边界必须另验。

本次发现双IR约1.13px纵向一致性偏差及厂商health绝对值0.9045。原厂K保留，候选仅临时RAM对照后显式恢复，Flash表未变；未判定相机物理精度通过，先不开始正式新Mesh采集。诊断、失败原因、恢复证据与下一步场景条件见 [硬板最终复核](camera_calibration/REVIEW_RIGID_BOARD_20261017.md)。后续运行仍通过项目记录器，不能直接使用厂商示例中默认的写入Flash步骤。

## 2026-10-17 当前杯子颜色与杯把检查

新彩色预览和现有FoundationPose渲染器验证见[专项报告](reports/RED_CUP_COLOR_HANDLE_REVIEW_20261017.md)。当前OBJ含顶点RGB，未生成高分辨率UV贴图；旧单色形状图不能用来判断颜色丢失。`preview_cup_mesh_local.py`现在读取顶点颜色，另存`color_views_8.png`并保留形状图。杯把局部Mask已覆盖而原始深度仍缺失，当前候选仍未通过精确几何验收。

## 2026-10-18 新模型实时入口

Ubuntu使用`bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000`，页面`http://127.0.0.1:8765`。如已有会话，使用已有页面，避免重复占用相机。该入口显式选择10月17日新OBJ、SAM2首帧、自动重获及固定杯码ID6/30mm协议。原通用入口默认legacy旧模型；也可追加`--mesh-profile redcup72`或`legacy`明确选择。新旧模型都会在访问相机前验证米制文件SHA，原文件不覆盖。

新模型已完成真实相机初始化和约23.74FPS静止初跑；当前ArUco未识别，静止估计变化不作为物理精度。完整证据及现状见[新模型实时记录](reports/RED_CUP_LIVE_NEW_MODEL_20261018.md)。

构图预览可以在Ubuntu运行`bash setup/run_realsense_viewer_ubuntu.sh`，或从桌面应用“RealSense Viewer (FoundationPos)”启动。建议RGB/Depth均选640×480、30FPS；打开相应流后调整相机。预览完先关闭Viewer/全部流再运行FoundationPose。原生Viewer已完成安装/启动/设备识别，安装位置和失败复验见[记录](reports/UBUNTU_REALSENSE_VIEWER_20261018.md)。

<!-- RED-CUP-HANDLE-MOTION-20261018 -->
2026-10-18新杯子入口增加可选初始化杯把朝向检查，默认启用，追加`--no-cup-yaw-init`可作对照；仅用于当前已固定SHA的redcup72模型。首帧SAM2 Mask仍需包含可见杯把、空隙留作背景；官方top1、top8及自定义朝向候选分别保存。初始化后页面停在旧状态的图片加载冲突已修复，刷新页面载入新版。详见[修正与验证](reports/RED_CUP_HANDLE_DASHBOARD_FIX_20261018.md)。

固定杯码评测沿用`bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000`；杯子或码会相对移动时追加`--no-aruco-fixed-scene`，只跟踪和保存参考，不计算固定场景误差。绿色码框仅表示当前参考门限通过；码像素小仍可能出现跨帧跳变。仅移动相机新轮20.77FPS、相对漂移与参考不连续证据见[本轮分析](reports/RED_CUP_CAMERA_MOTION_REVIEW_20261018.md)，不得只取中位数宣称毫米级精度。

<!-- CUP-RETURN-PROGRESS-20261018 -->
相机移开后重新对准目标，当前流程需要停稳约5秒供SAM2全图搜索、注册和连续3新帧验证。新提示会区分无匹配候选、已有候选但画面移动、正在注册和验证，后续host结果保存`acceptance_reason`。暂停/重新冻结会使未完成的结果失效，防止旧结果覆盖新操作。17:09启动轮6次找到杯子但未完成现场恢复的具体时间线、前段误差和现有限制见[返回测试复核](reports/CUP_RETURN_FAILURE_REVIEW_20261018.md)。
