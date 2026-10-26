#!/usr/bin/env python3
"""Verify recorded pilot artifacts and limitations, without claiming pose accuracy."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path('/data/ZJC/foundationPos')


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def translated(path):
    source = Path(path)
    if source == Path('/data') or Path('/data') in source.parents:
        target = ROOT / 'foundationpose_data' / source.relative_to('/data')
    elif Path('/workspace/FoundationPose') in source.parents:
        target = ROOT / 'FoundationPose' / source.relative_to('/workspace/FoundationPose')
    else:
        raise ValueError('Unrecognized container source path: ' + str(path))
    target = target.resolve(strict=True)
    if ROOT not in target.parents:
        raise ValueError('Source resolves outside project')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Preserve prior evidence; output must be new')
    result = {'passed': False, 'scope': 'saved artifacts, run exits, provenance and documented limitations',
              'reliable_cup_reproduction_complete': False, 'pose_ground_truth_available': False,
              'network_pose_training_performed': False, 'artifact_checks': [], 'quality': [], 'runs': []}
    data = ROOT / 'foundationpose_data'
    inference = load(data / 'derived/cup_fp_heldout5_pilot_v1_20261013_2208/report.json')
    if inference.get('passed') is not True or inference.get('completed_frames') != 5:
        raise ValueError('Official five-frame inference is incomplete')
    for item in inference['frames']:
        for key in ('pose', 'obb_display_pose', 'visualization'):
            information = item[key]
            path = translated(information['path'])
            if sha(path) != information['sha256']:
                raise ValueError('Inference output changed: ' + str(path))
        for information in item['inputs'].values():
            if sha(translated(information['path'])) != information['sha256']:
                raise ValueError('Inference input changed')
        result['artifact_checks'].append({'frame': item['id'], 'passed': True,
                                         'rigid_matrix_validation': item['validation'],
                                         'pose_accuracy_validated': False})
    for information in [inference['source_mesh']] + list(inference['capture_sources'].values()):
        if sha(translated(information['path'])) != information['sha256']:
            raise ValueError('Provenance changed after inference')
    for name, weight in inference['weights'].items():
        if not weight['loaded']:
            raise ValueError('Weight loading was not verified')
        for key in ('checkpoint', 'config'):
            information = weight[key]
            if sha(translated(information['path'])) != information['sha256']:
                raise ValueError('Pretrained weight/config changed')
        result.setdefault('weights', {})[name] = weight['checkpoint']['sha256']
    for folder in ('cup_mesh_local_preview_v4_20261013', 'cup_mesh_local_preview_top36_v1_20261013',
                   'cup_mesh_local_preview_frozen_pose_v1_20261014'):
        qa_path = data / 'derived' / folder / 'visual_qa_final.json'
        qa = load(qa_path)
        if qa.get('rejected_for_reliable_reconstruction') is not True:
            raise ValueError('Saved mesh quality verdict differs from reported limitation')
        result['quality'].append({'artifact': folder, 'sha256': sha(qa_path),
                                  'rejected_for_reliable_reconstruction': True})
    for run_id, expected in (
        ('20261013_215033_528375_cup_bundlesdf_side36_reconstruction_v4_7f5f2c18', 139),
        ('20261013_222110_086300_cup_bundlesdf_top36_reconstruction_v1_fa1ecdb0', 139),
        ('20261013_223900_962145_cup_side36_frozen_neural_pose_experiment_febbc694', 139),
        ('20261013_220903_425564_cup_foundationpose_heldout5_pilot_v1_a757ba18', 0),
        ('20261013_221830_974291_cup_fp_heldout5_candidates_side_v1_78d7c842', 0),
    ):
        report = load(data / 'runs' / run_id / 'run.json')
        if report.get('exit_code') != expected or not report.get('end'):
            raise ValueError('Unexpected recorded process status: ' + run_id)
        result['runs'].append({'run_id': run_id, 'exit_code': expected, 'status': report['status']})
    recovery = load(data / 'incoming/cup_complete_batch_20261013_2055/recovery_report.json')
    if not recovery.get('passed') or recovery.get('final_verified_output_files') != 6380:
        raise ValueError('Full import recovery evidence is incomplete')
    result['full_import_final_verified_files'] = 6380
    for name in ('EXPERIMENT_LOG.md', 'ISSUES.md'):
        text = (ROOT / name).read_text(encoding='utf-8')
        if '<!-- CUP-PILOT-QUALITY-20261014 -->' not in text:
            raise ValueError('Pilot summary missing from ' + name)
    for name in ('CUP_UBUNTU_RECONSTRUCTION_20261013.md', 'reports/CUP_POSE_PILOT_RESULTS_20261014.md'):
        path = ROOT / name
        result.setdefault('guides', []).append({'path': str(path), 'sha256': sha(path)})
    gpu = subprocess.run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader'],
                         capture_output=True, text=True, check=True)
    result['gpu_inventory'] = gpu.stdout.strip()
    result['containers'] = {}
    for container in ('foundationpose', 'foundationpose-bundlesdf'):
        state = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', container],
                               capture_output=True, text=True, check=True)
        if state.stdout.strip() != 'true':
            raise ValueError('Container is not running: ' + container)
        result['containers'][container] = 'running'
    result.update(passed=True, cleanup_139_resolved=False, mesh_quality_passed=False,
                  official_independent_inference_completed_frames=5,
                  custom_mask_selection_is_official_baseline=False,
                  existing_server_journals_replaced=False)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
