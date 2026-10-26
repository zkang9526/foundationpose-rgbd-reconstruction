#!/usr/bin/env python3
"""Append isolated deployment evidence; retain prior manifests and server records."""
import hashlib
import json
import os
from pathlib import Path
import fcntl
from deploy_bundlesdf_isolated_20261013 import ROOT, CODE, AUDIT

manifest = json.loads((AUDIT/'environment_ready_manifest.json').read_text())
manifest['previous_manifest'] = str(AUDIT/'environment_ready_manifest.json')
manifest['compiled_extensions'] = {}
for directory in [CODE/'mycuda', CODE/'BundleTrack/build_deploy_20261013']:
    for path in directory.glob('*.so'):
        manifest['compiled_extensions'][str(path.relative_to(CODE))] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest['cuda_device_link_flags'] = '-gencode=arch=compute_86,code=sm_86'
manifest['final_native_fatbin'] = 'libMY_CUDA_LIB.1.sm_86.cubin (cuobjdump verified)'
manifest['qualified_import_validation'] = str(AUDIT/'runtime_qualified_import_v2.json')
manifest['gpu_reconstruction_performed'] = False
output = AUDIT/'environment_ready_manifest_v2.json'
if output.exists():
    raise FileExistsError(str(output))
output.write_text(json.dumps(manifest, indent=2)+'\n')

text = '''
## 2026-10-13：未知杯子重建的独立 BundleSDF 环境

新增容器 `foundationpose-bundlesdf`，继承 `foundationpose:ready-20261010`；原 `foundationpose` 容器、原生 FoundationPose Conda 均未改动。独立环境 Python3.8.18 / Torch2.0.0+cu118，编译器 nvcc11.3.109。已保存镜像 `foundationpose-bundlesdf:ready-20261013`，ID `sha256:7a49dd8a52111bc317164155552100d5579229c39c105fd9ac018ed7047cc3ab`；源码与编译产物挂载在宿主机，不在 Docker commit 中，恢复需要同时保留源码目录。

- 官方源码 `/data/ZJC/foundationPos/BundleSDF-cf0610e`，固定提交 `cf0610e3636bc42535c996f129161f44beeadc56`（避免最新源码要求 Torch2.6 影响已有环境）。容器目录 `/workspace/BundleSDF`。
- 新容器补装 PCL1.10、OpenCV4.2 开发包、dearpygui1.11.1/PyMCubes0.1.4/gdown5.2.0；编译 `mycuda.common`、`mycuda.gridencoder`、`BundleTrack/my_cpp` 成功。原生 BundleTrack 保留 C++14；Torch CUDA 扩展适配 C++17。
- 兼容适配保留完整 `deployment_adaptations_v1/v2/v3.diff`：系统 yaml-cpp 路径、sm86、删除无用 nonfree/CUDA OpenCV include，旧 SIFT 描述子匹配采用 CPU 分支。实际 tracker 为 `GluNet`/LoFTR，LoFTR GPU与CUDA RANSAC代码保留。
- LoFTR `outdoor_ds.ckpt` 从官方 Google Drive folder 查得精确文件 ID `1M-VD35-qdB5Iw-AtbDBCKC7hPolFW9UY`，大小46,341,978字节，SHA256 `21f5bec5968178e8bc8b7633441836fe5de4f47d861dd2cd7dc38e271b0479ec`。CPU严格加载211个state_dict项通过，无缺失/多余项，参数有限。
- 启动必须使用 `env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7`，解决 Conda libffi 与系统 p11-kit ABI冲突；没有替换系统或Conda符号链接。
- CUDA native library 经 `cuobjdump --list-elf` 实测含 `libMY_CUDA_LIB.1.sm_86.cubin`。旧 CMake忽略 `CMAKE_CUDA_ARCHITECTURES`，真正生效的是 `CMAKE_CUDA_FLAGS=-gencode=arch=compute_86,code=sm_86`，仅修改对象编译flags不足以确保device-link正确。
- 官方 `run_custom.py --help` exit0；按官方限定名 `mycuda.common/mycuda.gridencoder` 导入6个模块 exit0。诊断中曾把同一个扩展按顶层别名再次加载，造成退出时 `free(): invalid pointer`；限定名复验已消除，失败证据保留。
- 当前验收范围为编译、正确架构、导入、命令行和资产完整性；杯子GPU联合跟踪/网格质量由后续独立运行验证，不凭这些环境检查宣称已重建成功。

运行命令应经 `setup/run_logged.sh`。精确基础入口：

```bash
docker exec -w /workspace/BundleSDF foundationpose-bundlesdf \\
  env LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7 \\
  /opt/conda/envs/my/bin/python run_custom.py --help
```

留档：`foundationpose_data/bundlesdf_setup_20261013/environment_ready_manifest_v2.json`、`runtime_qualified_import_v2.json`、`loftr_cpu_strict_validation.json`、下载尝试manifest、patches、首轮错误架构native二进制备份，以及各唯一run目录。官方 `run_custom.py` 会清理指定输出目录，每次必须通过有新目录保护的专用入口，不能指定原始数据目录或既有结果。
'''
marker = '<!-- bundlesdf-isolated-environment-20261013 -->'
with (ROOT/'.records.lock').open('a') as lock:
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
    destination = ROOT/'Ubuntu_environment.md'
    existing = destination.read_text(encoding='utf-8')
    if marker in existing:
        raise RuntimeError('Deployment environment note already present')
    with destination.open('a', encoding='utf-8') as stream:
        stream.write('\n'+marker+'\n'+text+'\n')
print(json.dumps({'manifest': str(output), 'environment_doc_appended': str(destination),
                  'native_library_sha256': manifest['compiled_extensions']['BundleTrack/build_deploy_20261013/libMY_CUDA_LIB.so']}))
