## 最终增量Bootstrap清单问题：已复验解决

初次 `cup_pilot_updates_20261014_0220` 导入失败，现象为 `Staged payload file list differs from manifest`。只读清单诊断证实额外项唯一为 `setup/__pycache__/import_cup_offline_batch.cpython-38.pyc`，没有缺失文件；Python通过PYTHONPATH导入暂存模块时自动写缓存。失败发生在任何项目文件替换/日志追加之前，原stage/report/cache均保留。

新建retry2暂存目录，不删除或修改原失败证据，启动明确使用 `PYTHONDONTWRITEBYTECODE=1` 和 `python3 -B`。复验run `20261014_022737_546038_cup_final_updates_deploy_retry2_3367c85a` 退出0，3781文件全量SHA通过、80份Windows run索引追加且原issues.md未重写。只将本次增量入口问题标为解决；网格质量、参考配准、姿态精度及重建清理139仍未解决。
