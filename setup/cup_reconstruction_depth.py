"""Reproduce saved reconstruction depth selection for derived cloud/TSDF tools."""
import cv2
import numpy as np


def selected_depth_mask(depth, mask, report, frame):
    """Legacy defaults remain unchanged; optional v2 rejection is pixel-exact."""
    valid=mask & (depth>=300) & (depth<=800)
    valid &= np.abs(depth.astype(float)-frame['sampled_body_depth_median_mm'])<=report['body_halfspan_mm']
    margin=int(report.get('mask_erode_pixels',0))
    tolerance=float(report.get('depth_consistency_mm',0))
    if margin<0 or tolerance<0:raise ValueError('Negative saved filter setting')
    if margin:
        valid &= cv2.erode(mask.astype(np.uint8),np.ones((2*margin+1,)*2,np.uint8))>0
    if tolerance:
        median=cv2.medianBlur(depth,3)
        neighbors=cv2.boxFilter((depth>0).astype(np.float32),-1,(3,3),normalize=False)
        valid &= (neighbors>=5)&(np.abs(depth.astype(float)-median.astype(float))<=tolerance)
    return valid
