"""Optional broad yaw validation for this metric cup model's known model-Z axis.

Uses the observed mask, not a measured pose. Official initial outputs remain saved.
"""
import time
import cv2
import numpy as np


def select_cup_yaw(seed,mask,raw,K,projection):
    started=time.monotonic()
    opened=cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_OPEN,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(21,21)))
    core=cv2.dilate(opened,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))>0
    protrusion=mask&~core
    count=int(protrusion.sum());rows=[]
    for degrees in range(-180,180,10):
        angle=np.deg2rad(degrees);rotation=np.eye(4)
        rotation[:2,:2]=[[np.cos(angle),-np.sin(angle)],[np.sin(angle),np.cos(angle)]]
        pose=seed@rotation;predicted=projection.render_depth(pose,K,raw.shape)
        sil=predicted>0;common=sil&(raw>0)
        iou=float((sil&mask).sum()/max(1,(sil|mask).sum()))
        recall=float((sil&protrusion).sum()/max(1,count))
        median=float(np.median(np.abs(predicted[common]-raw[common]*.001))) if common.any() else .1
        score=iou+(.15*recall if count>=50 else 0)-min(.1,median*2)
        eligible=int(common.sum())>=100 and median<=.015 and iou>=.6
        overlap=dict(iou=iou,precision=float((sil&mask).sum()/max(1,sil.sum())),recall=float((sil&mask).sum()/max(1,mask.sum())),consistent=eligible)
        rows.append(dict(yaw_degrees=degrees,pose=pose.tolist(),iou=iou,overlap=overlap,observed_protrusion_recall=recall,
                         median_depth_residual_m=median,score=score,eligible=eligible))
    baseline=next(row for row in rows if row['yaw_degrees']==0)
    eligible=[row for row in rows if row['eligible']]
    best=max(eligible,key=lambda row:row['score']) if eligible else baseline
    changed=bool(count>=50 and best['score']>=baseline['score']+.03 and best['iou']>=baseline['iou']-.01)
    selected=best if changed else baseline
    return np.array(selected['pose']),dict(enabled=True,changed=changed,selected=selected,baseline=baseline,
        candidates=rows,observed_protrusion_pixels=count,seconds=time.monotonic()-started,
        method='custom model-Z yaw search with init-mask protrusion recall and depth gate',
        protrusion_is_independent_ground_truth=False,pose_accuracy_validated=False)
