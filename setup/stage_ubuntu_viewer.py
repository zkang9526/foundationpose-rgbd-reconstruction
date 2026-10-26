#!/usr/bin/env python3
"""Logged RealSense Viewer readiness and deployment on the Ubuntu desktop."""
import argparse
import hashlib
from pathlib import Path
from stage_reviewed_reconstruction import remote,run,SSH,HOST,REMOTE


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect','transfer','probe','install','launch','verify','diagnose','fetch','archive-notes','git-commit'])
    p.add_argument('--attempt',default='v1',choices=['v1','v2','v3'])
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    folder=REMOTE+'/foundationpose_data/tools/viewer_installer_20261018'+('' if args.attempt=='v1' else '_'+args.attempt)
    prefix=REMOTE+'/foundationpose_data/tools/realsense_viewer_20261018_'+args.attempt
    if args.action=='inspect':
        code=r'''import json,os,shutil,subprocess,urllib.request
from pathlib import Path
def command(argv):
 r=subprocess.run(argv,capture_output=True,text=True,timeout=30);return dict(exit_code=r.returncode,stdout=r.stdout.strip(),stderr=r.stderr.strip())
desktop=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  if proc.stat().st_uid!=os.getuid():continue
  name=(proc/'comm').read_text().strip()
  if name not in ['gnome-shell','gnome-session-b','xfce4-session','plasmashell']:continue
  fields=(proc/'environ').read_bytes().split(b'\0')
  env={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode(errors='replace') for x in fields if b'=' in x}
  allowed={k:env[k] for k in ['DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS'] if k in env}
  desktop.append(dict(pid=int(proc.name),name=name,desktop_environment=allowed))
 except (OSError,ValueError):pass
try:
 with urllib.request.urlopen('http://127.0.0.1:8765/status',timeout=3) as stream:live=json.loads(stream.read())
except Exception as e:live=dict(unavailable=str(e))
report=dict(os_release=Path('/etc/os-release').read_text(),viewer=shutil.which('realsense-viewer'),
 sdk_packages=command(['dpkg-query','-W','-f=${binary:Package} ${Version} ${db:Status-Abbrev}\n','librealsense2*']),
 apt_candidate=command(['apt-cache','policy','librealsense2-utils']),sudo_noninteractive=command(['sudo','-n','true'])['exit_code']==0,
 desktop=desktop,live_status={k:live.get(k) for k in ['state','output','completed','failed']},
 display_session=command(['loginctl','list-sessions','--no-legend']))
print(json.dumps(report,indent=2))
'''
        remote('ubuntu_realsense_viewer_readiness',['python3','-B','-c',code])
    elif args.action=='transfer':
        remote('ubuntu_viewer_setup_directory',['mkdir',folder])
        source=root/'setup/install_realsense_viewer_user.py'
        run(['scp']+SSH+[str(source),HOST+':'+folder+'/'])
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        remote('ubuntu_viewer_setup_source_sha',['python3','-B','-c','from pathlib import Path;import hashlib;assert hashlib.sha256(Path('+repr(folder+'/install_realsense_viewer_user.py')+').read_bytes()).hexdigest()=='+repr(digest)])
    elif args.action in ['probe','install','launch']:
        remote('ubuntu_viewer_'+args.action,['python3','-B',folder+'/install_realsense_viewer_user.py',args.action,'--prefix',prefix,'--root',REMOTE])
    elif args.action=='verify':
        code=r'''from pathlib import Path
import subprocess,json,os
p=Path(PREFIX)
info=json.loads((p/'installation.json').read_text())
active=[]
for proc in Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  if proc.stat().st_uid==os.getuid() and (proc/'comm').read_text().strip().startswith('realsense-view'):
   active.append(dict(pid=int(proc.name),executable=str((proc/'exe').resolve())))
 except OSError:pass
env=os.environ.copy();env['LD_LIBRARY_PATH']=info['library_path']
enumeration=subprocess.run([str(p/'root/usr/bin/rs-enumerate-devices'),'-s'],env=env,capture_output=True,text=True,timeout=20)
report=dict(viewer_processes=active,enumeration_exit_code=enumeration.returncode,devices=enumeration.stdout,
            stderr=enumeration.stderr,binary=info['binary'],desktop_entry=info['desktop_entry'],
            system_packages_modified=info['system_packages_modified'])
(p/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
print('Viewer log tail:',(p/'viewer_stdout.log').read_text(errors='replace')[-2500:])
'''.replace('PREFIX',repr(prefix))
        remote('ubuntu_viewer_running_check',['python3','-B','-c',code])
    elif args.action=='diagnose':
        code='from pathlib import Path;import subprocess;p=Path('+repr(prefix)+');print((p/"signature_verification.txt").read_text());print(subprocess.run(["gpg","--batch","--show-keys","--with-fingerprint",str(p/"downloads/vendor.asc")],capture_output=True,text=True).stdout);print((p/"downloads/InRelease").read_text()[:2200])'
        remote('ubuntu_viewer_signature_diagnosis',['python3','-B','-c',code])
    elif args.action=='fetch':
        if args.output is None:p.error('fetch requires --output')
        args.output.mkdir(parents=True,exist_ok=False)
        for name in ['repository.json','installation.json','verification.json','signature_verification.txt','detached_signature_verification.txt','viewer_ldd.txt','launch.json']:
            run(['scp']+SSH+[HOST+':'+prefix+'/'+name,str(args.output/name)])
        destination=root/'setup/run_realsense_viewer_ubuntu.sh'
        if destination.exists():raise FileExistsError('Preserve prior local launcher')
        run(['scp']+SSH+[HOST+':'+REMOTE+'/setup/run_realsense_viewer_ubuntu.sh',str(destination)])
    elif args.action=='archive-notes':
        names=['UBUNTU_REALSENSE_VIEWER_20261018.md','UBUNTU_VIEWER_EXPERIMENT_20261018.md','UBUNTU_VIEWER_ISSUES_20261018.md']
        notes=prefix+'/session_notes'
        remote('ubuntu_viewer_notes_directory',['mkdir',notes])
        files=[root/'reports'/name for name in names]
        run(['scp']+SSH+[str(f) for f in files]+[HOST+':'+notes+'/'])
        hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
        code='from pathlib import Path;import hashlib;p=Path('+repr(notes)+');expected='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==v for n,v in expected.items());print("Viewer notes SHA verified")'
        remote('ubuntu_viewer_notes_sha',['python3','-B','-c',code])
        remote('ubuntu_viewer_notes_append',['python3','setup/append_manual_records.py','--root',REMOTE,
            '--event-id','UBUNTU-VIEWER-INSTALL-20261018','--experiment',notes+'/'+names[1],'--issues',notes+'/'+names[2]])
    elif args.action=='git-commit':
        code=r'''from pathlib import Path
import subprocess,shutil
root=Path(ROOT);prefix=Path(PREFIX);folder=Path(FOLDER)
assert not subprocess.check_output(['git','diff','--cached','--name-only'],cwd=root,text=True).strip(),'Existing staged changes preserved'
names=['UBUNTU_REALSENSE_VIEWER_20261018.md','UBUNTU_VIEWER_EXPERIMENT_20261018.md','UBUNTU_VIEWER_ISSUES_20261018.md']
paths=['setup/run_realsense_viewer_ubuntu.sh','setup/install_realsense_viewer_user.py']
source=folder/'install_realsense_viewer_user.py';dest=root/'setup/install_realsense_viewer_user.py'
if dest.exists():assert dest.read_bytes()==source.read_bytes()
else:shutil.copy2(source,dest)
for name in names:
 source=prefix/'session_notes'/name;dest=root/'reports'/name
 if dest.exists():assert dest.read_bytes()==source.read_bytes()
 else:shutil.copy2(source,dest)
 paths.append('reports/'+name)
addition='\n<!-- UBUNTU-VIEWER-INSTALL-20261018 -->\n## 2026-10-18 RealSense Viewer\n\nUbuntu可运行 bash setup/run_realsense_viewer_ubuntu.sh 或打开桌面应用 RealSense Viewer (FoundationPos)。官方2.55.1用户目录安装于数据盘，未改系统包/内核/固件/Python环境。查看RGB/Depth建议640x480、30FPS，先关Viewer或全部流后再启动FoundationPose。官方InRelease失败保留，独立Release.gpg及索引/包SHA通过。详见 reports/UBUNTU_REALSENSE_VIEWER_20261018.md 。\n'
for name in ['Ubuntu_environment.md','REPRODUCTION_GUIDE.md']:
 file=root/name
 if 'UBUNTU-VIEWER-INSTALL-20261018' not in file.read_text():
  with file.open('a') as stream:stream.write(addition)
 paths.append(name)
subprocess.run(['git','add','--']+paths,cwd=root,check=True)
subprocess.run(['git','commit','-m','feat: install logged user-scope RealSense Viewer'],cwd=root,check=True)
'''.replace('ROOT',repr(REMOTE)).replace('PREFIX',repr(prefix)).replace('FOLDER',repr(folder))
        remote('ubuntu_viewer_stage_git_commit',['python3','-B','-c',code])


if __name__=='__main__':main()
