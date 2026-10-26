"""Target appearance/size gates and fresh-frame checks; no pose GT or class detector."""
import cv2
import numpy as np


def color_signature(rgb, mask):
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    selected = mask > 0
    if selected.sum() < 100:
        raise ValueError('Target mask too small')
    chromatic = selected & (hsv[:, :, 1] >= 45) & (hsv[:, :, 2] >= 35)
    bins = (hsv[:, :, 0].astype(np.int32) // 10) * 8 + hsv[:, :, 1].astype(np.int32) // 32
    labels = np.where(chromatic, bins, 144)
    hist = np.bincount(labels[selected], minlength=145).astype(np.float64)
    # Soften adjacent hue/saturation bins against exposure/white-balance changes.
    colored = hist[:144].reshape(18, 8)
    colored = .5 * colored + .25 * np.roll(colored, 1, axis=0) + .25 * np.roll(colored, -1, axis=0)
    padded = np.pad(colored, ((0, 0), (1, 1)), mode='edge')
    hist[:144] = (.6 * padded[:, 1:-1] + .2 * padded[:, :-2] + .2 * padded[:, 2:]).ravel()
    return (hist / hist.sum()).tolist()


def color_distance(reference, rgb, mask):
    observed = np.array(color_signature(rgb, mask))
    return float(np.sqrt(max(0, 1 - np.sqrt(np.array(reference) * observed).sum())))


def target_signature(rgb, mask, depth, K):
    selected = mask > 0
    yy, xx = np.nonzero(selected)
    values = depth[selected & (depth > 0)]
    if len(values) < 100:
        raise ValueError('Target has insufficient measured depth')
    z = float(np.median(values)) * .001
    return dict(color_hist=color_signature(rgb, mask), median_depth_m=z,
                projected_area_m2=float(selected.sum() * z * z / (K[0, 0] * K[1, 1])),
                width_m=float((xx.max() - xx.min() + 1) * z / K[0, 0]),
                height_m=float((yy.max() - yy.min() + 1) * z / K[1, 1]),
                identity_is_guaranteed=False)


def choose_target(reference, rgb, depth, K, masks, metadata):
    ranked = []
    for index, (mask, meta) in enumerate(zip(masks, metadata)):
        try:
            value = target_signature(rgb, mask, depth, K)
            distance = color_distance(reference['color_hist'], rgb, mask)
            area = value['projected_area_m2'] / reference['projected_area_m2']
            width = value['width_m'] / reference['width_m']
            height = value['height_m'] / reference['height_m']
            valid = distance <= .35 and .45 <= area <= 2.2 and .60 <= width <= 1.8 and .70 <= height <= 1.7
            score = distance + .2 * abs(np.log(area)) + .1 * abs(np.log(height)) - .05 * meta['predicted_iou']
            ranked.append(dict(index=index, eligible=bool(valid), score=float(score), color_distance=distance,
                               area_ratio=area, width_ratio=width, height_ratio=height))
        except ValueError:
            continue
    ranked.sort(key=lambda v: v['score'])
    eligible = [v for v in ranked if v['eligible']]
    selected = eligible[0]['index'] if eligible else None
    ambiguous = False
    if selected is not None:
        for candidate in eligible[1:]:
            a, b = masks[selected] > 0, masks[candidate['index']] > 0
            iou = np.count_nonzero(a & b) / max(1, np.count_nonzero(a | b))
            if iou < .3 and candidate['score'] - eligible[0]['score'] < .08:
                ambiguous, selected = True, None
                break
    return selected, dict(candidates=ranked, ambiguous=ambiguous, selected=selected,
                          identity_gate='initial confirmed color histogram and depth-scaled footprint; not unique object identity')


def fresh_frame_check(old, latest, mask):
    if np.array_equal(old, latest):
        return dict(consistent=True, median_flow_px=0., valid_features=None, identical_pixels=True)
    a, b = [cv2.cvtColor(v, cv2.COLOR_RGB2GRAY) for v in (old, latest)]
    points = cv2.goodFeaturesToTrack(a, maxCorners=180, qualityLevel=.01, minDistance=5, mask=(mask > 0).astype(np.uint8) * 255)
    if points is None or len(points) < 8:
        return dict(consistent=False, reason='insufficient features to certify frozen frame is current', valid_features=0)
    forward, ok, _ = cv2.calcOpticalFlowPyrLK(a, b, points, None, winSize=(21, 21), maxLevel=3)
    if forward is None or ok is None:
        return dict(consistent=False, reason='forward optical flow failed', valid_features=0)
    back, ok_back, _ = cv2.calcOpticalFlowPyrLK(b, a, forward, None, winSize=(21, 21), maxLevel=3)
    if back is None or ok_back is None:
        return dict(consistent=False, reason='backward optical flow failed', valid_features=0)
    good = (ok[:, 0] > 0) & (ok_back[:, 0] > 0) & (np.linalg.norm(back[:, 0] - points[:, 0], axis=1) < 1.5)
    count = int(good.sum())
    flow = np.linalg.norm(forward[good, 0] - points[good, 0], axis=1)
    median = float(np.median(flow)) if count else None
    p90 = float(np.percentile(flow, 90)) if count else None
    return dict(consistent=bool(count >= 8 and count / len(points) >= .45 and median <= 3 and p90 <= 8),
                median_flow_px=median, p90_flow_px=p90, valid_features=count, initial_features=len(points),
                scope='LK forward/backward frozen-frame motion gate; no physical accuracy verdict')


def mask_overlap(rendered, mask):
    a, b = rendered > 0, mask > 0
    common = int(np.count_nonzero(a & b))
    iou = common / max(1, np.count_nonzero(a | b))
    precision = common / max(1, a.sum())
    recall = common / max(1, b.sum())
    return dict(iou=float(iou), precision=float(precision), recall=float(recall),
                consistent=bool(iou >= .65 and precision >= .72 and recall >= .72))
