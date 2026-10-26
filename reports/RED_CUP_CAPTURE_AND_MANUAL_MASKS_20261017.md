# 2026-10-17 新红色杯口采集与人工Mask

用户明确决定暂停相机参数验证，先使用当前SDK参数重新采集杯子，并希望采完后自己逐张标注或修正Mask。本阶段执行采集及标注工具准备，不将未完成的相机标定、实体边缘对齐或几何精度标记通过，也不继续自动运行校准或写设备标定。

## 当前采集

- Windows项目 `E:\foundationPos`，数据新批次 `E:\foundationPos_data\windows_captures\obj_side_20261017_183122_148`，与10月14日黑色杯口旧批次分开。
- 72张侧面圈、计划5°，固定相机，手动旋转杯子，松手退出并停稳，回车后继续读取新帧1秒再保存。计划角度不是实测姿态或6D真值。
- 640×480/30FPS，SDK对齐到RGB；保存原始未补洞的毫米uint16深度PNG、RGB、K、SDK原生深度内外参、帧号/时间戳和metadata；原生bag包含等待和转动，用于保留原始流证据。
- 明确High Density与深度AE，按既有入口备份并在结束时恢复采集选项；没有替换标定表。E盘启动时剩余约104.18GiB，既有存储保护低于2GiB停止并保留已有数据。
- 用户追问是否调参数后，按metadata/备份实际核对：visual preset从Custom=0改为High Density=4；深度AE启动前已为True，本轮显式确认保持1；emitter=1、laser power=150、当时曝光8500/增益16。没有启用派生滤波/补洞。此前“按现有参数”表述不精确，实际保留当前标定、沿用既有High Density采集方案；已向用户说明。备份 `camera_settings_before.json` SHA `b12ea3618e97a62f341e78f02ae4f340ebc818b164dea55de90535d7c1af3432`，当前未结束不能提前宣称恢复通过。
- 启动窗口PID15812；run `20261017_183122_309483_windows_obj_photos_6bd3210f`。启动后90对预热完成，最初为0/72等待手动回车，不能把启动成功记为采满/质量通过。
- 用户后续明确确认“杯子倒扣，已摆好”；实际光照强度/材质计量未给出，不编造。该确认晚于启动，追加在本报告/人工日志中，不修改运行中的metadata或启动时备注。先保存第一张检查构图。每圈中途不翻面，第二圈更高观察方向单独目录；正放/倒扣等明显变化也单独保存并独立处理。

## Viewer失败与切换任务证据

用户之前给出的裁切图显示Calibration Failed、Invalid Value in rs2_run_on_chip_calibration及hwmon command 0x80(8 2 0 8) failed，后续response被裁切。不能从此断言是低有效深度、固件故障或硬件损坏。失败图已复制到 `reports/capture_preparation_20261017_183027_975` 并保存SHA。

项目Viewer PID172 Responding=True；先CloseMainWindow请求，未退出后仅终止已核验路径的这一个Viewer进程，相机占用释放。没有删历史数据、重试校准或写标定。记录run `20261017_183025_985372_red_cup_capture_preparation_a3382c92`，preparation.json保留进程身份和操作。

新启动入口 `setup/launch_red_cup_photos.ps1`沿用既有 `start_obj_photos.ps1`。启动准备/执行分别通过logger保存，报告 `reports/RED_CUP_CAPTURE_LAUNCH_20261017_183121_196.json`。既有命令仍可使用。

## 采完由用户标注

每张采集RGB需要对应同尺寸、同编号8-bit单通道二值PNG，背景0、杯子255。原RGB/depth保持只读，标注新目录独立保存；每次修订留版本、RGB/depth/Mask SHA、编辑动作和人工确认，不能覆盖旧自动候选或把自动Mask当人工确认。

杯身、杯把、可见内壁属于前景；桌面、手和把手空隙为背景。杯口中看见的杯底/内壁是物体，看穿到背景才是背景；不能整块挖掉杯口。深度为0的可见杯子也保留前景，Mask不替代深度有效率检查。人工Mask能减少分割偏差，但不能补回缺失深度、纠正相机参数或解决所有配准/重建失败。

本机人工标注页已准备，完整命令及版本规则见 `MANUAL_CUP_MASKS.md`。支持从零画前景/背景孔、画笔橡皮、撤销、缩放、逐帧预览和确认；最终预览由服务端按保存算法生成，保存校验同一PNG的SHA，拒绝空Mask。每次确认独立修订，导出最新确认副本。先采集，完成后按目标范围、原始深度和视角覆盖检查，之后逐张标注，再打包至Ubuntu，不提前上传半成品或混用旧批次Mask。

工具验证：`foundationpose_data/verification/manual_mask_editor_20261017_v2/report.json`的24项合成HTTP/文件系统检查通过（run `20261017_183359_658280_manual_mask_editor_synthetic_http_smoke_fb817d70`）；前景孔/笔刷、预览与实际PNG SHA一致、并发冲突、旧版本不变、原图只读和重启恢复均验证。v1因测试客户端发送超大请求时被提前断连而失败，保留，v2改为头部验证服务器读取前拒绝。嵌入JS通过Node语法检查，`foundationpose_data/verification/manual_mask_editor_js_20261017_v1`，run `20261017_183425_160132_manual_mask_editor_javascript_syntax_c1afbefe`。这些不是实际杯子人工分割验收，当前尚未启动8767真实标注服务。

本轮倒扣不能覆盖贴桌杯口/内壁；后续需独立正放或倾斜批次才有机会覆盖红色杯口，不能把侧面圈采满当完整几何覆盖。
