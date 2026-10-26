#!/usr/bin/env python3
"""Make offline GrabCut *candidate* masks without modifying a capture scene.

Rectangle coordinates are [x0, y0, x1, y1], with exclusive right/bottom
bounds. OpenCV HSV uses H=0..179 and S/V=0..255. These masks require visual
review; they are neither accepted annotations nor pose ground truth.
"""

import argparse
import datetime
import hashlib
import json
import shutil
import sys
import traceback
from pathlib import Path

import cv2
import numpy as np


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_image(path):
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError("Cannot decode image: " + str(path))
    return image


def write_image(path, image):
    success, encoded = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Cannot encode image: " + str(path))
    encoded.tofile(str(path))


def rectangle(value, label, width, height):
    if (not isinstance(value, list) or len(value) != 4 or
            any(type(coordinate) is not int for coordinate in value)):
        raise ValueError(label + " must contain four integer coordinates")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(label + " lies outside the image or has no area")
    return x0, y0, x1, y1


def rectangle_mask(rect, shape):
    result = np.zeros(shape, dtype=bool)
    x0, y0, x1, y1 = rect
    result[y0:y1, x0:x1] = True
    return result


def polygon_mask(points, shape, label):
    """Rasterize a manually described polygon, validating every coordinate."""
    height, width = shape
    if (not isinstance(points, list) or len(points) < 3 or
            any(not isinstance(point, list) or len(point) != 2 or
                any(type(coordinate) is not int for coordinate in point)
                for point in points)):
        raise ValueError(label + " must contain at least three [integer x, integer y] points")
    if any(not (0 <= x < width and 0 <= y < height) for x, y in points):
        raise ValueError(label + " contains an out-of-image coordinate")
    vertices = np.asarray(points, np.int32)
    if abs(cv2.contourArea(vertices)) < 1:
        raise ValueError(label + " has no area")
    result = np.zeros(shape, np.uint8)
    cv2.fillPoly(result, [vertices], 1)
    return result > 0


