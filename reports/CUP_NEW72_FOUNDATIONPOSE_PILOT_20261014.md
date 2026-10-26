# 新72张候选网格：独立5图FoundationPose初跑

2026-10-14用户授权有孔洞模型先尝试6D位姿。Ubuntu `/data/ZJC/foundationPos` 已用官方预训练FoundationPose完成5张独立RGB-D照片的初始化，进程退出0；保存5个合法4×4矩阵、框/轴及完整网格投影。流程试跑完成，**几何与位姿精度尚未验收**。

## 输入与范围

- 网格：`foundationpose_data/derived/cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj`，SHA256 `5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de`。原米制坐标、26731顶点/51318面，没有缩放、补孔或按手工尺寸拟合。
- 模型由杯底平面/杯把方向候选、部分插值、受限ICP与TSDF生成；不是官方BundleSDF成功重建或真值。53方向候选/19插值的来源记录保留。
- 测试为`windows_captures/cup_photos_20261013_204739_875/000001..000005`，首张裁切的`000000`继续排除。测试图未参与重建。本次未对72张参考照片做自测/跟踪。
- 640×480原始RGB、uint16毫米对齐深度、K及已接受Mask，逐项SHA验证。每张独立`register(iteration=5)`，没有前帧姿态、计划角度或自定义Mask重选。
- 官方scorer `2024-01-11-20-02-45`、refiner `2023-10-28-18-33-37`加载成功，checkpoint/config哈希在报告；RTX3090，没有训练杯子位姿网络。
- OBJ有顶点颜色、无UV/MTL贴图。固定官方`Utils.py:106`支持顶点颜色分支，推理正常运行；未生成替代纹理。

## 结果与人工复核

|测试帧|人工Mask与网格轮廓IoU|目视结论|
|---|---:|---|
|000001|0.8742|杯身大致重合，把手同侧但有位置/外形偏差，下沿破损|
|000002|0.8242|右侧可见杯把未被预测网格正确覆盖，朝向明显存疑|
|000003|0.8527|同样杯把未覆盖，不能因杯身重合认定旋转准确|
|000004|0.8720|把手大致同侧，投影/开孔边界有偏差，下沿破损|
|000005|0.8911|把手大致同侧，下沿孔洞及杯把偏差仍在，未验收准确|

平均IoU `0.8628276918`只是2D轮廓一致性：杯身面积大，可能掩盖把手朝向错误。没有6D GT，不能给出旋转/平移误差、ADD/ADD-S或准确率。五矩阵均有限、旋转正交/行列式正确、对象原点在相机前方；这些仅是数值合法检查，视觉复核未通过可靠位姿验收。本次也没有证明重复初始化稳定或连续跟踪能力。

## 孔洞、黑色与相似角度

原RGB确认杯子倒扣：朝上的青色椭圆是外杯底，杯口在桌面接触侧。两圈均未看见完整杯口内壁/支撑接触面；增加同高度旋转照片无法测量不可见表面。该侧孔洞、薄壁断裂和噪声还需补观测及复核融合，不用任意补孔当真实几何。

RGB黑色不能直接等同于无效深度。新72张场景专用人工小样区原始非零深度均值：黑带约94.07%、杯身97.46%、朝上外杯底中心98.44%；完整Mask均值91.07%。小样区覆盖率不是精度，也不代表整圈边缘。深度PNG数值0才是本项目的无效深度。黑带多数能获得测量，但边缘、反光和遮挡处仍可能失败；不能从当前数据判定RGB黑色是所有孔洞的唯一原因。[RealSense官方光学说明](https://dev.realsenseai.com/docs/optical-filters-for-intel-realsense-depth-cameras-d400/)解释D400通过左右图像匹配获得深度，输入纹理/曝光/反射条件会影响测量。

相邻视角相似能提供重叠；杯身接近轴对称、纹理少，杯把被遮挡时角度更难辨别。既有官方72帧跟踪仅1关键帧、相对首帧最大约3.275度，去背景对照也未恢复整圈转动，未证明参考圈可可靠配准。计划角度不是实测外参。本次第2/3图也显示只看杯身或框会漏判朝向。

建议下一次先少量补拍正常放置、真正能看见杯口/内壁/原接触侧的参考，同时保留完整杯身/杯把和重叠；先检查真实非零深度与配准，再扩整圈。不同摆放的数据必须独立估计变换，不能按计划角度直接拼接。若仍难辨角度，再受控验证可识别纹理的改动并记录外观变化。

## 坐标定义与文件

`poses/000001.txt`等是**原始候选网格（米）→OpenCV相机**的估计：`p_camera_m = R @ p_mesh_m + t_m`。相机x右、y下、z前；对象原点/轴沿用候选OBJ，未标定到机器人或世界。`obb_display_poses/`是画框坐标系，只供显示。

Ubuntu推理目录：`foundationpose_data/derived/cup_fp_new72_geometric_heldout5_v1_20261014_1958/`；完整投影：`foundationpose_data/derived/cup_fp_new72_geometric_heldout5_projection_v1_20261014_2000/`。

- 官方run `20261014_195814_663349_newmesh_heldout5_official_inference_1c7e4d67`退出0；投影run `20261014_195901_915168_newmesh_heldout5_projection_review_6836aab4`退出0。
- E盘同名推理/投影位于`E:\foundationPos_data\derived\`。
- 放大对比、原始R/t CSV、复验及人工QA位于`E:\foundationPos_data\reviews\cup_fp_new72_geometric_heldout5_v2_20261014_2004\`，包括`comparison_5views.png`、`poses_6d.csv`、`summary.json`、`visual_qa.json`。
- CSV保存R的9元素及米制t，避免未声明欧拉角约定。V1小图保留，V2只改变放大尺寸，不改变推理。
- 下载后原RGB/depth/Mask、5矩阵、轴图、完整投影及报告关联SHA全部通过，新网格本机/服务器SHA一致。

## 重现命令

输出需换新名字；官方方法可用预训练模型处理新对象，见[FoundationPose官方项目](https://github.com/NVlabs/FoundationPose)。

```bash
cd /data/ZJC/foundationPos
bash setup/run_logged.sh --label newmesh_heldout5_official_rerun \
  --note 'Independent held-out5; geometric candidate holes remain; no pose GT.' \
  -- docker exec -w /workspace/FoundationPose foundationpose \
  /opt/conda/envs/my/bin/python -u \
  /data/incoming/cup_inference_helpers_20261013_2207/run_cup_mesh_inference.py \
  --repo /workspace/FoundationPose \
  --scene /data/windows_captures/cup_photos_20261013_204739_875 \
  --mask-dir /data/derived/cup_masks_test_204739_v2 \
  --qa /data/incoming/cup_complete_batch_20261013_2055/verified_payload/reports/cup_masks_test_204739_v2_final_visual_qa_ready.json \
  --mesh /data/derived/cup_new72_geometric_tsdf_v2_clean_20261014_1920/cup_clean.obj \
  --mesh-units m --output /data/derived/cup_fp_newmesh_heldout5_NEW_RUN \
  --register-iterations 5
```

随后经记录器运行`setup/review_cup_heldout_projection.py`检查完整网格；`setup/summarize_cup_pose_pilot.py`复验及导出R/t。未改官方配置/采集原始数据。BundleSDF退出139未解决，不能由另一个容器本次推理退出0推断修复。

工具记录：Ubuntu无rg，首次只读颜色分支查询失败留档；新run用grep读取源码退出0。这个替代只解决源码查询，不是几何修复。
