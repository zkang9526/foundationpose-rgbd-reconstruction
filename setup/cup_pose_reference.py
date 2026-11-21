"""Read a mesh-bound display reference and project its physical body-axis midpoint."""
import hashlib
import json
from pathlib import Path


def load_reference(meshfile, mesh_sha256):
    path = Path(meshfile).parent/'pose_reference.json'
    if not path.exists():
        return None
    reference = json.loads(path.read_text())
    if reference['mesh_sha256'] != mesh_sha256:
        raise ValueError('Display/body reference does not match the selected mesh')
    import numpy as np
    offset = np.asarray(reference['body_center_mesh_m'], dtype=float)
    if offset.shape != (3,) or not np.all(np.isfinite(offset)):
        raise ValueError('Invalid body-center reference')
    reference['reference_file_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    return reference


def body_center_pose(mesh_pose, reference):
    import numpy as np
    shift = np.eye(4)
    shift[:3, 3] = reference['body_center_mesh_m']
    return np.asarray(mesh_pose) @ shift


def mark_body_reference(image, pose, K, reference):
    import cv2
    import numpy as np
    center = body_center_pose(pose, reference)
    point = K @ center[:3, 3]
    if point[2] > 0:
        pixel = tuple(np.rint(point[:2]/point[2]).astype(int))
        cv2.circle(image, pixel, 6, (255, 0, 255), 2)
        cv2.putText(image, 'Cup body center', (pixel[0]+9, pixel[1]-7),
                    cv2.FONT_HERSHEY_SIMPLEX, .42, (255, 0, 255), 1, cv2.LINE_AA)
    return image
