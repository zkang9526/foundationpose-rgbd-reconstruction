# BundleSDF 独立环境完成记录（2026-10-13）

## 完成范围

Ubuntu已新增 `foundationpose-bundlesdf`，完成官方代码固定、依赖安装、CUDA/C++扩展编译、最终sm86架构检查、官方LoFTR权重SHA256与CPU严格加载、官方CLI `--help`及6个模块导入。**这些验证没有启动杯子GPU重建；网格、估计位姿和最终推理效果仍由后续专用运行验收。** 原 `foundationpose` 容器和原生FoundationPose Conda未修改、Torch未升级。

| 项目 | 最终状态 |
| --- | --- |
| 官方固定提交 | `cf0610e3636bc42535c996f129161f44beeadc56` |
| 宿主代码目录 | `/data/ZJC/foundationPos/BundleSDF-cf0610e` |
| 容器 / 工作目录 | `foundationpose-bundlesdf` / `/workspace/BundleSDF` |
| 宿主数据 / 容器数据 | `/data/ZJC/foundationPos/foundationpose_data` / `/data` |
| Python / Torch / nvcc | 3.8.18 / 2.0.0+cu118 / 11.3.109 |
| 新增主要依赖 | PCL1.10、OpenCV4.2开发包、dearpygui1.11.1、PyMCubes0.1.4、gdown5.2.0 |
| 编译产物 | `mycuda.common`、`mycuda.gridencoder`、`libMY_CUDA_LIB.so`、`libBundleTrack.so`、`my_cpp` |
| 最终CUDA native binary | `cuobjdump --list-elf` 确认 `libMY_CUDA_LIB.1.sm_86.cubin` |
| 最终native library SHA256 | `a2b70a0e1a5e270207cf13abcbbd3731b06c025adc7832d5756d683e2729d46a` |
| 保存镜像 | `foundationpose-bundlesdf:ready-20261013` |
| 镜像ID | `sha256:7a49dd8a52111bc317164155552100d5579229c39c105fd9ac018ed7047cc3ab` |
| 启动环境 | `LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7` |

Docker快照保存新容器依赖层；源码、编译产物、权重在宿主挂载目录，恢复时需要同时保留该目录。最终完整清单在Ubuntu `foundationpose_data/bundlesdf_setup_20261013/environment_ready_manifest_v2.json`，旧清单与早期错误架构二进制均保留。

## 官方资产与实际复验

