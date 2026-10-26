#!/usr/bin/env python3
"""Append the verified environment scope to Ubuntu's existing environment guide."""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve(strict=True)
report = json.loads((root / 'reports/OBJ_SETUP_SUMMARY_20261014.json').read_text(encoding='utf-8'))
if report.get('passed') is not True or report.get('real_object_obj_ready') is not False:
    raise RuntimeError('Expected passed environment-only report')
marker = '<!-- OBJ-ENVIRONMENT-20261014 -->'
path = root / 'Ubuntu_environment.md'
existing = path.read_text(encoding='utf-8')
if marker not in existing:
    with path.open('a', encoding='utf-8') as stream:
        stream.write('\n' + marker + '\n## 2026-10-14 Windows采集、Ubuntu OBJ环境复验\n\n'
                     '沿用原生foundationpose环境（Python3.11.14、Open3D0.19.0、NumPy2.1.3、'
                     'OpenCV4.11.0.86、trimesh5.1.1、PyTorch2.4.1+cu121），无Ubuntu依赖重装。'
                     '实际ICP、位姿图、合成TSDF、米制OBJ往返和RTX3090 CUDA运算通过。'
                     '新增自动留档入口setup/run_obj_environment_check.sh；Windows新入口'
                     'setup/start_obj_photos.ps1保留原始深度，可选原生bag与独立滤波深度。'
                     '这是环境测试，实物几何QA与BundleSDF退出139仍未解决。'
                     '版本、命令与证据见[OBJ配置说明](reports/OBJ_ENVIRONMENT_SETUP_20261014.md)。\n')
print('Ubuntu environment note appended or already present:', marker)
