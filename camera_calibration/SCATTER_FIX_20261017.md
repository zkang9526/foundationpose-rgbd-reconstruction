# 2026-10-17 棋盘IR散斑识别排查与临时投射器模式

用户确认已拍3组，横竖连续5格实测均100mm。检查实际记录发现接收数为0；用户继续试拍后原会话最终13组/0接收。不能将“已保存”视为“已接受”。当前处理解决了实拍角点识别阻断，尚未验收相机物理内外参精度。

## 原始证据和诊断

原会话`camera_calibration/sessions/windows_20261017_153107_486`完整保留并通过页面停止。0001、0002 RGB原生SB均检出66角点，IR1/IR2均未检出；IR中密集亮散斑覆盖棋盘。0003 RGB右侧棋盘裁切，三路原生检测未全通过。全会话RGB检出11/13，IR1/IR2检出0/13；最后143个原图/深度等文件SHA校验通过。没有改旧接受标记、没有拿拒绝帧拟合标定。

独立离线诊断固定0001–0003：6路IR原始SB全失败，经典角点检测原图全检出66点，Gaussian9灰度后SB也全检出；转置11×6没有改善IR。0003 RGB在这些方法下仍失败，符合图像裁切。支持当前SB对投射纹理不鲁棒，而非棋盘规格错误；候选检测未独立验证定位精度，不能提升旧拒绝帧为有效样本。原始深度未滤波。

诊断：`diagnostics/checkerboard_3trial_detection_20261017_a`（README、完整JSON和角点对比图）；run `20261017_154237_395715_checkerboard_detection_diagnostics_06a2a8e8`。主代理首次复核时现场又增加第4组，所以`results/review_first_three_20261017_v1`实际覆盖4组；停止后最终全13组复核在`results/review_scatter_session_20261017_final`，run `20261017_154607_500666_checkerboard_scatter_session_final_review_c5117e67`。

## 处理与实机复验

保持原SB、原0.75px静止门限、原20ms时间戳门限。新增显式`--emitter-mode preserve/off/on`，Windows对应`-EmitterMode`；默认preserve保持旧命令兼容。只临时设置`emitter_enabled`，保存` sensor_settings_before.json`、采集时factory中的实际值、恢复读回和事件。恢复失败返回非零。未刷写出厂内外参，没有修改激光功率、预设或深度滤波。

1. 独立快照` sessions/windows_20261017_154610_604`，run `20261017_154610_757903_checkerboard_snapshot_6189b7d9`：RGB、IR1、IR2原生SB全部检出66点。设置实测before=1→active=0→restore=1，verified=true；其余所记录选项值不变。快照明示不纳入多视图标定。
2. 新正式会话` sessions/windows_20261017_154720_168`，http://127.0.0.1:8766 ，run见`launches/windows_20261017_154719_884/stdout.txt`；启动器完整成功，先前哈希辅助错误未再出现。此会话off只做棋盘几何，结束时恢复原开关。
3. 为检查实际采样路径，新会话自动触发一组新照片0001，并按真实检查接收：三路66角点，光流P95约0.413px，14份图/深度文件SHA通过。请求run `20261017_154816_628853_checkerboard_projector_off_first_fresh_trial_ce350fbb`，复核run `20261017_154843_889304_checkerboard_projector_off_first_trial_review_5daabac8`，结果`results/review_projector_off_first_trial_20261017_v1`。

4. 报告范围检查run `20261017_155223_126827_checkerboard_off_mode_report_scope_check_348d6b96`运行时用户继续采集，因此该报告实际使用5个有效视角，并非运行备注所说的单组；输入清单/逐帧结果真实保留，未拟合候选。报告明确保存emitter=0和生产深度尚未验收。前5组法向两个轴跨度仅3.70°/1.77°，中心跨度29.91×68.08px、表观尺度比1.133，提醒用户增加整板双轴倾斜/位置/距离。此处采样阈值是本工具诊断条件，不是厂家精度容差。

这组RGB原厂PnP重投影RMS约1.390px，IR1→RGB约2.735px；估计板中心Z约0.311m。原生深度板ROI有效约82%，相对IR/RGB估计平面的Z差中位约−5.73/−7.42mm，深度自身平面RMS约1.70mm。**单视角且投射器关闭，不代表生产深度误差，更不等于绝对标定精度通过。**建议稍退到0.45–0.7m、整板留边，采用平整硬板并覆盖多姿态再判断。

## 后续采样与范围

刷新同一页面，累计25–35组accepted，再用页面停止。覆盖中央和四周、远近、左右和上下倾角；将整块板绕水平/竖直方向倾斜，单纯横竖转向不能替代法向倾角变化。结束自动留出每第五个有效视角验证原厂与候选。物理精度不由程序成功或接收数单独判定。

之后在生产开启投射器的设置下另做原始深度/平面/实体板边缘及涂红杯口ROI检查。analyze报告现在保存输入实际投射器设置，关闭时明确提示不能替代生产on深度QA。手动Action analyze的日志也明确是离线无相机变更，避免默认preserve备注混淆输入off模式。

棋盘配置已追加用户横竖5格100mm的尺测陈述，未编造尺子精度或板平整度。旧会话保留各自拍摄时配置。临时开关正常退出/异常清理恢复有实机证据；恢复核验仅针对emitter_enabled，不宣称强杀或拔线也能执行清理。

依据：[RealSense投射器用于添加匹配纹理](https://dev.realsenseai.com/docs/projectors/)、[有纹理场景的被动双目深度](https://dev.realsenseai.com/docs/tuning-depth-cameras-for-best-performance/)。投射器关闭不改变读取的出厂内外参，但会改变深度可用性与噪声，故分开报告采集条件。
