#!/usr/bin/env python3
"""Archive isolated image identity, pinned code/adaptations, assets and package list."""
import hashlib
import json
from pathlib import Path
import subprocess
from deploy_bundlesdf_isolated_20261013 import ROOT, CODE, AUDIT, CONTAINER, PYTHON, docker, logged

def capture(argv):
    return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip()

tag = 'foundationpose-bundlesdf:ready-20261013'
if capture(['docker', 'images', '--quiet', tag]):
    raise RuntimeError('Preserve existing ready image tag: '+tag)
logged('bundlesdf_isolated_ready_image', ['docker', 'commit', CONTAINER, tag])
sources = ['mycuda/setup.py', 'BundleTrack/CMakeLists.txt', 'BundleTrack/src/FeatureManager.h',
           'BundleTrack/src/FeatureManager.cpp', 'BundleTrack/src/Utils.cpp', 'run_custom.py', 'bundlesdf.py', 'loftr_wrapper.py']
manifest = {'source_pin': capture(['git', '-C', str(CODE), 'rev-parse', 'HEAD']),
            'git_status': capture(['git', '-C', str(CODE), 'status', '--short']),
            'code_directory': str(CODE), 'container': CONTAINER, 'ready_image': tag,
            'ready_image_id': capture(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag]),
            'parent_image_id': capture(['docker', 'inspect', '--format', '{{.Image}}', CONTAINER]),
            'source_sha256': {name: hashlib.sha256((CODE/name).read_bytes()).hexdigest() for name in sources},
            'required_launch_environment': {'LD_PRELOAD': '/usr/lib/x86_64-linux-gnu/libffi.so.7'},
            'python': PYTHON, 'working_directory': '/workspace/BundleSDF',
            'package_list': json.loads(capture(docker([PYTHON, '-m', 'pip', 'list', '--format=json']))),
            'native_package_versions': capture(docker(['dpkg-query', '-W', 'libpcl-dev', 'libopencv-dev', 'libyaml-cpp-dev', 'libzmq3-dev', 'libeigen3-dev'])),
            'gpu_reconstruction_performed': False, 'inference_weights_retrained': False,
            'known_scope_limit': 'Optional legacy SIFT descriptor matching uses CPU; active GluNet/LoFTR and CUDA RANSAC retained.'}
manifest['compiled_extensions'] = {}
for directory in [CODE/'mycuda', CODE/'BundleTrack/build_deploy_20261013']:
    for path in directory.glob('*.so'):
        manifest['compiled_extensions'][str(path.relative_to(CODE))] = hashlib.sha256(path.read_bytes()).hexdigest()
asset = CODE/'BundleTrack/LoFTR/weights/outdoor_ds.ckpt'
manifest['loftr_asset'] = {'path': str(asset), 'size': asset.stat().st_size,
                          'sha256': hashlib.sha256(asset.read_bytes()).hexdigest(),
                          'official_file_id': '1M-VD35-qdB5Iw-AtbDBCKC7hPolFW9UY'}
output = AUDIT/'environment_ready_manifest.json'
if output.exists():
    raise FileExistsError(str(output))
output.write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps({key:value for key,value in manifest.items() if key != 'package_list'}, indent=2))
