"""Logged transfer and first BundleSDF run for the current reviewed72 cup ring."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

REMOTE='/data/ZJC/foundationPos'
HOST='USER@UBUNTU_HOST'
SSH=['-o','BatchMode=yes','-o','ConnectTimeout=8','-o','UpdateHostKeys=no']
CODE='redcup_reconstruction_code_v2_20261017_2044'
SNAPSHOT='redcup_human72_snapshot_20261017_2036'
PREPARED='redcup_reviewed_prepared_20261017_2040'
SCENE='obj_side_20261017_184953_656_corrected_last_190116'
RECON='cup_reconstruction_redcup72_v2_20261017_2044'
AUDIT='redcup_mesh_audit_v2_20261017_2044'
LABEL='redcup72_bundlesdf_initial_v2_20261017'


def run(argv,check=True,timeout=1800):
    result=subprocess.run(argv,timeout=timeout)
    if check and result.returncode:raise RuntimeError('Child command returned '+str(result.returncode))
    return result.returncode


def remote(label,command,check=True):
    argv=['bash','setup/run_logged.sh','--root',REMOTE,'--label',label,'--note',
          'New red-painted cup reviewed72 ring; human-reviewed masks; originals retained; estimated poses are not GT.', '--']+command
    return run(['ssh']+SSH+[HOST,'cd '+shlex.quote(REMOTE)+' && '+shlex.join(argv)],check=check)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['transfer','transfer-code','run','inspect','audit','fetch'])
    p.add_argument('--package',type=Path,required=True)
    p.add_argument('--batch-id',required=True)
    args=p.parse_args()
    if not args.batch_id.replace('_','').isalnum():raise ValueError('Simple unique batch ID required')
    folder=REMOTE+'/foundationpose_data/incoming/'+args.batch_id
    if args.action=='transfer':
        info=json.loads((args.package/'package_report.json').read_text())
        archive=args.package/'capture_batch.zip'
        if not info['passed'] or hashlib.sha256(archive.read_bytes()).hexdigest()!=info['sha256']:
            raise ValueError('Package SHA differs')
        code='from pathlib import Path;p=Path('+repr(folder)+');p.parent.mkdir(parents=True,exist_ok=True);p.mkdir(exist_ok=False)'
        remote('redcup_reviewed_import_directory',['python3','-c',code])
        run(['scp']+SSH+[str(archive),HOST+':'+folder+'/capture_batch.zip'])
        remote('redcup_reviewed_import_sha',['python3','setup/import_external_capture_package.py',
            '--root',REMOTE,'--zip',folder+'/capture_batch.zip','--sha256',info['sha256'],'--batch-id',args.batch_id])
    elif args.action=='transfer-code':
        source=Path(__file__).resolve().parent.parent/'foundationpose_data/derived'/CODE
        files=sorted(source.glob('*.py'))
        if len(files)!=4:raise ValueError('Expected four frozen reconstruction scripts')
        dest=REMOTE+'/foundationpose_data/derived/'+CODE
        remote('redcup_portable_code_directory',['mkdir',dest])
        run(['scp']+SSH+[str(path) for path in files]+[HOST+':'+dest+'/'])
        expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        verify='from pathlib import Path;import hashlib;p=Path('+repr(dest)+');d='+repr(expected)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in d.items());print("Frozen portable code SHA verified")'
        remote('redcup_portable_code_sha',['python3','-c',verify])
    elif args.action=='run':
        command=['docker','exec','-e','LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7',
            '-e','PYOPENGL_PLATFORM=egl','-w','/workspace/BundleSDF','foundationpose-bundlesdf',
            '/usr/bin/timeout','--signal=TERM','--kill-after=10s','1200s','python','-B','-u',
            '/data/derived/'+CODE+'/run_cup_bundlesdf_pilot.py','--expected-frames','72',
            '--video-dir','/data/derived/'+PREPARED+'/'+SCENE,'--output','/data/derived/'+RECON,'--debug-level','1']
        result=remote(LABEL,command,check=False)
        (args.package/(RECON+'_client_exit.json')).write_text(json.dumps(dict(exit_code=result,
            remote_reconstruction=REMOTE+'/foundationpose_data/derived/'+RECON,remote_label=LABEL),indent=2)+'\n')
        if result:raise SystemExit(result)
    elif args.action=='inspect':
        code=('from pathlib import Path;import json;p=Path('+repr(REMOTE+'/foundationpose_data/derived/'+RECON)+');'
            'r=json.loads((p/"report.json").read_text()) if (p/"report.json").exists() else {};'
            'print(json.dumps({k:r.get(k) for k in ["passed","status","error","elapsed_seconds"]}));'
            'print("MESHES",[str(q.relative_to(p)) for q in p.rglob("*.obj")]);'
            'print("ONLINE_POSES",len(list((p/"pipeline/ob_in_cam").glob("*.txt"))))')
        remote('redcup_initial_result_inventory',['python3','-c',code])
    elif args.action=='audit':
        remote('redcup_initial_mesh_cpu_audit',['docker','exec','-e','LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libffi.so.7',
            '-e','PYOPENGL_PLATFORM=egl','foundationpose-bundlesdf','python','-B','-u',
            '/data/derived/'+CODE+'/review_cup_reconstruction.py','--reconstruction','/data/derived/'+RECON+'/pipeline',
            '--scene','/data/derived/'+PREPARED+'/'+SCENE,'--expected-frames','72','--output','/data/derived/'+AUDIT])
    elif args.action=='fetch':
        delivery=folder+'/result_delivery'
        code=('from pathlib import Path;import shutil,json;p=Path('+repr(REMOTE+'/foundationpose_data/derived/'+RECON)+');'
            'a=Path('+repr(REMOTE+'/foundationpose_data/derived/'+AUDIT)+');d=Path('+repr(delivery)+');d.mkdir();'
            'shutil.copy2(p/"report.json",d/"reconstruction_report.json");'
            'shutil.copytree(a,d/"audit") if a.exists() else None;'
            '[( (d/"meshes"/q.relative_to(p)).parent.mkdir(parents=True,exist_ok=True),shutil.copy2(q,d/"meshes"/q.relative_to(p))) '
            'for q in p.rglob("*") if q.is_file() and (q.suffix in [".obj",".mtl"] or q.name in ["texture_map.png","material_0.png","texture.png"])];'
            'shutil.copytree(p/"pipeline/ob_in_cam",d/"online_poses") if (p/"pipeline/ob_in_cam").exists() else None')
        remote('redcup_initial_delivery_prepare',['python3','-c',code])
        remote('redcup_initial_delivery_archive',['tar','-czf',folder+'/result_delivery.tar.gz','-C',folder,'result_delivery'])
        archive=args.package/'result_delivery.tar.gz'
        if archive.exists():raise FileExistsError('Preserve prior delivery')
        run(['scp']+SSH+[HOST+':'+folder+'/result_delivery.tar.gz',str(archive)])
        import tarfile
        with tarfile.open(archive) as stream:
            for member in stream.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected delivery member')
            stream.extractall(args.package,filter='data')
        print(json.dumps(dict(delivery=str(args.package/'result_delivery'),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())))


if __name__=='__main__':main()
