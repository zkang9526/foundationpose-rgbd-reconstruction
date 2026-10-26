#!/usr/bin/env python3
"""Append shared phase evidence and commit only reviewed changes on Ubuntu."""
import hashlib
import json
from pathlib import Path
from stage_reviewed_reconstruction import remote, run, SSH, HOST, REMOTE


def main():
    root=Path(__file__).resolve().parent.parent
    folder=REMOTE+'/foundationpose_data/derived/redcup_handle_motion_notes_20261018'
    report_names=['RED_CUP_HANDLE_DASHBOARD_FIX_20261018.md','RED_CUP_CAMERA_MOTION_REVIEW_20261018.md',
                  'RED_CUP_HANDLE_MOTION_EXPERIMENT_20261018.md','RED_CUP_HANDLE_MOTION_ISSUES_20261018.md']
    sources=['cup_live_dashboard.py','run_cup_live_fast.py','run_cup_live_redcup72.sh','run_cup_live_worker.py',
             'cup_handle_yaw.py','verify_cup_dashboard_restart.py','verify_cup_dashboard_image_race.py','verify_cup_yaw_worker.py',
             'review_live_handle_failure.py','compare_cup_handle_yaw.py','review_saved_camera_motion.py']
    extra=[root/'reports/redcup_camera_only_review_v2_20261018/report.json',
           root/'reports/redcup_handle_worker_check_20261018/report.json',
           root/'reports/dashboard_image_race_protocol_final_20261018/report.json']
    remote('redcup_handle_motion_notes_stage',['mkdir',folder])
    files=[root/'reports'/n for n in report_names]+[root/'setup'/n for n in sources]
    run(['scp']+SSH+[str(f) for f in files]+[HOST+':'+folder+'/'])
    for path in extra:
        run(['scp']+SSH+[str(path),HOST+':'+folder+'/'+path.parent.name+'_report.json'])
    expected={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    for path in extra:expected[path.parent.name+'_report.json']=hashlib.sha256(path.read_bytes()).hexdigest()
    guide_marker='<!-- RED-CUP-HANDLE-MOTION-20261018 -->'
    guide_addition=guide_marker+root.joinpath('REPRODUCTION_GUIDE.md').read_text(encoding='utf-8').split(guide_marker,1)[1]
    code='''from pathlib import Path
import hashlib,shutil,subprocess
root=Path(ROOT);stage=Path(STAGE);expected=EXPECTED;names=SOURCES;reports=REPORTS
assert all(hashlib.sha256((stage/n).read_bytes()).hexdigest()==s for n,s in expected.items()),'Notes/source transfer hash mismatch'
assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=root,text=True).strip(),'Existing staged changes must be preserved'
for n in names:
 destination=root/'setup'/n
 if destination.exists():assert destination.read_bytes()==(stage/n).read_bytes(),'Installed source differs: '+n
 else:shutil.copy2(stage/n,destination)
for n in reports:
 destination=root/'reports'/n
 if destination.exists():assert destination.read_bytes()==(stage/n).read_bytes(),'Existing phase report differs'
 else:shutil.copy2(stage/n,destination)
guide=root/'REPRODUCTION_GUIDE.md'
if MARKER not in guide.read_text():
 with guide.open('a') as stream:stream.write('\\n'+ADDITION+'\\n')
logger=root/'setup/run_logged.py';original=logger.read_text()
missing=[n for n in names if repr(n) not in original]
if missing:logger.write_text(original.replace('SOURCE_NAMES = (','SOURCE_NAMES = (\\n    '+', '.join(repr(n) for n in missing)+',',1))
print('SHA verified; source and curated notes archived, separate journals preserved')
'''.replace('ROOT',repr(REMOTE)).replace('STAGE',repr(folder)).replace('EXPECTED',repr(expected)).replace('SOURCES',repr(sources)).replace('REPORTS',repr(report_names)).replace('MARKER',repr(guide_marker)).replace('ADDITION',repr(guide_addition))
    remote('redcup_handle_motion_archive_sources',['python3','-B','-c',code])
    remote('redcup_handle_motion_journal_append',['python3','setup/append_manual_records.py','--root',REMOTE,
        '--event-id','RED-CUP-HANDLE-MOTION-20261018',
        '--experiment',folder+'/'+report_names[2],'--issues',folder+'/'+report_names[3]])
    paths=['setup/'+n for n in sources]+['setup/run_logged.py','REPRODUCTION_GUIDE.md']+['reports/'+n for n in report_names]
    remote('redcup_handle_motion_stage_paths',['git','add','--']+paths)
    remote('redcup_handle_motion_commit',['git','commit','-m','fix: keep live status responsive and validate cup handle yaw'])
    remote('redcup_handle_motion_commit_head',['git','log','-1','--oneline'])


if __name__=='__main__':main()
