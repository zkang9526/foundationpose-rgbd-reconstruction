#!/usr/bin/env python3
"""CPU-only read-only mesh/reference-pose coordinate audit, new JSON evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import scipy.spatial
import trimesh
import ruamel.yaml

parser = argparse.ArgumentParser()
parser.add_argument('--pipeline', required=True)
parser.add_argument('--output', required=True)
args = parser.parse_args()
base = Path(args.pipeline)
yaml = ruamel.yaml.YAML(typ='safe')
online_files = sorted((base/'ob_in_cam').glob('*.txt'))
last = online_files[-1].stem
keyframes = yaml.load((base/last/'keyframes.yml').read_text())
ids = [key.replace('keyframe_', '') for key in keyframes]
original = np.array([keyframes[key]['cam_in_ob'] for key in keyframes]).reshape(-1,4,4)
global_file = base/ids[-1]/'poses_after_nerf.txt'
refined = np.loadtxt(global_file).reshape(-1,4,4)
if len(refined) != len(ids):
    raise RuntimeError('Selected keyframe mapping mismatch')
config = yaml.load((base/'final/nerf/config.yml').read_text())
scale = float(config['sc_factor'])
translation = np.asarray(config['translation'])
normalized = np.loadtxt(base/'final/nerf/trainval_poses.txt').reshape(-1,4,4)
unnormalized = normalized.copy()
unnormalized[:,:3,3] = unnormalized[:,:3,3]/scale-translation
flip = np.diag([1,-1,-1,1])
camera_cv = unnormalized@flip
original_error = float(np.max(np.abs(camera_cv-original)))
first_anchor_error = float(np.max(np.abs(refined[0]-original[0])))
offset = np.linalg.inv(unnormalized[0])@unnormalized[0]
raw_mesh = trimesh.load(base/'mesh_cleaned.obj', process=False, force='mesh')
metric_mesh = trimesh.load(base/'textured_mesh.obj', process=False, force='mesh')
raw_real = raw_mesh.vertices/scale-translation
distances = scipy.spatial.cKDTree(raw_real).query(metric_mesh.vertices,k=1)[0]
rows=[]
for index, frame_id in enumerate(ids):
    object_camera = np.linalg.inv(refined[index])
    online = np.loadtxt(base/'ob_in_cam'/str(frame_id+'.txt')).reshape(4,4)
    delta = np.linalg.inv(online)@object_camera
    angle = np.arccos(np.clip((np.trace(delta[:3,:3])-1)/2,-1,1))*180/np.pi
    rows.append({'frame_id':frame_id,'global_row_index':index,
                 'camera_in_object_matrix':refined[index].tolist(),
                 'object_in_camera_matrix':object_camera.tolist(),
                 'rotation_det':float(np.linalg.det(refined[index,:3,:3])),
                 'orthogonality_error':float(np.linalg.norm(refined[index,:3,:3].T@refined[index,:3,:3]-np.eye(3))),
                 'global_vs_saved_online_translation_m':float(np.linalg.norm(delta[:3,3])),
                 'global_vs_saved_online_rotation_deg':float(angle)})
report={'passed': bool(original_error<1e-5 and first_anchor_error<1e-5 and distances.max()<1e-4),
        'cpu_only':True,'pipeline':str(base),'metric_units':'meters','camera_convention':'OpenCV',
        'gt_available':False,'reference_pose_type':'estimated_from_tracking_and_global_neural_refinement',
        'global_keyframe_yaml':str(base/last/'keyframes.yml'),'global_refined_pose_file':str(global_file),
        'frame_id_order':ids,'global_refined_poses_camera_in_object':True,
        'online_pose_file_object_in_camera':True,'trainval_poses_file_is_normalized_opengl':True,
        'scale':scale,'translation':translation.tolist(),
        'unnormalized_trainval_vs_keyframe_cv_max_abs':original_error,
        'refined_first_frame_anchor_max_abs':first_anchor_error,
        'theoretical_offset_if_fixed_first_pose':offset.tolist(),
        'textured_metric_vertices_vs_unnormalized_cleaned_nn_max_m':float(distances.max()),
        'textured_metric_vertices_vs_unnormalized_cleaned_nn_mean_m':float(distances.mean()),
        'metric_mesh_bounds':metric_mesh.bounds.tolist(),'metric_mesh_extent':metric_mesh.extents.tolist(),
        'source_formula':{'mesh':'v_export = pose_offset @ homogeneous(v_normalized/sc_factor - translation)',
                          'refined_pose':'camera_in_object_cv = optimized_camera_in_object_gl_metric @ pose_offset @ diag(1,-1,-1,1)',
                          'projection':'p_camera = inverse(camera_in_object_cv) @ p_mesh_metric'},
        'sha256':{str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [base/last/'keyframes.yml',global_file,base/'textured_mesh.obj',base/'final/nerf/config.yml']},
        'frames':rows}
output=Path(args.output)
if output.exists(): raise FileExistsError(str(output))
output.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({key:value for key,value in report.items() if key!='frames'},indent=2))
raise SystemExit(0 if report['passed'] else 1)
