# 杯子实时入口：SAM初始化分割（2026-10-15）

用户授权将当前Mask生成改为SAM。已在Windows E盘修改代码并部署Ubuntu，Ubuntu官方SAM真实GPU推理与同帧FoundationPose集成验证通过。

## 使用

Ubuntu执行（相机接Ubuntu）：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000
```
打开 `http://127.0.0.1:8765`；结束旧会话后重新运行并刷新网页。分割栏应为 `SAM ViT-B`。
冻结 → 拖框包含完整杯子和杯把 → 生成SAM Mask → 需要时选择前景点/背景点并点击 → 再生成 → 检查后确认初始化。
绿色点补杯身/杯把；红色点排除桌面或把手空隙。可撤销最后一点/清空点，最多64点。提示改变后必须重新生成。
相机和杯子保持静止，直到完成初始化进入跟踪。黄色半透明区域为物体Mask。

默认快速入口使用SAM，错误会明确返回，不静默回退。`--mask-backend grabcut` 是显式历史对照；旧 `run_cup_live.sh` 保持原GrabCut行为。

## 环境与留档

- 官方源码：https://github.com/facebookresearch/segment-anything，固定提交 `dca509fe793f601edb92606367a655c15ac00fdf`。
- 官方ViT-B权重：https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth，375042383字节；SHA256 `ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912`。HTTPS来源、下载长度及本地SHA留档；不声称作者发布了此SHA。
- Ubuntu源码在 `foundationpose_data/tools/segment-anything`；模型在 `foundationpose_data/checkpoints/sam/`，`installation.json` 记录来源、提交和SHA。
- 复用现有容器Python3.8、Torch2.0.0+cu118、torchvision0.15.1+cu118，直接加载独立源码目录，没有pip安装或升级依赖；Windows相机venv没有新增Torch。
- SAM每次Mask请求启动独立GPU进程；结束后释放SAM占用，不在逐帧跟踪中运行。容器内100秒TERM/5秒KILL限制，外层120秒超时。生成期间采集线程继续更新，用同一冻结原始RGB分割；暂停/停止会使过期结果不能初始化。
- 每次生成在 `mask_attempts/<唯一ID>` 保存 `rgb.npy`、`request.json`、`mask.png`、`result.json`、`worker.log`。输入/输出SHA核验；确认时保存选中尝试、提示点和SAM元数据到实际推理帧 `capture.json`。失败与历史候选保留。
- 所有Windows新文件位于E盘；Ubuntu产物保留其数据盘，不迁移Windows相机venv到Ubuntu。

## 已验证的范围

真实RTX3090、官方SAM权重、HTTP和FoundationPose闭环：
`foundationpose_data/live_sessions/cup_sam_verification_20261015_v1/report.json`。

- 框选SAM、框+前景/背景点SAM真实推理成功，提示点响应符合预期；改变提示生成了不同候选Mask。
- 无效坐标/标签与过期Mask版本被拒绝；最终注册的原RGB与SAM输入逐像素相同，实际注册Mask PNG与确认候选字节相同。
- 采用已有独立测试照片000004反复回放，完成60帧，数值推理失败0、深度一致性拒绝0；跟踪仍为官方2次细化。
- 本次保存图像30Hz重复回放约29.25FPS，跟踪延迟中位数45.66ms。不是现场移动相机FPS，也不是物理精度评测；没有ArUco参考，误差为空。
- SAM纯图像编码/分割约0.236–0.379秒；包含导入/加载的worker耗时约1.52–2.76秒；另一次实际图分割包含进程通信约1.93秒。GPU分配峰值约2770MiB。不保证每次现场耗时相同。
- Python AST与网页JavaScript语法检查通过；HTTP流程经过实际请求验证，未声称已完成现场用户浏览器交互验收。

最近真实会话 `cup_fast_20261015_105319_214e4f54/frames/000000` 使用同一原RGB、同一原ROI对比：GrabCut选中18745像素，SAM19600像素；数量差不代表精度。
人工查看对比图，GrabCut漏选部分黑色杯底且误选把手内部背景，SAM该帧较好地包含杯底并排除把手孔背景。没有独立真值，不能声明分割IoU或6D准确率。

Windows复核图：`E:\foundationPos\reviews\cup_sam_20261015\recent_real_mask_comparison.jpg`（左GrabCut/右SAM）。
Ubuntu完整60帧证据留在上述会话；精简证据与SHA清单归档在 `foundationpose_data/exports/cup_sam_verified_evidence_20261015`，下载后在Windows E盘按清单复核。

SAM不修复缺失深度或候选OBJ几何；Mask仍需人工检查。杯子外部轮廓、杯把及孔洞要逐帧场景确认，杯内可见表面不能仅因黑色/无深度而作为背景去掉。后续用新入口现场验证移动相机FPS与跟踪，ArUco贴好后再测误差。
