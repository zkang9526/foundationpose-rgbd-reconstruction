# 2026-10-14：清理近期采集并改为E盘重采

用户明确要求：新结果保存E盘，删除刚才采集的文件，迁移储存位置后重新采集。本次只清理三次近期OBJ侧面采集；历史日志、参数、时间戳、问题证据和更早的参考数据保留。原始数据删除由此次用户指令授权，不把删除目录伪记为完成或正常停止。

## 空间与清理结果

清理前读取C盘可用21,151,744字节（约20.17 MiB），E盘186,782,400,512字节（约173.95 GiB）。最新C盘批次`obj_side_20261014_160527_974`由用户q退出，保存22/72张、平均原始整图深度91.64%，pipeline_stopped和完整参数恢复已确认，属于未拍满序列。

已核对各绝对路径属于Windows项目的`foundationpose_data/windows_captures`，拒绝reparse point和仍被采集进程使用的目标，通过原生PowerShell删除：

| 删除目录 | 字节数 | 原采集记录 |
| --- | ---: | --- |
| obj_side_20261014_154627_286 | 1,343,466,610 | 0张、中断 |
| obj_side_20261014_154706_548 | 7,878,917,437 | 9张、中断、稀疏深度 |
| obj_side_20261014_160527_974 | 10,283,022,260 | 22/72张、q正常停止、未完成 |

共释放18.17 GiB；复读C盘可用19,561,615,360字节（约18.22 GiB）。这三个目录已不存在，`.bag`和原始PNG确实删除，不保留副本。删除前保存元数据/时间戳/内参/设置，以及逐文件大小、非bag文件SHA256；大bag删除前不新增哈希。所有原运行目录和已有深度预览仍保留。

清理档案：`20261014_161407_809775_windows_clear_recent_obj_captures_c7b13369`退出0；证据：deletion_manifest.json（原始附件未随公开快照提供）。原先深度诊断文档的“9张保留”是清理前状态，本记录明确更新其当前位置为原图已删、元数据和诊断结果保留。

## 当前储存设置

`setup/windows_capture_storage.json`的`capture_root`已持久设为：

```text
E:\foundationPos_data\windows_captures
```

`start_obj_photos.ps1`、`start_cup_photos.ps1`和`start_cup_trial.ps1`默认读取同一配置。新批次RGB、原始深度、独立滤波深度、bag、内参、时间戳、设置备份和采集报告都在E盘。项目代码、`.windows-camera-venv`和体积较小的`foundationpose_data/runs`运行档案/总日志继续留在原Windows项目；Ubuntu目录没有改变，没有SSH或上传。

OBJ/手动照片入口可以用`-CaptureRoot`显式覆盖配置，旧命令仍可用；`-DryRun`可检查OBJ目的地且不启动相机。低层`run_d435i_*.ps1 --output ...`仍以调用者显式路径为准。照片脚本新增2 GiB剩余空间保护：启动前及采集期间每秒检查，低于阈值按错误流程正常收尾并保留已有照片；本次验证了正常空间的检查，未人为填满硬盘触发阈值。

## E盘实测与重新启动

E盘静态自动单张验证位于`E:\foundationPos_data\storage_validation_20261014_1617\single_photo`，原始整图深度92.7%。运行`20261014_161619_582057_e_drive_rgbd_storage_validation_4a72022d`退出0：High Density+深度AE，原始/派生16-bit PNG读写、原生bag回放、完整参数恢复、相机停止通过。这是存储验证照片，不是正式多视角参考。

已通过交互前台PowerShell重新启动72位置侧面采集（用户需要手动旋转、停稳、回车），参数为High Density、深度AE、bag、独立滤波，计划5°仅作备注。启动档案`20261014_161654_869609_e_drive_manual_recapture_launch_8c6636ea`退出0，窗口进程PID22332。**启动后已读取实际新目录、90对预热和Photo 1/72提示，确认相机运行并等待用户回车，尚未宣称72张采集完成。**

- 新目录：`E:\foundationPos_data\windows_captures\obj_side_20261014_161656_953`。
- 实际采集档案：`20261014_161657_076437_windows_obj_photos_b268c84a`。
- 启动记录：E_DRIVE_RECAPTURE_LAUNCH_20261014_161656_316.json（原始附件未随公开快照提供）。

复用启动命令：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\start_obj_photos.ps1 -Ring side -Views 72 -AngleStep 5 -DepthPreset high-density -DepthAutoExposure -RecordBag -FilteredDepth
```

勿在当前采集未退出时再运行第二个相机采集。小步旋转、停稳且手退出后回车，Saved之后再转；提前退出用q回车并等待最终JSON。原生bag包含持续等待/运动，仍会在E盘持续增长，2 GiB保护避免再次耗尽整个盘。

## 后续批次传输

现有`package_cup_offline.py`只遍历项目根目录下的采集树，未自动纳入E盘外部目录。采完后先显式纳入E盘新批次及C盘执行证据，生成安全目录映射/包和SHA256，再上传Ubuntu新暂存目录，追加唯一run_id。不能直接把旧打包命令的成功当成包含了本次E盘数据；这一适配待正式采集完成时执行。
