#!/usr/bin/env python3
"""Check pinned mesh switching and changed-file rejection before live camera use."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from cup_mesh_selection import MESH_PROFILES,resolve_mesh


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    data=args.root.resolve()/'foundationpose_data'
    selections={name:resolve_mesh(data,name) for name in MESH_PROFILES}
    assert selections['legacy']['sha256'] != selections['redcup72']['sha256']
    with tempfile.TemporaryDirectory(prefix='mesh_selection_',dir=str(data)) as folder:
        base=Path(folder)
        target=base/MESH_PROFILES['redcup72']['relative'];target.parent.mkdir(parents=True)
        target.write_text('changed mesh must never be accepted\n')
        try:resolve_mesh(base,'redcup72')
        except ValueError:rejected=True
        else:raise AssertionError('Changed mesh accepted')
    sources={name:hashlib.sha256((args.root/'setup'/name).read_bytes()).hexdigest()
             for name in ['run_cup_live.py','run_cup_live_fast.py','cup_mesh_selection.py']}
    report=dict(passed=True,selections=selections,changed_mesh_rejected=rejected,source_sha256=sources,
                camera_access=False,pose_accuracy_validated=False)
    with args.output.open('x') as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
