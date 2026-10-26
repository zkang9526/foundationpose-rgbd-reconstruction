## 最终留档同步与复核（2026-10-14）

- `cup_pilot_updates_20261014_0220_retry2` 增量部署3781文件全部来源/输出SHA复验通过，先备份指南/脚本、80份结束Windows run按唯一ID追加，原Ubuntu总日志不覆盖。实际run `20261014_022737_546038_cup_final_updates_deploy_retry2_3367c85a`。
- 初次增量暂存目录因导入staged Python模块自动生成一个__pycache__文件而被清单校验拒绝，未修改项目文件；原失败stage/report/cache保留。新目录使用 `PYTHONDONTWRITEBYTECODE=1` 与 `python3 -B` 后全部通过。
- Windows生成的四份CPU视觉/候选选择目录86文件与冻结实验预览21文件，合计107项在Ubuntu逐SHA复验通过。每个目的目录上传前确认不存在，原始RGB-D/候选mesh/官方基线均未覆盖。
- 阶段总结以 `CUP-PILOT-QUALITY-20261014` event-id在Windows/Ubuntu两侧追加，真实业务限制保留：5张官方预训练初始化退出0；三份网格质量拒收，重建退出139未解决，无GT或可靠6D准确率声明。
- 最终状态报告 `reports/CUP_PILOT_FINAL_STATE_20261014.json` 由Ubuntu真实读文件、来源/官方权重SHA、5预测输出、3负面QA及实际run退出码核验生成。GPU为RTX3090/535.230.02/24576MiB，原FP与独立BundleSDF容器均running。该报告passed仅认证留档事实，`mesh_quality_passed=false`、`reliable_cup_reproduction_complete=false`。
- 后续关注可靠参考配准/几何与杯子实测尺度，再扩大连续跟踪与GT评测；当前可交付为环境、可重跑离线流程和完整试跑证据。尾部同步动作的Windows记录本机保留，Ubuntu对应动作也有自己的记录；后续以新批次追加，不能无限回写原快照。
