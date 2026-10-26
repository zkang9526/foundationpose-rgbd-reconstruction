# 2026-10-14：杯子原始深度有效率约30%的排查与修正

后续状态更新：用户因C盘不足明确要求删除刚采批次、转E盘重采。本文所述15:46/15:47两个OBJ原始目录已于16:14删除，原日志/参数/时间戳、文件清单和诊断派生图保留；“原始数据保留”描述属于清理前状态。新采集默认E盘，实际操作见 [E盘迁移记录](WINDOWS_E_DRIVE_CAPTURE_20261014.md)。

已确认本次入口强制High Accuracy，是当前深度稀疏的主要设置因素。静态对比中，仅打开深度自动曝光没有明显改善；High Density与自动曝光组合让整图原始非零深度从约27%提高到92.18%。正式照片脚本新参数复验为91.3%，16-bit毫米PNG、独立滤波输出、bag回放和完整参数恢复均通过。本阶段不验收物理深度精度、完整目标覆盖、配准或实物OBJ。

## 原始采集事实

- `foundationpose_data/windows_captures/obj_side_20261014_154706_548`保存9/72张，平均整图原始非零深度29.58%；第9张为31.1%。实际命令包含`--depth-preset high-accuracy --record-bag --save-filtered-depth`，预设读取为3/High Accuracy。
- `depth valid`此前的分母是整幅640×480图，不是目标Mask面积，也不是深度准确率。现在控制台明确显示`raw depth valid (whole image)`。
- 已查看9张RGB及原始深度。杯子完整、杯把缓慢变化，原始杯身/黑色下沿有明显空洞；不能只归因于背景。
- 人工小矩形：杯身核心`[267,315,324,355)`，黑色下沿`[268,387,324,400)`，可见倒扣杯底中心`[275,275,313,285)`。首张非零深度分别78.20%、22.12%、0%；第9张74.82%、4.95%、0%。小矩形不是全杯Mask。
- 新批次前的8张`cup_photos_20261014_153854_799`使用`device-default`保留设置，平均整图92.92%，原始杯身抽样99.66–100%、黑色下沿90.52–100%；其角度标签不是实测角度。
- 两次`obj_side_20261014_154627_286`和`obj_side_20261014_154706_548`均保留。前者0张，后者9张；运行档案标记中断，后者退出130。console显示在`pipeline.stop()`中再次收到KeyboardInterrupt，最后留下的报告未确认pipeline正常停止；本批bag完整性尚未验收，不覆盖其记录或宣称正常结束。

2026-10-14 15:55只读探测：D435i序列号238222071455、USB3.2；Custom=0，深度AE=0、曝光8500µs、增益16、发射器开启、激光功率150。读取值属于当前时刻，不反推之前每张照片的曝光。当前完整参数已保存为`OBJ_DEPTH30_CURRENT_SETTINGS_20261014_1555_advanced_settings.json`，SHA256 `401696d74f1980cce911766d2cabab16ea825343879b910239fc08af954dc441`。

## 同一静态场景的有界对比

D435i固定，当前倒扣杯子/桌面/墙面可见，无手；每组640×480@30、预热90对、保存30对RGB与未滤波原始深度。没有改变标定、固件、距离或人为光照。RGB检查显示目标仍在上述矩形区域内。每组开始加载本次备份，比较结束恢复备份并核对稳定参数；自动曝光运行时变化的彩色曝光/增益读数排除于恢复比较。

| 设置 | 整图非零深度均值 | 杯身核心 | 黑色下沿核心 | 可见杯底中心 |
| --- | ---: | ---: | ---: | ---: |
| 当前Custom参数，深度AE关闭 | 27.41% | 84.45% | 27.88% | 0% |
| 当前参数，深度AE开启 | 26.71% | 84.47% | 28.21% | 0% |
| High Accuracy，深度AE开启 | 27.05% | 83.43% | 26.42% | 0% |
| High Density，深度AE开启 | 92.18% | 100% | 99.98% | 84.39% |

