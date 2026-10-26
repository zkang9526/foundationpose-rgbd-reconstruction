#!/usr/bin/env python3
"""Inspect and stage the new cup model live test without changing old models."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from stage_reviewed_reconstruction import remote,run,SSH,HOST,REMOTE


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect','preflight','fetch-preflight','deploy','open-interface','archive-interface','review-handle','evaluate-motion','compare-yaw','stage-handle-fix','test-handle-fix','install-handle-fix','start','status','preview','control','baseline','analyze','archive-notes','git-status','git-commit','fetch'])
    p.add_argument('--session',required=True,help='Unique simple session identifier')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--control',choices=['freeze','mask','initialize','pause','stop'])
    p.add_argument('--payload',type=Path)
    p.add_argument('--code-revision',choices=['v1','v2'],default='v1')
    p.add_argument('--tracking-only',action='store_true',help='Do not calculate fixed-marker scene errors when object/marker relative position can change')
    args=p.parse_args()
    if not args.session.replace('_','').isalnum():raise ValueError('Simple unique session identifier required')
    root=Path(__file__).resolve().parent.parent
    data=REMOTE+'/foundationpose_data/'
    stage=data+'derived/'+args.session+'_launch'
    session=data+'live_sessions/'+args.session
    fix_folder=stage+'/handle_fix_code'+('' if args.code_revision=='v1' else '_'+args.code_revision)
    if args.action=='inspect':
        code='''import json,subprocess,hashlib,shutil
from pathlib import Path
import pyrealsense2 as rs
root=Path(ROOT)
names=['run_cup_live.py','run_cup_live_fast.py','run_cup_live_worker.py','cup_live_dashboard.py','run_cup_live_aruco_id6.sh']
devices=[]
for d in rs.context().query_devices():
 devices.append({str(k):d.get_info(k) for k in [rs.camera_info.name,rs.camera_info.serial_number,rs.camera_info.usb_type_descriptor] if d.supports(k)})
processes=subprocess.check_output(['ps','-eo','pid,etimes,args'],text=True).splitlines()
active=[x for x in processes if any(t in x for t in ['setup/run_cup_live_fast.py','setup/run_cup_live.py','realsense-viewer','setup/capture_d435i.py']) and 'python -c' not in x]
gpu=subprocess.run(['nvidia-smi','--query-gpu=name,memory.used,memory.total,utilization.gpu','--format=csv,noheader'],capture_output=True,text=True)
print(json.dumps(dict(devices=devices,active_camera_processes=active,gpu=gpu.stdout.strip(),free_data_gib=shutil.disk_usage(root).free/1024**3,source_sha256={n:hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest() for n in names},containers=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()),indent=2))
'''.replace('ROOT',repr(REMOTE))
        remote('redcup_live_readiness',['.camera-venv/bin/python','-B','-c',code])
    elif args.action=='preflight':
        remote('redcup_live_short_scene_preflight',['.camera-venv/bin/python','-B','setup/inspect_cup_aruco_scene.py',
            '--root',REMOTE,'--capture','--frames','15','--marker-id','6','--length-m','0.030',
            '--output',data+'derived/'+args.session+'_preflight'])
    elif args.action=='fetch-preflight':
        args.output.mkdir(parents=True,exist_ok=False)
        source=data+'derived/'+args.session+'_preflight/'
        for name in ['report.json','preview_000000.png','preview_000007.png','preview_000014.png']:
            run(['scp']+SSH+[HOST+':'+source+name,str(args.output/name)])
    elif args.action=='deploy':
        names=['run_cup_live.py','run_cup_live_fast.py','cup_mesh_selection.py','run_cup_live_redcup72.sh','verify_cup_mesh_selection.py']
        remote('redcup_live_launch_code_directory',['mkdir',stage])
        run(['scp']+SSH+[str(root/'setup'/n) for n in names]+[HOST+':'+stage+'/'])
        hashes={n:hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest() for n in names}
        # Baselines are the exact previously committed versions, not unchecked server files.
        baseline={n:hashlib.sha256(subprocess.check_output(['git','show','HEAD:setup/'+n],cwd=root)).hexdigest() for n in names[:2]}
        code='''from pathlib import Path
import hashlib,json,shutil
root=Path(ROOT);stage=Path(STAGE);expected=EXPECTED;baseline=BASELINE
assert all(hashlib.sha256((stage/n).read_bytes()).hexdigest()==s for n,s in expected.items()),'Stage SHA mismatch'
for n,s in baseline.items():
 assert hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest()==s,'Remote code differs; preserve and review '+n
backup=stage/'previous_setup';backup.mkdir()
for n in expected:
 dest=root/'setup'/n
 if dest.exists():shutil.copy2(dest,backup/n)
 shutil.copy2(stage/n,dest)
assert all(hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest()==s for n,s in expected.items())
(stage/'deployment.json').write_text(json.dumps(dict(installed_sha256=expected,previous_sha256=baseline),indent=2)+'\\n')
print('Installed reviewed code; previous source preserved')
'''.replace('ROOT',repr(REMOTE)).replace('STAGE',repr(stage)).replace('EXPECTED',repr(hashes)).replace('BASELINE',repr(baseline))
        remote('redcup_live_code_install',['python3','-B','-c',code])
        remote('redcup_live_mesh_selection_verify',['.camera-venv/bin/python','-B','setup/verify_cup_mesh_selection.py','--root',REMOTE,'--output',stage+'/selection_check.json'])
        remote('redcup_live_entry_syntax',['bash','-n','setup/run_cup_live_redcup72.sh'])
        remote('redcup_live_entry_mesh_help',['.camera-venv/bin/python','-B','setup/run_cup_live_fast.py','--help'])
    elif args.action=='open-interface':
        code=r'''from pathlib import Path
import json,os,signal,subprocess,sys,time,urllib.request
root=Path(ROOT);stage=Path(STAGE);session=Path(SESSION)
stage.mkdir(parents=True,exist_ok=False)
base='http://127.0.0.1:8765'
def status():
 try:
  with urllib.request.urlopen(base+'/status',timeout=3) as stream:return json.loads(stream.read())
 except (OSError,ValueError):return None
existing=status()
report=dict(requested_session=str(session),previous_interface=existing,viewer_closed=[])
if existing is not None:
 current=Path(existing['output']);current.resolve().relative_to((root/'foundationpose_data/live_sessions').resolve())
 manifest=json.loads((current/'session.json').read_text())
 if manifest.get('mesh_profile')!='redcup72':raise RuntimeError('Existing interface uses another mesh; preserved for review')
 if existing.get('state')=='paused':
  # A fresh freeze/mask is required after camera changes; leave the user in control.
  report['requires_fresh_initialization']=True
 report.update(reused_existing_interface=True,session=str(current))
else:
 expected=(root/'foundationpose_data/tools/realsense_viewer_20261018_v2/root/usr/bin/realsense-viewer').resolve()
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit():continue
  try:
   if proc.stat().st_uid!=os.getuid() or (proc/'exe').resolve()!=expected:continue
   pid=int(proc.name);os.kill(pid,signal.SIGTERM);report['viewer_closed'].append(pid)
  except (OSError,ValueError):pass
 deadline=time.monotonic()+10
 while any(Path('/proc',str(pid)).exists() for pid in report['viewer_closed']) and time.monotonic()<deadline:time.sleep(.2)
 if any(Path('/proc',str(pid)).exists() for pid in report['viewer_closed']):raise RuntimeError('Viewer did not stop gracefully; no forced termination or new camera start')
 command=['bash','setup/run_cup_live_redcup72.sh','--output',str(session),'--duration-seconds','3600','--max-frames','10000']
 if TRACKING_ONLY:command.append('--no-aruco-fixed-scene')
 log=(stage/'launcher_stdout.log').open('xb')
 launch_env=os.environ.copy()
 if TRACKING_ONLY:launch_env['FP_RUN_NOTE']='User reported changing cup/marker relative position; tracking-only test, no fixed-scene ArUco error metrics. New redcup72 mesh, SAM2 and experimental init yaw check; no absolute accuracy acceptance.'
 process=subprocess.Popen(command,cwd=root,env=launch_env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
 report.update(reused_existing_interface=False,session=str(session),pid=process.pid,command=command)
 (stage/'launcher.json').write_text(json.dumps(report,indent=2)+'\n')
 deadline=time.monotonic()+110
 while time.monotonic()<deadline:
  actual=status()
  if actual and actual.get('output')==str(session) and actual.get('state')=='waiting_for_roi':break
  if process.poll() is not None:raise RuntimeError('New interface exited; inspect preserved launcher/worker output')
  time.sleep(.3)
 else:raise TimeoutError('New GPU interface not ready within 110s; logs preserved')
actual=status();manifest=json.loads((Path(report['session'])/'session.json').read_text())
report.update(interface_status=actual,mesh_profile=manifest.get('mesh_profile'),mesh_sha256=manifest.get('mesh_sha256'),camera_connected=manifest.get('camera_connected'))
if report['mesh_profile']!='redcup72' or not report['camera_connected']:raise RuntimeError('Actual model/camera did not match requested live interface')
sys.path.insert(0,str(root/'setup'))
from install_realsense_viewer_user import desktop_environment
env=os.environ.copy();env.update(desktop_environment())
with (stage/'browser_stdout.log').open('xb') as stream:
 browser=subprocess.Popen(['xdg-open',base],env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
report.update(browser_open_dispatched=True,browser_launcher_pid=browser.pid,preview_url=base)
(stage/'interface_ready.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
'''.replace('ROOT',repr(REMOTE)).replace('STAGE',repr(stage)).replace('SESSION',repr(session)).replace('TRACKING_ONLY',repr(args.tracking_only))
        remote('redcup_live_interface_handoff',['python3','-B','-c',code])
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+stage+'/interface_ready.json',str(args.output/'interface_ready.json')])
    elif args.action=='stage-handle-fix':
        folder=fix_folder
        names=['run_cup_live_fast.py','run_cup_live_worker.py','cup_live_dashboard.py','cup_handle_yaw.py',
               'verify_cup_yaw_worker.py','verify_cup_dashboard_image_race.py','verify_cup_dashboard_restart.py','run_cup_live_redcup72.sh']
        remote('redcup_handle_fix_code_directory',['mkdir',folder])
        files=[root/'setup'/name for name in names]
        run(['scp']+SSH+[str(f) for f in files]+[HOST+':'+folder+'/'])
        hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        code='from pathlib import Path;import hashlib,json;p=Path('+repr(folder)+');expected='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in expected.items());(p/"source_sha256.json").write_text(json.dumps(expected,indent=2)+"\\n");print("Handle fix source SHA verified")'
        remote('redcup_handle_fix_code_sha',['python3','-B','-c',code])
    elif args.action=='test-handle-fix':
        output='/data/derived/'+args.session+'_yaw_worker_check'
        remote('redcup_actual_gpu_yaw_worker_check',['docker','exec','-w','/workspace/FoundationPose','foundationpose','/opt/conda/envs/my/bin/python','-B','-u',
            '/data/derived/'+args.session+'_launch/handle_fix_code/verify_cup_yaw_worker.py',
            '--source-session','/data/live_sessions/'+args.session,'--code-dir','/data/derived/'+args.session+'_launch/handle_fix_code','--output',output])
        args.output.mkdir(parents=True,exist_ok=False)
        source=data+'derived/'+args.session+'_yaw_worker_check/'
        for name in ['report.json','000000_overlay.jpg','000024_overlay.jpg']:
            run(['scp']+SSH+[HOST+':'+source+name,str(args.output/name)])
    elif args.action=='install-handle-fix':
        names=['run_cup_live_fast.py','run_cup_live_worker.py','cup_live_dashboard.py','run_cup_live_redcup72.sh']
        baseline={n:hashlib.sha256(subprocess.check_output(['git','show','HEAD:setup/'+n],cwd=root)).hexdigest() for n in names}
        code=r'''from pathlib import Path
import json,hashlib,shutil,urllib.request
root=Path(ROOT);stage=Path(STAGE);baseline=BASELINE
try:
 with urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=2) as stream:active=json.loads(stream.read())
except OSError:active=None
if active is not None:raise RuntimeError('A live interface is running; preserve it before changing deployed sources')
result=root/'foundationpose_data/derived'/RESULT
assert json.loads((result/'report.json').read_text())['passed'],'GPU worker test did not pass'
folder=Path(FIX_FOLDER);expected=json.loads((folder/'source_sha256.json').read_text())
tested=json.loads((stage/'handle_fix_code/source_sha256.json').read_text())
assert all(expected[n]==tested[n] for n in ['run_cup_live_worker.py','cup_handle_yaw.py']),'GPU-tested worker/helper changed; revalidate first'
for n,s in baseline.items():assert hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest()==s,'Remote source changed; preserve it: '+n
backup=stage/'before_handle_fix';backup.mkdir()
for n,s in expected.items():
 source=folder/n;assert hashlib.sha256(source.read_bytes()).hexdigest()==s
 dest=root/'setup'/n
 if dest.exists():shutil.copy2(dest,backup/n)
 shutil.copy2(source,dest)
print('Tested init correction and dashboard fix installed; previous sources preserved')
'''.replace('ROOT',repr(REMOTE)).replace('STAGE',repr(stage)).replace('BASELINE',repr(baseline)).replace('RESULT',repr(args.session+'_yaw_worker_check')).replace('FIX_FOLDER',repr(fix_folder))
        remote('redcup_install_tested_handle_dashboard_fix',['python3','-B','-c',code])
    elif args.action=='compare-yaw':
        source=root/'setup/compare_cup_handle_yaw.py'
        run(['scp']+SSH+[str(source),HOST+':'+stage+'/compare_cup_handle_yaw.py'])
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        remote('redcup_handle_yaw_code_sha',['python3','-B','-c','from pathlib import Path;import hashlib;assert hashlib.sha256(Path('+repr(stage+'/compare_cup_handle_yaw.py')+').read_bytes()).hexdigest()=='+repr(digest)])
        destination='/data/derived/'+args.session+'_yaw_comparison'
        remote('redcup_initial_handle_yaw_comparison',['docker','exec','-w','/workspace/FoundationPose','foundationpose','/opt/conda/envs/my/bin/python','-B',
            '/data/derived/'+args.session+'_launch/compare_cup_handle_yaw.py','--session','/data/live_sessions/'+args.session,
            '--mesh','/data/derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj','--output',destination])
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+data+'derived/'+args.session+'_yaw_comparison/*',str(args.output)])
    elif args.action=='evaluate-motion':
        source=root/'setup/review_saved_camera_motion.py'
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        staged_source=stage+'/review_saved_camera_motion_'+digest[:12]+'.py'
        run(['scp']+SSH+[str(source),HOST+':'+staged_source])
        remote('redcup_camera_motion_code_sha',['python3','-B','-c','from pathlib import Path;import hashlib;assert hashlib.sha256(Path('+repr(staged_source)+').read_bytes()).hexdigest()=='+repr(digest)])
        destination=data+'derived/'+args.output.name
        remote('redcup_offline_fixed_scene_camera_motion_review',['/home/ni/anaconda3/envs/foundationpose/bin/python','-B',
            staged_source,'--session',session,'--output',destination,'--user-confirmed-fixed-scene'])
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+destination+'/*',str(args.output)])
    elif args.action=='review-handle':
        source=root/'setup/review_live_handle_failure.py'
        run(['scp']+SSH+[str(source),HOST+':'+stage+'/review_live_handle_failure.py'])
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        remote('redcup_live_handle_review_source_sha',['python3','-B','-c','from pathlib import Path;import hashlib;assert hashlib.sha256(Path('+repr(stage+'/review_live_handle_failure.py')+').read_bytes()).hexdigest()=='+repr(digest)])
        destination=data+'derived/'+args.session+'_handle_review'
        remote('redcup_live_saved_handle_review',['.camera-venv/bin/python','-B',stage+'/review_live_handle_failure.py',
            '--session',session,'--mesh',data+'derived/redcup_geometric_clean_v1_20261017_2050/cup_clean.obj','--output',destination])
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+destination+'/*',str(args.output)])
    elif args.action=='archive-interface':
        folder=stage+'/interface_notes'
        names=['RED_CUP_INTERFACE_REOPEN_20261018.md','RED_CUP_INTERFACE_ISSUES_20261018.md']
        remote('redcup_interface_notes_directory',['mkdir',folder])
        files=[root/'reports'/n for n in names]
        run(['scp']+SSH+[str(f) for f in files]+[HOST+':'+folder+'/'])
        hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        check='from pathlib import Path;import hashlib;p=Path('+repr(folder)+');expected='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in expected.items());print("Interface notes SHA verified")'
        remote('redcup_interface_notes_sha',['python3','-B','-c',check])
        remote('redcup_interface_notes_append',['python3','setup/append_manual_records.py','--root',REMOTE,
            '--event-id',args.session.upper()+'-INTERFACE','--experiment',folder+'/'+names[0],'--issues',folder+'/'+names[1]])
    elif args.action=='start':
        command=['bash','setup/run_cup_live_redcup72.sh','--output',session,'--duration-seconds','3600','--max-frames','10000']
        code='''import subprocess,json
from pathlib import Path
stage=Path(STAGE)
log=(stage/'launcher_stdout.log').open('xb')
process=subprocess.Popen(COMMAND,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(stage/'launcher.json').write_text(json.dumps(dict(pid=process.pid,command=COMMAND,session=SESSION),indent=2)+'\\n')
print(json.dumps(dict(pid=process.pid,session=SESSION,preview='http://127.0.0.1:8765')))
'''.replace('STAGE',repr(stage)).replace('COMMAND',repr(command)).replace('ROOT',repr(REMOTE)).replace('SESSION',repr(session))
        remote('redcup_live_new_mesh_launch',['python3','-B','-c',code])
    elif args.action=='status':
        code='''from pathlib import Path
import json,urllib.request
p=Path(SESSION)
print('session_path',p)
for n in ['session.json','ready.json']:
 if (p/n).exists():
  d=json.loads((p/n).read_text());print(n,json.dumps(d if n=='ready.json' else {k:d.get(k) for k in ['status','source','mesh_profile','mesh_path','mesh_sha256','camera_connected','device','completed_frames','failed_frames','error']}))
try:
 with urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=4) as r:print('HTTP_STATUS',r.read().decode())
except Exception as e:print('HTTP_STATUS_ERROR',repr(e))
for name in ['launcher_stdout.log']:
 f=Path(STAGE)/name
 if f.exists():print(name,f.read_text(errors='replace')[-3500:])
f=p/'worker_stdout.log'
if f.exists():print('worker_stdout.log',f.read_text(errors='replace')[-2500:])
'''.replace('SESSION',repr(session)).replace('STAGE',repr(stage))
        remote('redcup_live_status',['python3','-B','-c',code])
    elif args.action=='preview':
        code='''from pathlib import Path
import urllib.request
stage=Path(STAGE)
with urllib.request.urlopen('http://127.0.0.1:8765/preview.jpg',timeout=5) as response:raw=response.read()
p=stage/FILENAME
with p.open('xb') as stream:stream.write(raw)
print('Saved preview',p)
'''
        filename='preview_'+args.output.stem+'.jpg'
        code=code.replace('STAGE',repr(stage)).replace('FILENAME',repr(filename))
        remote('redcup_live_preview_snapshot',['python3','-B','-c',code])
        args.output.parent.mkdir(parents=True,exist_ok=True)
        if args.output.exists():raise FileExistsError('Preserve prior preview')
        run(['scp']+SSH+[HOST+':'+stage+'/'+filename,str(args.output)])
    elif args.action=='control':
        if not args.control:p.error('control action requires --control')
        payload=json.loads(args.payload.read_text(encoding='utf-8')) if args.payload else {}
        code='''import urllib.request,json
from pathlib import Path
stage=Path(STAGE)
payload=PAYLOAD
request=urllib.request.Request('http://127.0.0.1:8765/'+ACTION,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=180) as r:result=json.loads(r.read())
print(json.dumps(result,ensure_ascii=False))
with (stage/('control_'+ACTION+'_'+STAMP+'.json')).open('x') as f:f.write(json.dumps(dict(action=ACTION,payload=payload,response=result),indent=2)+'\\n')
'''
        from datetime import datetime
        code=code.replace('STAGE',repr(stage)).replace('PAYLOAD',repr(payload)).replace('ACTION',repr(args.control)).replace('STAMP',repr(datetime.now().strftime('%H%M%S_%f')))
        remote('redcup_live_control_'+args.control,['python3','-B','-c',code])
    elif args.action=='baseline':
        code='''import json,time,urllib.request
from pathlib import Path
stage=Path(STAGE);deadline=time.monotonic()+55;status={}
while time.monotonic()<deadline:
 with urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=4) as r:status=json.loads(r.read())
 if status.get('completed',0)>=200:break
 time.sleep(.5)
(stage/'baseline_status.json').write_text(json.dumps(status,indent=2)+'\\n')
try:
 with urllib.request.urlopen('http://127.0.0.1:8765/overlay.jpg',timeout=4) as r:raw=r.read()
 with (stage/'baseline_overlay.jpg').open('xb') as f:f.write(raw)
except Exception as error:print('overlay_error',repr(error))
request=urllib.request.Request('http://127.0.0.1:8765/pause',data=b'{}',headers={'Content-Type':'application/json'})
with urllib.request.urlopen(request,timeout=4) as r:print('pause',r.read().decode())
print(json.dumps(status,ensure_ascii=False))
'''.replace('STAGE',repr(stage))
        remote('redcup_live_static_baseline',['python3','-B','-c',code])
        args.output.mkdir(parents=True,exist_ok=True)
        for name in ['baseline_status.json','baseline_overlay.jpg']:
            run(['scp']+SSH+[HOST+':'+stage+'/'+name,str(args.output/name)])
    elif args.action=='analyze':
        script=root/'setup/analyze_redcup_live_trial.py'
        run(['scp']+SSH+[str(script),HOST+':'+stage+'/analyze_redcup_live_trial.py'])
        digest=hashlib.sha256(script.read_bytes()).hexdigest()
        remote('redcup_live_analysis_code_sha',['python3','-c','from pathlib import Path;import hashlib;assert hashlib.sha256(Path('+repr(stage+'/analyze_redcup_live_trial.py')+').read_bytes()).hexdigest()=='+repr(digest)])
        destination=data+'derived/'+args.session+'_baseline_summary'
        remote('redcup_live_static_summary',['.camera-venv/bin/python','-B',stage+'/analyze_redcup_live_trial.py',
            '--session',session,'--output',destination])
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+destination+'/report.json',str(args.output/'report.json')])
    elif args.action=='archive-notes':
        names=['RED_CUP_LIVE_NEW_MODEL_20261018.md','RED_CUP_LIVE_NEW_MODEL_EXPERIMENT_20261018.md','RED_CUP_LIVE_NEW_MODEL_ISSUES_20261018.md']
        folder=stage+'/session_notes'
        remote('redcup_live_notes_directory',['mkdir',folder])
        files=[root/'reports'/n for n in names]+[root/'reports/redcup72_live_baseline_20261018/report.json']
        run(['scp']+SSH+[str(path) for path in files]+[HOST+':'+folder+'/'])
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        code='from pathlib import Path;import hashlib;p=Path('+repr(folder)+');expected='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in expected.items());print("Live notes SHA verified")'
        remote('redcup_live_notes_sha',['python3','-B','-c',code])
        remote('redcup_live_notes_append',['python3','setup/append_manual_records.py','--root',REMOTE,
            '--event-id','RED-CUP-LIVE-NEW-MODEL-20261018-FIRST',
            '--experiment',folder+'/'+names[1],'--issues',folder+'/'+names[2]])
    elif args.action=='git-status':
        remote('redcup_live_git_status',['git','status','--short'])
        remote('redcup_live_git_branch',['git','branch','--show-current'])
    elif args.action=='git-commit':
        code='''from pathlib import Path
import hashlib,subprocess,shutil
root=Path(ROOT);stage=Path(STAGE)
installed=json.loads((stage/'deployment.json').read_text())['installed_sha256']
assert all(hashlib.sha256((root/'setup'/n).read_bytes()).hexdigest()==s for n,s in installed.items())
names=['RED_CUP_LIVE_NEW_MODEL_20261018.md','RED_CUP_LIVE_NEW_MODEL_EXPERIMENT_20261018.md','RED_CUP_LIVE_NEW_MODEL_ISSUES_20261018.md']
for n in names:
 destination=root/'reports'/n
 if destination.exists():assert destination.read_bytes()==(stage/'session_notes'/n).read_bytes()
 else:shutil.copy2(stage/'session_notes'/n,destination)
guide=root/'REPRODUCTION_GUIDE.md'
addition='\\n<!-- RED-CUP-LIVE-NEW-MODEL-20261018 -->\\n## 2026-10-18 新杯子模型实时入口\\n\\nUbuntu执行 bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000 ，页面 http://127.0.0.1:8765 。如已有会话请使用已有页面，避免重复占用相机。新入口显式选择redcup72米制OBJ、SAM2与固定杯码ID6/30mm协议；通用入口默认仍为legacy。启动前检查所选文件SHA，原模型不覆盖。约23.74FPS静止初跑完成，当前ID6未识别，静止估计变化不能作为物理精度。详见 reports/RED_CUP_LIVE_NEW_MODEL_20261018.md 。\\n'
if 'RED-CUP-LIVE-NEW-MODEL-20261018' not in guide.read_text():
 with guide.open('a') as stream:stream.write(addition)
paths=['setup/'+n for n in installed]+['reports/'+n for n in names]
paths.append('REPRODUCTION_GUIDE.md')
assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=root,text=True).strip(),'Existing staged changes preserved; review before commit'
subprocess.run(['git','add','--']+paths,cwd=root,check=True)
subprocess.run(['git','commit','-m','feat: select reviewed redcup mesh for logged live trials'],cwd=root,check=True)
'''
        code='import json\n'+code.replace('ROOT',repr(REMOTE)).replace('STAGE',repr(stage))
        remote('redcup_live_stage_git_commit',['python3','-B','-c',code])
    elif args.action=='fetch':
        args.output.mkdir(parents=True,exist_ok=False)
        run(['scp']+SSH+[HOST+':'+stage+'/launcher.json',str(args.output/'launcher.json')])
        run(['scp']+SSH+[HOST+':'+session+'/session.json',str(args.output/'session.json')])


if __name__=='__main__':main()
