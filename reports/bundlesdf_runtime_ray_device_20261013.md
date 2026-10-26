# 杯子重建 V3：NeRF 射线索引设备错误

2026-10-13，第一轮实际GPU跟踪已推进到多关键帧，NeRF工作进程在 `nerf_runner.py` 的无有效深度射线补采样分支退出：`indices should be either on cpu or on the same device as the indexed tensor (cpu)`。主tracker等待工作进程，不能把已经产生的跟踪日志视为完整重建成功。V3输出和失败运行档案保留，停止范围只限独立 `foundationpose-bundlesdf` 容器。

源码证据：`DataLoader.ids = torch.randperm(...)` 默认在CPU；`__next__`只把返回的ray batch迁移到CUDA，`batch_ray_ids`仍在CPU。`render_rays`用CUDA上的 `invalid_depth_mask` 索引CPU `ray_ids`，因此触发设备不匹配。

修复仅作用于固定BundleSDF checkout：在 `render_rays` 入口把非None `ray_ids`显式迁移至 `ray_batch.device`；在无有效深度分支保留可选None参数。索引值、顺序、采样算法和位姿网络均不改变。

```python
if ray_ids is not None:
    ray_ids = ray_ids.to(device=ray_batch.device)
```

原文保存：Ubuntu `foundationpose_data/bundlesdf_setup_20261013/nerf_runner_before_ray_device_v4.py`。完整git diff：`deployment_adaptations_v4_ray_device.diff`，变更SHA和根因：`ray_device_patch_v4.json`。修改前SHA256 `084b8c7cf4ad09ca7b62eae8ccf8ac2b218ded0b423dca200f46f6495f89ac80`，修改后 `084015477723ce762493091601c5a0b52f4a0b01d524d7d61174417b8b537bf8`。

Ubuntu运行 `20261013_214927_829340_bundlesdf_ray_device_patch_stage_7225de65` 保存修改、备份、diff与AST语法验证。运行 `20261013_215015_322473_bundlesdf_ray_device_cpu_recheck_47210a2d` 官方help/导入exit0。**GPU修复结果需新V4重建实际复验，本记录不提前标记已解决。** 未启动第二个GPU任务。