对比档案`20261014_155753_559045_obj_depth30_static_preset_comparison_a3cab1b9`退出0；报告位于`foundationpose_data/windows_captures/depth_density_ab_20261014_1557/report.json`，`original_settings_restored=true`、`restore_differences=[]`、`pipeline_stopped=true`。这些是不同时间依次采集的静态场景，不是同一帧重处理，不保证全视角都有相同填充率。High Density保留更多测量点，仍需按原始目标深度检查边缘、异常点和几何；补洞不会产生新的测量。

[官方调参说明](https://dev.realsenseai.com/docs/tuning-depth-cameras-for-best-performance/)明确：High Accuracy筛选标准更严格，通常深度更稀疏；High Density改善填充率。自动曝光也是需要检查的因素，但本次单独开启AE并未改善密度，因此不能把这次主要原因归给AE关闭。

## 修改及真实脚本复验

- `setup/start_obj_photos.ps1`默认`-DepthPreset device-default`，保留相机当前参数；显式支持`high-accuracy`和`high-density`，另有`-DepthAutoExposure`。`device-default`名称表示不切换，并不恢复出厂或过去的好参数。
- `setup/capture_d435i_photos.py`传递相应参数，明确整图原始深度比例。`depth/`仍是对齐到RGB的uint16毫米原始深度，`depth_filtered/`独立保存。
- 修正`setup/realsense_capture_options.py`：切换预设或开启AE前保存`camera_settings_before.json`及哈希；退出时加载实际完整参数并比对稳定字段。此前只恢复枚举0/Custom，没有证据证明恢复了原来的高级参数，历史“恢复预设0”仅指标签读回，不能当完整参数恢复验收。
- 第一次正式脚本复验失败且保存：`obj_high_density_validation_20261014_1600`、运行`20261014_155940_315505_obj_high_density_capture_validation_e71c67c4`。SDK录包设备包装对象不能转换为advanced_mode，报`null pointer ... dev`；未切换设置、未保存照片。已修正为通过按序列号枚举的真实设备备份参数。
- 新目录复验：`obj_high_density_validation_retry_20261014_1601/single_photo`，运行`20261014_160128_038705_obj_high_density_capture_validation_retry_bb0bbf7f`退出0。自动触发1张静态照片，整图原始有效深度91.3%，时间戳差16.13ms；High Density=4、深度AE=1，原始/派生PNG可读，bag原生RGB/depth回放通过，完整参数恢复核对通过，相机正常停止。
- 格式档案`20261014_160216_189341_windows_d435i_format_ca39d68d`：1对，16-bit毫米深度，退出0。
- 最终帮助入口档案`20261014_160215_910019_obj_depth_preset_final_help_7f11ac12`退出0。

## 下一批采集

测试结束相机恢复了本次对比前的设置。**下一批明确指定以下两个参数，不能只运行保留当前设置的默认命令：**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5 -DepthPreset high-density -DepthAutoExposure -RecordBag -FilteredDepth
```

先确认前几张杯身、黑色下沿和杯把原始深度仍可用；每次小步旋转、停稳、手退出后回车，等Saved后再转。AngleStep是计划备注，不测量或控制旋转。需要提前停止时输入`q`再回车，等待最终JSON和正常停止，避免退出时重复中断。新目录拍摄，9张稀疏原始数据留作诊断，不混入首轮正式参考重建。bag持续记录等待和旋转、体积增长较快；原始PNG足以留存选出的静态对，bag和滤波均为显式可选项。

完整侧面圈、俯视和被支撑面遮挡的部分仍需分别采集/检查；92%整图不能替代目标Mask、物理对齐/尺寸精度、跨视角配准或网格QA。诊断照片不自动归入正式参考。此次仅Windows排查与留档，没有SSH上传或修改Ubuntu环境。

## 证据入口

- 9张原始深度联系表（原始附件未随公开快照提供）
- High Density原始深度预览（原始附件未随公开快照提供）：仅生成预览，非物理标定验收。
- 原始样区统计（原始附件未随公开快照提供）
- 当前设置读取（原始附件未随公开快照提供）
- [本阶段问题记录](OBJ_DEPTH_DENSITY_ISSUES_20261014.md)
