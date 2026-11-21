"""关节参考轨迹的时间分配与定时发送；不连接ROS或机械臂。"""

import math
import numpy as np


def checked_samples(times, positions):
    times, positions = np.asarray(times, dtype=float), np.asarray(positions, dtype=float)
    if (times.ndim != 1 or not 2 <= len(times) <= 10000 or positions.shape != (len(times), 6)
            or not np.all(np.isfinite(times)) or not np.all(np.isfinite(positions))
            or abs(times[0]) > 1e-9 or np.any(np.diff(times) <= 0) or times[-1] > 120):
        raise ValueError('关节轨迹必须为从0开始、严格递增且有限的时间和六关节位置')
    return times, positions


def retime_samples(times, positions, velocity, acceleration):
    """仅拉长时间，不改路径点；计入静止起止时的有限差分速度/加速度。"""
    times, positions = checked_samples(times, positions)
    velocity = np.broadcast_to(np.asarray(velocity, dtype=float), (6,))
    if (not np.all(np.isfinite(velocity)) or np.any(velocity <= 0)
            or not np.isfinite(acceleration) or acceleration <= 0):
        raise ValueError('轨迹速度及加速度上限无效')
    dt = np.diff(times)
    v = np.diff(positions, axis=0)/dt[:, None]
    a_dt = np.r_[dt[0]/2, (dt[:-1]+dt[1:])/2, dt[-1]/2]
    a = np.diff(np.vstack([np.zeros(6), v, np.zeros(6)]), axis=0)/a_dt[:, None]
    scale = max(1., float(np.max(np.abs(v)/velocity)), math.sqrt(float(np.max(np.abs(a)))/acceleration))
    result = times*scale
    checked_samples(result, positions)
    return result, {'time_scale':scale, 'peak_velocity_rad_s':float(np.max(np.abs(v)))/scale,
                    'peak_acceleration_rad_s2':float(np.max(np.abs(a)))/(scale*scale)}


def quintic_samples(start, goal, velocity, rate, acceleration=.5):
    start, goal = np.asarray(start, dtype=float), np.asarray(goal, dtype=float)
    velocity = np.broadcast_to(np.asarray(velocity, dtype=float), (6,))
    if (start.shape != (6,) or goal.shape != (6,) or not np.all(np.isfinite(np.r_[start, goal, velocity]))
            or np.any(velocity <= 0) or not np.isfinite(rate) or not 10 <= rate <= 100
            or not np.isfinite(acceleration) or acceleration <= 0):
        raise ValueError('五次关节轨迹输入无效')
    distance = np.abs(goal-start)
    duration = max(1.875*float(np.max(distance/velocity)),
                   math.sqrt(5.774*float(np.max(distance))/acceleration), .1)
    count = max(1, int(np.ceil(duration*rate)))
    times = np.linspace(0., duration, count+1)
    t = times/duration
    alpha = t*t*t*(10+t*(-15+6*t))
    positions = start+alpha[:, None]*(goal-start)
    times, stats = retime_samples(times, positions, velocity, acceleration)
    return times, positions, stats


def resample_limited_samples(times, positions, velocity, acceleration, rate):
    """Resample one phase at a uniform rate and check the actual output grid."""
    if not np.isfinite(rate) or not 10 <= rate <= 100:
        raise ValueError('轨迹重采样频率必须在10至100Hz之间')
    source_times, source_positions = checked_samples(times, positions)
    limited_times, original = retime_samples(source_times, source_positions, velocity, acceleration)
    duration = math.ceil(limited_times[-1]*rate)/rate
    for _ in range(12):
        count = int(round(duration*rate))
        output_times = np.arange(count+1, dtype=float)/rate
        lookup = output_times/duration*limited_times[-1]
        output_positions = np.column_stack([np.interp(lookup, limited_times, source_positions[:, joint]) for joint in range(6)])
        output_positions[0], output_positions[-1] = source_positions[0], source_positions[-1]
        _, stats = retime_samples(output_times, output_positions, velocity, acceleration)
        if stats['time_scale'] <= 1.+1e-8:
            stats.update(time_scale=float(duration/source_times[-1]), output_rate_hz=float(rate),
                         source_time_scale=original['time_scale'])
            return output_times, output_positions, stats
        duration = math.ceil(duration*stats['time_scale']*1.001*rate)/rate
    raise ValueError('均匀发送轨迹无法在速度和加速度约束内完成重采样')


def stream_samples(times, positions, publish, clock, sleep, max_gap=.2):
    """以发送开始时刻定下一期限，抵消发送耗时；不跳点、不突发补发。"""
    times, positions = checked_samples(times, positions)
    if not np.isfinite(max_gap) or max_gap <= 0 or np.max(np.diff(times)) >= max_gap:
        raise ValueError('轨迹周期或最大中断时长无效')
    began, previous, intervals = clock(), None, []
    deadline = began
    for index, values in enumerate(positions):
        remaining = deadline-clock()
        if remaining > 0:
            sleep(remaining)
        sent = clock()
        if previous is not None:
            interval = sent-previous
            if interval > max_gap:
                raise RuntimeError('轨迹发送中断超过{:.0f}ms，停止下发后续目标'.format(max_gap*1000))
            intervals.append(interval)
        publish(values)
        previous = sent
        if index+1 < len(times):
            deadline = sent+float(times[index+1]-times[index])
    actual = np.asarray(intervals)
    return {'samples':len(times), 'planned_duration_s':float(times[-1]),
            'elapsed_s':clock()-began, 'mean_interval_s':float(np.mean(actual)),
            'max_interval_s':float(np.max(actual)), 'p95_interval_s':float(np.percentile(actual,95)),
            'skipped_samples':0}
