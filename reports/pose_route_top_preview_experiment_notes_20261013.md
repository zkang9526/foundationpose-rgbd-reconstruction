## 2026-10-13 位姿/训练路线确认及俯视预览验收

- 用户询问是否必须记录物体位姿再训练，并明确选择先用官方预训练权重跑通杯子位姿估计。当前无CAD先重建网格、再用官方refiner/scorer推理，不新增杯子位姿网络训练任务。仍需估计并保存参考姿态/对象坐标系；算法估计值与GT分开标记。
- 官方核查：固定版本README说明新物体无需重训；model-free run_nerf.py读取cam_in_ob的4x4参考位姿，论文基准带GT参考姿态、附录允许真实应用从视频估计姿态；BundleSDF可联合物体跟踪与重建。监督训练/定量评测如另行开展需真值方案。具体来源和解释保存于POSE_AND_TRAINING_GUIDE.md。
- 新俯视预览cup_photos_20261013_172657_962只有1对。用户重复粘贴终端文本对应同一文件，不计两轮采集。原capture档案20261013_172658_075821_windows_d435i_photos_db5211b0，原format档案20261013_172728_793075_windows_d435i_format_6bd45ded。
- RGB已查看，杯子/把手完整、没有手遮挡，朝上的杯底及把手上缘可见，俯角较大使可见侧面面积减少。保持摆放姿态采补充参考组，新旧组后续需要物体位姿估计/配准，不能依靠计划转角直接拼接。
- 原始深度区域验收20261013_173609_205807_cup_top_preview_raw_depth_review_19f01888，报告reports/cup_top_preview_quality_20261013_172657.json：杯底内部矩形100%非零，绿色局部88.9%；下部小矩形52.5%非零且正读数混合，可能边界/支撑底座影响但原因未验证，不当全杯或暗色质量结论。
- 该组RGBDepth时间差9.268ms、按Enter后1秒保存，采集和format通过、pipeline停止；整图84.3%非零不当目标比例。保留原始9文件SHA清单/699219字节，档案20261013_174731_213986_cup_top_preview_original_sha256_f0e2bd69。
- 离线分割依赖已检查并留档：camera venv无cv2，全局C:/python/python311无cv2/np/Pillow，C:/anaconda/python.exe实际导入cv2/np/Pillow通过。未安装/改变任何环境、未生成Mask；README旧make_init_mask.py及starter.zip不在本地，不能当现成入口。
- 更新AGENTS/REPRODUCTION_GUIDE路线。下一步固定本俯视角手转停稳采36位置，后续完整Mask、估计参考位姿/重建、网格质量及官方权重推理。尚未启动本俯视整圈或任何杯子训练/推理，仍Windows本地保存、不连Ubuntu。