def geometry_constraints(geometry, config, shape):
    """Approximate cup support and conservative body seeds; never pose labels."""
    height, width = shape
    keys = ("body_left_x", "top_y", "body_right_x_exclusive", "bottom_y_exclusive")
    bounds = rectangle([geometry.get(key) for key in keys], "geometry body bounds", width, height)
    x0, y0, x1, y1 = bounds
    polygon = geometry.get("body_polygon_xy")
    if polygon is None:
        # Chamfered rounded-cylinder approximation, rather than a broad rectangle.
        bevel_x = min(6, max(1, (x1 - x0) // 12))
        bevel_y = min(8, max(1, (y1 - y0) // 16))
        polygon = [[x0 + bevel_x, y0], [x1 - 1 - bevel_x, y0],
                   [x1 - 1, y0 + bevel_y], [x1 - 1, y1 - 1 - bevel_y],
                   [x1 - 1 - bevel_x, y1 - 1], [x0 + bevel_x, y1 - 1],
                   [x0, y1 - 1 - bevel_y], [x0, y0 + bevel_y]]
        strategy = "chamfered rounded-cylinder approximation from manual exclusive body bounds"
    else:
        strategy = "manually supplied body polygon"
    body = polygon_mask(polygon, shape, "body_polygon_xy")
    if np.any(body & ~rectangle_mask(bounds, shape)):
        raise ValueError("body_polygon_xy lies outside its manual body bounds")
    parameters = {}
    for key, default in (("body_core_inset_x_pixels", 8),
                         ("body_core_top_inset_pixels", 20),
                         ("body_core_bottom_inset_pixels", 4),
                         ("handle_hole_erosion_pixels", 3),
                         ("handle_hole_cyan_margin_pixels", 3),
                         ("body_hole_fill_max_pixels", 128)):
        value = geometry.get(key, config.get(key, default))
        maximum = 30 if key.startswith("handle_hole_") else width * height
        if type(value) is not int or not (0 <= value <= maximum):
            raise ValueError(key + " must be an integer in [0,{}]".format(maximum))
        parameters[key] = value
    inset_x = parameters["body_core_inset_x_pixels"]
    core_bounds = [x0 + inset_x, y0 + parameters["body_core_top_inset_pixels"],
                   x1 - inset_x, y1 - parameters["body_core_bottom_inset_pixels"]]
    core_bounds = rectangle(core_bounds, "inset body core", width, height)
    core = rectangle_mask(core_bounds, shape) & body
    explicit = {}
    for key in ("foreground_polygons", "background_polygons"):
        polygons = geometry.get(key, [])
        if not isinstance(polygons, list):
            raise ValueError(key + " must be a list of polygons")
        union = np.zeros(shape, bool)
        for index, points in enumerate(polygons):
            union |= polygon_mask(points, shape, "{}[{}]".format(key, index))
        explicit[key] = union
    if np.any(explicit["foreground_polygons"] & explicit["background_polygons"]):
        raise ValueError("Manual foreground and background polygons overlap")
    details = {"source": "per-frame human approximate geometry, not accepted mask or pose ground truth",
               "body_bounds_xyxy": list(bounds), "body_polygon_xy": polygon,
               "body_support_strategy": strategy, "body_pixels": int(np.count_nonzero(body)),
               "body_core_bounds_xyxy": list(core_bounds), "body_core_pixels": int(np.count_nonzero(core)),
               "parameters": parameters, "confidence": geometry.get("confidence"),
               "comment": geometry.get("comment"),
               "manual_foreground_polygon_pixels": int(np.count_nonzero(explicit["foreground_polygons"])),
               "manual_background_polygon_pixels": int(np.count_nonzero(explicit["background_polygons"]))}
    return body, core, explicit, details


def ellipse_kernel(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def handle_hole_background(cyan, body, geometry_details):
    """A handle hull proposes *background* only, never fills the entire handle."""
    x0, _, x1, _ = geometry_details["body_bounds_xyxy"]
    parameters = geometry_details["parameters"]
    erosion = parameters["handle_hole_erosion_pixels"]
    margin = parameters["handle_hole_cyan_margin_pixels"]
    protected_cyan = (cv2.dilate(cyan.astype(np.uint8), ellipse_kernel(margin)) > 0
                      if margin else cyan)
    xx = np.arange(cyan.shape[1])[None, :]
    result = np.zeros(cyan.shape, bool)
    sides = []
    for side, outside in (("left", xx < x0), ("right", xx >= x1)):
        ys, xs = np.nonzero(cyan & outside & ~body)
        if xs.size < 3:
            continue
        hull = cv2.convexHull(np.column_stack((xs, ys)).astype(np.int32))
        hull_mask = np.zeros(cyan.shape, np.uint8)
        cv2.fillConvexPoly(hull_mask, hull, 1)
        if erosion:
            hull_mask = cv2.erode(hull_mask, ellipse_kernel(erosion))
        proposed = (hull_mask > 0) & ~protected_cyan & ~body
        result |= proposed
        sides.append({"side": side, "external_cyan_pixels": int(xs.size),
                      "hard_background_pixels": int(np.count_nonzero(proposed)),
                      "hull_polygon_xy": hull.reshape(-1, 2).tolist()})
    return result, {"strategy": "eroded external handle cyan hull minus dilated cyan minus body polygon; hull is not foreground",
                    "body_visible_inside_handle_is_protected": True,
                    "hard_background_pixels": int(np.count_nonzero(result)), "sides": sides}


def fill_small_body_holes(foreground, body, hard_background, maximum):
    """Fill only small enclosed body-interior gaps, preserving exterior/handle holes."""
    if not maximum:
        return foreground, {"filled_holes": 0, "filled_pixels": 0, "maximum_pixels": 0}
    absent = ~foreground
    count, components, stats, _ = cv2.connectedComponentsWithStats(absent.astype(np.uint8), connectivity=8)
    filled_pixels = 0
    filled_holes = 0
    for index in range(1, count):
        if stats[index, cv2.CC_STAT_AREA] > maximum:
            continue
        gap = components == index
        # Entire component must lie strictly within the body, not reach a background constraint.
        if np.any(gap & (~body | hard_background)):
            continue
        if (stats[index, cv2.CC_STAT_LEFT] == 0 or stats[index, cv2.CC_STAT_TOP] == 0 or
                stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] == foreground.shape[1] or
                stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] == foreground.shape[0]):
            continue
        foreground[gap] = True
        filled_holes += 1
        filled_pixels += int(stats[index, cv2.CC_STAT_AREA])
    return foreground, {"strategy": "small enclosed gaps wholly inside manual body support only; no global hole filling",
                        "filled_holes": filled_holes, "filled_pixels": filled_pixels,
                        "maximum_pixels": maximum}


def validate_config(config, width, height):
    roi = rectangle(config.get("roi_xyxy"), "roi_xyxy", width, height)
    parsed = {"roi": roi}
    for key in ("probable_foreground_rectangles", "definite_foreground_rectangles"):
        values = config.get(key, [])
        if not isinstance(values, list):
            raise ValueError(key + " must be a list of rectangles")
        parsed[key] = []
        for index, value in enumerate(values):
            rect = rectangle(value, "{}[{}]".format(key, index), width, height)
            if not (roi[0] <= rect[0] < rect[2] <= roi[2] and
                    roi[1] <= rect[1] < rect[3] <= roi[3]):
                raise ValueError(key + " seed lies outside roi_xyxy")
            parsed[key].append(rect)
    hard_y = config.get("hard_background_y_min")
    if type(hard_y) is not int or not (0 <= hard_y <= height):
        raise ValueError("hard_background_y_min must be an integer in [0,height]")
    parsed["hard_y"] = hard_y
    hard_rectangles = config.get("hard_background_rectangles", [])
    if not isinstance(hard_rectangles, list):
        raise ValueError("hard_background_rectangles must be a list of rectangles")
    parsed["hard_background_rectangles"] = [
        rectangle(value, "hard_background_rectangles[{}]".format(index), width, height)
        for index, value in enumerate(hard_rectangles)]
    parsed["restrict_shape"] = config.get("restrict_to_cup_shape", False)
    parsed["include_nearby_cyan"] = config.get("include_nearby_cyan_components", True)
    if type(parsed["restrict_shape"]) is not bool or type(parsed["include_nearby_cyan"]) is not bool:
        raise ValueError("restrict_to_cup_shape and include_nearby_cyan_components must be boolean")
    for key, default, maximum in (("shape_dilation_pixels", 5, 30),
                                  ("shape_top_margin_pixels", 4, 30),
                                  ("cyan_neighbor_distance_pixels", 10, 40),
                                  ("cyan_neighbor_min_pixels", 15, width * height)):
        value = config.get(key, default)
        if type(value) is not int or not (0 <= value <= maximum):
            raise ValueError(key + " must be an integer in [0,{}]".format(maximum))
        parsed[key] = value
    body_reference = config.get("body_reference_rectangle")
    if body_reference is None and parsed["probable_foreground_rectangles"]:
        body_reference = list(parsed["probable_foreground_rectangles"][0])
    if parsed["restrict_shape"]:
        parsed["body_reference"] = rectangle(body_reference, "body_reference_rectangle", width, height)
    cyan = config.get("cyan_seed")
    if not isinstance(cyan, dict):
        raise ValueError("cyan_seed must contain h_min/h_max/s_min/s_max/v_min/v_max")
    for channel, maximum in (("h", 179), ("s", 255), ("v", 255)):
        low, high = cyan.get(channel + "_min"), cyan.get(channel + "_max")
        if (type(low) is not int or type(high) is not int or
                not 0 <= low <= high <= maximum):
            raise ValueError("Invalid cyan_seed bounds for " + channel)
    parsed["cyan_lower"] = np.array([cyan["h_min"], cyan["s_min"], cyan["v_min"]], np.uint8)
    parsed["cyan_upper"] = np.array([cyan["h_max"], cyan["s_max"], cyan["v_max"]], np.uint8)
    iterations = config.get("iterations", 5)
    if type(iterations) is not int or not (1 <= iterations <= 30):
        raise ValueError("iterations must be an integer in [1,30]")
    parsed["iterations"] = iterations
    keep_largest = config.get("keep_largest_component", True)
    if type(keep_largest) is not bool:
        raise ValueError("keep_largest_component must be boolean")
    parsed["keep_largest"] = keep_largest
    for key in ("minimum_foreground_seed_pixels", "minimum_background_seed_pixels"):
        count = config.get(key, 64)
        if type(count) is not int or count < 1:
            raise ValueError(key + " must be a positive integer")
        parsed[key] = count
    return parsed


def anchored_cyan(raw_cyan, anchors, parsed):
    """Strong color seeds must be connected to this cup, not arbitrary scenery."""
    count, component_labels, stats, _ = cv2.connectedComponentsWithStats(
        raw_cyan.astype(np.uint8), connectivity=8)
    anchored = [index for index in range(1, count)
                if np.any(anchors & (component_labels == index))]
    if not anchored:
        raise ValueError("No cyan component intersects a definite foreground rectangle")
    primary = max(anchored, key=lambda index: int(stats[index, cv2.CC_STAT_AREA]))
    selected = [primary]
    px, py, pw, ph, _ = [int(value) for value in stats[primary]]
    if parsed["include_nearby_cyan"]:
        for index in range(1, count):
            if index == primary or stats[index, cv2.CC_STAT_AREA] < parsed["cyan_neighbor_min_pixels"]:
                continue
            x, y, w, h, _ = [int(value) for value in stats[index]]
            dx = max(px - (x + w), x - (px + pw), 0)
            dy = max(py - (y + h), y - (py + ph), 0)
            if max(dx, dy) <= parsed["cyan_neighbor_distance_pixels"]:
                selected.append(index)
    selected_mask = np.isin(component_labels, selected)
    details = {"strategy": "primary cyan component intersects definite foreground; optional nearby cyan components",
               "raw_cyan_pixels": int(np.count_nonzero(raw_cyan)),
               "raw_cyan_components": count - 1,
               "primary_component_label": primary,
               "primary_component_bbox_xyxy": [px, py, px + pw, py + ph],
               "selected_component_labels": selected,
               "selected_cyan_pixels": int(np.count_nonzero(selected_mask)),
               "excluded_cyan_pixels": int(np.count_nonzero(raw_cyan & ~selected_mask)),
               "nearby_component_distance_pixels": parsed["cyan_neighbor_distance_pixels"],
               "nearby_component_min_pixels": parsed["cyan_neighbor_min_pixels"]}
    return selected_mask, details


def candidate_mask(bgr, config, geometry=None):
    height, width = bgr.shape[:2]
    parsed = validate_config(config, width, height)
    shape = (height, width)
    roi_pixels = rectangle_mask(parsed["roi"], shape)
    labels = np.full(shape, cv2.GC_BGD, dtype=np.uint8)
    labels[roi_pixels] = cv2.GC_PR_BGD
    for rect in parsed["probable_foreground_rectangles"]:
        labels[rectangle_mask(rect, shape)] = cv2.GC_PR_FGD
    requested_definite = np.zeros(shape, dtype=bool)
    for rect in parsed["definite_foreground_rectangles"]:
        requested_definite |= rectangle_mask(rect, shape)
    geometry_details = None
    body = None
    body_core = np.zeros(shape, bool)
    manual_foreground = np.zeros(shape, bool)
    manual_background = np.zeros(shape, bool)
    if geometry is not None:
        if not isinstance(geometry, dict):
            raise ValueError("Per-frame geometry must be an object")
        body, body_core, explicit, geometry_details = geometry_constraints(geometry, config, shape)
        manual_foreground = explicit["foreground_polygons"]
        manual_background = explicit["background_polygons"]
        requested_definite |= body_core | manual_foreground
        labels[body & roi_pixels] = cv2.GC_PR_FGD
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    raw_cyan = cv2.inRange(hsv, parsed["cyan_lower"], parsed["cyan_upper"]) > 0
    raw_cyan &= roi_pixels
    # The red turntable/tape is context, not part of this cyan/black cup.
    red = (((hsv[:, :, 0] <= 12) | (hsv[:, :, 0] >= 170)) &
           (hsv[:, :, 1] >= 80) & (hsv[:, :, 2] >= 50))
    # A manually bounded body core can contain red reflections on the black cup.
    # Context red remains background outside these explicit foreground seeds.
    protected_manual_foreground = body_core | manual_foreground
    hard_background = ~roi_pixels | (red & ~protected_manual_foreground)
    if geometry_details is not None:
        geometry_details["red_pixels_protected_by_manual_foreground_seeds"] = int(
            np.count_nonzero(red & protected_manual_foreground))
    hard_background[parsed["hard_y"]:, :] = True
    for rect in parsed["hard_background_rectangles"]:
        hard_background |= rectangle_mask(rect, shape)
    hard_background |= manual_background
    if np.any(requested_definite & hard_background):
        raise ValueError("Definite foreground rectangle intersects red/external/lower hard background")
    raw_cyan &= ~hard_background
    cyan, cyan_details = anchored_cyan(raw_cyan, requested_definite, parsed)
    shape_enabled = parsed["restrict_shape"] or geometry is not None
    shape_details = {"enabled": shape_enabled,
                     "strategy": "allowed support only; cyan and conservative body core are foreground seeds"}
    handle_details = None
    if geometry is not None:
        radius = parsed["shape_dilation_pixels"]
        cyan_support = (cv2.dilate(cyan.astype(np.uint8), ellipse_kernel(radius)) > 0
                        if radius else cyan)
        support = body | cyan_support | manual_foreground
        # Optional manually bounded cup-plus-handle support suppresses adjacent
        # similarly colored context. It is an allowed region, not foreground;
        # external handle openings still receive the normal background seeds.
        object_support_polygon = geometry.get("object_support_polygon_xy")
        if object_support_polygon is not None:
            object_support = polygon_mask(object_support_polygon, shape,
                                          "object_support_polygon_xy")
            before_support_pixels = int(np.count_nonzero(support))
            support &= object_support
            shape_details.update({
                "object_support_polygon_applied": True,
                "object_support_polygon_xy": object_support_polygon,
                "object_support_strategy": "manual cup-plus-handle allowed region only; no foreground or hole filling",
                "object_support_pixels": int(np.count_nonzero(object_support)),
                "context_support_pixels_removed": before_support_pixels - int(np.count_nonzero(support)),
            })
            geometry_details["object_support_polygon_xy"] = object_support_polygon
        hard_background |= ~support
        hole_background, handle_details = handle_hole_background(cyan, body, geometry_details)
        hard_background |= hole_background
        if np.any(requested_definite & hard_background):
            raise ValueError("Definite foreground intersects external/lower/manual/handle background")
        shape_details.update({"manual_body_geometry_applied": True,
                              "cyan_dilation_radius_pixels": radius,
                              "support_pixels": int(np.count_nonzero(support)),
                              "shape_forced_background_pixels": int(np.count_nonzero(roi_pixels & ~support))})
    elif parsed["restrict_shape"]:
        body_reference = rectangle_mask(parsed["body_reference"], shape)
        body_cyan = cyan & body_reference
        ys_body, xs_body = np.nonzero(body_cyan)
        if xs_body.size < 16:
            raise ValueError("Too little selected cyan inside body_reference_rectangle")
        # Horizontal bounds come from the cup's color, not a broad scene ROI.
        body_x0, body_x1 = int(xs_body.min()), int(xs_body.max() + 1)
        body_y0 = max(0, int(np.nonzero(cyan)[0].min()) - parsed["shape_top_margin_pixels"])
        if body_y0 >= parsed["hard_y"]:
            raise ValueError("Cup body support has no height before hard-background cutoff")
        support = np.zeros(shape, np.uint8)
        radius = parsed["shape_dilation_pixels"]
        if radius:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
            support = cv2.dilate(cyan.astype(np.uint8), kernel)
        else:
            support = cyan.astype(np.uint8)
        support[body_y0:parsed["hard_y"], body_x0:body_x1] = 1
        hard_background |= support == 0
        if np.any(requested_definite & hard_background):
            raise ValueError("Definite foreground rectangle lies outside cup shape support")
        shape_details.update({"body_reference_rectangle": list(parsed["body_reference"]),
                              "body_support_rectangle": [body_x0, body_y0, body_x1, parsed["hard_y"]],
                              "cyan_dilation_radius_pixels": radius,
                              "support_pixels": int(np.count_nonzero(support)),
                              "shape_forced_background_pixels": int(np.count_nonzero(roi_pixels & (support == 0)))})
    definite = requested_definite | (cyan & ~hard_background)
    labels[definite] = cv2.GC_FGD
    labels[hard_background] = cv2.GC_BGD
    foreground_seeds = int(np.count_nonzero(labels == cv2.GC_FGD))
    background_seeds = int(np.count_nonzero(labels == cv2.GC_BGD))
    if foreground_seeds < parsed["minimum_foreground_seed_pixels"]:
        raise ValueError("Too few definite foreground seeds: " + str(foreground_seeds))
    if background_seeds < parsed["minimum_background_seed_pixels"]:
        raise ValueError("Too few definite background seeds: " + str(background_seeds))
    cv2.grabCut(bgr, labels, None, np.zeros((1, 65), np.float64),
                np.zeros((1, 65), np.float64), parsed["iterations"], cv2.GC_INIT_WITH_MASK)
    foreground = ((labels == cv2.GC_FGD) | (labels == cv2.GC_PR_FGD))
    foreground[hard_background] = False
    hole_fill_details = None
    if geometry_details is not None:
        foreground, hole_fill_details = fill_small_body_holes(
            foreground, body, hard_background,
            geometry_details["parameters"]["body_hole_fill_max_pixels"])
    # Component selection retains hard-background holes; no global hole filling.
    count, component_labels, stats, _ = cv2.connectedComponentsWithStats(
        foreground.astype(np.uint8), connectivity=8)
    components = [{"label": index, "pixels": int(stats[index, cv2.CC_STAT_AREA]),
                   "bbox_xyxy": [int(stats[index, cv2.CC_STAT_LEFT]),
                                  int(stats[index, cv2.CC_STAT_TOP]),
                                  int(stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH]),
                                  int(stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT])],
                   "definite_seed_pixels": int(np.count_nonzero(definite & (component_labels == index)))}
                  for index in range(1, count)]
    if not components:
        raise ValueError("GrabCut produced an empty candidate mask")
    selected_label = None
    if parsed["keep_largest"]:
        selected_label = max(components, key=lambda item: item["pixels"])["label"]
        foreground = component_labels == selected_label
    lost_seeds = int(np.count_nonzero(definite & ~foreground))
    ys, xs = np.nonzero(foreground)
    x0, y0, x1, y1 = parsed["roi"]
    boundary = {"roi_left": bool(np.any(foreground[:, x0])),
                "roi_right": bool(np.any(foreground[:, x1 - 1])),
                "roi_top": bool(np.any(foreground[y0, :])),
                "roi_bottom": bool(np.any(foreground[y1 - 1, :])),
                "hard_background_cut": bool(parsed["hard_y"] > 0 and
                                              np.any(foreground[parsed["hard_y"] - 1, :])),
                "image_border": bool(np.any(foreground[0, :]) or np.any(foreground[-1, :]) or
                                      np.any(foreground[:, 0]) or np.any(foreground[:, -1]))}
    flags = []
    if lost_seeds:
        flags.append("definite_foreground_seeds_discarded")
    if any(boundary.values()):
        flags.append("candidate_touches_roi_or_hard_background_boundary")
    if len(components) > 1:
        flags.append("multiple_foreground_components_before_selection")
    return (foreground.astype(np.uint8) * 255, {
        "mask_pixels": int(len(xs)),
        "bbox_xyxy": [int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)],
        "foreground_seed_pixels": foreground_seeds, "background_seed_pixels": background_seeds,
        "cyan_seed_pixels": int(np.count_nonzero(cyan & ~hard_background)),
        "cyan_seed_strategy": cyan_details,
        "cup_shape_support": shape_details,
        "manual_body_geometry": geometry_details,
        "handle_opening_background": handle_details,
        "body_interior_hole_filling": hole_fill_details,
        "constraint_flags": (["cup_anchored_cyan_seeds"] +
                             (["cup_shape_support_applied"] if shape_enabled else []) +
                             (["manual_body_geometry_core_seeds_applied", "external_handle_hole_background_applied"]
                              if geometry is not None else []) +
                             (["explicit_hard_background_rectangles_applied"]
                              if parsed["hard_background_rectangles"] else [])),
        "hard_background_rectangles": [list(rect) for rect in parsed["hard_background_rectangles"]],
        "components_before_selection": components,
        "component_count_before_selection": len(components),
        "selected_component_label": selected_label,
        "definite_seed_pixels_discarded": lost_seeds,
        "roi_boundary_flags": boundary, "flags": flags,
    })


