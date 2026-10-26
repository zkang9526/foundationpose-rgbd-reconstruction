#!/usr/bin/env python3
"""Compile stages independently; preserve all failed builds and source changes."""
import argparse
import subprocess
from deploy_bundlesdf_isolated_20261013 import CODE, PYTHON, AUDIT, docker, logged

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['cuda', 'native'], required=True)
    args = parser.parse_args()
    if args.stage == 'cuda':
        logged('bundlesdf_isolated_cuda_extensions', docker([
            'env', 'CUDA_HOME=/usr/local/cuda', 'TORCH_CUDA_ARCH_LIST=8.6', 'MAX_JOBS=4',
            PYTHON, '-m', 'pip', 'install', '--no-build-isolation', '--no-deps', '-e', '.'
        ], '/workspace/BundleSDF/mycuda'))
        return
    logged('bundlesdf_isolated_cmake', docker(['cmake', '-S', '/workspace/BundleSDF/BundleTrack',
        '-B', '/workspace/BundleSDF/BundleTrack/build_deploy_20261013',
        '-DPython_EXECUTABLE='+PYTHON, '-DPYTHON_EXECUTABLE='+PYTHON,
        '-Dpybind11_DIR=/opt/conda/envs/my/lib/python3.8/site-packages/pybind11/share/cmake/pybind11']))
    logged('bundlesdf_isolated_bundletrack_build', docker(['cmake', '--build',
        '/workspace/BundleSDF/BundleTrack/build_deploy_20261013', '--parallel', '4']))
    destination = CODE / 'BundleTrack/build'
    if destination.exists():
        raise FileExistsError('Preserve existing build alias: ' + str(destination))
    destination.symlink_to('build_deploy_20261013', target_is_directory=True)

if __name__ == '__main__':
    main()
