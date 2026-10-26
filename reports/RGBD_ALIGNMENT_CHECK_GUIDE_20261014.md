# RGB与深度是否对齐：Windows叠图检查

2026-10-14 13:55纸盒检查已复核：软件取帧/内参匹配通过，但全图仅29.01%非零深度，纸盒内部手选样区约66.82%–75.91%，外轮廓周围缺失深度使绿色跳变边缘为0。本次无法验收物理对齐，需先改善原始深度覆盖并用新目录复拍；事实/条件/设置见 [纸盒复核记录](ALIGNMENT_BOX_CHECK_EXPERIMENT_20261014_135434.md)。

当前相机程序保存的是SDK对齐到彩色相机的原始深度：`rs.align(rs.stream.color)`后调用`align.process(...)`。这确认软件执行了对齐；相同分辨率/内参或程序passed不能单独证明真实边缘误差合格。[官方对齐示例](https://github.com/realsenseai/librealsense/blob/v2.55.1/wrappers/python/examples/align-depth2color.py)

## 1. 准备静止目标

使用轮廓清楚的哑光硬板/纸盒，距相机约40–60cm，背景比目标更远；不要把板平铺在同一平面的桌面上。保持板与相机静止，手退出画面，避免反光和透明目标。分别检查中央、左/右/上/下边缘位置，再检查不同工作距离。物体/尺寸/距离/光照按实际情况补充，不虚构测量条件。

## 2. 新拍并自动留档生成叠图

Windows PowerShell在项目目录执行：

```powershell
cd C:\Users\YOUR_USER\Desktop\foundationPos
$env:FP_RUN_NOTE='RGB-depth静态对齐校验板；补充实际距离/光照/位置；不作为杯子重建参考或位姿测试'
$checkDir = Join-Path $PWD.Path ('foundationpose_data\windows_captures\alignment_check_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_d435i_check.ps1 --output $checkDir --frames 60 --warmup 30
if ($LASTEXITCODE -ne 0) { throw '取帧检查失败，先保留日志排查' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_rgbd_alignment_check.ps1 -InputDirectory $checkDir
```

取帧入口保存最后一对静止RGB/原始对齐depth、内参、native深度比例和统计；叠图入口新建`reports/rgbd_alignment_<时间戳>/`，不改原图或重新对齐。采集时退出Viewer等占用相机的程序。

也支持已保存的手动照片序列，例如下列命令只读取已有独立测试第2张，保留其测试角色：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup\run_rgbd_alignment_check.ps1 -InputDirectory .\foundationpose_data\windows_captures\cup_photos_20261013_204739_875 -Frame 000001
```

## 3. 看什么、怎样判断

- `alignment_panel.png`：左RGB，中对齐深度伪彩，右在RGB上画出的绿色深度突变边缘。
- `depth_edges_on_rgb.png`：原尺寸观察目标外轮廓是否与绿色边缘贴近，有没有多张照片里重复出现、同方向的整体偏移。
- `overlay.png`：RGB和有效深度透明叠加；目标与背景的深度分界应在对应图像位置，检查是否整体平移/拉伸。
- `invalid_depth_boundaries_on_rgb.png`：橙线仅表示有效/缺失深度的交界，不能直接当几何边缘或对齐误差。
- `report.json`：记录原图SHA256、内参、深度单位、显示范围及生成条件；`physical_alignment_assessed=false`，需要人工检查，不自动给出标定合格结论。

绿色线默认来自相邻有效像素间大于20mm的深度跳变；**20mm是提取深度边缘的阈值，不是允许的RGB/Depth对齐偏差**。必要时用`-JumpMm 10`查看较小的深度分界。没有绿线可能是两侧深度相近或缺失，不表示自动通过/失败。

颜色/文字/贴纸边缘可能只是纹理变化，不应该强求它们都有深度边缘。真实遮挡、深度孔洞和不同光学中心的可见性差异也会影响边缘；应使用多个位置的静态清楚轮廓复核，不能把任意黑洞直接判成标定故障。[官方投影与对齐说明](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)

若中央与边缘、多个位置和距离都出现重复稳定的轮廓偏移，先核对同名RGB/depth、时间戳、保存单位、使用彩色/对齐K以及是否裁剪或缩放；保留原始数据，再决定是否需要物理标定。SDK原生bag尚未对齐，不能与已对齐PNG混用。更完整的标定与配准区分见 [既有相机校验说明](CUP_CAMERA_CALIBRATION_GUIDE_20261014.md)。

## 本次已有示例与范围

已只读生成杯子独立测试`000001`叠图：绿色深度边缘（原始附件未随公开快照提供）、透明叠图（原始附件未随公开快照提供）。运行`20261014_134626_483182_rgbd_alignment_visual_check_29000438`退出0；640×480、保存单位0.001m/值、记录的彩色和对齐内参一致。

杯子示例绿色深度边缘稀疏，未据此给出整圈轮廓/物理标定合格判定。墙面格式示例同样通过文件读取，但没有大于20mm的深度跳变，不能验收目标外轮廓。新增工具支持单对检查目录和照片序列；原始参考/独立测试角色、旧K、深度和位姿均保持。

本次没有重新拍摄校验板、修改标定/SDK/固件或执行重建。工具和结果在Windows留档，后续与相应数据批次打包；物理精度仍需上述静态目标检查。
