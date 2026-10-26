### 2026-10-17 Viewer校准报错保留，标定暂停而非解决

- 用户截图只有Calibration Failed/Invalid Value/hwmon command 0x80(8 2 0 8)与截断response，完整设备响应未知，不能据此归类低有效像素或硬件故障。
- Viewer虽Responding=True但关闭主窗口后未退出，按用户转采集的指令，仅停止已验证项目可执行路径的PID172，相机释放。截图与process证据存reports/capture_preparation_20261017_183027_975。
- 用户明确暂停相机验证；双IR纵向偏差、厂商health和物理RGB-D边界精度仍未验收，不标记解决，不阻止已授权的新实验性采集。
- 之前Mask可能有分割偏差，本轮改为用户采后逐张人工确认；仍需分别检查原始深度和重建质量，人工Mask不作为相机校准或可靠6D GT。
