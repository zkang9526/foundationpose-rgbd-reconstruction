# V4 最终网格、参考位姿与退出异常

## 数值与源码核实的坐标结论

V4 `pipeline/textured_mesh.obj` 是**以米为单位的跟踪物体坐标网格**。源码 `mesh_to_real_world` 将神经场归一化网格顶点转换为 `v_metric = v_normalized / sc_factor - translation`，再应用首帧锚定 `pose_offset`。本次 `PoseArray.get_matrices(ids==0)` 固定为单位变换，因此锚定offset理论为I；实际最终网格与反归一化 `mesh_cleaned.obj` 顶点最近邻差最大仅 `3.80e-8 m`。

`pipeline/ob_in_cam/000000.txt ... 000035.txt` 是36张图像逐帧保存的**物体→OpenCV相机**历史估计矩阵，平移为米。C++保存入口直接输出 `inverse(frame._pose_in_model)`。它们与最终网格同一物体坐标基准，但不是全部完成global refinement后的逐帧最优值。

本次global refinement使用18张关键帧；与最终网格直接配对的global文件是：

```text
pipeline/000035/keyframes.yml                # 有序mapping，关联原始frame_id
pipeline/000033/poses_after_nerf.txt          # 18个4×4，camera_in_object
pipeline/final/nerf/config.yml               # 归一化参数
pipeline/textured_mesh.obj                   # metric推理候选网格
```

global函数从最后在线帧 `000035` 的 `keyframes.yml` 读取key顺序，最后选中关键帧是 `000033`，因此把global优化后的矩阵堆叠写到 `000033/poses_after_nerf.txt`。不能根据文件所在目录假定只对应一张图片，也不能假定每张参考图片都有global位姿。

18行块依次对应：`000000, 000002, 000003, 000004, 000005, 000006, 000007, 000008, 000009, 000010, 000011, 000012, 000014, 000016, 000020, 000024, 000031, 000033`。

这些global矩阵是**OpenCV camera→object、米**，用于投影最终metric网格时须取逆：

```python
camera_in_object = np.loadtxt(global_pose_file).reshape(18, 4, 4)
object_in_camera = np.linalg.inv(camera_in_object)
p_camera = object_in_camera[i] @ p_mesh_metric_homogeneous
uv_h = K @ p_camera[:3]
uv = uv_h[:2] / uv_h[2]
```

若推理或显示额外将mesh平移居中/旋转，则需显式保存该变换A。新mesh坐标 `v_new=A@v_old` 时，匹配矩阵为 `object_new_in_camera=object_old_in_camera@inverse(A)`，不能只把网格居中后继续使用旧矩阵。

`trainval_poses.txt` 保存时已经经 `preprocess_data` 原地修改，**是归一化后的OpenGL camera→object**，不能直接作为metric参考矩阵。恢复方法：旋转不变，平移 `t_metric=t_normalized/s-translation`，然后右乘 `diag(1,-1,-1,1)` 转OpenCV。实际恢复后与18个keyframe原始矩阵差最大 `5.55e-17`。

global精炼后的18参考矩阵与对应online历史矩阵相差平均5.64mm/7.01°、最大10.89mm/13.30°。因此投影QA优先使用上述18个global矩阵，在线36矩阵只作为历史跟踪诊断，并单独标记来源。两类都是**估计参考位姿，均不是GT**。

## 实测参数、路径和证据

- V4宿主目录：`/data/ZJC/foundationPos/foundationpose_data/derived/cup_reconstruction_side36_v4_20261013_2150`。
- `sc_factor=12.08494049297586`；`translation=[-0.00043684843404646553,-0.00015633954594854171,-0.006455201255931874]`。
- 最终mesh AABB尺寸：`[0.11362865,0.10608318,0.10307514] m`。这是坐标轴对齐包围范围，不是人工尺量尺寸。
- 最终mesh SHA256：`400e8409fa537ae2b20995c93c93aa05564408a158e82e5bb05bee5e87bb5c33`。
- global pose file SHA256：`bb48e550d70cb013a0a968a38435c3d6104c1204bd2601cf06ae3042bfb9f7a7`。
- keyframe YAML SHA256：`e705e42f100231e9288bab9092deaff25689f664ce987d56e8f78da3c50218c3`。
- 完整CPU报告：Ubuntu `foundationpose_data/bundlesdf_setup_20261013/v4_pose_mesh_coordinate_audit.json`，本机 `reports/v4_pose_mesh_coordinate_audit.json`。包含18张原始frame_id、两种方向的矩阵、合法性误差、来源哈希与历史对比。
- Ubuntu运行 `20261013_220922_903692_bundlesdf_actual_pose_gauge_audit_retry_e56d6260` **exit0**；首次JSON诊断因NumPy bool序列化失败记录保留，修复只影响诊断脚本。

官方固定源依据：[mesh/pose转换](https://github.com/NVlabs/BundleSDF/blob/cf0610e3636bc42535c996f129161f44beeadc56/Utils.py)、[global关键帧与输出](https://github.com/NVlabs/BundleSDF/blob/cf0610e3636bc42535c996f129161f44beeadc56/bundlesdf.py)、[PoseArray首帧固定与归一化](https://github.com/NVlabs/BundleSDF/blob/cf0610e3636bc42535c996f129161f44beeadc56/nerf_helpers.py)、[C++ online导出](https://github.com/NVlabs/BundleSDF/blob/cf0610e3636bc42535c996f129161f44beeadc56/BundleTrack/src/Bundler.cpp)。本次实际修改未改变这些坐标转换。

## V4退出139：当前事实与限制

主任务核实实际Ubuntu V4进程在导出网格与位姿、wrapper记录official entry返回后，退出阶段发生SIGSEGV（exit139）。`report.json passed`只记录入口已返回和产物检查，不能覆盖进程exit139；应分别保留“产物已导出可审查”与“整个进程退出异常”两个事实。

只读源码显示 `Bundler::~Bundler`只打印日志；成员容器随后销毁Frame，`Frame::~Frame`调用三个 `cudaFree`，还存在静态ZeroMQ上下文/套接字及多个Python/C++对象的退出顺序。online tracker和global tracker分别创建Bundler，两个Destructor打印**符合两个对象的预期行为**，不能仅据此断言double-free。尚无native调用栈，不能确认具体析构根因或标记已解决。

36个online矩阵和metric mesh、18global矩阵已保存且CPU坐标审计通过，可作为后续几何QA和独立FoundationPose推理的候选输入，必须注明来源run存在退出异常、未证明重建质量或绝对精度。下一步定位退出错误应在新的隔离诊断进程捕获native stack，并保留实际exit；不采用 `os._exit(0)` 吞掉错误，不修改原FoundationPose环境。
