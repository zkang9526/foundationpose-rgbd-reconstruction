#!/usr/bin/env python3
"""Preserve prior compiled libraries then force sm86 CUDA device-link code."""
import shutil
from deploy_bundlesdf_isolated_20261013 import CODE, AUDIT, docker, logged

build = CODE/'BundleTrack/build_deploy_20261013'
backup = AUDIT/'native_binary_before_sm86_link'
backup.mkdir(parents=True, exist_ok=False)
for name in ['CMakeCache.txt', 'libMY_CUDA_LIB.so', 'libBundleTrack.so', 'my_cpp.cpython-38-x86_64-linux-gnu.so']:
    shutil.copy2(build/name, backup/name)
logged('bundlesdf_device_link_sm86_cmake', docker(['cmake', '-S', '/workspace/BundleSDF/BundleTrack',
    '-B', '/workspace/BundleSDF/BundleTrack/build_deploy_20261013',
    '-DCMAKE_CUDA_FLAGS=-gencode=arch=compute_86,code=sm_86', '-DCMAKE_CUDA_ARCHITECTURES=86']))
logged('bundlesdf_device_link_sm86_build', docker(['cmake', '--build',
    '/workspace/BundleSDF/BundleTrack/build_deploy_20261013', '--parallel', '4']))
logged('bundlesdf_device_link_sm86_cuobjdump', docker(['/usr/local/cuda/bin/cuobjdump', '--list-elf',
    '/workspace/BundleSDF/BundleTrack/build_deploy_20261013/libMY_CUDA_LIB.so']))