从[BundleSDF官方README](https://github.com/NVlabs/BundleSDF#data-download)链接的[官方公共权重目录](https://drive.google.com/drive/folders/1xu2Pq6mZT5hmFgiYMBT9Zt8h1yO-3SIp)解析出 `outdoor_ds.ckpt` 精确ID `1M-VD35-qdB5Iw-AtbDBCKC7hPolFW9UY`，最终由官方Google usercontent下载成功。

- 保存路径：`BundleSDF-cf0610e/BundleTrack/LoFTR/weights/outdoor_ds.ckpt`。
- 大小：46,341,978字节。
- SHA256：`21f5bec5968178e8bc8b7633441836fe5de4f47d861dd2cd7dc38e271b0479ec`。
- 固定源码内vendor LoFTR严格加载211个state_dict项通过；无missing/unexpected key，参数全部有限。记录：`loftr_cpu_strict_validation.json`，进程exit0。
- 使用离线逐帧掩码，`--use_segmenter 0`，不新增XMem权重或杯子位姿网络训练。与[官方自有数据接口](https://github.com/NVlabs/BundleSDF#run-on-your-custom-data)一致。

## 为现有机器作的适配

完整适配保存在Ubuntu `foundationpose_data/bundlesdf_setup_20261013/deployment_adaptations_v1.diff`、`v2.diff`、`v3.diff`，固定原始提交可追溯：

1. Torch CUDA扩展从C++14改C++17；BundleTrack原生代码保留原C++14。旧原生comparator不满足C++17 const要求，首次统一改17失败，已按实证分开处理。
2. BundleTrack链接已安装的系统yaml-cpp，编译目标限制RTX3090的sm86。仅给旧 `CUDA_NVCC_FLAGS` 设置sm86仍会让CMake device-link默认sm52，最终必须明确 `CMAKE_CUDA_FLAGS=-gencode=arch=compute_86,code=sm_86`。旧CMake不消费 `CMAKE_CUDA_ARCHITECTURES`，不能只凭该参数宣称正确。
3. Ubuntu打包OpenCV没有CUDA/nonfree模块。删除未使用的相关include；旧SIFT匹配采用CPU分支，旧SIFT多对辅助函数改为串行CPU匹配。实际tracker在 `Bundler.cpp` 初始化 `GluNet`，覆盖该匹配方法，实际LoFTR GPU与CUDA RANSAC路径保持。未声称所有可选SIFT GPU功能都可用。
4. 原Conda libffi遮蔽系统libffi会使p11-kit导入失败。只在启动子进程预加载系统libffi7，未替换宿主或Conda库文件/链接。

## 可执行入口

Ubuntu中先通过统一记录器执行。环境复验命令：

```bash
bash /data/ZJC/foundationPos/setup/run_logged.sh \
  --root /data/ZJC/foundationPos --label bundlesdf_help_recheck \
  --note 'Independent BundleSDF CLI environment recheck' -- \
  docker exec -w /workspace/BundleSDF foundationpose-bundlesdf \
  env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7 \
  /opt/conda/envs/my/bin/python run_custom.py --help
```

实际重建需使用另行准备的安全入口，`--use_segmenter 0 --use_gui 0 --stride 1`，输入应为一个已准备好的完整单圈。**官方run_custom会清理out_folder；输出必须为专用重建runs下不存在的新目录。不得指定原始采集目录或已有结果目录。** 两圈相机俯仰不同，planned_angle不是标定外参，先验收一个完整单圈，再决定第二圈融合；独立检测照片不得混入重建参考。

## 失败、处理和验证证据

均通过Windows `setup/run_logged.py`和Ubuntu `setup/run_logged.sh`双留档，失败、中断及重试使用唯一run目录：

| 事实/问题 | 处理与最终验证 |
| --- | --- |
| 本机curl代理端口9/升级后TLS失败；Ubuntu raw/API有超时 | 失败保留；Ubuntu git clone官方仓库成功，固定HEAD和sources SHA已保存 |
| 官方APT逐包下载慢 | 对新容器确切apt进程SIGINT，中断exit130留档；新建独立清华Ubuntu镜像列表，保持官方签名与security源，依赖安装exit0 |
| Kornia文档HTTPS权重源180s/0bytes超时，gdown下载remoteclose | 失败manifest保留；官方GDrive精确ID的Googleusercontent curl成功并通过严格模型加载 |
| 第一轮native compile缺OpenCV CUDA头、C++17比较器错误 | 保存失败日志、适配v3后native编译100% exit0 |
| 未预加载libffi时my_cpp导入失败 | 启动限定环境后官方help exit0 |
| 诊断退出 `free(): invalid pointer` | 诊断将同个.so按顶层common/gridencoder和官方mycuda限定名重复加载；改为限定名后导入进程exit0，修复诊断而未改官方算法 |
| native库初版仅sm52 | 首版二进制和cache另存 `native_binary_before_sm86_link/`；强制device-link，最终cuobjdump仅sm86，限定名导入复验exit0 |

最终重要Ubuntu运行记录：

- `20261013_213516_757584_bundlesdf_cpu_loftr_validation_632f0843`：官方权重CPU严格加载exit0。
- `20261013_213708_666487_bundlesdf_cli_help_libffi_retry_f58f1edc`：官方CLI help exit0。
- `20261013_214122_781064_bundlesdf_device_link_sm86_cuobjdump_93e58556`：最终CUDA fatbin架构sm86。
- `20261013_214315_103926_bundlesdf_final_qualified_imports_9d863676`：最终6模块限定名导入exit0，记录 `runtime_qualified_import_v2.json`。
- `20261013_214320_261079_bundlesdf_finalize_environment_stage_2b943f9d`：最终manifest与Ubuntu环境说明追加成功。

Ubuntu `Ubuntu_environment.md`已通过记录器在服务器端追加完成/限制，未拿旧Windows文件覆盖服务器记录。旧probe文档作为早期事实保留。
