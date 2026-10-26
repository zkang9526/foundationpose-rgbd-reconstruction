# 2026-10-18 新杯子模型实时FoundationPose初跑

## 已验证范围

用户已将D435i连接Ubuntu，并确认杯子、码固定，相机停稳。Ubuntu识别D435i `238222071455`，USB3.2，RTX3090可用，无其他相机进程占用。数据盘约88.15GiB可用。无需安装或升级环境。

新模型首次SAM2初始化及真实相机跟踪已完成；尚无有效ArUco参考，不能据此评价绝对精度或移动相机时的漂移。当前模型几何仍为未验收候选。

## 入口与模型选择

Ubuntu执行：

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

页面：`http://127.0.0.1:8765`（Ubuntu本机浏览器）。若已有会话，不应再启动占用相机的第二个实例；使用已有页面。

此专用入口选择`--mesh-profile redcup72 --mask-backend sam2 --auto-reacquire`，并沿用已确认的`DICT_5X5_50`、ID6、30mm黑边测量和固定杯码评测协议。SAM2只在首帧/重获分割时运行。

- 新模型：`foundationpose_data/derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj`，SHA256 `88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53`，米制、顶点RGB。
- 旧模型可显式使用`bash setup/run_cup_live_fast.sh --mesh-profile legacy ...`。通用快/旧入口默认仍为legacy，以保持旧命令行为。新旧OBJ都未修改、缩放或覆盖。
- 两入口均通过共享`cup_mesh_selection.py`在访问相机前检查所选文件必须位于项目数据根目录内，且SHA与固定配置一致。会话记录profile/path/SHA/米制及几何未验收状态，GPU worker使用所选模型，而非原先固定的旧模型常量。
- 两端旧入口源码SHA完全一致后才安装；原Ubuntu源码备份于`foundationpose_data/derived/redcup72_live_20261018_first_launch/previous_setup`。冻结新源码、安装前后SHA、启动命令和PID均保存。
- Ubuntu实际新旧模型选择、篡改网格拒绝、Bash语法及CLI参数检查通过。未改官方FoundationPose算法、权重、CUDA、相机标定表或原始标注。

## 首段现场结果

会话：`/data/ZJC/foundationPos/foundationpose_data/live_sessions/redcup72_live_20261018_first`。

- 初次15帧预检杯子约100像素高，未识别ID6。用户随后反馈调整停稳；实际冻结帧仍是相近构图，不能仅依据回复认定码达到建议像素尺寸。
- 首帧框`[254,148,130,125]`，SAM2前景点覆盖青色杯身、红色区域、杯把；背景点覆盖杯把空隙与周围背景。助手检查黄色轮廓完整包含杯身/杯把且排除真实孔隙后执行初始化，不冒充用户逐像素标注或Mask GT。框、提示点、原冻结RGB、Mask、候选ID、控制记录均保留。
- 首帧Mask8689像素，Mask内原始非零深度69.88%；注册推理约2.224秒。同冻结RGB-D、原RGB/深度/时间戳原样保存。初始化前图像/光流变化检查通过。
- 暂停前1178份完成事件，推理成功1178/1178；1177份被接纳用于跟踪，最后一份在暂停改变状态版本后归档，不能将其误报为物理质量拒绝。GUI取样时连续跟踪23.74FPS，失败0、质量拒绝0。
- 初步叠图中杯身及杯把投影大致贴合，仍有边沿/杯把几何残差。大绿框是模型包围盒，不应要求框线贴住物体表面；洋红色为网格投影轮廓。本轮仅检查可用性，不以视觉对上证明6D精度。
- 1174个连续确认姿态相对首个确认估计（000003）：平移变化中位1.883mm、P95 3.610mm、最大4.825mm；旋转变化中位1.949°、P95 4.158°、最大7.118°。它们只在相机和杯子实际保持不动的条件下可解释为静止重复性/估计变化，初始偏差会被消去，**不是实物位姿误差**。
- 输入到结果延迟中位58.50ms，P95 75.03ms，属于该次构图/GPU/输入下的观测；不能外推快移稳定性。
- ArUco found=0、accepted=0，无同帧参考和误差配对，因此没有报告ArUco物理误差。已经请用户提高机位/靠近，让码正面更朝向镜头且完整杯子入镜；后续必须根据实际图像检测结果复核。
- 全4713个输入文件及对应位姿SHA检查通过，原始数据未改。

Windows摘要：`E:\foundationPos\reports\redcup72_live_baseline_20261018\report.json`；叠图：`E:\foundationPos\reports\redcup72_live_20261018_first\baseline_overlay.jpg`；初始/Mask图和控制payload在同一目录。大型现场原RGB-D留Ubuntu数据盘，Windows新增文件均在E盘。

## 问题、处理和复验

1. 前次自动审批因服务额度不足未执行SSH检查；用户继续后，同一授权检查重新通过。没有绕过审批，未把未执行动作记为成功。
2. 初次状态查询脚本用通用字符串替换`SESSION`时误替换了打印标签，引发SyntaxError，仅状态查询失败，实时会话未中断。将标签改为不冲突的小写文本后，新run复查成功，确认camera_connected、新模型SHA和GPU ready。失败run保留。
3. 摄像场景偏远、光照偏暗、码斜视且未识别，限制本轮几何/参考判断。这是本次数据事实，不标记相机或ArUco算法故障，也没有将绿色框当作物理精度验收。
4. 首次已处理约1177帧时才执行短基线暂停控制，实际记录多于计划200帧；1178事件全部保留，没有裁掉后续数据以美化统计。

## 关键运行记录

- Ubuntu预检：`20261018_153817_906705_redcup_live_readiness_fb81ee4f`、`20261018_154014_253577_redcup_live_short_scene_preflight_d00dd644`。
- 部署/验证：`20261018_154140_836395_redcup_live_code_install_f0515ba2`、`20261018_154141_714748_redcup_live_mesh_selection_verify_89fed152`、`20261018_154142_664555_redcup_live_entry_syntax_5c40e964`、`20261018_154143_555615_redcup_live_entry_mesh_help_b1c1ea09`。
- 实时外层run：`20261018_154227_181788_cup_live_fast_rgbd_aruco_6e9b8b90`；独立GPU worker另留档。
- 冻结/分割/初始化：`20261018_154432_331294_redcup_live_control_freeze_98ff025d`、`20261018_154517_403464_redcup_live_control_mask_b8d6c128`、`20261018_154648_979320_redcup_live_control_initialize_a0f24075`。
- 暂停基线：`20261018_154740_875136_redcup_live_static_baseline_65f3301d`；完整SHA与数值摘要：`20261018_154938_302969_redcup_live_static_summary_560a7b85`。
