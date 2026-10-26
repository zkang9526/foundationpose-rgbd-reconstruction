# 失跟后自动找回与SAM2首帧评估（2026-10-15）

用户选择目标回到画面后自动找回并继续跟踪。本期独立分支 `fix/reacquisition-sam2-eval`，保留main/ubuntu原基线，不合并。

## 行为与使用

Ubuntu `/data/ZJC/foundationPos` 已部署；运行：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000 --auto-reacquire
```
页面 `http://127.0.0.1:8765`。首次仍冻结、框选、人工确认完整杯子Mask；目标失跟后自动搜索，无需再人工框选。
目标返回时请短暂停稳。搜索、注册和3帧确认完成之前隐藏有效位姿；没有候选或存在歧义时继续等待。
默认首帧仍为SAM ViT-B，首帧SAM2试用追加 `--mask-backend sam2`；禁用自动找回追加 `--no-auto-reacquire`。旧 `run_cup_live.sh` 保留原行为。

恢复流程：深度或初始目标颜色不一致→停止沿用位姿→SAM2全图Mask候选→首次确认目标的颜色/深度尺度筛选→冻结帧光流检查→FoundationPose全局注册→Mask/深度验收→连续3新帧确认→继续跟踪。
不使用上次杯子ROI作为全图搜索位置限制，也不使用旧姿态作为新注册起点。epoch检查阻止跨初始化周期的跟踪请求。
候选Mask相似且处于分离位置时拒绝选择。该功能是杯子外观/尺度匹配，不是语义检测器，不保证区分同色同尺寸的另一只杯子。

## 检查发现与处理

- 原代码register已清空 `pose_last`，没有证据支持“忘记清空旧姿态”是根因。
- 旧入口没有自动检测/重获目标；普通track只局部细化，依靠深度一致性可能漏检背景漂移。新增初始颜色一致性检查，失跟后全图搜索并重新注册。
- 旧冻结图检查仅用RGB中位差，历史重初始化首帧延迟约9.65秒且RGB差18.33仍可接受；这是检查偏弱的证据，不能从此单独推断当时位姿误差。新增目标内LK双向光流检查，无法确认新鲜度时拒绝。
- 旧注册只选择官方分数top1，且宽松深度检查不验证完整轮廓。新增前8候选的Mask重合与深度检查，保留官方top1和全部8候选；自定义选择单独标记。IoU≥0.65、precision/recall≥0.72为当前启发式，非物理精度或概率。
- 页面不再将被拒绝姿态作为有效结果显示，恢复后需3帧连续检查；当前FPS按连续跟踪分段统计，排除搜索/暂停/注册间隔。所有原始帧事件仍保留。

## 验证结果与范围

所有GPU测试均使用原RTX3090、原FoundationPose源码固定提交及官方权重、原候选OBJ。没有重新训练，也没有现场GT。

| 验证 | 结果 | 证据 |
|---|---|---|
| 原普通跟踪回归 | 180帧完成，失败/质量拒绝0；回放约27.19FPS | AUTO_RECOVERY_TRACKING_REGRESSION_20261015.json |
| 合成目标消失6秒，再横移100px返回 | 全图自动找回；75帧，1个故意的缺失帧被拒绝；无人工重初始化 | AUTO_RECOVERY_SHIFT_VERIFICATION_20261015.json |
| 目标消失后切换真实蓝桌垫场景的杯子RGB-D | 全图找回，重新注册和3帧确认；75帧，无人工重初始化 | AUTO_RECOVERY_REAL_VIEW_VERIFICATION_20261015.json |
| 最终检查与日志版本复验真实返回画面 | 75帧，数值失败0，缺失帧拒绝1，3次搜索；连续回放约27.68FPS | AUTO_RECOVERY_FINAL_VERIFICATION_20261015.json |
| SAM2首帧框+前/背景提示，经HTTP初始化 | 60帧通过，0失败/拒绝；过期Mask版本拒绝；输入RGB和确认Mask一致 | SAM2_FIRST_FRAME_VERIFICATION_20261015.json |
| 错误颜色、歧义目标、冻结画面30px变化 | 均拒绝；相同帧通过 | 自动找回验证报告pure_checks |

