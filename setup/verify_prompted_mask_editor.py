"""Regression for repeated SAM proposals, old saved masks and reconstruction replay."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageDraw
from manual_mask_editor import Editor, atomic_bytes, atomic_json, mask_bytes, sha


class SyntheticSam:
    def generate(self, editor, frame, value):
        mask = Image.new('L', tuple(frame['size']))
        x, y, width, height = value['rect']
        ImageDraw.Draw(mask).rectangle((x, y, x + width, y + height), fill=255)
        content = mask_bytes(mask)
        folder = editor.output / 'sam_attempts' / hashlib.sha256(content).hexdigest()
        folder.mkdir(parents=True, exist_ok=True)
        atomic_bytes(folder / 'mask.png', content)
        return dict(frame, mask_sha256=sha(folder / 'mask.png'), backend='synthetic_sam_test',
                    artifact=(folder / 'mask.png').relative_to(editor.output).as_posix())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    scene, manual = args.output / 'scene', args.output / 'manual'
    for directory in ('rgb', 'depth'):
        (scene / directory).mkdir(parents=True)
    for index in range(72):
        name = '%06d.png' % index
        Image.new('RGB', (640, 480), (100, 140, 180)).save(scene / 'rgb' / name)
        Image.new('I;16', (640, 480), 450).save(scene / 'depth' / name)
    editor = Editor(scene, manual)
    original_files = {path: sha(path) for path in scene.rglob('*.png')}
    try:
        editor.sam = SyntheticSam()
        first = editor.segment(dict(index=0, rect=[200, 200, 150, 150], points=[], labels=[]))
        operations = [dict(type='proposal', proposal_id=first['proposal_id'])]
        preview = editor.preview(dict(index=0, operations=operations))
        assert preview['mask_sha256'] == first['mask_sha256']
        editor.save(dict(index=0, operations=operations, base_revision=None, confirmed=True,
                         preview_sha256=preview['mask_sha256']))
        saved_revision = editor.state['000000.png']
        saved_bytes = (manual / 'revisions' / saved_revision / 'mask.png').read_bytes()
        second = editor.segment(dict(index=0, rect=[210, 210, 120, 120], points=[], labels=[]))
        assert first['proposal_id'] != second['proposal_id']
        detail = editor.detail(0)
        assert detail['proposals'][0]['id'] == first['proposal_id']
        assert detail['proposal']['id'] == second['proposal_id']
        assert base64.b64decode(detail['mask_png']) == saved_bytes
        for index in range(1, 72):
            operations = [dict(type='polygon', value=255, points=[[200, 200], [350, 200], [350, 350], [200, 350]])]
            preview = editor.preview(dict(index=index, operations=operations))
            editor.save(dict(index=index, operations=operations, base_revision=None, confirmed=True,
                             preview_sha256=preview['mask_sha256']))
    finally:
        editor.close()
    resumed = Editor(scene, manual)
    try:
        assert resumed.detail(0)['revision'] == saved_revision
        assert resumed.preview(dict(index=0, operations=[dict(type='proposal', proposal_id=first['proposal_id'])]))['mask_sha256'] == first['mask_sha256']
        assert len(resumed.state) == 72
    finally:
        resumed.close()
    subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('audit_reviewed_cup_masks.py')),
                    '--scene', str(scene), '--masks', str(manual), '--output', str(args.output / 'audit')], check=True)
    retained = json.loads((args.output / 'audit/proposal_index.json').read_text())['frames']
    assert len(retained) == 1 and retained[0]['proposal_id'] == first['proposal_id']
    assert sha(args.output / 'audit' / retained[0]['artifact']) == first['mask_sha256']
    assert (manual / 'revisions' / saved_revision / 'mask.png').read_bytes() == saved_bytes
    assert all(sha(path) == digest for path, digest in original_files.items())
    report = dict(passed=True, scope='synthetic_proposal_history_and_72_frame_reconstruction_audit',
                  repeated_proposals_preserved=True, saved_revision_preserved=True,
                  source_rgb_depth_unchanged=True, actual_human_annotations_modified=False)
    atomic_json(args.output / 'report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
