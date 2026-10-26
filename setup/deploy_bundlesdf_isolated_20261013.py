#!/usr/bin/env python3
"""Stage-by-stage isolated BundleSDF deployment. No changes to existing FP envs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/data/ZJC/foundationPos')
CODE = ROOT / 'BundleSDF-cf0610e'
PIN = 'cf0610e3636bc42535c996f129161f44beeadc56'
CONTAINER = 'foundationpose-bundlesdf'
PYTHON = '/opt/conda/envs/my/bin/python'
AUDIT = ROOT / 'foundationpose_data/bundlesdf_setup_20261013'

def logged(label, argv):
    subprocess.run([sys.executable, '-u', str(ROOT / 'setup/run_logged.py'),
                    '--root', str(ROOT), '--label', label,
                    '--note', 'Isolated BundleSDF setup; original foundationpose container and Conda unchanged.',
                    '--'] + argv, check=True)

def docker(command, workdir=None):
    argv = ['docker', 'exec']
    if workdir:
        argv += ['-w', workdir]
    return argv + [CONTAINER] + command

def dump(name, data):
    AUDIT.mkdir(parents=True, exist_ok=True)
    path = AUDIT / name
    if path.exists():
        raise FileExistsError('Refusing to overwrite evidence: ' + str(path))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

def source():
    if CODE.exists():
        raise FileExistsError('Preserve prior checkout/partial source: ' + str(CODE))
    logged('bundlesdf_clone_official', ['git', 'clone', '--filter=blob:none', '--no-checkout', 'https://github.com/NVlabs/BundleSDF.git', str(CODE)])
    logged('bundlesdf_pin_checkout', ['git', '-C', str(CODE), 'checkout', '--detach', PIN])
    dump('source_pin.json', {'repo': 'https://github.com/NVlabs/BundleSDF', 'pin': PIN,
                           'files': {str(path.relative_to(CODE)): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in [CODE/'docker/dockerfile', CODE/'mycuda/setup.py', CODE/'BundleTrack/CMakeLists.txt', CODE/'run_custom.py']}})
    for relative in ['mycuda/setup.py', 'Utils.py', 'nerf_runner.py', 'gui.py']:
        path = CODE / relative
        print(relative + ':\n' + '\n'.join(path.read_text().splitlines()[:60]))

def create():
    state = subprocess.run(['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True, check=True)
    if CONTAINER in state.stdout.splitlines():
        raise RuntimeError('Container already exists; inspect and resume without recreating: ' + CONTAINER)
    if not (CODE / 'run_custom.py').is_file():
        raise RuntimeError('Pinned source missing')
    logged('bundlesdf_isolated_container_create', ['docker', 'create', '--name', CONTAINER,
           '--gpus', 'all', '--network', 'host', '--ipc', 'host', '--shm-size', '8g',
           '-v', str(CODE)+':/workspace/BundleSDF', '-v', str(ROOT / 'foundationpose_data')+':/data',
           '-v', str(ROOT / 'setup')+':/setup:ro', '-w', '/workspace/BundleSDF',
           'foundationpose:ready-20261010', 'sleep', 'infinity'])
    logged('bundlesdf_isolated_container_start', ['docker', 'start', CONTAINER])

def deps():
    logged('bundlesdf_isolated_apt_update', docker(['apt-get', 'update']))
    logged('bundlesdf_isolated_native_deps', docker(['apt-get', 'install', '-y', '--no-install-recommends',
           'libpcl-dev', 'libopencv-dev', 'libeigen3-dev', 'libyaml-cpp-dev', 'libzmq3-dev',
           'freeglut3-dev', 'libblas-dev', 'liblapack-dev', 'libboost-system-dev',
           'libboost-program-options-dev', 'libboost-serialization-dev', 'libspdlog-dev']))
    logged('bundlesdf_isolated_python_deps', docker([PYTHON, '-m', 'pip', 'install', '--no-deps',
           'dearpygui==1.11.1', 'PyMCubes==0.1.4', 'gdown==5.2.0']))

def patch():
    # Limit machine-dependent compilation to this RTX3090; Torch2.0 C++ headers need C++17.
    cmake = CODE / 'BundleTrack/CMakeLists.txt'
    original = cmake.read_text()
    updated = original.replace('c++14', 'c++17')
    updated = re.sub(r'-gencode=arch=compute_(?!86)\d+,code=sm_\d+\s*', '', updated)
    updated = updated.replace('set(YAML_CPP_LIBRARIES "/usr/local/lib/libyaml-cpp.so")',
                              'find_library(YAML_CPP_LIBRARIES NAMES yaml-cpp REQUIRED)')
    if updated != original:
        cmake.write_text(updated)
    setup = CODE / 'mycuda/setup.py'
    original_setup = setup.read_text()
    # Older CUDA-extension flags had no C++17 requirement. Build under existing Torch2.0.
    updated_setup = original_setup.replace('c++14', 'c++17')
    setup.write_text(updated_setup)
    diff = subprocess.run(['git', '-C', str(CODE), 'diff'], capture_output=True, text=True, check=True)
    AUDIT.mkdir(parents=True, exist_ok=True)
    evidence = AUDIT / 'deployment_adaptations_v1.diff'
    if evidence.exists():
        raise FileExistsError(str(evidence))
    evidence.write_text(diff.stdout, encoding='utf-8')
    print(diff.stdout)

def build():
    env = ['env', 'CUDA_HOME=/usr/local/cuda', 'TORCH_CUDA_ARCH_LIST=8.6', 'MAX_JOBS=4']
    logged('bundlesdf_isolated_cuda_extensions', docker(env + [PYTHON, '-m', 'pip', 'install',
           '--no-build-isolation', '--no-deps', '-e', '.'], '/workspace/BundleSDF/mycuda'))
    logged('bundlesdf_isolated_cmake', docker(['cmake', '-S', '/workspace/BundleSDF/BundleTrack',
           '-B', '/workspace/BundleSDF/BundleTrack/build_deploy_20261013',
           '-DPython_EXECUTABLE='+PYTHON, '-DPYTHON_EXECUTABLE='+PYTHON,
           '-Dpybind11_DIR=/opt/conda/envs/my/lib/python3.8/site-packages/pybind11/share/cmake/pybind11']))
    logged('bundlesdf_isolated_bundletrack_build', docker(['cmake', '--build',
           '/workspace/BundleSDF/BundleTrack/build_deploy_20261013', '--parallel', '4']))
    # Official imports expect BundleTrack/build. New checkout has no previous build to overwrite.
    destination = CODE / 'BundleTrack/build'
    if destination.exists():
        raise FileExistsError(str(destination))
    destination.symlink_to('build_deploy_20261013', target_is_directory=True)

def verify():
    logged('bundlesdf_isolated_import_help', docker([PYTHON, 'run_custom.py', '--help'], '/workspace/BundleSDF'))
    logged('bundlesdf_isolated_versions', docker([PYTHON, '-m', 'pip', 'show', 'torch', 'kaolin', 'common', 'dearpygui']))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', required=True, choices=['source', 'create', 'deps', 'patch', 'build', 'verify'])
    args = parser.parse_args()
    if not ROOT.is_dir():
        raise RuntimeError('Unexpected host root')
    globals()[args.stage]()

if __name__ == '__main__':
    main()
