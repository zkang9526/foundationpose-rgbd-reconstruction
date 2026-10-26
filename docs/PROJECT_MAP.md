# 模块与文档索引

保留已有脚本路径，避免改名破坏历史启动命令。

| 模块 | 主要实现（相对项目根目录） |
| --- | --- |
| RGB-D 采集 | `setup/capture_d435i.py`、`capture_d435i_photos.py`、`start_obj_photos.ps1` |
| 参数/对齐检查 | `setup/review_rgbd_alignment.py`、`camera_calibration/` |
| Mask 草稿与人工确认 | `setup/cup_sam2_worker.py`、`prepare_sam_assisted_masks.py`、`manual_mask_editor.py` |
| 几何初始化、ICP、TSDF | `setup/reconstruct_cup_geometric_tsdf.py`、`audit_geometric_cup_mesh.py` |
| 跟踪主循环/网页 | `setup/run_cup_live_fast.py`、`run_cup_live_worker.py`、`cup_live_dashboard.py` |
| GPU 投影/质量检查 | `setup/cup_pose_quality.py` |
| 自动找回 | `setup/cup_reacquisition.py`、`cup_sam2_mask.py`、`cup_sam2_worker.py` |
| ArUco 评估 | `setup/cup_aruco_reference.py`、`summarize_cup_aruco_session.py`、`review_saved_camera_motion.py` |
| 运行与 Git 证据 | `setup/run_logged.py`、`project_git_state.py` |

## 阅读顺序

1. [快速指南](QUICKSTART.md)：当前入口与依赖/路径边界。
2. [Ubuntu 环境](../Ubuntu_environment.md)：实测配置，不是通用安装器。
3. [照片采集](../CUP_MANUAL_PHOTOS.md)、[人工 Mask](../MANUAL_CUP_MASKS.md)。
4. [红杯重建](../reports/RED_CUP_REVIEWED72_MESH_RESULT_20261017.md)、[颜色/杯把检查](../reports/RED_CUP_COLOR_HANDLE_REVIEW_20261017.md)。
5. [GPU 加速](../reports/CUP_FAST_ARUCO_RESULT_20261014.md)、[评估协议](../reports/CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md)。
6. [最新成功找回与漂移](../reports/CUP_RECOVERED_ACCURACY_20261018_172656.md)。

## 历史记录与公开范围

[完整操作指南](../REPRODUCTION_GUIDE.md)、[早期 README](../README_LEGACY.md) 与日期报告保留当时的判断和失败结果。历史“尚未接入/未完成”描述不能代替后续报告。
`stage_*`、`archive_*` 和日期脚本多为特定批次编排，不是新数据的一键入口。

公开快照包括项目脚本、配置、阶段文字报告和少量汇总证据；不包含原始采集、标注历史、Mesh、权重、venv、缓存、完整上游源码、运行账本与原本地 Git 历史。
`PUBLICATION_MANIFEST.json` 记录导出文件 SHA256、来源提交及文本脱敏。原始资料与完整原历史仍在本地；公开版本单独建立 `main`，不把新快照伪装成早期提交。
