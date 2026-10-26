## 2026-10-14 OBJ指南环境配置与复验

用户指定依据优化版D435i-to-OBJ文档配置环境，D435i留在Windows采集，Ubuntu USER@UBUNTU_HOST进行后续重建；用户明确允许直接执行已授权配置/验证。Windows与Ubuntu均通过现有记录器留档，旧数据和失败证据保留。

- Windows沿用Python3.11/SDK2.55.1/NumPy1.26.4/Pillow12.3.0，补装OpenCV4.11.0.86并缓存其官方wheel。60对640×480@30对齐RGB-D检查通过，设备238222071455、USB3.2；运行`20261014_132151_137055_windows_d435i_check_947e3924`。检查画面是墙面，物体尺寸/距离/材质/光照没有人工确认，不当正式目标采集。
- 新`start_obj_photos.ps1`使用High Accuracy、按回车选取静止照片，并可录原生bag及另外保存滤波深度。原始对齐深度保留在depth/。最终实际单张自动检查、原预设0恢复、uint16文件与bag回放通过，run为`20261014_133130_732069_obj_windows_final_options_check_666d2140`；产物`foundationpose_data/windows_captures/obj_options_final_20261014_133130_611/`。此自动检查不需要用户旋转/按键，不是完整多视角参考。
- 官方便携Viewer2.55.1已缓存，SHA256与Valid数字签名写入`20261014_132743_104528_obj_viewer_sha256_record_0d1a9107`；未运行GUI，未改固件/设备标定。
- Ubuntu SSH可用，沿用现有原生foundationpose环境；未重装Ubuntu模型/重建依赖。Open3D0.19.0实际ICP、位姿图、12视角TSDF、米制OBJ导出/再读与CUDA计算通过：服务器run`20261014_133110_132279_obj_open3d_environment_check_54ba3cfc`，Windows外层run`20261014_133054_251152_obj_tsdf_final_environment_check_c584bad7`。
- 合成结果在Ubuntu `foundationpose_data/obj_environment_checks/open3d_20261014_1333_surface/`；Windows报告与网格副本在`reports/open3d_20261014_1333_surface/`。7808顶点、15580三角面，表面误差95分位2.69mm；盒子边缘包围框偏差如实保留，不当实物精度验证或真实杯子OBJ。
- 新脚本通过新incoming批次SHA256复验并部署，替换时备份原脚本；此前失败测试/脚本版本保留。最终操作说明见`reports/OBJ_ENVIRONMENT_SETUP_20261014.md`，根优化指南、采集/环境/复现说明同步更新。

后续需要摆放正式目标、核查目标区域深度、分圈采集、打包及校验传输，再做物体Mask、目标配准、TSDF与实物网格QA。相机固定不能代替物体配准，planned_angle不当外参或GT。旧BundleSDF退出139、杯子几何变形仍未解决；未新增位姿训练或GT评测。
