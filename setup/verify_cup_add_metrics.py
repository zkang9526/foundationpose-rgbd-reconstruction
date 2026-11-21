#!/usr/bin/env python3
"""Analytic ADD checks; no camera, experimental poses, or physical-GT claims."""
import argparse
import hashlib
import json
from pathlib import Path
import traceback

import numpy as np

from cup_add_metrics import (
    add_error,
    adds_error,
    pose_error_mm_deg,
    sample_mesh_surface,
    stats_mm,
    validated_transform,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New validation directory")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, condition, details=None):
        if not bool(condition):
            raise AssertionError(name)
        checks.append(dict(name=name, passed=True, details=details))

    def rejects(name, function):
        try:
            function()
        except ValueError:
            check(name, True)
        else:
            raise AssertionError(name + ": invalid input was accepted")

    report = dict(passed=False, scope="analytic numerical correctness only; no physical accuracy measured")
    try:
        identity = np.eye(4)
        asymmetric = np.array([[0, 0, 0], [.010, 0, 0], [0, .020, 0], [.003, .004, .030]])
        check("identical_ADD_is_zero", add_error(asymmetric, identity, identity) < 1e-15)
        check("identical_ADDS_is_zero", adds_error(asymmetric, identity, identity) < 1e-15)
        moved = identity.copy()
        moved[:3, 3] = [.003, .004, .012]
        check("translation_ADD_is_13_mm", abs(add_error(asymmetric, moved, identity) - .013) < 1e-14)
        check("pose_translation_is_13_mm", abs(pose_error_mm_deg(moved, identity)["translation_error_mm"] - 13) < 1e-11)

        quarter_turn = identity.copy()
        quarter_turn[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        expected = float(np.mean([0, np.sqrt(2) * .010, np.sqrt(2) * .020, np.sqrt(2) * .005]))
        check("asymmetric_rotation_ADD_matches_analytic_distances",
              abs(add_error(asymmetric, quarter_turn, identity) - expected) < 1e-14)
        check("rotation_geodesic_is_90_degrees",
              abs(pose_error_mm_deg(quarter_turn, identity)["rotation_error_deg"] - 90) < 1e-12)

        square = np.array([[.010, 0, 0], [0, .010, 0], [-.010, 0, 0], [0, -.010, 0]])
        check("symmetric_rotation_ADD_is_nonzero", abs(add_error(square, quarter_turn, identity) - np.sqrt(2) * .010) < 1e-14)
        check("symmetric_rotation_ADDS_is_zero", adds_error(square, quarter_turn, identity) < 1e-15)

        # This non-symmetric arrangement gives distinct directed nearest-neighbor
        # means: reference->estimated = 7/4 mm, reverse = 2 mm.
        line = np.array([[0, 0, 0], [.002, 0, 0], [.003, 0, 0], [.010, 0, 0]])
        shifted = identity.copy()
        shifted[0, 3] = .003
        check("ADDS_uses_BOP_reference_to_estimated_direction",
              abs(adds_error(line, shifted, identity) - .007 / 4) < 1e-14)
        check("ADDS_direction_is_not_symmetric_Chamfer",
              abs(adds_error(line, identity, shifted) - .002) < 1e-14)

        small_roundoff = identity.copy()
        small_roundoff[:3, :3] = quarter_turn[:3, :3]
        small_roundoff[0, 1] -= 2e-7
        before = small_roundoff.copy()
        fixed = validated_transform(small_roundoff)
        check("float32_rotation_roundoff_is_projected",
              np.allclose(fixed[:3, :3].T @ fixed[:3, :3], np.eye(3), atol=1e-14, rtol=0))
        check("validation_does_not_mutate_input", np.array_equal(small_roundoff, before))

        reflected = identity.copy()
        reflected[0, 0] = -1
        rejects("reflection_rejected", lambda: validated_transform(reflected))
        scaled = identity.copy()
        scaled[:3, :3] *= 1.05
        rejects("scaled_rotation_rejected", lambda: validated_transform(scaled))
        wrong_bottom = identity.copy()
        wrong_bottom[3, 0] = .01
        rejects("nonhomogeneous_bottom_row_rejected", lambda: validated_transform(wrong_bottom))
        nan_pose = identity.copy()
        nan_pose[0, 3] = np.nan
        rejects("nonfinite_pose_rejected", lambda: validated_transform(nan_pose))
        rejects("empty_points_rejected", lambda: add_error(np.empty((0, 3)), identity, identity))
        rejects("nonfinite_points_rejected", lambda: adds_error([[np.inf, 0, 0]], identity, identity))
        rejects("invalid_statistics_not_silently_filtered", lambda: stats_mm([.001, np.nan]))
        check("empty_statistics_are_missing_not_zero", stats_mm([]) is None)
        statistics = stats_mm([.001, .002, .003])
        check("statistics_convert_meters_to_mm",
              statistics["count"] == 3 and abs(statistics["mean"] - 2) < 1e-12
              and abs(statistics["median"] - 2) < 1e-12)

        # Disjoint triangles have areas 0.5 and 2 square units, so the expected
        # sample split is 20% / 80%. A third face has zero area.
        vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0],
                             [10, 0, 0], [12, 0, 0], [10, 2, 0]], dtype=float) * .01
        faces = np.array([[0, 1, 2], [3, 4, 5], [0, 0, 0]], dtype=np.int64)
        samples = sample_mesh_surface(vertices, faces, count=50000, seed=1729)
        repeated = sample_mesh_surface(vertices, faces, count=50000, seed=1729)
        check("surface_sampling_is_fixed_seed_reproducible", np.array_equal(samples, repeated))
        first_fraction = float(np.mean(samples[:, 0] < .05))
        check("sampling_is_weighted_by_triangle_area", abs(first_fraction - .2) < .01,
              dict(observed_fraction=first_fraction, expected_fraction=.2, tolerance=.01))
        first = samples[samples[:, 0] < .05]
        second = samples[samples[:, 0] >= .05] - [.10, 0, 0]
        check("surface_samples_remain_inside_triangles",
              np.all(first[:, :2] >= -1e-14) and np.all(first[:, 0] + first[:, 1] <= .01 + 1e-14)
              and np.all(second[:, :2] >= -1e-14) and np.all(second[:, 0] + second[:, 1] <= .02 + 1e-14)
              and np.all(np.abs(samples[:, 2]) < 1e-15))
        check("triangle_sampling_has_uniform_area_centroid",
              np.allclose(first.mean(axis=0), [.01 / 3, .01 / 3, 0], atol=1e-4)
              and np.allclose(second.mean(axis=0), [.02 / 3, .02 / 3, 0], atol=1e-4))
        rejects("out_of_range_triangle_rejected",
                lambda: sample_mesh_surface(vertices, [[0, 1, 6]], count=10))
        rejects("fractional_face_indices_rejected",
                lambda: sample_mesh_surface(vertices, [[0., 1., 2.]], count=10))
        rejects("degenerate_only_surface_rejected",
                lambda: sample_mesh_surface(vertices, np.array([[0, 0, 0]]), count=10))

        np.save(args.output / "fixed_surface_samples.npy", samples, allow_pickle=False)
        report.update(passed=True, checks=checks,
                      sample_sha256=hashlib.sha256((args.output / "fixed_surface_samples.npy").read_bytes()).hexdigest())
    except Exception as error:
        report.update(checks=checks, error=str(error), traceback=traceback.format_exc())
        traceback.print_exc()
    finally:
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=report["passed"], checks=len(checks), output=str(args.output))), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
