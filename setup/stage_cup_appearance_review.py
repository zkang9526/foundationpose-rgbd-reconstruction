#!/usr/bin/env python3
"""Logged, immutable appearance review on the existing Ubuntu environments."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from stage_reviewed_reconstruction import run,remote,SSH,HOST,REMOTE,PREPARED,SCENE

CODE='redcup_appearance_code_20261017_2106'
PREVIEW='redcup_vertex_color_preview_20261017_2106'
RENDER='redcup_foundationpose_color_render_20261017_2106'
CLEAN='redcup_geometric_clean_v1_20261017_2050'
RESULT='redcup_geometric_tsdf_v1_20261017_2050'
DATA=REMOTE+'/foundationpose_data/derived/'
PYTHON='/home/ni/anaconda3/envs/foundationpose/bin/python'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['transfer','preview','render','fetch','archive-notes'])
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    root=Path(__file__).resolve().parent.parent
    if args.action=='transfer':
        folder=root/'foundationpose_data/derived'/CODE
        folder.mkdir(parents=True,exist_ok=False)
        names=['preview_cup_mesh_local.py','verify_mesh_color_render.py']
        for name in names:(folder/name).write_bytes((root/'setup'/name).read_bytes())
        files=[folder/name for name in names]
        remote('redcup_appearance_code_directory',['mkdir',DATA+CODE])
        run(['scp']+SSH+[str(path) for path in files]+[HOST+':'+DATA+CODE+'/'])
        hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
        verify='from pathlib import Path;import hashlib;p=Path('+repr(DATA+CODE)+');d='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in d.items());print("Appearance code SHA verified")'
        remote('redcup_appearance_code_sha',['python3','-c',verify])
    elif args.action=='preview':
        remote('redcup_vertex_rgb_cpu_preview',[PYTHON,'-B','-u',DATA+CODE+'/preview_cup_mesh_local.py',
            '--mesh',DATA+CLEAN+'/cup_clean.obj','--output',DATA+PREVIEW])
    elif args.action=='render':
        remote('redcup_installed_foundationpose_vertex_color_render',['docker','exec','-w','/workspace/FoundationPose',
            'foundationpose','/opt/conda/envs/my/bin/python','-B','-u',
            '/data/derived/'+CODE+'/verify_mesh_color_render.py',
            '--mesh','/data/derived/'+CLEAN+'/cup_clean.obj',
            '--scene','/data/derived/'+PREPARED+'/'+SCENE,
            '--poses','/data/derived/'+RESULT+'/estimated_camera_to_model',
            '--output','/data/derived/'+RENDER])
    elif args.action=='fetch':
        args.output.mkdir(parents=True,exist_ok=False)
        archive=DATA+'redcup_color_delivery_20261017_2106.tar.gz'
        remote('redcup_appearance_delivery_archive',['tar','-czf',archive,'-C',DATA,PREVIEW,RENDER])
        target=args.output/'color_delivery.tar.gz'
        run(['scp']+SSH+[HOST+':'+archive,str(target)])
        with tarfile.open(target) as stream:
            for member in stream.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isdir() or member.isfile()):
                    raise ValueError('Unexpected archive member')
            stream.extractall(args.output,filter='data')
        preview=json.loads((args.output/PREVIEW/'report.json').read_text())
        for item in preview['outputs']:
            local=args.output/PREVIEW/Path(item['path']).name
            if hashlib.sha256(local.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Preview SHA differs')
        report=json.loads((args.output/RENDER/'report.json').read_text())
        for item in report['outputs']:
            path=args.output/RENDER/('%06d_render_rgb.png'%item['frame'])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item['render_sha256']:raise ValueError('Renderer SHA differs')
        print(json.dumps(dict(output=str(args.output),appearance_source=preview['appearance_source'],
            installed_renderer_passed=report['passed'],delivery_image_sha_verified=True)))
    elif args.action=='archive-notes':
        folder=DATA+CODE+'/session_notes'
        names=['RED_CUP_COLOR_HANDLE_REVIEW_20261017.md','RED_CUP_COLOR_HANDLE_EXPERIMENT_20261017.md',
               'RED_CUP_COLOR_HANDLE_ISSUES_20261017.md']
        remote('redcup_color_handle_notes_directory',['mkdir',folder])
        paths=[root/'reports'/name for name in names]
        sample=Path('E:/foundationPos_data/derived/redcup_handle_samples_20261017_2106')
        paths.extend([sample/'report.json',sample/'handle_mask_depth_samples.png'])
        run(['scp']+SSH+[str(path) for path in paths]+[HOST+':'+folder+'/'])
        hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        verify='from pathlib import Path;import hashlib;p=Path('+repr(folder)+');d='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in d.items());print("Notes and handle evidence SHA verified")'
        remote('redcup_color_handle_notes_sha',['python3','-c',verify])
        remote('redcup_color_handle_notes_append',['python3',REMOTE+'/setup/append_manual_records.py','--root',REMOTE,
            '--event-id','RED-CUP-COLOR-HANDLE-20261017-2106',
            '--experiment',folder+'/'+names[1],'--issues',folder+'/'+names[2]])


if __name__=='__main__':main()
