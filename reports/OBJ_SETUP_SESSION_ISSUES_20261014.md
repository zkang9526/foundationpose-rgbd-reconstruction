## 2026-10-14 OBJ环境配置问题与复验

1. **Windows沙盒相机拒绝访问：本次访问路径已复验。** 事实：`20261014_132044_758289_windows_d435i_check_32fefc25`在MFCreateDeviceSource报HResult0x80070005、0帧。处理：按工具要求申请沙盒外设备访问。复验：`20261014_132151_137055_windows_d435i_check_947e3924`识别同一D435i并完成60对取帧；最终录包检查也通过。不修改相机隐私设置或标定，不把此错误归因于硬件坏损。

2. **沙盒内获取OpenCV失败：安装交付已解决。** 事实：`20261014_132202_326450_obj_windows_opencv_install_7ddf35dd`提示无匹配发行版。推测：受限索引/网络路径有关，未断言具体pip配置根因。处理：沙盒外隔离模式指定官方PyPI及固定版本。复验：`20261014_132224_002787_obj_windows_opencv_install_retry_579533af`成功，最终pip check及实际深度PNG读取通过；wheel已缓存，固定SHA256为`085ad9b77c18853ea66283e98affefe2de8cc4c1f43eda4c100cf9b2721142ec`。

3. **Viewer发布API请求失败：API失败保留，Viewer已交付。** 沙盒curl连接127.0.0.1:9失败；沙盒外GitHub API返回403，不能由此推断SDK本体不可用。通过官方release的独立Viewer下载地址取得二进制并验证Windows数字签名Valid。相关失败run为`20261014_132313_166472_obj_realsense_release_metadata_608010d5`与`20261014_132323_615658_obj_realsense_release_metadata_retry_e6025954`；签名/哈希证据为`20261014_132743_104528_obj_viewer_sha256_record_0d1a9107`。本次未打开GUI。

4. **更新helper未找到setup模块：已解决。** 首次部署`20261014_132637_107667_obj_helper_ubuntu_deploy_224fd2d5`报ModuleNotFoundError(import_cup_offline_batch)，发生在helper导入前，尚未替换文件。处理：仅指定`PYTHONPATH=/data/ZJC/foundationPos/setup`，不用全量环境变量日志。复验：`20261014_132701_530243_obj_helper_ubuntu_deploy_retry_2fb960fb`及服务器`20261014_132717_678563_obj_helper_ubuntu_deploy_retry_752905d2`退出0、3文件SHA及部署验证通过；后续批次也通过。

5. **合成检查对位姿图writer返回值作了错误判断：已修正复验。** 首次Open3D测试`20261014_132717_934212_obj_open3d_ubuntu_smoke_133f052d`判写入失败；诊断确认文件已生成。处理：改为文件存在/非空及回读节点和约束数的验证。最终服务器环境run`20261014_133110_132279_obj_open3d_environment_check_54ba3cfc`通过位姿图往返和变换约定检查；原测试保留。

6. **合成TSDF包围框与理想盒子有边缘偏差：事实保留，环境门槛已修正，几何偏差不标解决。** 固定15mm包围框门槛在`20261014_132826_504705_obj_open3d_ubuntu_smoke_retry_e807c0bd`和诊断run`20261014_132921_240753_obj_tsdf_geometry_diagnosis_fb7bdaf7`失败。理想尺寸0.10×0.12×0.08m，提取0.1171653×0.1266227×0.0944343m。考虑TSDF截断带边缘伪影，改为表面距离95分位小于两体素(6mm)，同时边界在两倍截断距离加两体素(30mm)内；没有改写旧结果。最终表面距离95分位2.69mm、OBJ往返尺寸保持并通过环境验收。此门槛仅检查运行与量纲/变换，不能证明实物尺寸准确。

7. **实物数据与质量：仍待执行。** 本次相机画面为墙面，没有完成正式物体多视角采集/物理标定QA/可靠OBJ。既有杯子网格变形、BundleSDF退出139仍未解决。本次环境测试不改变它们的状态，也不把算法估计/计划角度当GT。
