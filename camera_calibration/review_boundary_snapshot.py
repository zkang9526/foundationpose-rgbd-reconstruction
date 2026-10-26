"""Apply an explicit human RGB board-perimeter annotation to a saved snapshot.

This diagnostic neither edits inputs nor returns a physical calibration pass.
"""
import argparse
import json
from pathlib import Path

from boundary import check_boundary
from common import sha, snapshot_sources, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--annotation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    meta = json.loads((args.input / 'factory.json').read_text(encoding='utf-8'))
    annotation = json.loads(args.annotation.read_text(encoding='utf-8'))
    trial = args.input / 'trials' / annotation['trial']
    evidence = json.loads((trial / 'trial.json').read_text(encoding='utf-8'))
    for item in evidence['files']:
        if sha(trial / item['name']) != item['sha256']:
            raise ValueError('Original evidence changed: ' + item['name'])
    result = check_boundary(trial, annotation['vertices_rgb_px'], meta['depth_scale_m'], args.output)
    result['annotation'] = annotation
    result['annotation_sha256'] = sha(args.annotation)
    result['source_factory_sha256'] = sha(args.input / 'factory.json')
    result['source_trial_sha256'] = sha(trial / 'trial.json')
    result['projector_enabled'] = meta['depth_options'].get('emitter_enabled')
    result['source_was_accepted_for_calibration'] = evidence['accepted']
    result['scope'] = 'Single snapshot with user-reported stillness; no automatic stationarity verification. Manual perimeter uncertainty and depth occlusion affect these offsets.'
    result['excluded_from_interpretation_edges'] = annotation.get('excluded_edges', [])
    snapshot_sources(args.output)
    write_json(args.output / 'boundary.json', result)
    print(json.dumps(dict(output=str(args.output), physical_calibration_accepted=False,
                          edges=result['edges'], excluded_edges=annotation.get('excluded_edges', []))))


if __name__ == '__main__':
    main()
