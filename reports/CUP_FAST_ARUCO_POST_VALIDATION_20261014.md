# 2026-10-14 加速/ArUco入口追加复验

- Ubuntu直连真实D435i（serial238222071455、USB3.2），640×480 RGB/depth各30FPS，warmup30后检查30个唯一配对帧通过；按配对收到间隔统计29.993FPS。原始RGB与对齐深度的完整内参字典相同，零畸变系数。报告 `CUP_FAST_ARUCO_CAMERA_PREFLIGHT_20261014.json`，原始末帧数据仍在Ubuntu `foundationpose_data/camera_checks/fast_bridge_preflight_20261014_2331`。这是硬件采集复验，不是新版位姿推理FPS/实物精度结论。
- 最终新版180帧回放后，自动汇总正常完成，`summary_status.json`为exit_code0/passedtrue；180次尝试、无推理失败、无深度一致性拒绝、721份输入文件SHA256复核通过。因保存场景没有ArUco，参考覆盖率0，所有误差为空，未生成虚假精度。
- 原始PNG实时入口再次GPU/HTTP复验通过，5帧，冻结/Mask/初始化/跟踪/暂停/重新初始化/推理中停止以及最后响应记录均通过；pip check通过。日志 `cup_live_legacy_regression_20261014_2328`。
- 已存在的原生foundationpose环境执行matplotlib导出通过；没有安装或修改推理依赖。图像经过人工查看，无码误差面板明确提示无有效配对，延迟曲线包含初始化耗时而非隐藏异常。E盘产物：`E:\foundationPos_data\derived\cup_live_fast_summary_plot_v1_20261014_2330\errors_and_latency.png`；Ubuntu同名derived目录保留原产物。
- E盘保留前两次完整回放和控制测试、最终回放的紧凑报告/自动汇总；最后一次完整NPY原始像素保留Ubuntu。实际贴码、固定杯子移动相机实验尚待采集；绝对码→原始OBJ独立标定尚不存在。
