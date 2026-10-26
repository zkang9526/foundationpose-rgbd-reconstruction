### 2026-10-17 用户暂停标定，启动新红杯采集与人工Mask流程

- 用户明确暂不继续验证相机参数，按当前参数采杯子，采后自己逐张标注/修Mask；保留精度未验收状态，不继续自动校准。
- 已留存Viewer失败裁切截图和SHA；核验项目Viewer进程后关闭，未删数据或写标定。
- 新72张侧面圈已启动并完成90帧预热，等待用户逐张回车；数据E:\foundationPos_data\windows_captures\obj_side_20261017_183122_148，run20261017_183122_309483_windows_obj_photos_6bd3210f。
- 原始RGB、SDK对齐未补洞毫米深度、K、时戳/帧号/原生内外参及bag均存E盘；计划5°不是GT，启动不是完成。
- 本机人工Mask编辑页准备中，原图只读、标注独立版本；Mask包括可见内壁和把手，排除真实背景孔，不能因depth=0自动删前景。阶段报告reports/RED_CUP_CAPTURE_AND_MANUAL_MASKS_20261017.md。