def overlay(bgr, mask):
    result = bgr.copy()
    chosen = mask > 0
    result[chosen] = (0.62 * bgr[chosen] + 0.38 * np.array([0, 255, 0])).astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(result, contours, -1, (0, 255, 255), 1)
    cv2.putText(result, "CANDIDATE - REVIEW REQUIRED", (8, 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path, help="Original RGB-D capture directory (read only)")
    parser.add_argument("--output", required=True, type=Path, help="New derived candidate directory, outside the scene")
    parser.add_argument("--config", required=True, type=Path, help="JSON ROI, seed rectangles, hard-background and HSV settings")
    parser.add_argument("--geometry", type=Path,
                        help="Optional per-frame manual body bounds/polygons and FG/BG polygons JSON; not ground truth")
    parser.add_argument("--frames", help="Optional comma-separated frame stems, e.g. 000000,000027, for subset candidate QA")
    args = parser.parse_args()
    scene, output = args.scene.resolve(), args.output.resolve()
    if output == scene or scene in output.parents:
        parser.error("Output must be outside the original scene directory")
    if output.exists():
        parser.error("Refusing to overwrite an existing output directory: " + str(output))
    output.mkdir(parents=True, exist_ok=False)
    (output / "masks").mkdir()
    (output / "overlays").mkdir()
    report_path = output / "report.json"
    report = {"schema_version": 2, "status": "running", "passed": False,
              "candidate_generation_only": True, "masks_accepted": False,
              "manual_review_required": True, "not_pose_ground_truth": True,
              "source_scene": str(scene), "output": str(output),
              "started_at_utc": utc_now(), "frames": [], "processed_frames": 0,
              "method": "OpenCV GrabCut with cup-anchored HSV/rectangular seeds; optional manual body support/core, external handle-hole BG and small body-only hole filling",
              "opencv_version": cv2.__version__, "numpy_version": np.__version__,
              "depth_zero_does_not_remove_rgb_foreground": True}
    write_json(report_path, report)
    current_frame = None
    try:
        config_path = args.config.resolve()
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("Config root must be an object")
        write_json(output / "config.json", config)
        script = Path(__file__).resolve()
        shutil.copy2(script, output / "make_cup_masks_grabcut.py")
        report["configuration"] = config
        report["source_hashes"] = {"config": {"path": str(config_path), "sha256": sha256(config_path)},
                                   "script": {"path": str(script), "sha256": sha256(script)}}
        geometry_frames = None
        if args.geometry is not None:
            geometry_path = args.geometry.resolve()
            geometry = json.loads(geometry_path.read_text(encoding="utf-8-sig"))
            if not isinstance(geometry, dict):
                raise ValueError("Geometry JSON root must be an object")
            source_frames = geometry.get("frames")
            if isinstance(source_frames, dict):
                geometry_frames = source_frames
            elif isinstance(source_frames, list):
                geometry_frames = {}
                for item in source_frames:
                    if not isinstance(item, dict) or not isinstance(item.get("frame"), str):
                        raise ValueError("Each geometry frames list item must contain a string frame")
                    key = item["frame"]
                    if key.endswith(".png"):
                        key = key[:-4]
                    if key in geometry_frames:
                        raise ValueError("Duplicate geometry frame: " + key)
                    geometry_frames[key] = item
            else:
                raise ValueError("Geometry JSON frames must be an object or frame-keyed list")
            write_json(output / "geometry.json", geometry)
            report["source_hashes"]["geometry"] = {"path": str(geometry_path), "sha256": sha256(geometry_path)}
            report["manual_geometry_provenance"] = {
                "not_ground_truth": True, "masks_accepted": False,
                "description": "Human approximate image-space cup geometry for candidate segmentation seeds/support only",
                "source_sha256": sha256(geometry_path)}
        for filename in ("K.txt", "cam_K.txt", "depth_scale.txt", "metadata.json",
                         "report.json", "timestamps.csv", "timestamps.json"):
            path = scene / filename
            if path.is_file():
                report["source_hashes"][filename] = {"path": str(path), "sha256": sha256(path)}
        if "metadata.json" not in report["source_hashes"]:
            raise ValueError("Original metadata.json is missing")
        if not any(name in report["source_hashes"] for name in ("K.txt", "cam_K.txt")):
            raise ValueError("Original camera intrinsics are missing")
        rgb_paths = sorted((scene / "rgb").glob("*.png"))
        depth_paths = sorted((scene / "depth").glob("*.png"))
        if not rgb_paths or [path.name for path in rgb_paths] != [path.name for path in depth_paths]:
            raise ValueError("Nonempty one-to-one RGB/depth PNG pairs are required")
        report["source_scene_paired_frames"] = len(rgb_paths)
        if args.frames is not None:
            selected_names = []
            for token in args.frames.split(","):
                stem = token.strip()
                if stem.endswith(".png"):
                    stem = stem[:-4]
                if not stem or any(character not in "0123456789" for character in stem):
                    raise ValueError("--frames must contain comma-separated numeric stems")
                name = stem + ".png"
                if name in selected_names:
                    raise ValueError("--frames contains a duplicate: " + name)
                selected_names.append(name)
            available_names = {path.name for path in rgb_paths}
            missing = [name for name in selected_names if name not in available_names]
            if missing:
                raise ValueError("Selected frames do not exist: " + ", ".join(missing))
            rgb_paths = [path for path in rgb_paths if path.name in selected_names]
            report["subset_selection"] = {"enabled": True, "requested_frames": selected_names,
                                          "processed_in_sorted_source_order": True,
                                          "complete_source_scene_claimed": False}
        else:
            report["subset_selection"] = {"enabled": False, "complete_source_scene_claimed": True}
        report["expected_frames"] = len(rgb_paths)
        # Keep GrabCut reproducible for this OpenCV build and frame processing order.
        cv2.setRNGSeed(0)
        for rgb_path in rgb_paths:
            current_frame = rgb_path.name
            depth_path = scene / "depth" / rgb_path.name
            bgr, depth = read_image(rgb_path), read_image(depth_path)
            if bgr.dtype != np.uint8 or bgr.ndim != 3 or bgr.shape[2] != 3:
                raise ValueError("RGB must decode as uint8 three-channel PNG: " + rgb_path.name)
            if depth.dtype != np.uint16 or depth.ndim != 2 or depth.shape != bgr.shape[:2]:
                raise ValueError("Depth must be paired uint16 one-channel PNG: " + depth_path.name)
            frame_geometry = None
            if geometry_frames is not None:
                frame_geometry = geometry_frames.get(rgb_path.stem, geometry_frames.get(rgb_path.name))
                if frame_geometry is None:
                    raise ValueError("Geometry is missing for selected frame: " + rgb_path.name)
            frame_config = dict(config)
            per_frame_background = config.get('per_frame_hard_background_rectangles', {})
            if not isinstance(per_frame_background, dict):
                raise ValueError('per_frame_hard_background_rectangles must be an object')
            frame_config['hard_background_rectangles'] = list(config.get('hard_background_rectangles', [])) + list(
                per_frame_background.get(rgb_path.stem, []))
            mask, details = candidate_mask(bgr, frame_config, frame_geometry)
            selected_depth = depth[mask > 0]
            nonzero = selected_depth[selected_depth > 0]
            details.update({"frame": rgb_path.name, "candidate": True,
                            "manual_review_required": True, "accepted": False,
                            "source_rgb_sha256": sha256(rgb_path),
                            "source_depth_sha256": sha256(depth_path),
                            "mask_depth_nonzero_pixels": int(nonzero.size),
                            "mask_depth_zero_pixels": int(selected_depth.size - nonzero.size),
                            "mask_depth_valid_percent": float(100 * nonzero.size / selected_depth.size),
                            "mask_nonzero_depth_millimeters": None if not nonzero.size else {
                                "p05": float(np.percentile(nonzero, 5)),
                                "median": float(np.median(nonzero)),
                                "p95": float(np.percentile(nonzero, 95))}})
            mask_path = output / "masks" / rgb_path.name
            overlay_path = output / "overlays" / rgb_path.name
            write_image(mask_path, mask)
            write_image(overlay_path, overlay(bgr, mask))
            details["mask_sha256"] = sha256(mask_path)
            details["overlay_sha256"] = sha256(overlay_path)
            report["frames"].append(details)
            report["processed_frames"] = len(report["frames"])
            write_json(report_path, report)
            print(json.dumps({"frame": rgb_path.name, "mask_pixels": details["mask_pixels"],
                              "candidate": True, "flags": details["flags"]}), flush=True)
        report["status"] = "complete"
        report["passed"] = True
        report["summary"] = {
            "frames_with_flags": sum(bool(frame["flags"]) for frame in report["frames"]),
            "frames_discarding_definite_seeds": sum(frame["definite_seed_pixels_discarded"] > 0
                                                    for frame in report["frames"]),
            "mean_mask_depth_valid_percent": float(np.mean([
                frame["mask_depth_valid_percent"] for frame in report["frames"]]))}
        exit_code = 0
    except BaseException as error:
        report["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        report["failed_frame"] = current_frame
        report["error"] = "{}: {}".format(type(error).__name__, error)
        report["traceback"] = traceback.format_exc()
        print(report["error"], file=sys.stderr, flush=True)
        exit_code = 130 if isinstance(error, KeyboardInterrupt) else 1
    finally:
        report["ended_at_utc"] = utc_now()
        write_json(report_path, report)
    print(json.dumps({"passed": report["passed"], "status": report["status"],
                      "candidate_generation_only": True, "manual_review_required": True,
                      "processed_frames": report["processed_frames"], "output": str(output)}), flush=True)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
