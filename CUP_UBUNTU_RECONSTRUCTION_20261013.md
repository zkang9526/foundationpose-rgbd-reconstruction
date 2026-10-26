# Ubuntu恢复后的杯子重建与推理记录

2026-10-14新增E盘两组72张静态参考已上传校验，原生bag留Windows E盘。官方72帧未正确跟踪旋转、仍退出139；独立深度几何方向初始化+ICP/TSDF提供候选OBJ，53方向候选/19插值不是GT，孔洞和噪声未达到精确模型验收。当前实跑状态与文件见 [新72张结果](reports/CUP_NEW72_UBUNTU_RESULT_20261014.md)，下方旧36帧/5测试结果保持历史含义。

用户2026-10-13确认六张独立测试照片已采集，并恢复Ubuntu连接。继续沿用无CAD先重建、再官方预训练权重推理，不训练杯子位姿网络。Windows离线阶段已封存，不改写历史包。

## 已复核的Ubuntu状态

- SSH密钥连接成功，无密码写入命令/日志。
- Ubuntu20.04内核5.15、RTX3090 24GB，驱动535.230.02，GPU当前约946MiB已用；`/data`约117GB可用。
- 原 `foundationpose` 容器运行中，Python3.8.18、Torch2.0.0+cu118、CUDA可用；Open3D/Kornia/Kaolin/PyRender/NVDiffRast/mycpp现有模块可找到。该检查不是BundleSDF已可运行的证明。
- 官方FoundationPose源码仍为 `a1b694b83e633c2cb6115b9063d940a687759392`；现有bundlesdf目录只有神经场重建相关代码，缺完整BundleSDF动态目标跟踪流程。完整BundleSDF重建环境需要另行配置。
- 复核通过Windows与Ubuntu记录器留档；检查中一个末尾可选目录查询返回非零，前面的源码/挂载/磁盘结果保留，该目录查询不视为GPU或容器故障。

## 独立测试照片检查

原始目录 `foundationpose_data/windows_captures/cup_photos_20261013_204739_875`：6/6采集与格式通过，最大RGB-D时间差约9.348ms，按键后等待至少1秒、SDK帧独立、相机正常停止。

逐张原RGB已查看：`000000.png`杯子下部被画面底边裁切，保留原图与深度、排除首轮完整目标测试；`000001.png`–`000005.png`完整清楚，可先用于独立推理。杯子全部倒扣，把手均大体在右侧，位置/大小/背景与参考有变化，尚不能称广泛旋转/倾斜精度评测。计划角度不当外参或GT。证据见 `reports/cup_test_204739_visual_inventory.json` 与时序报告。

参考仍为16:58侧面Mask V4和18:53斜俯视Mask V5（72张），测试照片绝不混入重建。测试距离不同，分割和深度须独立检查，不能机械套用参考300–800毫米窗口。

## 本阶段执行方式

1. 5张测试Mask已逐张验收，最终目录 `foundationpose_data/derived/cup_masks_test_204739_v2`，证据 `reports/cup_masks_test_204739_v2_final_visual_qa_ready.json`。V1混入相似蓝色桌垫，已拒收保留；V2使用人工物体外轮廓限制候选范围，仍保留真实把孔背景。原始深度不改。各帧杯身核心深度中位数约507/574/539/602/584mm，整Mask非零80.96%–91.17%，不是精度验收。
2. 将参考、6张测试原图、5张验收测试Mask、脚本与全部已结束运行证据制作新完整批次；上传新的 `foundationpose_data/incoming/cup_complete_batch_20261013_2055/` 暂存目录。
3. 校验整ZIP与全部manifest文件；再把原始/派生数据导入项目。相同文件按SHA跳过、不同原始数据保留并报冲突；更新脚本/白名单指南先备份，不覆盖Ubuntu总日志。Windowsrun按唯一ID追加，人工总结按event-id追加。
4. BundleSDF使用独立容器/源码固定版本，避免最新依赖升级已验收FoundationPose环境。首次验证扩展/模型导入后，先小规模参考跟踪/重建检查，再完整初轮重建。
5. 保存网格、算法估计参考位姿与坐标约定，检查杯把孔、尺度、支撑污染/跟踪丢失；然后用官方预训练scorer/refiner对独立测试初始化。每张测试独立注册，不能把随机换位置照片当连续跟踪。

