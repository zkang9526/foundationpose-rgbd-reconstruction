# D435i 棋盘格内外参与 RGB-D 对齐验证

2026-10-17最新结果：硬板独立批次29组静态视角完成，采样条件满足；双IR约1.13px纵向偏差跨算法/新快照重复，厂商常规health绝对值0.9045在需要校准档，另一扫描因有效深度不足失败。RAM候选短IR对照后已显式恢复原表，Flash未变；不替换内参、不开始新Mesh采集。实体边界测试仍因裁切/支撑条件不足未验收，见[硬板最终复核](REVIEW_RIGID_BOARD_20261017.md)。

本文件夹独立于杯子数据。Windows：`E:\foundationPos\camera_calibration`；Ubuntu：`/data/ZJC/foundationPos/camera_calibration`。

2026-10-17 16:14：用户确认硬板固定后已启动独立新批次`windows_20261017_161416_850`，页面仍8766；固定后横竖5格100mm也已再次确认。当前采样进度与动作说明见[硬板批次记录](RIGID_BOARD_SESSION_20261017.md)。旧纸质批次不混入。

2026-10-17实测定位：开启投射器时的密集亮散斑使当前SB检测器在IR上失败；独立关闭投射器对照三路均检出，新鲜静态试次已接收。现阶段棋盘几何验证使用下面的`-EmitterMode off`，生产开启投射器的深度/实体边缘另验；详情见[散斑识别排查与处理](SCATTER_FIX_20261017.md)。

用户于2026-10-17明确确认：**7×12个方格，6×11个内角点，每格2 cm**，配置在 `board.json`。这是之前12×7方格规格的转置方向，旧会话保留各自拍摄时的配置，不改写。当前相机连接Windows；此前真实采样不足，内外参与物理对齐精度仍待验收。

本期38次试拍/26组接收已结束，用户确认尚未固定硬板；横向覆盖不足，未拟合新参数。下一轮先固定纸张到平整硬板，再采独立批次，见[本批最终复核](REVIEW_PAPER_BATCH_20261017.md)。

## Windows 实测

1. 将D435i接到Windows的USB3接口，关闭其他占用相机的Viewer/采集程序。相机固定在支架上，棋盘格平整固定在哑光硬板上，避免折痕、气泡和边缘翘起；不要用手弯折单张纸模拟板面倾角。可用平整木板或硬泡沫板，均匀固定纸张；只贴一角不能保证纸面完全贴合。用户已报告横竖5格实测均100mm，固定后再复核格距，记录测量条件，不假定尺子无误差。
2. 在PowerShell执行（此命令显式关闭投射器用于棋盘几何采集）：

   ```powershell
   cd E:\foundationPos
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\camera_calibration\run_windows.ps1 -EmitterMode off
   ```

3. 出现 `Calibration page` 后打开 **http://127.0.0.1:8766**。上排左边RGB、中间对齐深度、右边绿色深度跳变；下排是IR1/IR2预览。棋盘应在三个相机视场内完整可见。采集分辨率为640×480、30 FPS，与现有生产入口一致。绿色20 mm是显示阈值，不是精度合格线。
4. 拍25–35张**不同姿态**：画面中央及四周、约0.4–0.8 m可清晰成像的远近位置、左右与上下倾斜。始终让完整棋盘同时出现在RGB和红外视场；不要只平移或只正对相机。可以固定相机移动整块硬板，也可以固定硬板、换相机观察方向并在每次拍摄前把相机支撑放稳。移动相机后转动镜头看向棋盘，才会改变板面相对朝向；只平移且保持朝向不变不能替代倾角变化。还需让棋盘中心出现在RGB不同位置，始终居中会缺少画面覆盖。
5. 每个位置停稳，点击“倒计时3秒后保存一组”，在倒计时及检测期间保持不动，等接收数`accepted`增加后再移动。程序在倒计时结束时选择新RGB-D，不使用点击瞬间的旧帧；自动检查帧龄、完整角点、RGB/红外时间戳域与间隔，以及至少0.3秒内的光流位移。既有0.75 px静止门限保持不变。拒绝的照片和原因也保留。累计25–35张接收成功的不同姿态，不能用保存次数代替接收数。
6. 棋盘内外参验证后，另在生产的投射器开启状态测3–5个实体板边界。保存照片后点击“标注上次照片的板外轮廓”，在静态RGB照片上顺时针点实体板最外面的4个角，再保存。板离背景至少5 cm；不要标打印图案边缘或内角点。输出各边的像素偏移、匹配率、缺失/歧义计数和叠图。不同传感器遮挡可能造成局部轮廓差异，应结合多姿态判断；不以关闭投射器时的缺失率代替生产状态表现。
7. 点击“完成采集并停止”。相机释放后自动分析，控制台显示 `REPORT.md` 路径。默认30分钟自动结束。需要停止时优先用页面按钮。

延时可通过`-CaptureDelaySeconds 5`改为5秒。倒计时期间点击停止会取消本次待拍，取消事件留档，不计为有效照片。板与背景的间隔是本项目边界测试的建议条件；边界遮挡和采样不足需要在结果中单列。

`-EmitterMode off/on/preserve`仅临时改变`emitter_enabled`，默认仍preserve以兼容旧命令。采集前备份、采集中实际值、正常退出/异常清理时恢复和读回结果分别保存；不会写入设备标定。关闭投射器时缺乏纹理的背景可能出现深度空洞，不据此判相机损坏。仅这一开关的恢复经过核对，不宣称其他选项也做了独立恢复测试。

