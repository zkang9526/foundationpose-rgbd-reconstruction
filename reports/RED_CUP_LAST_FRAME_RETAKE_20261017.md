# 2026-10-17 仅重采最后一帧

用户完成 `E:\foundationPos_data\windows_captures\obj_side_20261017_184953_656` 的72张，并明确最后一帧采错、仅重采最后一帧。检查原RGB可见000071有人物头部/手遮挡，000070无此遮挡。随后用户确认相机未移动、倒扣杯子已恢复到最后应有位置并停稳；计划355°只是目标标签，不是实测旋转。

## 本轮结果与后续使用目录

**后续人工Mask和重建输入使用修正版：**
`E:\foundationPos_data\windows_captures\obj_side_20261017_184953_656_corrected_last_190116`

- 总数72对，前71对RGB/depth复制后逐文件SHA完全一致，仅000071对应的一对换为新采集。
- 原72张目录保持原样，错误000071、原metadata/时间戳及原bag完整保留，没有删除/覆盖失败证据。
- 补拍独立会话 `E:\foundationPos_data\windows_captures\cup_retake_last_20261017_190116_590714`，只采1对，新会话本地编号000000，在修正版映射为000071。新会话打印的计划0°是本地单帧入口默认值，修正版保留原序列计划355°并记录映射，不将任一角度当实测/GT。
- 用户确认停稳后自动向既有采集入口发送一次请求；90对预热+1秒继续读新帧，独立bag保留新原始流。没有重新拍前71张。
- 新帧无人物/手遮挡；RGB-depth时差9.6914ms、整图原始非零深度84.3421%。原错误帧整图25.7939%；该比例不是目标区域精度或相机标定验收。
- 原/新设备序号、RGB/原生深度/对齐深度内参、原生depth→RGB外参、K、保存单位均一致。采集实际选项均Custom0、AE1、emitter1、laser150、当时exposure8500/gain16；补拍保持当前设置，没有切预设、改曝光或校准。
- 两个真实采集会话均结束释放相机。修正版是文件选择派生序列，原始bag不拼接；metadata/时间戳明确各帧来源、不同会话的帧计数/局部host时间。原/补拍metadata与CSV另存provenance，不伪造连续录制或连续帧号。

## 留档与验证

- 补拍run `20261017_190115_122210_red_cup_last_frame_retake_e47cad27`，retake_request.json包含用户条件和原错误帧/原metadata SHA。
- 组合run `20261017_190253_750873_red_cup_single_retake_compose_3e9c5588`；工具 `setup/compose_rgbd_retake.py`，验证来源、设备/参数兼容、图像格式、前71对与原始数据SHA不变。
- 修正版格式检查72对通过，run `20261017_190317_316894_windows_d435i_format_6e400d5d`。
- 完整162文件transfer_manifest逐文件SHA通过，run `20261017_190317_031026_red_cup_corrected_sequence_manifest_verify_e39b7f72`。
- 修正版 replacement_manifest.json逐张列实际来源与SHA，记录原错误RGB/depth路径；current引用见 `reports/RED_CUP_CURRENT_REFERENCE.json`。

本轮只处理最后一帧，未作整圈目标深度/覆盖/几何QA，也未生成或确认Mask。下一步由用户按 `MANUAL_CUP_MASKS.md` 对修正版72张人工标注；旧空批次183122不作为本轮数据。
