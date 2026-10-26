# E盘新72张：已上传、重建与候选OBJ结果

已按用户直接执行授权完成：两批E盘静态RGB-D/参数/掩码/复核证据打包到Ubuntu，包与每文件SHA256校验、Windows run_id追加、72帧输入适配、实际重建和候选OBJ导出/回传。**当前可以提供候选OBJ和复现证据；没有验收为完整、精确杯子模型或6D真值。**

## 可查看结果

- Windows候选OBJ：`E:\foundationPos_data\derived\cup_new72_geometric_tsdf_v2_clean_20261014_1920\cup_clean.obj`。
- WindowsPLY及审核：同目录`cup_clean.ply`、`report.json`及7张重投影图。
- 多角度检查图：`E:\foundationPos_data\reviews\new72_20261014_164948\cup_new72_geometric_preview_20261014_1920\geometry_views_8.png`。
- Ubuntu同名OBJ：`/data/ZJC/foundationPos/foundationpose_data/derived/cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj`。
- OBJ SHA256：`5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de`，E盘下载后与服务器报告一致；坐标单位米，无尺寸强制缩放。OBJ保存顶点RGB，没有制作UV贴图。

## 数据检查、打包和导入

新72张`obj_side_20261014_164948_678`实际观察位置更高，朝上的倒扣杯底更清楚，不能由obj_side名字推断相机角度。整图原始非零深度平均91.94%；手工杯底中心样区平均98.44%（前圈独立样区61.23%，位置/视角不同，不作同区域精度对照），杯身样区97.46%、黑带94.07%。72帧时序/格式/正常停止/参数恢复通过。

掩码V1底边/文字有问题，V2部分杯把开孔被错选为前景，均保留；V3添加实际RGB确认的背景种子、全部72张叠图复核后接受作初轮参考。全Mask内原始深度平均91.07%、最低85.50%。接受单和生成报告哈希绑定，未将掩码/算法姿态当GT。

用户明确选推荐方案：上传静态PNG、内参、时间戳、metadata/参数备份、独立depth_filtered、目标Mask与日志。两批连续原始bag合计54,541,372,196字节（约50.80GiB）留在E盘；排除项及大小在manifest明确记录，不伪称已上传bag。

- 本机包：`E:\foundationPos_data\exports\cup_E_new72_20261014_1730\capture_batch.zip`，158,539,848字节（约151.2MiB）。
- 包SHA256：`a1d9a41db08de7d57eda81dda7d0447f6e6d7866add491dac352ca4113b6a81e`。
- 共4,403文件，51份结束Windows档案；两批原始目录分别新增到Ubuntu`foundationpose_data/windows_captures`，没有合并成一组或用planned_angle硬拼。
- 导入报告：`foundationpose_data/incoming/cup_E_new72_20261014_1730/static_capture_import_report.json`，包/逐文件SHA验证通过。更新setup先备份，既有raw/结果冲突拒绝覆盖，Windows索引按唯一run_id追加，Ubuntu总日志未被Windows替换。
- Ubuntu导入run：`20261014_173621_574940_new72_static_package_import_089d01b6`；本机打包run：`20261014_173308_622194_e_rgbd_static_reconstruction_package_e7c7961c`。

## 官方BundleSDF实跑及拒收原因

新72帧入口保留原默认36帧命令，实际官方reader、全部RGB/depth/Mask及毫米转换哈希校验通过。官方源码仍为固定`cf0610e3636bc42535c996f129161f44beeadc56`，没有注入计划角度或6D标签，保留官方全局更正。

