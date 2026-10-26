## 2026-10-13 Windows杯子参考照片、分割与深度准备

- 用户选择固定D435i、手动旋转倒扣杯、停稳手退出后保存RGB-D；无CAD，先重建再用官方权重，不重训杯子位姿网络。尺寸/材质尚未由用户补充。Ubuntu主动断开期间本阶段未执行SSH、未修改服务器环境。
- 新核实18:53 `cup_photos_20261013_185306_528` 是真正的36张斜俯视圈；18:36 `cup_photos_20261013_183611_673` 仍属侧面。两组时序审核36/36通过、独立帧号递增、按键后等待至少1秒，最大RGB-D时间差约10.899/9.898ms。证据 `cup_photos_timing_185306_review.json`、`cup_photos_timing_183611_review.json`。
- 16:58侧面与18:53斜俯视共72张作为初轮参考，各组独立保存。175220也是完整侧面，但仅抽查未验收为独立测试。165440/183447/183539各1/36中断，保留且不误报完整；原285对试采保留。
- `setup/make_cup_masks_grabcut.py` 使用人工图像空间杯身种子/轮廓、杯把孔背景种子和局部小洞修补。V1/V2与中间候选虽可退出0，视觉质量不足已拒收；失败和中断重试均保留。新增几何合并与逐帧可追溯接口，不从planned_angle生成外参或位姿。
- 最终侧面 `foundationpose_data/derived/cup_masks_side_165803_v4`、斜俯视 `cup_masks_top_185306_v5` 各36张已逐原RGB/overlay验收，SHA匹配。仅首轮重建视觉验收、非Mask或位姿GT；轮廓1–3px、接触处2–4px不确定性保留。QA见 `cup_masks_side_165803_v4_final_visual_qa.json`、`cup_masks_top_185306_v5_final_visual_qa.json`。
- 生成运行：侧面 `20261013_202033_643098_cup_side_165803_mask_v4_full_25876346`，斜俯视 `20261013_202203_030001_cup_top_185306_mask_v5_full_d26c1d65`；均退出0、36帧，视觉验收另存而非改写生成报告的候选状态。
- `20261013_202846_048188_cup_mask_depth_outlier_review_4b671c21` 完成72帧原始深度距离审计。侧面掩码非零81.02%、>1500mm像素4.44%；俯视80.11%、0.22%。杯身核心近距离较多，杯把较弱，仍需网格复验；不当传感器精度。
- `20261013_203218_579109_cup_reference_range_filtered_inputs_328112ac` 独立派生毫米深度：Mask内300–800mm保留原值、其他写0、不插值；RGB/Mask原样复制，原始图像/深度不改。72帧PNG保存复读及来源SHA核验通过，平均整Mask保留深度侧面76.49%、俯视79.84%。目录 `foundationpose_data/derived/cup_reference_inputs_range300_800_v1`，逐帧报告在该目录 `report.json`。
- `20261013_203406_430871_cup_reference_package_readiness_5aa9f83e` 重新核验72帧原始/Mask/派生来源与文件SHA，报告 `reports/cup_reference_package_readiness_20261013.json`。后续本地ZIP包含数据、全部分割版本、报告与已结束运行证据；打包结果另有独立run及整包SHA。不在Windows日志快照上覆盖服务器日志。
- 新操作说明 `CUP_NEXT_STEPS_20261013.md` 已写6张独立检测测试照片建议与留档命令，修正为现有脚本实际支持的 `-Views 6`（角度参数不接受0）。参考整圈无需重复；独立测试和物理尺寸尚未确认。
- 下一阶段：补独立测试 → 完整批次打包并在Ubuntu恢复连接后校验/追加导入 → 验证BundleSDF重建依赖 → 独立序列跟踪/重建及跨序列物体配准 → 保存估计参考位姿与网格 → 官方权重杯子推理。尚无杯子网格、参考位姿或推理；未声称完整复现或GT精度。
