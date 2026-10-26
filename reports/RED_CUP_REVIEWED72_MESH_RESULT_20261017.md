# 2026-10-17 人工Mask复核与首轮Mesh结果

用户已检查并确认全部72张。本轮Mask可用于实验性重建，已完成Ubuntu首跑及独立几何对照。**当前有可识别杯身和杯把的初步OBJ，但未通过精确几何或6D精度验收。**

## 当前查看的初步模型

2026-10-17补充：[颜色与杯把专项检查](RED_CUP_COLOR_HANDLE_REVIEW_20261017.md)。OBJ已保存顶点RGB；旧预览未读取该颜色，现已修正，并用现有FoundationPose渲染器验证。新彩色图见专项报告，旧图保留。杯把缺陷仍未通过精确几何验收。

- Windows OBJ：`E:\foundationPos_data\derived\redcup_geometric_comparison_20261017_2050\redcup_geometric_clean_v1_20261017_2050\cup_clean.obj`。
- 同目录`cup_clean.ply`保留顶点颜色；OBJ含米制顶点和可选顶点RGB，未缩放。该候选是几何初始化+ICP+TSDF，不冒称官方BundleSDF输出。
- 多视图：`E:\foundationPos_data\derived\redcup_geometric_comparison_20261017_2050\redcup_geometric_preview_v1_20261017_2050\geometry_views_8.png`。
- Ubuntu OBJ：`/data/ZJC/foundationPos/foundationpose_data/derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj`。

模型杯身及杯把已成形，杯把接头/接触侧仍有噪声、毛刺和缺失，表面粗糙。此次杯子倒扣，可见杯底有数据，未观察到的杯口内壁及贴桌面侧仍不能由Mask补回。坐标轴为算法构建的模型坐标，预览中的朝向不等于采集时正放。

## 72张Mask验收范围

- 当前源：`E:\foundationPos_data\windows_captures\obj_side_20261017_184953_656_corrected_last_190116`；用户标注：`E:\foundationPos_data\manual_masks\red_cup72_sam2_assisted_20261017_1945`。
- 72/72确实保存为人工确认，逐张验证RGB/depth/Mask SHA、导出与不可变revision SHA、确认的最终预览SHA及操作回放。所有回放与最终二值PNG完全一致，Mask为原始640×480单通道0/255。未代替用户点击确认或改原Mask。
- 全72张最终叠图均查看：杯把及红色区域较草稿完整；仍有小孔和边界偏差，000044/000045的左上尺子残留。可作初跑，不作为像素GT或分割精度证明。
- 不可变快照：`E:\foundationPos\foundationpose_data\derived\redcup_human72_snapshot_20261017_2036`。保存最新确认Mask、annotation、机器草稿来源与报告SHA；原完整标注历史留原输出。后续页面修改不影响本次输入。
- 目标Mask内非零原始深度平均85.508%、最低76.068%、最高91.108%。正深度主体为380–480mm，少量约600–650mm返回主要位于轮廓附近；超过520mm的16310像素中75.4%在Mask边缘3像素内。这是可用性/一致性检查，不是深度精度或物理标定验收。
- 本轮独立派生重建深度：Mask内保留350–520mm、其他归0，不插值、不补洞、不改原RGB/深度/K/Mask。保留深度占目标Mask平均84.303%；该区间是本轮摆放的数据选择，不是所有杯子的固定阈值。缺失深度对应的可见杯子仍保留在RGB Mask。

审核run：`20261017_203505_416390_redcup_human72_mask_audit_e2545244`；深度分布run`20261017_203633_330574_redcup_target_depth_distribution_784110f6`；派生准备run`20261017_203856_648138_redcup_reviewed72_prepare_reference_75a642ed`。snapshot下report.json、mask_qa.json和9张contact/masks_*.png保留数值/视觉证据。

## 数据与执行证据上传

静态包`E:\foundationPos_data\exports\redcup_mesh_reviewed72_20261017_2040\capture_batch.zip`，94,890,670字节，SHA256=`8c812bbc208dadd9c85e7e279656707bb3a498da906758d8769e9f4f3dbde400`。包含实际E盘修正版原始RGB-D、内参/时间戳、确认快照、派生输入、冻结源码和44份已结束Windowsrun，共7437文件。bag留E盘；未传Windows venv。

Ubuntu入口`/data/ZJC/foundationPos/foundationpose_data/incoming/redcup_mesh_reviewed72_20261017_2040`，ZIP及逐文件SHA全部通过；已有日志/档案按唯一run_id追加，未覆盖Ubuntu总日志。导入run`20261017_204110_417306_redcup_reviewed_import_sha_736cd096`。GPU为现有RTX3090，现有容器/Conda均未安装或升级。

## 官方BundleSDF：失败结果保留

首轮v1在进入算法前因准备报告的Windows反斜杠路径被PurePosixPath当作单一文件名而拒绝。新增仅规范化记录路径分隔符的校验兼容，不改变官方算法；未来准备报告使用as_posix()。v1目录与run保留，v2使用新冻结代码/新输出，完成72帧输入验证并实际进入重建。