这次杯口原黑色区域已涂红，后续需要独立静态试拍并标出杯口ROI，测原始有效深度比例、噪声和跨帧稳定性；仅凭RGB颜色改变不能认定红外深度改善。棋盘验证完成后再开始新的重建批次。

默认同时保存RGB、原生深度、对齐深度、IR1/IR2的无损NPY和PNG。RGB NPY是RGB顺序；PNG是标准彩色编码。深度为原生uint16单位，**必须乘当次 `factory.json` 的 `depth_scale_m`**，0是无效深度。深度不做平滑、时间滤波或补洞。

单张连接/对齐试拍（不接受为多视图标定数据）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\camera_calibration\run_windows.ps1 -Action snapshot
```

重新分析已经采集的会话（每次新建结果目录）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\camera_calibration\run_windows.ps1 -Action analyze -InputDirectory 'E:\foundationPos\camera_calibration\sessions\实际会话目录'
```

## 结果如何判读

|检查|实际测量|限制|
|---|---|---|
|RGB与IR内参|独立训练视角拟合K/畸变；每第五个有效视角留作验证，比较原厂/候选重投影误差和焦距变化|单平面姿态可吸收部分误差；必须有双轴倾角、远近和画面覆盖，板平整度/格距也影响结果|
|IR1→RGB、IR1→IR2外参|原厂跨传感器投影；固定原厂K拟合候选外参，在验证集比较像素残差及旋转/平移差|拟合外参也可能吸收内参偏差；候选不是精确真值|
|原生深度|分别与IR1、RGB棋盘格PnP估计平面比较Z偏差、尺度比、法向差和深度自身平面残差|是几何一致性，非独立测距仪GT；不把RGB-D对齐图的Z直接当RGB相机Z|
|软件RGB-D对齐|实际调用SDK align，检查对齐深度的分辨率/内参是否与RGB匹配|这不能单独证明真实边缘对齐精度|
|实体板外轮廓对齐|人工静态RGB轮廓与深度阶跃偏移；逐边报告匹配率/缺失样本|黑白格的纹理线没有深度台阶；遮挡、反光和无效深度不是自动标定失败|

最少20张有效照片才拟合候选；推荐25–35张。采样检查条件为：中心横向跨度≥160 px、纵向≥120 px；法向两个轴变化各≥15°；表观线性尺寸比≥1.4。**这些是本工具的采样诊断条件，不是厂家精度容差**。不自动把重投影小或程序退出0标记为精度通过，需结合验证集、图像和测量条件解释。

这里的外参主要指D435i传感器之间的刚体关系，以及每张照片的板→相机位姿。相机→机器人/世界或手眼标定还需要对应的独立参考观测。

## 保存结构与留档

```text
camera_calibration/
  board.json                    # 用户给定棋盘参数
  sessions/windows_时间/        # 原始采集；每次新目录
    factory.json                # 序列号、固件、K/畸变、刚体外参、深度尺度、选项
    K_color.txt / K_native_depth.txt
    source/                     # 本次实际代码和配置快照
    session.json / events.jsonl  # 成功/失败/中断、人工控制
    trials/0001/                # 原始NPY/PNG、角点、时间戳、SHA、接收/拒绝原因
    boundary_checks/            # 人工外轮廓、偏移统计、叠图；原始试次保持不变
  results/                      # 每次独立分析；REPORT.md/report.json/per_view.csv
  preflight/                    # 当前设备检查及Ubuntu原始试拍的E盘副本
  verification/                 # 数学/流程合成验证，不能作为实测精度
```

两端入口都使用现有 `setup/run_logged.py`，全局执行档案仍按项目约定追加在 `foundationpose_data/runs/`；通过标签 `checkerboard_` 定位。Windows入口继承现有E盘TEMP/缓存策略，不安装/升级环境。大数据不进Git；源代码、说明、配置和阶段报告进Git。上述棋盘capture/analyze入口不改设备标定，历史数据K不改写；拟合的内外参仅保存在新报告中。

独立厂商诊断工具`check_onchip_health.py`会生成on-chip候选。厂商过程可能留下临时活动标定，因此先备份表，finally显式恢复原表到RAM；不写Flash。health第二个零在SDK2.55.1绑定中是占位值，不能作“校准后通过”。`evaluate_onchip_ram.py`仅对已留档候选做原/候选/原表的临时RAM切换与最小双IR对照，原表SHA必须匹配当前Flash；最终恢复并复测。Flash表SHA一致、RAM恢复命令成功、图像行为复验分别记录，不能互相替代；完整depth/实体边界精度仍需独立验证。实际使用条件、失败及当前状态见最终复核，不在低有效深度场景盲目重复扫描。

每次采集和分析都另外保存当次 `source/` 及 `source_manifest.json`，用于核验实际执行版本。

Ubuntu可复用：

```bash
cd /data/ZJC/foundationPos
bash camera_calibration/run_ubuntu.sh capture
# Ubuntu本机浏览器 http://127.0.0.1:8766
bash camera_calibration/run_ubuntu.sh analyze camera_calibration/sessions/实际会话目录
```

文件传回Windows前可在源端执行 `verify_evidence.py --input 会话目录 --create`，传输后在目标端执行 `verify_evidence.py --input 副本目录`。两步都通过当地记录器执行；manifest逐文件校验，不覆盖另一端总日志。

方法依据：[RealSense 投影和坐标系](https://dev.realsenseai.com/docs/projection-in-realsense-sdk-2-0/)、[RealSense 对齐与遮挡](https://dev.realsenseai.com/docs/projection-texture-mapping-and-occlusion-with-intel-realsense-depth-cameras/)、[OpenCV 标定/立体标定](https://docs.opencv.org/4.x/d9/d0c/group__calib3d.html)。
