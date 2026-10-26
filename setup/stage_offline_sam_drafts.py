"""Stage/fetch source-hashed RGB-only SAM drafts through existing Ubuntu logging."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tarfile
import zipfile
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
REMOTE = '/data/ZJC/foundationPos'
SSH = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'UpdateHostKeys=no']
HOST = 'USER@UBUNTU_HOST'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, timeout=420):
    result = subprocess.run(command, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Child command failed, return code ' + str(result.returncode))


def remote(label, command):
    argv = ['bash', 'setup/run_logged.sh', '--root', REMOTE, '--label', label,
            '--note', 'RGB-only offline SAM draft assistance; no camera, no user annotation overwrite; proposals require human review.', '--'] + command
    run(['ssh'] + SSH + [HOST, 'cd ' + shlex.quote(REMOTE) + ' && ' + shlex.join(argv)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'pilot', 'full', 'archive-notes'])
    parser.add_argument('--job', type=Path, required=True)
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--backend', choices=['sam','sam2'], default='sam')
    args = parser.parse_args()
    job = args.job.resolve()
    if not job.name.replace('_', '').isalnum() or not str(job).upper().startswith('E:'):
        raise ValueError('Expected an explicit E drive job with a simple unique name')
    remote_job = REMOTE + '/foundationpose_data/offline_masks/' + job.name
    container_job = '/data/offline_masks/' + job.name
    if args.action == 'prepare':
        scene = args.scene.resolve(strict=True)
        job.mkdir(parents=True, exist_ok=False)
        frames = []
        for rgb in sorted((scene / 'rgb').glob('*.png')):
            if not rgb.name[:-4].isdigit() or not (scene / 'depth' / rgb.name).is_file():
                raise ValueError('Expected paired numeric RGB/depth names')
            frames.append(dict(frame=rgb.name, size=[640,480], source_rgb_sha256=sha(rgb),
                source_depth_sha256=sha(scene / 'depth' / rgb.name)))
        if len(frames) != 72:
            raise ValueError('This staged cup review expects exactly72 paired frames')
        request = dict(source_scene=str(scene), frames=frames, draft_only=True, backend=args.backend,
            prompts=dict(box_xyxy=[230,255,450,440],
                         points=[[305,330],[355,335],[310,375],[360,380],[315,290],[336,414],
                                 [335,450],[240,440],[440,280],[330,442],[350,442]],
                         labels=[1,1,1,1,1,1,0,0,0,0,0], selected_by='assistant visual review; not human GT',
                         note='Fixed camera and current cup placement only; handle hole remains for visual review.'))
        (job / 'request.json').write_text(json.dumps(request, indent=2)+'\n', encoding='utf-8')
        with zipfile.ZipFile(job / 'input.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(job / 'request.json', 'request.json')
            archive.write(ROOT / 'setup/sam_offline_drafts.py', 'sam_offline_drafts.py')
            for frame in frames:
                archive.write(scene / 'rgb' / frame['frame'], 'rgb/' + frame['frame'])
        (job / 'stage.json').write_text(json.dumps(dict(remote_job=remote_job, source_scene=str(scene),
            input_zip_sha256=sha(job / 'input.zip'), rgb_frames=72, depth_uploaded=False),indent=2)+'\n')
        print(json.dumps(dict(prepared=True, job=str(job), frames=72, archive_bytes=(job/'input.zip').stat().st_size)))
        return
    info = json.loads((job / 'stage.json').read_text())
    if info['remote_job'] != remote_job or sha(job/'input.zip') != info['input_zip_sha256']:
        raise ValueError('Staged archive/target changed')
    if args.action == 'archive-notes':
        folder=remote_job+'/handoff_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        remote('offline_sam_handoff_directory',['mkdir',folder])
        names=['CUP_SAM2_ASSISTED_MASKS_20261017.md','CUP_SAM2_ASSISTED_MASKS_EXPERIMENT_20261017.md',
               'CUP_SAM2_ASSISTED_MASKS_ISSUES_20261017.md']
        run(['scp']+SSH+[str(ROOT/'reports'/name) for name in names]+[HOST+':'+folder+'/'])
        remote('offline_sam_assisted_session_notes',['python3',REMOTE+'/setup/append_manual_records.py',
            '--root',REMOTE,'--event-id','CUP-SAM2-ASSISTED-MASKS-20261017-1945',
            '--experiment',folder+'/'+names[1],'--issues',folder+'/'+names[2]])
        (job/'remote_handoff_notes.json').write_text(json.dumps(dict(remote_folder=folder,
            files={name:sha(ROOT/'reports'/name) for name in names}),indent=2)+'\n')
        return
    if args.action == 'pilot':
        code = 'from pathlib import Path;p=Path('+repr(remote_job)+');p.parent.mkdir(parents=True,exist_ok=True);p.mkdir(exist_ok=False)'
        remote('offline_sam_job_directory', ['python3','-c',code])
        run(['scp'] + SSH + [str(job/'input.zip'), HOST+':'+remote_job+'/input.zip'])
        code = ('from pathlib import Path;import zipfile,hashlib;p=Path('+repr(remote_job)+');z=p/"input.zip";'
                'assert hashlib.sha256(z.read_bytes()).hexdigest()=='+repr(info['input_zip_sha256'])+';'
                'a=zipfile.ZipFile(z);assert all(not Path(n).is_absolute() and ".." not in Path(n).parts for n in a.namelist());a.extractall(p)')
        remote('offline_sam_rgb_import_verify', ['python3','-c',code])
    phase = args.action
    command = ['docker','exec','foundationpose','/usr/bin/timeout','--signal=TERM','--kill-after=5s','300s',
               '/opt/conda/envs/my/bin/python','-B','-u',container_job+'/sam_offline_drafts.py',
               '--job',container_job,'--output',container_job+'/'+phase]
    if phase == 'pilot':
        command += ['--indices','0','18','36','54','71']
    request = json.loads((job/'request.json').read_text())
    if request.get('backend') == 'sam2':
        command = ['/usr/bin/timeout','--signal=TERM','--kill-after=5s','300s',
                   REMOTE+'/foundationpose_data/environments/sam2/bin/python','-B','-u',remote_job+'/sam_offline_drafts.py',
                   '--job',remote_job,'--output',remote_job+'/'+phase]
        if phase == 'pilot':
            command += ['--indices','0','18','36','54','71']
        launch = ('import sys,subprocess;sys.path.insert(0,'+repr(REMOTE+'/setup')+');'
                  'from sam2_runtime_environment import sam2_runtime_environment;'
                  'env,_=sam2_runtime_environment('+repr(REMOTE)+');sys.exit(subprocess.call(sys.argv[1:],env=env))')
        command = ['python3','-c',launch]+command
    remote('offline_sam_'+phase, command)
    remote('offline_sam_'+phase+'_package', ['tar','-czf',remote_job+'/'+phase+'.tar.gz','-C',remote_job,phase])
    archive_path = job/(phase+'.tar.gz')
    if archive_path.exists() or (job/phase).exists():
        raise FileExistsError('Preserve prior local result; choose a new job for retries')
    run(['scp'] + SSH + [HOST+':'+remote_job+'/'+phase+'.tar.gz',str(archive_path)])
    with tarfile.open(archive_path) as archive:
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or path.parts[0] != phase or not (member.isdir() or member.isfile()):
                raise ValueError('Unexpected draft archive member')
        archive.extractall(job, filter='data')
    report = json.loads((job/phase/'report.json').read_text())
    original = {f['frame']:f for f in json.loads((job/'request.json').read_text())['frames']}
    for frame in report['frames']:
        if (frame['source_rgb_sha256'] != original[frame['frame']]['source_rgb_sha256']
                or frame['source_depth_sha256'] != original[frame['frame']]['source_depth_sha256']
                or sha(job/phase/frame['mask_file']) != frame['mask_sha256']):
            raise ValueError('Returned draft/source SHA differs')
    if not report['passed']:
        raise ValueError('Partial result; inspect failure evidence')
    (job/phase/'windows_fetch_verified.json').write_text(json.dumps(dict(verified=True,frames=len(report['frames']),
        archive_sha256=sha(archive_path), draft_only=True, human_confirmed=False),indent=2)+'\n')
    print(json.dumps(dict(verified=True, frames=len(report['frames']), output=str(job/phase),draft_only=True)))


if __name__ == '__main__':
    main()
