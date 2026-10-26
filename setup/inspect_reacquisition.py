"""Read-only diagnosis of reinitialization evidence and SAM2 environment capacity."""
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess

root = Path('/data/ZJC/foundationPos')
out = dict(sessions=[], free_data_gib=shutil.disk_usage(root).free / 1024 ** 3)
for folder in sorted((root / 'foundationpose_data/live_sessions').glob('cup*'), key=lambda p: p.stat().st_mtime, reverse=True):
    if not (folder / 'session.json').exists():
        continue
    try:
        session = json.loads((folder / 'session.json').read_text())
    except ValueError:
        continue
    if session.get('source') != 'live_d435i':
        continue
    item = dict(session=folder.name, status=session.get('status'), completed=session.get('completed_frames'),
                rejected=session.get('quality_rejected_frames'), backend=session.get('segmentation_backend'),
                fps=session.get('steady_processing_fps'), registrations=[])
    if (folder / 'frame_events.jsonl').exists():
        events = [json.loads(line) for line in (folder / 'frame_events.jsonl').read_text().splitlines()]
        item['rejected_frames'] = [v['frame'] for v in events if not v.get('accepted_for_tracking', v.get('passed'))][:15]
        for event in events:
            if event.get('operation') != 'register':
                continue
            cap = json.loads((folder / 'frames' / event['frame'] / 'capture.json').read_text())
            item['registrations'].append(dict(frame=event['frame'], accepted=event.get('accepted_for_tracking'),
                depth_quality=event.get('depth_quality'), current_image_check=event.get('initialization_current_frame_check'),
                initialization=cap.get('initialization'), age_seconds=event.get('host_receive_to_result_seconds')))
    out['sessions'].append(item)
    if len(out['sessions']) >= 3:
        break
exe = '/home/ni/anaconda3/envs/foundationpose/bin/python'
code = "import torch,importlib.metadata as m,json;print(json.dumps(dict(torch=torch.__version__,cuda=torch.version.cuda,python=__import__('sys').version,packages={p.metadata['Name']:p.version for p in m.distributions() if p.metadata['Name'].startswith(('nvidia-','triton','torch','hydra','iopath'))})))"
res = subprocess.run([exe, '-c', code], capture_output=True, text=True)
out['native_gpu_environment'] = res.stdout.strip()
out['native_error'] = res.stderr[:500]
out['gpu'] = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.used,memory.total', '--format=csv'], text=True)
print(json.dumps(out, indent=2))
report = root / 'foundationpose_data/reacquisition_inspection_20261015.json'
if not report.exists():
    report.write_text(json.dumps(out, indent=2) + '\n')
