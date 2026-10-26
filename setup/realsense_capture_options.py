"""Optional per-run D435i settings; preserve raw depth and actual settings."""
import hashlib
import json


class CaptureOptions:
    def __init__(self, rs, sensor, report, device=None, output=None):
        self.rs, self.sensor, self.report = rs, sensor, report
        self.device, self.output = device, output
        self.original_preset = None
        self.advanced = None
        self.original_settings = None
        self.filters = []

    def configure(self, preset, filtered, depth_auto_exposure=False):
        rs, sensor, report = self.rs, self.sensor, self.report
        report['depth_processing'] = dict(raw_depth_preserved=True,
            filtered_depth_directory='depth_filtered' if filtered else None,
            filtered_depth_is_measured_raw=False, requested_preset=preset,
            requested_depth_auto_exposure='on' if depth_auto_exposure else 'preserve')
        if preset != 'device-default' or depth_auto_exposure:
            if not sensor.supports(rs.option.visual_preset):
                raise RuntimeError('D435i does not expose visual_preset')
            original = sensor.get_option(rs.option.visual_preset)
            # Preset 0 (Custom) is only a label; setting it back does not save
            # or reconstruct the original advanced configuration.
            self.advanced = rs.rs400_advanced_mode(self.device)
            if not self.advanced.is_enabled():
                raise RuntimeError('Advanced mode must already be enabled to back up settings; use device-default to preserve settings')
            self.original_settings = self.advanced.serialize_json()
            original_path = self.output / 'camera_settings_before.json'
            with original_path.open('x', encoding='utf-8') as stream:
                stream.write(self.original_settings)
            report['depth_processing']['settings_backup'] = dict(file=original_path.name,
                sha256=hashlib.sha256(original_path.read_bytes()).hexdigest())
            self.original_preset = original
            if preset != 'device-default':
                requested = int({'high-accuracy': rs.rs400_visual_preset.high_accuracy,
                                 'high-density': rs.rs400_visual_preset.high_density}[preset])
                sensor.set_option(rs.option.visual_preset, requested)
                if sensor.get_option(rs.option.visual_preset) != requested:
                    raise RuntimeError('Requested depth preset was not applied: ' + preset)
            if depth_auto_exposure:
                sensor.set_option(rs.option.enable_auto_exposure, 1)
                if sensor.get_option(rs.option.enable_auto_exposure) != 1:
                    raise RuntimeError('Depth auto-exposure was not enabled')
            actual = sensor.get_option(rs.option.visual_preset)
            report['depth_processing'].update(previous_preset=original, active_preset=actual,
                active_preset_name=sensor.get_option_value_description(rs.option.visual_preset, actual),
                restore_preset_after_run=True, restore_actual_settings_after_run=True)
        report['depth_processing']['active_sensor_options'] = {
            name: sensor.get_option(getattr(rs.option, name))
            for name in ('visual_preset', 'enable_auto_exposure', 'exposure', 'gain', 'emitter_enabled', 'laser_power')
            if sensor.supports(getattr(rs.option, name))}
        if filtered:
            self.filters = [rs.spatial_filter(), rs.temporal_filter(), rs.hole_filling_filter()]
            report['depth_processing']['filters'] = ['spatial', 'temporal', 'hole_filling']
            report['warnings'].append('Filtered depth is derived data. Hole filling can invent surface depth; retain raw depth for geometry QA.')

    def process(self, frame):
        if not self.filters:
            return None
        filtered = frame
        for operation in self.filters:
            filtered = operation.process(filtered)
        return filtered.as_depth_frame()

    def restore(self):
        if self.original_preset is not None:
            self.sensor.set_option(self.rs.option.visual_preset, self.original_preset)
            self.advanced.load_json(self.original_settings)
            restored = self.sensor.get_option(self.rs.option.visual_preset)
            self.report['depth_processing']['restored_preset'] = restored
            before = json.loads(self.original_settings)['parameters']
            after = json.loads(self.advanced.serialize_json())['parameters']
            # Exposure and gain can legitimately change while AE is enabled.
            volatile = set()
            for prefix in ('', 'color-'):
                if before.get('controls-' + prefix + 'autoexposure-auto') == 'True':
                    volatile.update(('controls-' + prefix + 'autoexposure-manual',
                                     'controls-' + prefix + 'gain'))
            differences = sorted(key for key in before.keys() | after.keys()
                                 if key not in volatile and before.get(key) != after.get(key))
            self.report['depth_processing'].update(settings_restore_verified=not differences,
                settings_restore_differences=differences, settings_restore_ignored_volatile_keys=sorted(volatile))
            if differences:
                raise RuntimeError('Could not restore camera settings: ' + ', '.join(differences))
