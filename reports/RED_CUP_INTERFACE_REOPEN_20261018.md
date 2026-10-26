# 2026-10-18 Viewer预览后开启FoundationPose接口

用户明确要求开启FoundationPose接口。已在Ubuntu启动新的真实D435i会话并验证HTTP状态为`waiting_for_roi`，相机已连接、GPU模型已就绪，新OBJ SHA匹配；向Ubuntu当前桌面浏览器发送打开页面请求。**本阶段只开启交互接口，没有复用之前视角的Mask，也未代替用户进行这次初始化。**

- 页面：Ubuntu本机 `http://127.0.0.1:8765`，打开或刷新。
- 操作：保持相机和杯子静止 → 冻结 → 框选完整杯身及杯把 → 生成SAM2 Mask → 检查杯把孔隙、前景/背景 → 确认初始化。结果出现、状态进入跟踪后再移动相机。
- 本轮会话：`/data/ZJC/foundationPos/foundationpose_data/live_sessions/redcup72_live_20261018_after_viewer_01`；60分钟或10000个处理帧上限，可从页面停止保存。
- 仍用新`redcup72`米制OBJ，SHA256 `88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53`，首帧SAM2.1 Hiera Tiny、自动重获、ID6/DICT_5X5_50/30mm固定杯码协议。
- 启动检查时旧接口已停止，已安装Viewer进程也已退出，故无需发送终止信号。本轮未停止其他用户程序。若该Viewer仍在运行，交接器只对同用户且可执行路径精确匹配的项目Viewer发送SIGTERM，等待退出后再启动相机；不强制终止。
- 新HTTP状态抽样时完成0帧、失败0帧、姿态为空，符合等待人工新Mask状态。ArUco当时仍未识别，不能将接口就绪当作参考或6D精度通过。
- 启动器、浏览器输出和运行回执在`foundationpose_data/derived/redcup72_live_20261018_after_viewer_01_launch`。Windows回执`E:\foundationPos\reports\redcup72_interface_20261018_after_viewer_01\interface_ready.json`，数据与原成功/失败记录保留。
- Windowsrun：`20261018_161613_066080_redcup_interface_after_viewer_7a38a063`；Ubuntu交接run：`20261018_161615_030183_redcup_live_interface_handoff_c2df83d8`。实际相机/worker还各自通过原有记录器留档。

没有新安装、校准、固件更新、网格改动或权重变更。后续的实测FPS和误差以本轮实际初始化/跟踪后保存的同帧数据为准。
