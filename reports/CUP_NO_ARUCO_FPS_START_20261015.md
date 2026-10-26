# 2026-10-15 未贴ArUco前的实际相机FPS检查：启动记录

用户要求先查看FPS，并持续记录问题、处理和复验。此次未启用ArUco，不设置名义码尺寸或参考位姿，不产生虚构的精度数值。保持官方2次跟踪细化和现有候选米制杯子模型。

## 已执行及证据

- SSH连接与实际SDK设备查询通过，识别Intel RealSense D435i，serial `238222071455`。
- 已执行实际相机入口（自动双层留档）：

```bash
cd /data/ZJC/foundationPos
FP_RUN_NOTE='2026-10-15 real-camera FPS trial before ArUco placement; cup target and lighting to be checked from actual preview; no accuracy reference' \
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000
```

- Ubuntu会话：`foundationpose_data/live_sessions/cup_fast_20261015_103852_12136619`。
- 主运行：`foundationpose_data/runs/20261015_103852_059243_cup_live_fast_rgbd_aruco_be1a2d45`；Windows外层启动记录：`20261015_103835_898845_start_no_aruco_fps_live_a32c0d5c`。运行标签虽然含aruco，但未传marker参数，实际配置为禁用参考。
- HTTP `http://127.0.0.1:8765/status` 返回 `waiting_for_roi`、completed0、failed0。此时还没有位姿处理FPS，不能用相机请求30FPS、昨日回放27.49FPS替代本次实物结果。
- 当前显示快照为天花板，尚无杯子：Ubuntu会话内 `inspection_preview_1039.jpg`；Windows E盘 `E:\foundationPos_data\reviews\cup_fast_no_aruco_20261015_1039_preview.jpg`。这是有损显示快照，不是原始推理输入，不包含目标深度质量结论。

## 现场继续测试

相机摆到杯子前，杯身、杯把完整入镜，先静止。当前会话还在运行时直接打开Ubuntu浏览器 `http://127.0.0.1:8765`，不要重复启动占用同一端口和相机。冻结→框完整杯子→生成并检查Mask→确认初始化；等状态进入跟踪后再移动相机。

先静止约20秒观察处理FPS和投影，然后缓慢移动相机约20秒，再适度加快。初始化期间保持相机/杯子不动。观察“实际处理FPS”、是否需要重新初始化、叠图是否跟随；FPS高不代表位姿正确。当前页面FPS是已处理跟踪帧的累计平均，暂停或重初始化跨段会影响平均，应以连续跟踪片段评估稳定速度。

停止时按“停止并保存记录”。每个处理帧的无损RGB/depth、时间戳、矩阵、叠图、深度一致性及失败都保留在该会话；自动汇总在 `evaluation_summary/report.json`，同时有 `frame_events.jsonl`、`session.json`、`worker_report.json`、worker输出和运行档案。未贴码时误差列为空是预期行为。

如果此次已结束，可在Ubuntu重新执行上面的命令，会创建新会话并保留旧记录。3000帧的无压缩RGB+毫米深度约4.6GB；不写Windows C盘原始数据目录。

## 当前结论和下一步

启动/相机/模型加载/HTTP显示可运行；现场目标尚未入镜，尚未得到本次实际杯子跟踪FPS，未完成准确度评测。待调整相机并完成同冻结帧初始化后，记录连续跟踪的处理速度、延迟、拒绝帧和实际投影情况，再按证据追加结果。不能把等待框选视为环境故障或标记问题已解决。
