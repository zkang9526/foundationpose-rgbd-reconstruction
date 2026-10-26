"""Synthetic regression of immutable proposal bases plus human editing/confirmation."""
import argparse
import hashlib
import json
from pathlib import Path
from PIL import Image
from manual_mask_editor import Editor, atomic_json


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    scene,out=args.output/'scene',args.output/'annotations'
    for folder in ('rgb','depth'):
        (scene/folder).mkdir(parents=True)
    for i in range(2):
        Image.new('RGB',(80,60),(100,140,180)).save(scene/'rgb'/('%06d.png'%i))
        Image.new('I;16',(80,60),450).save(scene/'depth'/('%06d.png'%i))
    editor=Editor(scene,out)
    frames=editor.frames
    editor.close()
    (out/'proposals'/'masks').mkdir(parents=True)
    entries=[]
    for frame in frames:
        mask=Image.new('L',(80,60),0)
        mask.paste(255,(10,10,65,50))
        path=out/'proposals'/'masks'/frame['frame']
        mask.save(path)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(dict(frame,mask_sha256=digest,proposal_id=hashlib.sha256((frame['frame']+':'+digest).encode()).hexdigest(),
            backend='synthetic_only',human_confirmed=False))
    atomic_json(out/'proposals'/'index.json',dict(frames=entries))
    editor=Editor(scene,out)
    tests=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        tests.append(name)
    try:
        check('drafts_do_not_confirm_frames',len(editor.state)==0 and not editor.detail(0)['confirmed'])
        check('same_mask_on_two_frames_has_distinct_source_binding',entries[0]['proposal_id']!=entries[1]['proposal_id'])
        operation=dict(type='proposal',proposal_id=entries[0]['proposal_id'])
        preview=editor.preview(dict(index=0,operations=[operation]))
        check('proposal_preview_matches_original_binary_exactly',preview['mask_sha256']==entries[0]['mask_sha256'])
        try:editor.preview(dict(index=1,operations=[operation]))
        except ValueError:tests.append('cross_frame_proposal_rejected')
        else:raise AssertionError('Cross-frame source accepted')
        hole=dict(type='polygon',value=0,points=[[25,20],[40,20],[40,35],[25,35]])
        operations=[operation,hole]
        check('manual_background_hole_on_proposal',editor.render(frames[0],operations).getpixel((30,25))==0)
        check('undo_retains_unmodified_proposal',editor.render(frames[0],operations[:-1]).getpixel((30,25))==255)
        preview=editor.preview(dict(index=0,operations=operations))
        payload=dict(index=0,base_revision=None,operations=operations,confirmed=False,preview_sha256=preview['mask_sha256'])
        try:editor.save(payload)
        except ValueError:tests.append('machine_draft_cannot_bypass_human_confirmation')
        else:raise AssertionError('Unconfirmed draft saved as human')
        saved=editor.save(dict(payload,confirmed=True))
        annotation=json.loads((out/'revisions'/saved['revision']/'annotation.json').read_text())
        check('human_review_records_machine_provenance',annotation['annotation_method']=='machine_draft_human_review'
              and annotation['proposal_sources'][0]['proposal_id']==entries[0]['proposal_id'])
        path=out/'proposals'/'masks'/frames[1]['frame']
        Image.new('L',(80,60),255).save(path)
        try:editor.detail(1)
        except ValueError:tests.append('changed_proposal_sha_rejected')
        else:raise AssertionError('Changed draft accepted')
    finally:editor.close()
    result=dict(passed=True,scope='synthetic proposal provenance and editing only',tests=tests,
                test_count=len(tests),actual_cup_masks_human_confirmed=False)
    (args.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
