#!/usr/bin/env python3
"""Controlled reconstruction experiment: set neural PoseArray learning rate to0.

Tracking and bundle adjustment still estimate poses. No planned angle or GT is
used. Keeps both default pilots as evidence; uses the shared bounded-output
wrapper and changes only two in-memory reconstruction configurations.
"""
import ast
import copy
import difflib
import hashlib
from pathlib import Path

import run_cup_bundlesdf_pilot as base

original_patch = base.patched_entry


def freeze_neural_pose_patch(source, filename, report):
    # First apply all existing exact-source and bounded-output safety checks.
    original_patch(source, filename, report)
    tree = ast.parse(source, filename=str(filename))
    functions = []
    changes = []
    source_lines = source.splitlines(keepends=True)
    after = list(source_lines)
    for name in ('run_one_video', 'run_one_video_global_nerf'):
        found = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
        if len(found) != 1:
            raise ValueError('Unexpected official function count: ' + name)
        function = copy.deepcopy(found[0])
        assignments = [(i, node) for i, node in enumerate(function.body)
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'cfg_nerf']
        if len(assignments) != 1:
            raise ValueError('Expected exactly one direct cfg_nerf load in ' + name)
        index, declaration = assignments[0]
        inserted = ast.parse("cfg_nerf['lrate_pose'] = 0.0").body[0]
        ast.copy_location(inserted, declaration)
        function.body.insert(index + 1, inserted)
        indentation = source_lines[declaration.lineno - 1][:declaration.col_offset]
        if declaration.end_lineno != declaration.lineno:
            raise ValueError('Expected one-line direct configuration load')
        changes.append({'function': name, 'after_line': declaration.end_lineno,
                        'source': ast.get_source_segment(source, declaration),
                        'insert': "cfg_nerf['lrate_pose'] = 0.0"})
        if name == 'run_one_video':
            expected = ast.parse("os.system(f'rm -rf {out_folder} && mkdir -p {out_folder}')").body[0]
            if ast.dump(function.body[1], include_attributes=False) != ast.dump(expected, include_attributes=False):
                raise ValueError('Unexpected official output initialization')
            safe = ast.parse('_cup_safe_create_pipeline_output(out_folder)').body[0]
            ast.copy_location(safe, function.body[1])
            original_line = function.body[1].lineno
            after[original_line - 1] = source_lines[original_line - 1][:function.body[1].col_offset] + '_cup_safe_create_pipeline_output(out_folder)\n'
            function.body[1] = safe
        functions.append(function)
    for change in sorted(changes, key=lambda item: item['after_line'], reverse=True):
        line = source_lines[change['after_line'] - 1]
        indent = line[:len(line) - len(line.lstrip())]
        after.insert(change['after_line'], indent + change['insert'] + '\n')
    patch = ''.join(difflib.unified_diff(source_lines, after,
                                       fromfile='official/run_custom.py',
                                       tofile='in_memory/frozen_neural_pose.py'))
    output = Path(report['output'])
    patch_file = output / 'frozen_neural_pose_configuration.diff'
    patch_file.write_text(patch, encoding='utf-8')
    report['in_memory_ast_patch']['only_destructive_initialization_replaced'] = False
    report['controlled_reconstruction_variant'] = {
        'name': 'frozen_neural_pose_array', 'lrate_pose': 0.0,
        'changes': changes, 'configuration_diff': base.file_info(patch_file),
        'wrapper': base.file_info(Path(__file__)),
        'neural_pose_gradients_still_computed': True,
        'neural_pose_parameters_updated': False,
        'tracking_and_bundle_adjustment_enabled': True,
        'same_tracking_values_as_default_assumed': False,
        'effect_on_geometry_validated': False,
        'upstream_sources_modified': False,
        'planned_angles_used': False, 'pose_ground_truth_used': False,
    }
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    report['frozen_function_ast_sha256'] = hashlib.sha256(ast.dump(module, include_attributes=False).encode()).hexdigest()
    return compile(module, str(filename) + '::frozen_neural_pose_experiment', 'exec')


if __name__ == '__main__':
    base.patched_entry = freeze_neural_pose_patch
    raise SystemExit(base.main())