- v1：远端run`20261017_204135_380680_redcup72_bundlesdf_initial_20261017_b03c380a`；输出`cup_reconstruction_redcup72_v1_20261017_2040`。
- v2：远端run`20261017_204239_729596_redcup72_bundlesdf_initial_v2_20261017_18d39bae`，Windowsrun`20261017_204237_930842_redcup_reviewed72_bundlesdf_v2_2e46dce8`。
- v2完整输出：`/data/ZJC/foundationPos/foundationpose_data/derived/cup_reconstruction_redcup72_v2_20261017_2044/pipeline`；官方来源pin仍`cf0610e3636bc42535c996f129161f44beeadc56`，完整全局refinement保留。wrapper仅在内存中替换官方破坏性输出初始化为新目录创建，沿用现有安全封装。
- 72在线矩阵均保存，但仅1关键帧；相对首帧最大SO(3)旋转3.328°，与杯把在照片中绕转明显不符。网格变形，只保留为失败候选，不能用作正确重建。
- 官方入口返回且导出textured_mesh.obj后，进程仍以139/core dump结束；包装report里的passed=true只代表入口返回，不代表进程成功。旧退出清理问题未解决。
- CPU数值检查通过只说明矩阵/网格数组合法，未通过追踪/几何质量；所得23115顶点/28323面、包围盒约116.2×124.0×88.4mm不作为实物尺寸精度。
- 结果及CPU预览已传回`E:\foundationPos_data\exports\redcup_mesh_reviewed72_20261017_2040\result_delivery`；metric OBJ及六张视图SHA与远端CPU报告一致。`mesh_cleaned.obj`是其归一化中间网格，不能直接作为米制位姿输入。

数值摘要见官方失败候选摘要（原始附件未随公开快照提供）。对称几何、弱纹理、反光和特征匹配偏向等是可能因素，本轮没有证明唯一根因；不能将此失败简单归结为人工Mask。

## 独立几何初始化+ICP+TSDF候选

在同一派生72帧上拟合可见杯底平面/圆及可见杯把方向，建立相机到模型的几何估计，再以有界ICP微调并融合TSDF。不使用planned_angle作外参，不使用固定相机位姿把转动物体直接叠加。

ROI由本轮RGB复核选择：杯身核心[310,351,344,374]，杯底平面候选y<340；44–63按RGB判断杯把被杯身遮挡，不将这些点当可靠方向观测。结合深度支持，最终49帧方向有数据支持、23帧需在邻近观测之间插值。估计展开角跨度359.899°只是算法结果，不是转台实测/GT；插值也不是真实外参。

参数：相对杯身深度窗口±120mm（输入已350–520mm），TSDF体素1.5mm、截断7.5mm；ICP校正仅角度<7°且平移<4mm时采纳。模型源数据、原始候选、清理候选及72个estimated_camera_to_model矩阵全部分开保留。

- 运行：远端`20261017_204842_778111_redcup_geometric_tsdf_comparison_2664b87b`，Windows`20261017_204840_687474_redcup_geometric_initial_reconstruction_da556685`。
- 原始候选：24572顶点/46913面，包围盒135.2×112.6×114.2mm。另存清理去除682个小碎片面，不做缩放；清理后23796顶点/46231面，包围盒约123.0×90.4×105.2mm，尚未独立实测验证尺寸。
- 在这些**估计/插值姿态**下与72张Mask的投影轮廓IoU平均0.8655、最低0.7798；这是自一致性，不是独立6D精度或几何精度。叠图绿色=观测Mask超出模型，红色=模型超出Mask，底沿/杯把仍有明显差异。
- 8角度CPU预览和000000/000036/000060叠图已查看。杯身及杯把形状可识别，表面粗糙、杯把附近毛刺/孔洞、未观察接触侧仍需改善，不能标记精确几何QA通过。
- 几何审核远端run`20261017_204916_609682_redcup_geometric_component_silhouette_audit_9edfffb3`；预览run`20261017_205041_930220_redcup_geometric_obj_preview_313c86c2`。回传原始/清理OBJ均按report SHA核验。

本次不将候选自动替换到实时FoundationPose。后续可以基于本轮模型做独立测试与配准改进；若要求杯口内壁/完整几何，需要另采正放或合适倾角并分别估计配准，不能用计划角度硬拼。

## 操作问题与留档

- 直接PowerShell ssh解析到沙箱占位命令，未把其输出当服务器内容；后续按授权通过记录器与相应执行权限运行真实SSH，读取/上传正常。
- 一次临时摘要尝试写E盘workspace外被文件权限拒绝，结果未被修改；改为记录器写项目reports目录后成功。该问题不属于重建或相机故障。
- 全部新代码、采集/标注SHA、Windows和Ubuntu运行档案、成功/失败候选分开保存。源照片、原Mask和旧模型不覆盖；本轮未改相机参数或进行厂商校准。
