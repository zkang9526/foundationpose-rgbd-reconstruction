# 杯身预抓取数值模块

这些模块来自Piper预抓取流程，提供几何候选、逆解搜索与轨迹检查函数。机器人驱动、ROS任务入口和现场标定由使用者的机械臂工程提供。

流程为连续稳定采样 → 平移中位数与SO(3)旋转聚合 → 手眼变换得到基座下杯身中心 → 生成径向预抓取候选 → 逐候选逆解及完整路径检查 → 返回关节轨迹。

| 模块 | 作用 |
| --- | --- |
| `pose_stability.py` | 多帧一致性门限与稳定位姿聚合 |
| `cup_grasp_search.py` | 每5°、两种工具轴符号，生成144个原始径向候选 |
| `cup_ik_search.py` | 多初值数值逆解、残差与碰撞回调检查 |
| `cup_ik_refinement.py` | 按位置/旋转容差归一化的有界细化 |
| `cup_route_search.py` | 多准备距离、高度、侧移与完整路线搜索 |
| `cup_approach_route.py` | 杯身/杯把代理与路径检查 |
| `cup_side_grasp.py` | 工具坐标构造和杯把几何规则 |
| `joint_motion.py` | 五次关节曲线、限速、限加速度和重采样 |
| `aruco_geometry.py` | 坐标、配置及工作空间计算 |

工具接近轴Z和闭合轴Y均垂直杯轴，X沿杯轴。预抓取点按配置在杯身参考点外退出，路径可在杯外调整后沿径向接近。与杯把闭合方向重合的候选可作为低优先备选，仍需通过完整碰撞检查。

`plan_search_pregrasp(solver, start, target, center, config)` 返回时间、六关节轨迹及检查摘要。长度单位米，关节角单位弧度，矩阵为4×4齐次变换。

solver接口需要 `reduced_robot.model` 的关节上下限、`forward_pose(q)`、`ik_fun(...)`、`check_self_collision(q, gripper)`，以及CupCollisionProxy所需的Pinocchio机器人几何模型。使用现有Piper运动学接口时，保持这些约定一致。

主要配置包括 `T_ee_tcp`、`pregrasp_distance_m`、杯身和杯把尺寸、工作空间、速度及加速度限制。扩展功能分别由 `pregrasp_search_enabled`、`pregrasp_closing_axis_fallback_enabled`、`search_ik_tolerance_refinement_enabled` 控制。相应默认值和边界检查见函数实现。

在保存的失败场景上，扩展搜索和容差细化已找到通过原2mm/0.02rad数值门限、自碰撞及杯体代理检查的预抓取路线。该门限描述数值运动学拟合。实体到位、手眼/TCP准确性和桌面等外部障碍需结合实际机器人验证。

依赖NumPy、SciPy、OpenCV、PyYAML，以及调用方已有的Pinocchio、hpp-fcl和数值逆解环境。导入模块不启动ROS或运动。
