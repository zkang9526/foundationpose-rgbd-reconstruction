#!/usr/bin/env python3
"""Install signed official RealSense Debian binaries in a private data prefix.

No sudo, package-manager database, udev, kernel, firmware, or Python changes.
The user explicitly requested a visible Ubuntu Viewer window.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request
from urllib.parse import urljoin,urlparse

BASE='https://librealsense.realsenseai.com/Debian/apt-repo/'
KEY='https://librealsense.realsenseai.com/Debian/librealsenseai.asc'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url,path):
    if path.exists():raise FileExistsError('Preserve earlier download: '+str(path))
    print('Downloading '+url,flush=True)
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'FoundationPos-ViewerSetup/1'}),timeout=40) as source:
        with path.open('xb') as target:shutil.copyfileobj(source,target)
    return dict(url=url,path=str(path),sha256=sha(path),bytes=path.stat().st_size)


def desktop_environment():
    for proc in sorted(Path('/proc').iterdir(),key=lambda p:int(p.name) if p.name.isdigit() else -1):
        if not proc.name.isdigit():continue
        try:
            if proc.stat().st_uid!=os.getuid() or (proc/'comm').read_text().strip() not in ['gnome-shell','gnome-session-b','xfce4-session','plasmashell']:continue
            fields=(proc/'environ').read_bytes().split(b'\0')
            values={x.split(b'=',1)[0].decode():x.split(b'=',1)[1].decode(errors='replace') for x in fields if b'=' in x}
            selected={k:values[k] for k in ['DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS'] if k in values}
            if selected.get('DISPLAY'):return selected
        except (OSError,ValueError):pass
    raise RuntimeError('No logged-in user graphical desktop DISPLAY found')


def probe(prefix):
    prefix.mkdir(parents=True,exist_ok=False)
    downloads=prefix/'downloads';downloads.mkdir()
    records=[download(KEY,downloads/'vendor.asc'),
             download(urljoin(BASE,'dists/focal/InRelease'),downloads/'InRelease'),
             download(urljoin(BASE,'dists/focal/main/binary-amd64/Packages.gz'),downloads/'Packages.gz')]
    subprocess.run(['gpg','--batch','--yes','--dearmor','--output',str(downloads/'vendor.gpg'),str(downloads/'vendor.asc')],check=True)
    verified=subprocess.run(['gpgv','--keyring',str(downloads/'vendor.gpg'),'--output',str(downloads/'Release'),str(downloads/'InRelease')],capture_output=True,text=True)
    (prefix/'signature_verification.txt').write_text(verified.stdout+verified.stderr)
    if verified.returncode:
        # Preserve bad InRelease; accept only an independently valid detached release.
        records.extend([download(urljoin(BASE,'dists/focal/Release'),downloads/'Release.detached'),
                        download(urljoin(BASE,'dists/focal/Release.gpg'),downloads/'Release.gpg')])
        detached=subprocess.run(['gpgv','--keyring',str(downloads/'vendor.gpg'),str(downloads/'Release.gpg'),str(downloads/'Release.detached')],capture_output=True,text=True)
        (prefix/'detached_signature_verification.txt').write_text(detached.stdout+detached.stderr)
        if detached.returncode:raise RuntimeError('Both official repository signature forms failed; preserve downloads and use another verified distribution')
        (downloads/'Release').write_bytes((downloads/'Release.detached').read_bytes())
    release=(downloads/'Release').read_text()
    expected=None;in_sha=False
    for line in release.splitlines():
        if line=='SHA256:':in_sha=True;continue
        if in_sha and line and not line.startswith(' '):in_sha=False
        pieces=line.split()
        if in_sha and len(pieces)==3 and pieces[2]=='main/binary-amd64/Packages.gz':expected=pieces[0]
    if expected is None or sha(downloads/'Packages.gz')!=expected:raise ValueError('Packages index SHA differs from signed release')
    text=gzip.decompress((downloads/'Packages.gz').read_bytes()).decode()
    (downloads/'Packages').write_text(text)
    packages=[]
    for paragraph in text.split('\n\n'):
        item={}
        for line in paragraph.splitlines():
            if line and not line.startswith(' ') and ': ' in line:
                key,value=line.split(': ',1);item[key]=value
        if item.get('Package') in ['librealsense2','librealsense2-utils','librealsense2-gl'] and item.get('Architecture')=='amd64':packages.append(item)
    # Match the already-working camera SDK when its official binaries are available.
    selected={}
    for name in ['librealsense2','librealsense2-utils','librealsense2-gl']:
        candidates=[x for x in packages if x['Package']==name and x['Version'].startswith('2.55.1-')]
        if not candidates:raise RuntimeError('Official focal 2.55.1 package unavailable: '+name)
        candidates.sort(key=lambda x:x['Version'])
        selected[name]=candidates[-1]
    report=dict(repository=BASE,repository_signature_verified=True,index_sha256_verified=True,
                downloads=records,selected_packages=selected,system_packages_modified=False)
    (prefix/'repository.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


def install(prefix,root):
    report=json.loads((prefix/'repository.json').read_text())
    target=prefix/'root';target.mkdir(exist_ok=False)
    archives=[]
    for name,item in report['selected_packages'].items():
        url=urljoin(BASE,item['Filename'])
        if urlparse(url).hostname!=urlparse(BASE).hostname:raise ValueError('Package URL escapes vendor origin')
        destination=prefix/'downloads'/Path(item['Filename']).name
        receipt=download(url,destination)
        if receipt['sha256']!=item['SHA256'] or receipt['bytes']!=int(item['Size']):raise ValueError('Official package SHA or size differs')
        subprocess.run(['dpkg-deb','--extract',str(destination),str(target)],check=True)
        archives.append(receipt)
    binary=target/'usr/bin/realsense-viewer'
    if not binary.is_file():raise FileNotFoundError('Official package did not supply viewer binary')
    library=target/'usr/lib/x86_64-linux-gnu'
    env=os.environ.copy();env['LD_LIBRARY_PATH']=str(library)
    deps=subprocess.run(['ldd',str(binary)],env=env,capture_output=True,text=True,check=True)
    (prefix/'viewer_ldd.txt').write_text(deps.stdout+deps.stderr)
    if 'not found' in deps.stdout:raise RuntimeError('Viewer has unresolved runtime libraries; see viewer_ldd.txt')
    launcher=root/'setup/run_realsense_viewer_ubuntu.sh'
    if launcher.exists():raise FileExistsError('Preserve existing viewer launcher')
    launcher.write_text('#!/usr/bin/env bash\nset -Eeuo pipefail\nROOT=/data/ZJC/foundationPos\nexec /usr/bin/python3 "$ROOT/setup/run_logged.py" --root "$ROOT" --label ubuntu_realsense_viewer_gui --note "Native Viewer for camera framing; stop before FoundationPose; no calibration or firmware action" -- /usr/bin/env LD_LIBRARY_PATH='+str(library)+' '+str(binary)+' "$@"\n')
    launcher.chmod(0o755)
    desktop=Path.home()/'.local/share/applications/foundationpos-realsense-viewer.desktop'
    desktop.parent.mkdir(parents=True,exist_ok=True)
    if desktop.exists():raise FileExistsError('Preserve existing desktop entry')
    desktop.write_text('[Desktop Entry]\nType=Application\nName=RealSense Viewer (FoundationPos)\nComment=RGB and depth camera preview\nExec=/bin/bash '+str(launcher)+'\nTerminal=false\nCategories=Utility;Video;\n')
    report.update(installed=True,package_downloads=archives,binary=str(binary),binary_sha256=sha(binary),
                  launcher=str(launcher),desktop_entry=str(desktop),library_path=str(library),
                  system_packages_modified=False,kernel_modified=False,camera_python_environment_modified=False)
    (prefix/'installation.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(installed=True,binary=str(binary),desktop_entry=str(desktop),packages={n:i['Version'] for n,i in report['selected_packages'].items()})),flush=True)


def launch(prefix):
    info=json.loads((prefix/'installation.json').read_text())
    selected=desktop_environment();env=os.environ.copy();env.update(selected)
    process_list=subprocess.check_output(['ps','-eo','pid,args'],text=True).splitlines()
    active=[line for line in process_list if ('setup/run_cup_live_fast.py' in line or 'setup/run_cup_live.py' in line) and ' -c ' not in line]
    if active:raise RuntimeError('Live camera process still active; preserve it and stop through its UI first')
    log=(prefix/'viewer_stdout.log').open('xb')
    process=subprocess.Popen(['bash',info['launcher']],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt=dict(pid=process.pid,desktop_environment=selected,binary=info['binary'])
    (prefix/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n')
    time.sleep(3)
    receipt['early_exit_code']=process.poll()
    if receipt['early_exit_code'] is not None:raise RuntimeError('Viewer exited early: '+str(receipt['early_exit_code'])+'; see viewer_stdout.log')
    print(json.dumps(receipt),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['probe','install','launch'])
    p.add_argument('--prefix',type=Path,required=True)
    p.add_argument('--root',type=Path,default=Path('/data/ZJC/foundationPos'))
    args=p.parse_args()
    args.prefix.resolve().relative_to((args.root/'foundationpose_data').resolve())
    if args.action=='probe':probe(args.prefix)
    elif args.action=='install':install(args.prefix,args.root)
    else:launch(args.prefix)


if __name__=='__main__':main()