横移合成测试Mask质心偏移约-100.25px，这是2D测试定位检查，不是6D真值。
真实返回画面为历史 `cup_fast_20261015_105319_214e4f54/frames/000678`，首次参考使用独立000004照片；消失段仍为明确合成均匀背景，不是连续实际遮挡视频。
两个恢复测试中自定义候选选择均仍选官方rank0；注册Mesh/Mask重合约0.867/0.869，不能称6D准确率。
搜索加注册需要数秒，目标返回后持续快速移动会被新鲜度检查拒绝。没有宣称立即重获、现场恢复成功率或毫米/角度精度通过。
最后增加SAM2源码提交匹配的失败前置检查；对应源码实际提交和installation.json一致，之前成功的图像/GPU路径保持相同。

## SAM与SAM2首帧对照建议

使用5张独立测试照片和2张历史真实初始化RGB，7张图各运行SAM ViT-B与SAM2.1 Hiera Tiny一次；同原图、同ROI、无提示点。精确统计在 `SAM_SAM2_COMPARISON_SUMMARY_20261015.json`。

两者Mask相互IoU约0.96–0.98，视觉检查杯身、黑色底部和杯把总体相似。相互一致性不是与人工GT的IoU，不比较跨模型预测IoU作为准确率。
本机测得SAM图像编码/分割中位约225ms、整次调用约1.82秒；SAM2约336ms、整次调用约2.17秒。SAM2峰值PyTorch分配显存约557MiB，SAM约2770MiB。不同软件环境和精度、单次运行的小样本，不是统一硬件优化基准，也不是视频FPS。

建议当前首帧继续默认SAM；SAM2首帧可选，但没有观察到足以直接替换默认值的准确度收益。采用SAM2作为本分支重获的候选Mask生成器，并用后续几何/深度/连续帧检查验收。官方SAM2支持图像提示和视频分割；本期只接图像预测及全图候选，没有启用视频传播或声称SAM2可独立保证离场后的同一物体识别。官方说明：https://github.com/facebookresearch/sam2 。

## 环境、数据和回溯

SAM2独立环境 `foundationpose_data/environments/sam2`，Python3.11、Torch2.5.1+cu121、torchvision0.20.1+cu121；继承现有原生环境的兼容依赖及CUDA库目录，依赖快照归档。原生环境仍Torch2.4.1+cu121/torchvision0.19.1+cu121，FoundationPose容器仍Torch2.0.0+cu118/torchvision0.15.1+cu118，相机venv没有Torch。
SAM2固定提交 `2b90b9f5ceec907a1c18123530e92e794ad901a4`；权重156008466字节，SHA256 `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`，来源和库路径见 `checkpoints/sam2/installation.json`。模型SHA来自实际HTTPS下载，未声称作者发布此SHA。可选CUDA扩展未构建，未启用填孔以保留把手空隙。
每次搜索保留无损RGB、原深度、时间戳、候选NPZ、JSON提示/筛选/结果、SHA和日志；`recovery_events.jsonl` 记录搜索及消费检查。注册保留 `official_top1_pose.txt` 与 `registration_candidates.json`。
完整原始验证会话位于Ubuntu `foundationpose_data/derived/`，均新目录；精简带SHA证据包为 `foundationpose_data/exports/reacquisition_verified_evidence_20261015`，Windows副本位于 `E:\foundationPos\reviews\reacquisition_verified_evidence_20261015`。报告和脚本进入实验分支Git；权重/环境/原始数据不进入Git。

杯口网格缺陷、深度缺失、杯把朝向歧义、未被启发式察觉的失跟仍可能影响结果；这些未标记解决。下一步按上述入口现场进行目标出画/返回、遮挡、转动及干扰物测试，并用固定ArUco协议评测误差。
