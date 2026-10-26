#!/usr/bin/env python3
"""Post-hoc reference-only quality/continuity analysis; never delete data or hide pose drift."""
import argparse
import collections
import copy
import csv
import datetime
import hashlib
import json
from pathlib import Path
import shutil
import numpy as np
from cup_aruco_reference import rigid_error
from summarize_cup_aruco_session import stats


def select_reference(records, strict_quality=True):
    """Accepts marker data only; no FoundationPose pose/error is used by the selector."""
    decisions = []
    quality = []
    for row in records:
        m = row['marker']; reasons = []
        if not m.get('reference_accepted'):
            reasons.append('original_reference_rejected')
        if strict_quality and m.get('min_edge_pixels', 0) < 40:
            reasons.append('marker_edge_under_40px')
        if strict_quality and m.get('reprojection_rms_px', 1e9) > .5:
            reasons.append('reprojection_over_0.5px')
        alternative = m.get('alternative_reprojection_rms_px')
        if (strict_quality and alternative is not None and m.get('alternative_rotation_difference_deg', 0) > 5
                and alternative-m.get('reprojection_rms_px', 0) < .3):
            reasons.append('planar_reprojection_margin_under_0.3px')
        quality.append(not reasons)
        decisions.append(dict(frame=row['frame'], quality_pass=not reasons, stable_reference=False, reasons=reasons))
    for index, row in enumerate(records):
        d = decisions[index]
        if not quality[index]:
            continue
        before = [j for j in range(max(0,index-10),index) if quality[j] and 0 < row['time']-records[j]['time'] <= .2][-2:]
        after = [j for j in range(index+1,min(len(records),index+11)) if quality[j] and 0 < records[j]['time']-row['time'] <= .2][:2]
        if len(before) != 2 or len(after) != 2:
            d['reasons'].append('insufficient_two_sided_quality_neighbors'); continue
        neighbors = [np.array(records[j]['marker']['pose_camera_from_marker']) for j in before+after]
        costs = [sum(rigid_error(a,b)['rotation_error_deg'] for b in neighbors) for a in neighbors]
        local = neighbors[int(np.argmin(costs))].copy()
        local[:3,3] = np.median(np.array([p[:3,3] for p in neighbors]), axis=0)
        delta = rigid_error(np.array(row['marker']['pose_camera_from_marker']), local)
        d['marker_deviation_from_neighbors'] = delta
        if delta['translation_error_mm'] > 5:
            d['reasons'].append('marker_translation_deviation_over_5mm')
        if delta['rotation_error_deg'] > 5:
            d['reasons'].append('marker_rotation_deviation_over_5deg')
        d['stable_reference'] = not d['reasons']
    return decisions


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--session', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    session = args.session.resolve(strict=True); args.output.mkdir(parents=True, exist_ok=False)
    summary = json.loads((session/'evaluation_summary/report.json').read_text())
    for name,digest in summary['evidence_sha256'].items():
        if hashlib.sha256((session/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Original evidence changed: '+name)
    events = [json.loads(line) for line in (session/'frame_events.jsonl').read_text().splitlines()]
    records = []
    for e in events:
        folder = session/'frames'/e['frame']
        capture = json.loads((folder/'capture.json').read_text())
        records.append(dict(frame=e['frame'], time=datetime.datetime.fromisoformat(capture['received_utc']).timestamp(),
                            marker=json.loads((folder/'aruco.json').read_text())))
    decisions = select_reference(records)
    continuity = select_reference(records, strict_quality=False)
    # Irrelevant FP values cannot change a decision, including very large injected errors.
    contaminated = copy.deepcopy(records)
    for row in contaminated:
        row['foundationpose_error'] = dict(translation_error_mm=1e6, rotation_error_deg=180.)
    assert select_reference(contaminated) == decisions
    assert select_reference(contaminated, strict_quality=False) == continuity
    anchor_id = next(e['reference_evaluation']['anchor_frame'] for e in events if e['reference_evaluation'].get('anchored_object_errors') is not None)
    anchor_index = next(i for i,r in enumerate(records) if r['frame']==anchor_id)
    start = records[anchor_index]['time']
    base = []; quality = []; stable = []; early = []; continuity_only = []; early_base = []; early_continuity = []
    csvrows = []
    for e,r,d,c in zip(events,records,decisions,continuity):
        error = e['reference_evaluation'].get('anchored_object_errors')
        value = dict(frame=e['frame'], seconds_from_anchor=r['time']-start, **(error or {}))
        csvrows.append(dict(value, quality_pass=d['quality_pass'], stable_reference=d['stable_reference'],
                            reasons=';'.join(d['reasons']), continuity_only_reference=c['stable_reference'],
                            continuity_only_reasons=';'.join(c['reasons'])))
        if error is None or e['frame']==anchor_id:
            continue
        base.append(value)
        if 0 <= value['seconds_from_anchor'] < 20:
            early_base.append(value)
        if c['stable_reference']:
            continuity_only.append(value)
            if 0 <= value['seconds_from_anchor'] < 20:
                early_continuity.append(value)
        if d['quality_pass']:
            quality.append(value)
        if d['stable_reference']:
            stable.append(value)
            if 0 <= value['seconds_from_anchor'] < 20:
                early.append(value)
    def metrics(values):
        return dict(frames=len(values), retained_fraction_of_original_pairs=len(values)/max(1,len(base)),
                    retained_fraction_of_all_attempts=len(values)/max(1,len(events)),
                    translation_mm=stats([v['translation_error_mm'] for v in values]),
                    rotation_deg=stats([v['rotation_error_deg'] for v in values]))
    reason_counts=collections.Counter(reason for d in decisions for reason in d['reasons'])
    report = dict(passed=True, session=str(session), attempts=len(events), anchor_frame=anchor_id,
        original_anchor_kept=True, anchor_reference_filter_decision=decisions[anchor_index],
        anchor_continuity_only_filter_decision=continuity[anchor_index],
        scope='Post-hoc sensitivity to declared reference-only gates; no absolute GT and no independent filter calibration',
        rules=dict(min_marker_edge_px=40, max_reprojection_rms_px=.5,
            min_alternative_rms_margin_px_if_normal_difference_over_5deg=.3,
            two_before_and_two_after_quality_references_within_seconds=.2,
            max_translation_from_neighbor_median_mm=5, max_rotation_from_neighbor_medoid_deg=5),
        motion_assumption='Small locally smooth camera motion; legitimate abrupt reference motion may also be excluded',
        independent_of_foundationpose_error=True, independence_injection_check_passed=True,
        baseline=metrics(base), reference_quality_only=metrics(quality), reference_quality_and_continuity=metrics(stable),
        original_reference_acceptance_plus_continuity=metrics(continuity_only),
        continuity_only_scope='Keep original per-frame quality gates; require two earlier/later accepted reference neighbors within0.2s and <=5mm/5deg deviation, independent of FP errors',
        first_20_seconds_original_quality=metrics(early_base), first_20_seconds_continuity_only=metrics(early_continuity),
        first_20_seconds_same_filter=metrics(early),
        early_scope='Post-hoc first 20s diagnostic only; cut chosen after prior drift-onset observation; not whole-run accuracy or a confirmed static stage',
        rejection_reason_counts=dict(reason_counts),
        continuity_only_rejection_reasons=dict(collections.Counter(reason for d in continuity for reason in d['reasons'])),
        continuity_only_retained_final_10_seconds=metrics([v for v in continuity_only if v['seconds_from_anchor']>=max(r['time']-start for r in records)-10]),
        retained_time_range_seconds=[min(v['seconds_from_anchor'] for v in stable),max(v['seconds_from_anchor'] for v in stable)] if stable else None,
        retained_final_10_seconds=metrics([v for v in stable if v['seconds_from_anchor']>=max(r['time']-start for r in records)-10]),
        evidence_sha256=summary['evidence_sha256'], inputs_previously_hash_verified=summary['input_files_sha256_verified'])
    with (args.output/'filter_decisions.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream, fieldnames=('frame','seconds_from_anchor','translation_error_mm','rotation_error_deg','quality_pass','stable_reference','reasons','continuity_only_reference','continuity_only_reasons'))
        writer.writeheader(); writer.writerows(csvrows)
    (args.output/'retained_frame_ids.json').write_text(json.dumps(dict(reference_quality_only=[v['frame'] for v in quality],
                        reference_quality_and_continuity=[v['frame'] for v in stable], original_reference_acceptance_plus_continuity=[v['frame'] for v in continuity_only],
                        first_20_seconds_same_filter=[v['frame'] for v in early]),indent=2)+'\n')
    source=args.output/'analysis_source';source.mkdir()
    for name in (Path(__file__).name,'cup_aruco_reference.py','summarize_cup_aruco_session.py'):
        shutil.copy2(Path(__file__).parent/name,source/name)
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    manifest={path.relative_to(args.output).as_posix():dict(bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for path in args.output.rglob('*') if path.is_file()}
    (args.output/'SHA256SUMS.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':
    main()