数据传输、BundleSDF安装、实际重建与推理结果将依实际日志继续追加。本文当前未声称网格/位姿输出已完成，没有6D真值时不报告ADD精度。

## 完整批次上传与导入复验

新包 `foundationpose_data/exports/cup_complete_batch_20261013_2055/cup_offline_snapshot.zip` 包含6380个来源文件，整包SHA256为 `0c146d2ceaa318cca2f70dc3880557efb02684388c65333bcb7672290827b6f9`。本机打包run `20261013_211753_488787_cup_complete_offline_package_8a4f8f29`、上传run `20261013_213010_988335_cup_complete_batch_upload_149193a2`。

Ubuntu已上传至 `foundationpose_data/incoming/cup_complete_batch_20261013_2055/`，整包及6380成员SHA验证、6118项新建/有备份更新、117份Windows运行索引追加及两份人工阶段总结均完成。初次最终复验发现索引函数重写20份历史run的 `issues.md`，把CRLF换成LF；RGB-D及Mask未受影响。失败报告 `import_report.json` 保留，不能改为成功。

专用恢复仅允许证明为CRLF→LF的历史run问题记录变化，全量preflight后备份LF版本，恢复ZIP对应原字节；6380项导入输出和6380项staged来源全部重新通过SHA复验。Ubuntu run `20261013_213931_599894_cup_import_newline_recovery_4215c027`，同incoming下 `recovery_report.json` 为当前成功证据。备份在 `foundationpose_data/import_backups/cup_complete_batch_20261013_2055_newline_recovery/`。原总日志不覆盖、不重复追加。

索引工具已在Windows修正：`append_records(..., write_run_issue=False)` 用于导入旧Windows档案，正常新run保持默认行为。后续增量部署会先备份旧脚本、校验新SHA并复验，不能通过重新打包覆盖失败证据。

## 已执行的重建与杯子推理

索引补丁及新工具已在Ubuntu增量部署，先备份后更新，2612项SHA复验通过、63份新增Windows run追加，见 `foundationpose_data/incoming/cup_core_updates_20261013_2150/deployment_report.json`。原记录不覆盖。

独立 `foundationpose-bundlesdf` 容器已验证源码固定版本、sm86 CUDA二进制、官方LoFTR权重严格加载及CPU导入/CLI帮助。启动需要 `LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7`，原FoundationPose环境不升级。实际NeRF曾出现CPU ray IDs被GPU Mask索引的问题，最小设备对齐修补后完整优化/网格导出已越过该错误；源码原文、diff、SHA保留。

- **侧面默认 V4**：`foundationpose_data/derived/cup_reconstruction_side36_v4_20261013_2150/pipeline/`。36份历史在线位姿、18份全局更正位姿与 `textured_mesh.obj` 已生成，约184秒完成算法入口；实际进程在退出清理阶段返回139，run保持失败。多角度网格变形、裂口与杯把不完整，QA拒收为可靠重建，只允许流程试跑。
- **斜俯视默认 V1**：`foundationpose_data/derived/cup_reconstruction_top36_v1_20261013_2220/pipeline/`。36份历史矩阵、16份全局矩阵及网格已生成，也发生退出139；多视角仍明显变形，未证明比侧面更可靠。两圈独立处理，未用planned_angle伪造外参或合并。
- **官方FoundationPose基线**：`foundationpose_data/derived/cup_fp_heldout5_pilot_v1_20261013_2208/`。5张完整测试图各自register，scorer/refiner均加载官方权重，退出0，保存原网格米坐标→相机4×4矩阵、另存OBB显示位姿及叠图；未训练位姿网络、未track随机照片。数值合法但第5张杯把朝向明显错误，其余有边缘/尺寸偏差，不能称5张准确。
- **候选与掩码一致性诊断**：官方top32候选另存 `cup_fp_candidates_side_v1_20261013_2219/`；新诊断 `cup_fp_side_mask_consistency_v1_20261013_2224/` 按预先固定的160×120全部候选、前4加官方rank0在640×480复核规则选择。原官方基线不改，`custom_mask_selected/` 与 `official_baseline/` 分开。第5张改选官方rank1后可见把手投影回右侧，仍不是GT或准确6D认证，网格变形没有因此解决。

