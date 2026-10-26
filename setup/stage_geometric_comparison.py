"""Independent data-derived geometry comparison, logged on existing Ubuntu CPU env."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
from datetime import datetime
from stage_reviewed_reconstruction import run,remote,SSH,HOST,REMOTE,PREPARED,SCENE,SNAPSHOT

CODE='redcup_geometric_code_20261017_2050'
RESULT='redcup_geometric_tsdf_v1_20261017_2050'
CLEAN='redcup_geometric_clean_v1_20261017_2050'
PREVIEW='redcup_geometric_preview_v1_20261017_2050'
PYTHON='/home/ni/anaconda3/envs/foundationpose/bin/python'
DATA=REMOTE+'/foundationpose_data/derived/'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['transfer','run','audit','preview','fetch','archive-notes'])
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.action=='transfer':
        folder=Path(__file__).resolve().parent.parent/'foundationpose_data/derived'/CODE
        files=sorted(folder.glob('*.py'))
        if len(files)!=3:raise ValueError('Expected frozen geometry comparison code')
        remote('redcup_geometric_code_directory',['mkdir',DATA+CODE])
        run(['scp']+SSH+[str(x) for x in files]+[HOST+':'+DATA+CODE+'/'])
        hashes={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in files}
        code='from pathlib import Path;import hashlib;p=Path('+repr(DATA+CODE)+');d='+repr(hashes)+';assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==s for n,s in d.items());print("Geometric code SHA verified")'
        remote('redcup_geometric_code_sha',['python3','-c',code])
    elif args.action=='run':
        remote('redcup_geometric_tsdf_comparison',[PYTHON,'-B','-u',DATA+CODE+'/reconstruct_cup_geometric_tsdf.py',
            '--scene',DATA+PREPARED+'/'+SCENE,'--masks',DATA+SNAPSHOT,'--output',DATA+RESULT,
            '--top-y-max','340','--body-core-roi','310','351','344','374','--body-halfspan-mm','120',
            '--handle-hidden-frames','44','63'])
    elif args.action=='audit':
        remote('redcup_geometric_component_silhouette_audit',[PYTHON,'-B','-u',DATA+CODE+'/audit_geometric_cup_mesh.py',
            '--result',DATA+RESULT,'--scene',DATA+PREPARED+'/'+SCENE,'--masks',DATA+SNAPSHOT,'--output',DATA+CLEAN])
    elif args.action=='preview':
        remote('redcup_geometric_obj_preview',[PYTHON,'-B','-u',DATA+CODE+'/preview_cup_mesh_local.py',
            '--mesh',DATA+CLEAN+'/cup_clean.obj','--output',DATA+PREVIEW])
    elif args.action=='archive-notes':
        root=Path(__file__).resolve().parent.parent
        folder=DATA+CODE+'/session_notes_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        names=['RED_CUP_REVIEWED72_MESH_RESULT_20261017.md','RED_CUP_REVIEWED72_MESH_EXPERIMENT_20261017.md',
               'RED_CUP_REVIEWED72_MESH_ISSUES_20261017.md','redcup_initial_pose_mesh_summary_20261017.json']
        remote('redcup_mesh_session_notes_directory',['mkdir',folder])
        run(['scp']+SSH+[str(root/'reports'/name) for name in names]+[HOST+':'+folder+'/'])
        remote('redcup_mesh_session_notes_append',['python3',REMOTE+'/setup/append_manual_records.py','--root',REMOTE,
            '--event-id','RED-CUP-REVIEWED72-MESH-20261017-2055','--experiment',folder+'/'+names[1],
            '--issues',folder+'/'+names[2]])
        (args.output/'session_notes_transfer.json').write_text(json.dumps(dict(remote_folder=folder,
            files={name:hashlib.sha256((root/'reports'/name).read_bytes()).hexdigest() for name in names}),indent=2)+'\n')
    elif args.action=='fetch':
        args.output.mkdir(parents=True,exist_ok=False)
        archive=DATA+'redcup_geometric_delivery_20261017_2050.tar.gz'
        remote('redcup_geometric_delivery_archive',['tar','-czf',archive,'-C',DATA,RESULT,CLEAN,PREVIEW])
        local=args.output/'geometry_delivery.tar.gz'
        run(['scp']+SSH+[HOST+':'+archive,str(local)])
        with tarfile.open(local) as stream:
            for member in stream.getmembers():
                if member.name.startswith('/') or '..' in Path(member.name).parts or not (member.isfile() or member.isdir()):
                    raise ValueError('Unexpected geometric delivery member')
            stream.extractall(args.output,filter='data')
        for base in (RESULT,CLEAN):
            report=json.loads((args.output/base/'report.json').read_text())
            name='cup_geometric_tsdf.obj' if base==RESULT else 'cup_clean.obj'
            if hashlib.sha256((args.output/base/name).read_bytes()).hexdigest()!=report['obj_sha256']:
                raise ValueError('Geometric OBJ SHA differs')
        print(json.dumps(dict(output=str(args.output),obj_sha_verified=True,geometry_quality_accepted=False)))


if __name__=='__main__':main()
