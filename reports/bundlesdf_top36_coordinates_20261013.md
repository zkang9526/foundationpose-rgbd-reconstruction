# 俯视圈 Top36：最终网格与估计参考位姿坐标

2026-10-13 对 `/data/derived/cup_reconstruction_top36_v1_20261013_2220/pipeline` 作CPU只读坐标审计，通过exit0。原网格、位姿和源码均未修改；原侧面V4报告保留。

最终 `textured_mesh.obj` 是该俯视圈独立跟踪物体坐标中的米制网格。它的物体坐标基准由该次首帧定义，**没有据此断言与侧面圈物体坐标之间存在已知刚性变换**。网格融合仍需估计跨圈配准，不得从计划旋转角生成矩阵。

匹配该最终网格的global参考矩阵来自：

```text
pipeline/000035/keyframes.yml
pipeline/000024/poses_after_nerf.txt
```

`poses_after_nerf.txt` 含16个4×4 `camera_in_object`（OpenCV、米），按YAML有序mapping依次关联：`000000,000001,000002,000003,000004,000005,000006,000007,000008,000009,000010,000012,000014,000017,000020,000024`。投影metric网格时取逆得到 `object_in_camera`。

归一化参数：`s=13.552019571056737`，`translation=[-0.0037224768341728547,-0.0030904239514910475,-0.040818151729245036]`。mesh转换为 `v_metric=v_normalized/s-translation`；首帧PoseArray固定I，锚定offset理论I。最终mesh相对于反归一化 `mesh_cleaned.obj` 顶点最近邻最大误差 `1.78e-8 m`；normalized trainval恢复后与keyframe源矩阵差最大 `5.55e-17`，refined首帧锚定误差 `1.08e-8`。

最终mesh SHA256：`e0e5e16781dcc28847a0ab991f182c04cd98f415751ef1742d8bc78a41ab5134`，AABB尺寸 `[0.12724453,0.13931552,0.1310569] m`；这是当前候选网格的坐标轴对齐范围，不是杯子人工尺量尺寸或精度指标。

16个global refined矩阵相对对应online历史矩阵平均相差6.46mm/9.56°，最大11.86mm/22.24°。36个online矩阵不得改名为global refined。两种矩阵都是估计值，均无GT；候选网格质量需独立几何和投影QA。

完整证据：Ubuntu `foundationpose_data/bundlesdf_setup_20261013/top36_v1_pose_mesh_coordinate_audit.json`，本机 `reports/top36_v1_pose_mesh_coordinate_audit.json`，schema与侧面审计相同，包含 `passed`、`pipeline`、`global_keyframe_yaml`、`global_refined_pose_file`、`frame_id_order`、`sha256`、`source_formula` 和 `frames[].object_in_camera_matrix`。可用于 `review_cup_reconstruction.py --coordinate-evidence` 的16个refined投影。

审计运行：Ubuntu `20261013_222843_261678_bundlesdf_top_pose_gauge_audit_ab3b7508`。**本次重建主进程在产物导出后实际exit139；坐标审计exit0不覆盖该事实，退出异常仍未解决。** 本记录只确认已导出候选产物的坐标/文件关系，不宣称重建质量通过。
