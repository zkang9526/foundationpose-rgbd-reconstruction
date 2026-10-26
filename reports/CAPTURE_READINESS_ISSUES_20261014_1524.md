# 当前试拍预热等帧超时：待复验

- 事实：`20261014_152458_179497_windows_d435i_check_d69654aa`识别设备且pipeline_started=true，在warmup的pipeline.wait_for_frames超时；warmup_frames=0、acquired_frames=0，pipeline_stopped=true，退出1。产物目录`foundationpose_data/windows_captures/capture_readiness_20261014_152457_584/`只保存失败报告，没有新图。
- 推测：Viewer/其它相机程序并用设备等可能原因待确认，不能由超时断言硬件损坏、标定失效或当前目标深度不合格。
- 处理：保留原run及console/report，复读字段并确认管线已停止；请用户确认/关闭Viewer后单独取帧，等待状态确认期间不重复打开相机。
- 复验：待使用新run/新输出目录重试并取得当前目标图像。13:55旧纸盒图不替代当前角度/条件验收；旧深度空洞及RGB-depth物理对齐结论不标记解决。
