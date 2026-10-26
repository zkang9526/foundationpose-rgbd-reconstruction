"""Snapshot committed human revisions and attach unconfirmed immutable SAM drafts."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from manual_mask_editor import Editor, atomic_json, e_path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manual',type=Path,required=True)
    p.add_argument('--drafts',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    source,drafts,output=map(e_path,(args.manual,args.drafts,args.output))
    manifest=json.loads((source/'manual_editor.json').read_text(encoding='utf-8'))
    state_bytes=(source/'state.json').read_bytes() if (source/'state.json').exists() else b'{}'
    state=json.loads(state_bytes)
    report=json.loads((drafts/'report.json').read_text())
    if not report['passed'] or not report['draft_only'] or report['human_confirmed']:
        raise ValueError('Expected complete machine drafts, never a human acceptance report')
    originals={f['frame']:f for f in manifest['frames']}
    if set(state)-set(originals) or {f['frame'] for f in report['frames']} != set(originals):
        raise ValueError('Human/draft frame lists differ')
    output.mkdir(parents=True,exist_ok=False)
    (output/'revisions').mkdir()
    (output/'proposals'/'masks').mkdir(parents=True)
    shutil.copy2(source/'manual_editor.json',output/'manual_editor.json')
    (output/'state.json').write_bytes(state_bytes)
    copied={}
    for revision in state.values():
        while revision and revision not in copied:
            if not re.fullmatch(r'[0-9]{8}T[0-9]{12}Z_[0-9a-f]{16}',revision):
                raise ValueError('Unexpected human revision ID')
            folder=source/'revisions'/revision
            annotation=json.loads((folder/'annotation.json').read_text(encoding='utf-8'))
            if sha(folder/'mask.png') != annotation['mask_sha256']:
                raise ValueError('Human revision SHA changed')
            shutil.copytree(folder,output/'revisions'/revision)
            copied[revision]={name:sha(folder/name) for name in ('mask.png','annotation.json')}
            revision=annotation['previous_revision']
    entries=[]
    report_sha=sha(drafts/'report.json')
    for item in report['frames']:
        original=originals[item['frame']]
        if any(item[k] != original[k] for k in ('source_rgb_sha256','source_depth_sha256','size')):
            raise ValueError('Draft RGB/depth source differs from human editor')
        name=item['frame']
        path=drafts/'masks'/name
        if sha(path) != item['mask_sha256']:
            raise ValueError('Draft mask SHA changed')
        shutil.copy2(path,output/'proposals'/'masks'/name)
        entries.append(dict(item,proposal_id=hashlib.sha256((name+':'+item['mask_sha256']).encode()).hexdigest(),
            backend=report['backend'],generator_report_sha256=report_sha,human_confirmed=False,
            masks_are_pose_ground_truth=False))
    shutil.copy2(drafts/'report.json',output/'proposals'/'generator_report.json')
    atomic_json(output/'proposals'/'index.json',dict(draft_only=True,human_confirmed=False,frames=entries))
    atomic_json(output/'imported_from.json',dict(source_manual_output=str(source),
        source_state_sha256=hashlib.sha256(state_bytes).hexdigest(),human_confirmations_preserved=len(state),
        revisions=copied,source_manual_unchanged=True,draft_source=str(drafts),draft_report_sha256=report_sha))
    editor=Editor(Path(manifest['source_scene']),output)
    try:
        for i,frame in enumerate(editor.frames):
            item=editor.proposals_by_frame[frame['frame']]
            editor.proposal(frame,item['proposal_id'])
        status=editor.report()
        print(json.dumps(dict(prepared=True,output=str(output),total_frames=status['total_frames'],
            prior_human_confirmed=status['confirmed_frames'],machine_drafts=len(entries),new_confirmations=0)))
    finally:
        editor.close()


if __name__=='__main__':
    main()
