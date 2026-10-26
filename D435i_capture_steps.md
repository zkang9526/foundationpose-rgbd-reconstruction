# 自有物体的下一步：试拍与多视角采集

目前 D435i 的 SDK、USB 权限和 RGB-D 采集已通过检查。接下来先准备一个物体，检查它在相机中的深度质量，再录制一段连续多视角数据。

连续采集脚本已部署到 Ubuntu；实际短测以 30 FPS 取流、约 10 FPS 保存，成功得到 30 对 RGB 与毫米单位的 16-bit 深度 PNG，文件配对、位深、内参和单位检查全部通过。

后续执行过程按 [复现操作与留档指南](REPRODUCTION_GUIDE.md) 保存。相机检查、采集和格式检查启动脚本已自动记录命令、输出、退出码与结果路径；总体进度和问题分别记录在 `EXPERIMENT_LOG.md`、`ISSUES.md`。

## 1. 摆放物体

1. 选择一个不透明、刚性、表面有纹理或标签的物体。首轮可以用手边的带标签塑料瓶；目标物体也可以是其他物品。
2. 单独放在平整、不反光的桌面，移开遮挡它的线缆和杂物，让物体与背景容易区分。
3. D435i 先距离物体约 0.4–0.8 米，略微俯拍；调整距离和角度，使物体完整、清楚地出现在画面中。这是起始试拍建议，实际以目标区域的深度质量为准。
4. 使用均匀光照，先让物体和相机都保持静止。相机继续接 Ubuntu 的 USB 3.x 接口。

曝光、距离和表面条件会影响深度质量，可参考 [RealSense 官方调优说明](https://dev.realsenseai.com/docs/tuning-depth-cameras-for-best-performance/)。

## 2. 先拍一组检查图

在 Ubuntu 宿主机执行：

```bash
ssh USER@UBUNTU_HOST
bash /data/ZJC/foundationPos/setup/run_d435i_check.sh \
  --output /data/ZJC/foundationPos/foundationpose_data/object_preview \
  --frames 60 --warmup 30
```

此阶段让物体与相机静止。完成后查看 `rgb.png` 和 `depth_preview_color.png`：

- RGB 中物体完整、清楚，主要表面未被手或其他物品遮挡。
- 深度预览中目标表面大部分有颜色，大块黑色区域表示缺少深度。
- 重点检查目标区域；整个画面的非零深度比例不能替代目标区域质量检查。

需要在 Windows 查看时，另开一个 Windows PowerShell 执行：

```powershell
scp -r USER@UBUNTU_HOST:/data/ZJC/foundationPos/foundationpose_data/object_preview C:\Users\YOUR_USER\Desktop\foundationPos\reports\
```

然后打开 `reports\object_preview\rgb.png` 和 `depth_preview_color.png`。也可以摆好物体后告诉我，我来远程拍摄并检查。

## 3. 质量合格后录制一段多视角序列

保持物体不动，准备手持相机缓慢绕拍。执行以下命令后，会先预热再进行 5 秒倒计时：

```bash
bash /data/ZJC/foundationPos/setup/run_d435i_capture.sh \
  --output /data/ZJC/foundationPos/foundationpose_data/my_object_$(date +%Y%m%d_%H%M%S) \
  --seconds 30 --save-fps 10 --countdown 5
```

终端出现 `Capturing` 后开始移动相机：

1. 从正面开始，缓慢经过一侧、背面和另一侧，始终对准同一个物体。
2. 保持相邻画面有大量重叠，移动平缓，避免突然改变视角或让物体离开画面。
3. 略微俯拍以覆盖顶部；此轮重点覆盖四周和顶部，桌面遮住的底部需要后续补采与处理。
4. 录制到结束提示后停止移动。30 秒、保存 10 FPS 是首轮试采参数，预计约 300 对图片，实际以报告为准；它不保证重建模型完整。

如果已有转台，也可以固定相机、让物体在转台上缓慢转动。

## 4. 输出与后续工作

```text
my_object_YYYYMMDD_HHMMSS/
├── rgb/                 # 000000.png、000001.png…
├── depth/               # 同名 uint16 PNG，单位毫米
├── cam_K.txt            # 对齐后的彩色相机内参
├── K.txt                # 同一份内参，供其他工具使用
├── depth_scale.txt      # 保存的深度值乘 0.001 得米
├── metadata.json        # 设备、原生比例、逐帧时间与质量统计
├── timestamps.csv
├── timestamps.json
└── report.json          # 采集结果与实际保存速率
```

脚本将原生深度通过 SDK 的实际比例换算为毫米，保留原生比例于元数据；RGB 与深度文件名一一对应。它会拒绝覆盖已有序列，可使用新的时间戳目录重采。

可以检查保存后的文件格式，在 Ubuntu 宿主机执行并替换为实际序列目录：

```bash
bash /data/ZJC/foundationPos/setup/run_d435i_format_check.sh \
  /data/ZJC/foundationPos/foundationpose_data/my_object_YYYYMMDD_HHMMSS
```

采集完成后还需生成目标分割 `masks/`，检查视角和深度，再配置重建流程。当前 BundleSDF 公开的自定义数据代码逐帧读取目标 Mask，需提供同名掩码序列，或另外接入在线分割传播程序；只有一张首帧 Mask 不能直接保证该公开流程可运行。[官方数据格式](https://github.com/NVlabs/BundleSDF#run-on-your-custom-data)、[分割实现](https://github.com/NVlabs/BundleSDF/blob/master/segmentation_utils.py)

本次新工具完成的是数据采集与文件验证；自有物体的分割、网格重建及位姿推理将在拿到合格的目标序列后继续。
