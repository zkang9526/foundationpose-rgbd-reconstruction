# 2026-10-18 初始化页面停滞与杯把朝向修正

本阶段仍在 `fix/reacquisition-sam2-eval` 实验分支，不合并 main。源数据、官方权重和新旧 OBJ 均保留；未标记绝对位姿或精确几何验收通过。

## 页面“初始化后没有反应”

旧页面实际停在“初始化中/0帧”，后端已经跟踪1573帧，单独的ArUco状态还在变化。`load()`重复使用同一个Image并覆盖onload，冻结操作与轮询交叠会让早先Promise永远不返回，`refresh.busy`因此持续为true。修正为独立Image、最新请求序号、加载期限、图像请求背压；状态刷新不等待图片，状态请求超时后显示断连并重试。开始初始化/跟踪时清除旧Mask控件，控制版本阻止旧轮询覆盖新操作。

`verify_cup_dashboard_image_race.py`用真实页面JS复现旧问题，并验证修正后的交叠加载、无图片完成时状态更新、断连恢复、清除旧控件。既有会话切换回归通过。一次测试Mock把带AbortSignal的GET误判为POST，失败档案保留，修正Mock后通过。最终HTML SHA256：`883bd2a84fa1bb1f64ba5dea4c6feacf55cacb04558d758090f278ce17ecd64c`。重启后的真实页面已观察到跟踪帧数、FPS和叠图更新。

## 杯把问题来源

旧会话 `redcup72_live_20261018_after_viewer_01` 首帧SAM2 Mask包含完整可见杯把和把手空隙，Mask8647像素，非零深度76.78%。实际模型杯把却投在杯身正面；后续真实杯把换到画面另一侧，估计朝向仍滞留。杯身近似旋转对称、现有全物体轮廓/深度检查主要受杯身支配，不能仅因一致性检查通过就判定杯把或6D正确。不是本轮首帧Mask漏掉杯把所致；模型本身杯把连接和噪声问题仍在。

旧会话用户确认移动过杯子或码，二者相对位置变化，原自动ArUco误差不得作为跟踪漂移或物理精度。原结果仍保留，不与下一轮混算。

## 可选初始化朝向检查

`cup_handle_yaw.py`只在初始化时检查绕已知模型Z轴的36个朝向，使用原始Mask突出区域覆盖、整物体轮廓和原始深度门限选择候选。仅允许SHA为`88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53`的redcup72模型；普通实时入口默认关闭。`run_cup_live_redcup72.sh`实验入口启用；追加`--no-cup-yaw-init`可对照。

实际旧首帧GPU对照：原候选IoU0.8664、突出区域覆盖0；新候选IoU0.8973、覆盖0.9336，候选朝向相差-100°。这不是实测真值误差。保留`official_top1_pose.txt`、原`registration_candidates.json`，新增`registration_yaw_candidates.json`；自定义输出不能冒称未修改官方top1。

真实GPU worker在同一保存RGB-D上执行1次注册+24次跟踪，25帧全成功、退出0；最后相对新初始化变化2.34mm/9.52°，说明还存在后续跟踪变化，不能视为精度或移动测试通过。修正后新真实会话首帧从原IoU0.8596提高到0.9049，突出区域覆盖0.8131；实际移动效果另见[相机移动评估](RED_CUP_CAMERA_MOTION_REVIEW_20261018.md)。

## 产物与执行证据

- Windows：`reports/redcup_handle_pose_review_20261018/`、`redcup_handle_yaw_comparison_20261018/`、`redcup_handle_worker_check_20261018/`、`dashboard_image_race_protocol_final_20261018/`。
- Ubuntu：`foundationpose_data/derived/redcup72_live_20261018_after_viewer_01_handle_review/`、`_yaw_comparison/`、`_yaw_worker_check/`；旧源备份在对应`_launch/before_handle_fix/`。
- 旧问题复现run：`20261018_163106_351072_dashboard_old_image_race_reproduction_2611cd4e`；GPU验证run：`20261018_163920_770569_redcup_actual_gpu_yaw_worker_check_6fb88958`；安装run：`20261018_164421_910454_redcup_install_tested_handle_dashboard_fix_de0ae423`。
- 更新命令均经记录器；不升级FoundationPose、SAM2、相机SDK或设备固件。本次仅源代码/说明变化，不改变厂商标定。

以后若只测试跟踪、杯码可以相对移动，追加`--no-aruco-fixed-scene`；页面明确显示不计算固定场景误差。若评测相机移动的相对漂移，杯码必须保持相对固定。所有指标均不是独立绝对GT。
