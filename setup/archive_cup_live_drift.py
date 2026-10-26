#!/usr/bin/env python3
"""Retain compact drift evidence and append current guide status on either host."""
import argparse
import hashlib
import json
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--root',type=Path,required=True)
p.add_argument('--analysis',type=Path)
p.add_argument('--comparison',type=Path)
args=p.parse_args()
root=args.root.resolve(strict=True)
mapping=[]
if args.analysis:
    mapping.extend([(args.analysis/'report.json','CUP_LIVE_DRIFT_AUDIT_20261014.json'),
                    (args.analysis/'frame_metrics.csv','CUP_LIVE_DRIFT_METRICS_20261014.csv'),
                    (args.analysis/'timeline_00.png','CUP_LIVE_DRIFT_TIMELINE_20261014.png')])
if args.comparison:
    mapping.extend([(args.comparison/'report.json','CUP_LIVE_DRIFT_COMPARISON_20261014.json'),
                    (args.comparison/'original_vs_fresh_120.png','CUP_LIVE_DRIFT_COMPARISON_20261014.png')])
for src,name in mapping:
    dest=root/'reports'/name
    data=src.read_bytes()
    if dest.exists():
        if dest.read_bytes()!=data:raise ValueError('Existing evidence differs; preserved '+name)
    else:
        with dest.open('xb') as f:f.write(data)
audit=json.loads((root/'reports/CUP_LIVE_DRIFT_AUDIT_20261014.json').read_text())
comparison=json.loads((root/'reports/CUP_LIVE_DRIFT_COMPARISON_20261014.json').read_text())
if not audit['passed'] or audit['completed_frames']!=399 or not comparison['passed']:
    raise ValueError('Need actual live drift audit and completed diagnostic replay')
marker='<!-- CUP-LIVE-DRIFT-20261014 -->'
line='2026-10-14实际Ubuntu直连D435i USB3.2会话399帧已验证输入与保存、约10FPS；用户确认移动相机。冻结帧到首跟踪帧24.39秒、杯身图像位置跳约182像素，旧姿态从首跟踪帧即失跟；初始Mask有效深度36.7%。同模型/权重在当前帧+检查过的新Mask重新初始化，独立120帧诊断重放的抽查投影明显改善（非GT）。正式实时入口仍需补初始化变化检查与失跟判定，本期没有改生产跟踪行为；见[漂移分析](reports/CUP_LIVE_DRIFT_ANALYSIS_20261014.md)。'
for name in ('AGENTS.md','REPRODUCTION_GUIDE.md','D435i_connection.md'):
    path=root/name
    old=path.read_text(encoding='utf-8') if path.exists() else ''
    if marker not in old:
        with path.open('a',encoding='utf-8') as f:f.write('\n'+marker+'\n'+line+'\n')
print(json.dumps(dict(passed=True,copied_files=len(mapping),guides_appended=True,original_live_outputs_modified=False,
                      analysis_report_sha256=hashlib.sha256((root/'reports/CUP_LIVE_DRIFT_AUDIT_20261014.json').read_bytes()).hexdigest())))