1. 原RGB参考运行：`20261014_174105_437882_bundlesdf_new72_complete_ring_4a9bc121`，输出`cup_reconstruction_new72_v1_20261014_1740/pipeline`。官方入口返回并导出网格，但进程退出139；72个在线姿态相对首帧最多仅3.275°，只选1关键帧。图像显示杯把绕转一圈，因此这个估计不成立，首轮网格拒收。数值姿态/网格审核通过只说明有限数值与合法数组，不说明几何正确。
2. RGB背景置零对照首次失败：目录`maskedrgb`被官方reader的全路径replace('rgb','depth')替成`maskeddepth`，在输入检查阶段失败，未开始跟踪。失败目录/日志保留；未改官方reader，仅换新输入父目录名`objectcolor`。
3. objectcolor完整72帧对照：`20261014_182425_814581_bundlesdf_new72_objectcolor_control_30beec0c`，输出`cup_reconstruction_new72_objectcolor_v3_20261014_1805`。仅派生RGB的非目标背景变黑，深度/K/Mask未变。仍只选1关键帧、导出后退出139。该对照未解决配准，不将失败归结为固定RGB背景，也未解决退出清理问题。

只读诊断第一次有PowerShell引号错误，未启动remote/logger；后续脚本写root-owned Docker输出目录权限失败，改写项目reports后成功。各失败与修正有独立记录，不覆盖旧证据。原因尚未唯一确定；杯子近轴对称、反光/弱纹理与匹配策略可能参与，但不能从这些结果直接诊断硬件损坏。

## 独立几何初始化、ICP与TSDF候选

官方跟踪失败后，按指南的几何配准/TSDF方向作独立候选，未冒充官方默认结果。针对当前固定相机、竖直倒扣杯子，原始深度估计可见杯底平面/圆心及可见杯把方向；姿态是算法估计，不是实测GT。缺乏可见方向的帧从邻近有依据的方向插值，明确标记。

V1对遮挡和离群点筛选不充分，包围范围约0.48m，明显不符合杯子，拒收并保留。V2使用实际杯身深度中位数±80mm剔除明显离群值，保留的深度原值不变；只从青色外侧点估计杯把，RGB确认隐藏的48–63不当作观测方向。这个规则是当前场景的专用近似，不是通用相机标定或位姿GT。

- V2 run：`20261014_190943_956258_new72_geometric_filtered_tsdf_v2_6a3db82b`，退出0。
- 53帧方向有几何候选依据，19帧插值；估计展开范围353.02°，没有读取planned_angle。部分“可见”方向仍可能受噪声/遮挡影响，不当作角度测量精度证据。
- 用有界point-to-plane ICP作小修正，再将Mask内未插值深度以depth_scale=1000（毫米/米）融合；TSDF体素1.5mm、截断7.5mm。世界/模型到相机变换为保存camera-to-model的逆。
- 原V2输出28,630顶点、53,360面，轴向范围126×97.19×102.11mm，未缩放。
- 连通性审核去除2,042个小型断开碎片，另存clean，不修改原网格；clean为26,731顶点、51,318面，完整包围范围123×93×99.25mm。
- clean顶点1–99百分位跨度112.52×83.77×95.76mm；该稳健范围接近用户近似尺寸115mm含把宽、84mm身径、94mm高，但不是独立尺度精度验收，不能以百分位忽略真实边界缺陷。
- 72张基于**同一估计姿态**的轮廓IoU平均0.8854、最低0.8350，仅内部一致性，不能当GT位姿精度或ADD/ADD-S。审核run`20261014_191437_686187_new72_geometric_mesh_silhouette_audit_59267102`退出0。

多角度视觉复核：杯身与杯把形状较首轮明显改善，闭合杯底一侧可见连续平面；未观测杯口/支撑接触一侧仍有大孔、粗糙边界，表面有噪声。因此只提供初步外形候选、用于流程检查；目前不验收为准确FoundationPose最终参考模型，没有进一步位姿网络训练或GT评测。

## 保留状态和下一步

原始两批E盘PNG/bag、Ubuntu新增原始数据、掩码候选、官方失败、几何V1/V2、清理版与估计/插值矩阵均保留。两圈不直接硬拼；没有把算法矩阵作为训练真值。

下一步针对模型误差检查原始边缘深度和跨视角几何；若要求杯口内壁/支撑接触面完整，需分开采能看见这些面的参考，当前两圈没有这些观测。若要求更可靠的通用特征配准，可受控增加可识别的表面纹理并复验，不能仅反复运行同一失败配置或按计划角度伪造外参。当前OBJ可供查看、流程试验；高精度6D位姿仍需改进几何与独立验证。
