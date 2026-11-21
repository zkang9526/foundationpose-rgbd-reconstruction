"""Optional local-mask evidence for registration candidates with a visible handle hole."""
import numpy as np


def handle_region(target_mask):
    import cv2
    mask = np.asarray(target_mask, dtype=bool)
    if mask.ndim != 2 or mask.sum() < 200:
        return None
    count, labels, components, _ = cv2.connectedComponentsWithStats((~mask).astype(np.uint8), 8)
    holes = []
    height, width = mask.shape
    for label in range(1, count):
        x, y, w, h, area = components[label]
        if x > 0 and y > 0 and x + w < width and y + h < height and 20 <= area <= mask.sum() * .3:
            holes.append(label)
    if not holes:
        return None
    label = max(holes, key=lambda value: components[value, cv2.CC_STAT_AREA])
    x, y, w, h, area = components[label]
    padding = max(6, int(max(w, h) * .65))
    region = np.zeros_like(mask)
    region[max(0, y-padding):min(height, y+h+padding), max(0, x-padding):min(width, x+w+padding)] = True
    if (region & mask).sum() < 100:
        return None
    return dict(region=region, hole=labels == label, hole_pixels=int(area),
                roi_xyxy=[int(max(0, x-padding)), int(max(0, y-padding)),
                          int(min(width, x+w+padding)), int(min(height, y+h+padding))])


def local_quality(predicted_mask, target_mask, reference):
    if reference is None:
        return None
    predicted = np.asarray(predicted_mask, dtype=bool)
    target = np.asarray(target_mask, dtype=bool)
    region = reference['region']
    foreground = target & region
    return dict(iou=float((predicted & foreground).sum() / max(1, ((predicted | target) & region).sum())),
                foreground_recall=float((predicted & foreground).sum() / max(1, foreground.sum())),
                hole_filled_fraction=float(predicted[reference['hole']].mean()),
                roi_xyxy=reference['roi_xyxy'], hole_pixels=reference['hole_pixels'])


def select_registration_candidate(candidates, use_local=False):
    eligible = [candidate for candidate in candidates
                if candidate['overlap']['consistent'] and candidate['depth_quality']['heuristic_consistent']]
    original_eligible = [candidate for candidate in eligible if candidate['rank'] < 8]
    chosen = max(original_eligible, key=lambda candidate: candidate['selection_metric']) if original_eligible else candidates[0]
    if candidates[0] in original_eligible and chosen['selection_metric'] - candidates[0]['selection_metric'] < .015:
        chosen = candidates[0]
    decision = dict(enabled=use_local, changed=False, fallback_rank=chosen['rank'],
                    reason='local_selection_disabled', pose_accuracy_validated=False)
    if not use_local:
        return chosen, decision
    if chosen.get('handle_quality') is None:
        decision['reason'] = 'no_reliable_interior_hole_region'
        return chosen, decision
    local = [candidate for candidate in eligible if candidate.get('handle_quality') is not None
             and candidate['overlap']['iou'] >= chosen['overlap']['iou'] - .005]
    if not local:
        decision['reason'] = 'no_eligible_local_candidates'
        return chosen, decision
    for candidate in local:
        candidate['handle_selection_metric'] = .5 * candidate['selection_metric'] + .5 * candidate['handle_quality']['iou']
    chosen['handle_selection_metric'] = .5 * chosen['selection_metric'] + .5 * chosen['handle_quality']['iou']
    best = max(local, key=lambda candidate: candidate['handle_selection_metric'])
    gain = best['handle_selection_metric'] - chosen['handle_selection_metric']
    local_gain = best['handle_quality']['iou'] - chosen['handle_quality']['iou']
    recall_gain = best['handle_quality']['foreground_recall'] - chosen['handle_quality']['foreground_recall']
    accepted = gain >= .02 and local_gain >= .03 and recall_gain >= -.02
    decision.update(reason='local_evidence_accepted' if accepted else 'insufficient_local_improvement',
                    proposed_rank=best['rank'], combined_gain=gain, local_iou_gain=local_gain,
                    local_recall_gain=recall_gain, changed=bool(accepted and best['rank'] != chosen['rank']),
                    weights=dict(global_metric=.5, local_iou=.5),
                    thresholds=dict(combined_gain=.02, local_iou_gain=.03, maximum_recall_loss=.02,
                                    maximum_global_iou_loss=.005))
    return (best if accepted else chosen), decision
