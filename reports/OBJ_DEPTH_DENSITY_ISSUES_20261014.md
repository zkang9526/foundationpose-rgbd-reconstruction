# 2026-10-14 深度有效率下降与设置恢复问题

## OBJ入口隐式切换High Accuracy：当前静态条件改善已验证

事实：前8张保留参数平均92.92%；用户转用OBJ入口后9张平均29.58%，日志确认预设High Accuracy。首/第9张黑色下沿原始深度仅22.12%/4.95%，不是只有背景缺失。

处理：OBJ默认保留参数，增加显式High Density及深度自动曝光开关。相同静态摆放每组90预热/30保存帧，对比当前27.41%、仅AE26.71%、High Accuracy+AE27.05%、High Density+AE92.18%。正式照片/录包脚本复验91.3%，完整恢复与格式通过。该设置因素在当前摆放下已验证改善；整圈/杯把/其他观察角度和真实几何精度仍待采集验收。没有依据认定相机硬件或标定损坏。

## 原来只恢复Custom枚举：恢复策略已修正，历史完整参数未确认

事实：原代码只set_option(visual_preset, 0)并读回0。该证据只证明标签，未保存或对比原高级参数。当前读取AE关闭，其历史切换时刻无法从已有照片确定。

处理：显式变更前serialize_json备份，退出load_json恢复；稳定参数逐项比较，自动曝光开启的曝光/增益允许变化。比较运行与新正式脚本复验均settings_restore_verified=true、差异为空。历史好参数没有完整快照，不能宣称恢复到了15:38那一批的配置；后续明确传High Density+AE。

## 录包wrapper不支持advanced_mode：已复验解决

事实：首个新版验证运行`20261014_155940_315505_obj_high_density_capture_validation_e71c67c4`，在变更参数前advanced_mode(recorder).is_enabled报null pointer，0张，失败目录保留。

处理：使用枚举得到的物理设备（按序列号匹配）进行高级参数备份。新目录运行`20261014_160128_038705_obj_high_density_capture_validation_retry_bb0bbf7f`完整取帧/PNG/bag回放/参数恢复通过，格式档案`20261014_160216_189341_windows_d435i_format_ca39d68d`退出0。本兼容问题在实际D435i录包模式已验证解决。

## 9张采集中断时停止报告未写完整：证据保留，bag完整性待验

事实：`20261014_154706_686904_windows_obj_photos_5db0e5a8`退出130，控制台显示9/72 retained后在pipeline.stop中KeyboardInterrupt；最后报告pipeline_stopped=false，不能改成正常完成。前一个0张OBJ运行也中断。两目录、原始PNG、bag、console和原报告均保留。

处理：将9张作为诊断数据；下一批新目录，提前退出用q回车并等待最终JSON。未验证这两个中断bag的可回放性，不标记解决；本次正常停止验证来自单独新运行，不替代原证据。
