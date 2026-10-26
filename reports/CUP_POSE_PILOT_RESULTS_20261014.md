# 杯子离线位姿估计：已运行结果与重跑步骤

已经完成数据上传、独立重建环境配置、两圈默认重建尝试和5张官方预训练FoundationPose初始化。推理代码可以运行，但目前网格明显变形，不能称可靠完成杯子6D位姿复现，也不能把输出直接当训练真值。全部成功、失败、候选和原始数据保留。

## 数据与结果位置

以下路径相对于Ubuntu `/data/ZJC/foundationPos`；原 `foundationpose` 容器可用，独立重建容器为 `foundationpose-bundlesdf`。

|内容|路径|实际结论|
|---|---|---|
|完整Windows批次|`foundationpose_data/incoming/cup_complete_batch_20261013_2055/`|6380文件SHA复验通过；初次导入最终校验失败与20份换行恢复证据均保留|
|侧面默认网格|`foundationpose_data/derived/cup_reconstruction_side36_v4_20261013_2150/pipeline/textured_mesh.obj`|米制导出，但形状QA拒收；实际重建退出139|
|俯视默认网格|`foundationpose_data/derived/cup_reconstruction_top36_v1_20261013_2220/pipeline/textured_mesh.obj`|独立米制导出，仍变形，未证明可靠改善；退出139|
|冻结NeRF位姿实验|`foundationpose_data/derived/cup_reconstruction_side36_frozen_pose_v1_20261013_2238/pipeline/textured_mesh.obj`|实际配置lrate_pose=0.0，13份全局矩阵与米坐标复验；16视图仍拒收，退出139|
|官方5图推理基线|`foundationpose_data/derived/cup_fp_heldout5_pilot_v1_20261013_2208/`|官方权重加载，5矩阵与叠图，退出0；第五张朝向明显错误|
|官方32候选|`foundationpose_data/derived/cup_fp_candidates_side_v1_20261013_2219/`|原官方top1保留，候选转换到原网格米坐标，不重新训练|
|自定义掩码一致性选择|`foundationpose_data/derived/cup_fp_side_mask_consistency_v1_20261013_2224/`|`official_baseline/`与`custom_mask_selected/`分开；第五张把手投影回右侧，仍不认证真实6D准确度|
|侧面/俯视网格多视图QA|`foundationpose_data/derived/cup_mesh_local_preview_v4_20261013/`、`cup_mesh_local_preview_top36_v1_20261013/`|16视图逐一检查、拒收可靠网格，允许流程试跑|

本轮测试原始采6张，`000000`下部裁切保留排除，完整的 `000001`–`000005`用于独立推理，不参与重建。全部倒扣、杯把大体右侧，尚未验证广泛旋转或直立状态。

## 查看已有预测

`poses/000001.txt`等是原网格米坐标到OpenCV相机的4×4估计变换：`p_camera = R @ p_mesh_m + t_m`。`obb_display_poses/`只是画框用的OBB坐标系，不能替代原网格坐标位姿。源网格单位来自RGB-D重建，独立物理尺寸尚未测量。

先看 `visualizations/`里的框与轴，再看 `cup_fp_heldout5_projection_v1_20261013_2211/overlays/` 的完整网格轮廓；只看框住杯子容易漏掉把手反向。黄色是人工Mask，紫色是预测网格。第五张官方首选把手投影在左、原物体在右，独立QA已记录。

候选选择使用相同固定规则：32候选全部在160×120比较轮廓，前4加官方rank0在640×480复核，选轮廓重合较高的；完全相同取官方排名更高者。它使用了人工测试Mask，是自定义辅助选择。Mask重合度、官方rawscore和数值合法矩阵均不是6D准确率/GT，不能据此报告ADD或训练标签。

## 在Ubuntu重跑官方基线

以下命令在新结果目录留档；现有模型是有缺陷的候选，所以该命令只用于重现流程试跑。用户替换更可靠网格时需声明正确单位及对象坐标，保留原版本。

```bash
cd /data/ZJC/foundationPos
CUP_POSE_OUTPUT="/data/derived/cup_fp_heldout5_rerun_$(date +%Y%m%d_%H%M%S)"
bash setup/run_logged.sh --root /data/ZJC/foundationPos \
  --label cup_heldout5_official_rerun \
  --note '5 independent held-out RGB-D images; pretrained weights; defective candidate mesh; qualitative pilot, no pose GT.' \
  -- docker exec -w /workspace/FoundationPose foundationpose \
  /opt/conda/envs/my/bin/python -u \
  /data/incoming/cup_inference_helpers_20261013_2207/run_cup_mesh_inference.py \
  --repo /workspace/FoundationPose \
  --scene /data/windows_captures/cup_photos_20261013_204739_875 \
  --mask-dir /data/derived/cup_masks_test_204739_v2 \
  --qa /data/incoming/cup_complete_batch_20261013_2055/verified_payload/reports/cup_masks_test_204739_v2_final_visual_qa_ready.json \
  --mesh /data/derived/cup_reconstruction_side36_v4_20261013_2150/pipeline/textured_mesh.obj \
  --mesh-units m --output "$CUP_POSE_OUTPUT" --register-iterations 5
```

每张图片重新初始化，不调用track。推理脚本逐一核对来源SHA、K与对齐内参、16-bit毫米深度、网格单位、官方权重和有限刚性矩阵。旧结果目录拒绝覆盖。重跑后继续检查完整网格投影，不能因report passed就称准确。

## 接下来怎么推进

先解决参考配准/几何质量，再扩大检测验证。侧面与俯视的坐标原点不同，要用实际物体配准处理，不能按planned_angle硬拼；当前没有可靠GT。优先检查参考RGB-D与估计位姿的逐帧投影、杯把处深度离群及跨帧跟踪变化，并记录杯子实测高度、杯身外径与含把手总宽，作为尺度复核；不能直接将物理尺寸估计当姿态标签。

受控实验已核验：冻结表面重建的PoseArray学习率为0，跟踪/BA继续估计参考位姿，两个默认版本不改。在线及全局配置0.0实际通过，13关键帧坐标与最终网格匹配；16视图仍明显变形、把手残缺，未证明可靠改善。这一项干预不足以解决问题，不能据此认定唯一根因。其QA在 `foundationpose_data/derived/cup_mesh_local_preview_frozen_pose_v1_20261014/visual_qa_final.json`，矩阵在 `pipeline/000034/poses_after_nerf.txt`，同样是相机→物体的算法估计。重建日志的`training`是优化物体SDF/外观，与重新训练FoundationPose位姿网络不同。

独立重建进程写完文件后的退出139尚未确认原生析构根因。两个Destructor日志对应online/global两个实例，不能仅据此判断double free；没有用强制exit吞掉错误。原FP五图推理退出0，限制主要在重建质量与独立重建清理，成功与失败分别记录。

操作总记录为 `EXPERIMENT_LOG.md`，问题为 `ISSUES.md`；最新服务器说明为 `CUP_UBUNTU_RECONSTRUCTION_20261013.md`。后续新数据/新配置用新运行目录，不覆盖任何失败证据。
