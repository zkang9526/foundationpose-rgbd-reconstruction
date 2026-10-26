## 2026-10-13 改为固定相机手动转杯、停稳逐张拍照

- 用户明确选择手动旋转杯子、停稳后拍照。更新AGENTS.md、WINDOWS_CAPTURE_UBUNTU.md及旧试采说明，当前优先手动入口，不连接Ubuntu，全部采好后统一打包。
- 新工具 setup/capture_d435i_photos.py、setup/start_cup_photos.ps1，复用旧采集的设备信息、内参和毫米转换函数；默认36位置、计划10度、预热90对、回车后1秒。后台读取终端输入，主线程持续对齐排帧；只保存时间域一致、差<=30ms、帧号新于触发基线和上张的RGB-D对。计划角度非测量值，不当位姿真值。
- 编译、Python帮助、PowerShell帮助通过，运行档案为20261013_163058_013197_windows_photos_compile_2b8f9572、20261013_163058_014197_windows_photos_python_help_825edc02、20261013_163058_189670_windows_photos_entry_help_a6e9156d。
- 新入口加入run_logged.py源快照名单。真实单照片验收使用start_cup_photos.ps1 -Views 1 -AngleStep 10，采集档案20261013_163353_839204_windows_d435i_photos_8f464aa9；通过终端发送一次Enter、1秒后存同一组RGB-D，timestamp gap 9.296ms，pipeline停止成功。等待输入时读取1050次，采集1对，完整36位置尚未执行。
- 自动格式检查20261013_163439_659657_windows_d435i_format_3592c762退出0，1对毫米16-bit PNG/内参/单位配对通过。测试目录foundationpose_data/windows_captures/cup_photos_20261013_163353_632/。
- 真实测试RGB已查看，杯子偏左且左/底边裁切；该数据为功能验收照片，不作为完整目标重建参考。下一步用户先调整目标完整居中，再按每约10度停稳、手退出后Enter拍一圈。
- 操作说明CUP_MANUAL_PHOTOS.md。新拍照模式q/EOF/中断设计保留partial并passfalse，但尚未做独立真实停止验收；不编造验证结果。逐帧Mask、完整重建和杯子位姿尚未执行。