参考位姿方向：`ob_in_cam/*.txt` 为物体→OpenCV相机、米，属于在线历史值；全局 `poses_after_nerf.txt` 为被选关键帧的相机→物体，须取逆后投影对应最终米制网格。侧面全局矩阵在 `000033/poses_after_nerf.txt`，18帧顺序来自 `000035/keyframes.yml`；俯视在 `000024/poses_after_nerf.txt`，16帧顺序同样从末帧关键帧文件读取。数值坐标审计通过不证明跟踪正确。归一化 `mesh_cleaned.obj` 不可直接当米制推理网格。

2026-10-14受控排查已核验完成：`foundationpose_data/derived/cup_reconstruction_side36_frozen_pose_v1_20261013_2238/` 保存冻结NeRF PoseArray学习率为0的试验，在线/全局配置均实际为0.0，特征跟踪/BA仍估计位姿。有36份在线历史矩阵、13份全局关键帧矩阵，后者在 `pipeline/000034/poses_after_nerf.txt`，两个集合不能串成49张最终姿态。坐标审计通过；16视图仍有褶皱、薄壁/缺口及残缺杯把，QA拒收，未证明比两个默认版本可靠改善。实际退出仍139，旧网格与失败目录不改。该实验说明冻结这一项不足以解决几何问题，不据此确定唯一根因。日志里的SDF/NeRF `training` 是对象表示优化，与重新训练FoundationPose位姿网络不同。

最新结果阅读、可在Ubuntu重跑的官方5图推理命令及下一步重点见 [CUP_POSE_PILOT_RESULTS_20261014.md](reports/CUP_POSE_PILOT_RESULTS_20261014.md)。当前可交付的是环境、完整留档及流程试跑结果；可靠网格、准确位姿、连续检测/跟踪及GT评测仍未完成。下一步先检查参考配准与实际杯子尺度，不能把当前矩阵当训练真值。

用户随后提供杯子近似尺寸：高94mm、杯身外径84mm、含把总宽115mm。已单独保存人工测量JSON，三网格来源SHA及包围范围/主成分跨度已CPU核验，报告 `reports/CUP_MANUAL_DIMENSION_SCREEN_20261014.json`。网格坐标轴不是语义高/径/宽，筛查不能当准确尺寸误差；原网格和预测位姿没有缩放，形状QA仍未通过。测量值不是CAD或6D GT。

包含这组新尺寸的最新操作说明另存 [CUP_POSE_PILOT_DIMENSIONS_UPDATE_20261014.md](reports/CUP_POSE_PILOT_DIMENSIONS_UPDATE_20261014.md)，原已发布结果文档保持字节不变，避免覆盖早期证据。

用户随后询问如何改善配准与重建，具体诊断顺序、受控配置对照、条件性12张/72张停稳补拍及几何验收见 [CUP_REGISTRATION_RECONSTRUCTION_PLAN_20261014.md](reports/CUP_REGISTRATION_RECONSTRUCTION_PLAN_20261014.md)。本次只制定方案，尚未执行新改善实验；先检查已有数据，不立即要求重拍全部参考。采集入口可用新帧数，现有36帧重建入口须先适配，不能直接套用。
