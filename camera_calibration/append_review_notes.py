"""Append real checkerboard review facts to platform journals, preserving history."""
import argparse
from pathlib import Path
import os


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    a = p.parse_args()
    marker = '<!-- CHECKERBOARD-REAL-REVIEW-20261015-164319 -->'
    entries = {
        'EXPERIMENT_LOG.md': '''
### 2026-10-15 Windows棋盘格真实采集复核

- 会话camera_calibration/sessions/windows_20261015_164319_478保存20组，仅0015接收；15组运动拒绝，4组IR1未检出完整棋盘。268个原始文件SHA一致。
- 0015 RGB重投影0.598px、IR1→RGB投影1.281px；约0.486m处板内有效深度96.7%，深度拟合平面RMS约1.29mm；相对RGB/IR1的估计板平面Z偏差分别约+1.91/+5.64mm，均非独立GT。
- SDK软件对齐尺寸/内参一致；实体板轮廓标注0组。未验收内外参或物理边界精度；没有改设备参数或把拒绝帧升级为有效。
- 包含拒绝帧的16组对应只用于独立诊断，不拟合；详见camera_calibration/REVIEW_20261015_164319.md。
- 复核run：20261015_165146_435967_checkerboard_real_capture_review_6047f147；结果camera_calibration/results/review_windows_20261015_164319_478_v1。
- 下一步：相机/硬板放稳，逐组确认接收，累计25–35个多姿态有效视图；实体板离背景至少5cm，补3–5组轮廓检查。
''',
        'ISSUES.md': '''
### 2026-10-15 棋盘格20组仅1组通过静态检查：待补采复验

- 事实：15组记录0.764–6.997px光流位移（0.312–0.344s），超过0.75px静态阈值；4组RGB检出但IR1未检出。仅0015通过。
- 事实：268个原始文件SHA通过；有对应的帧组记录system_time域约9.05–12.92ms时间跨度，不代表硬件同时曝光。
- 推测：手持/鼠标操作相关微动、红外散斑及斜视可能影响结果；具体原因未逐一验证，不将其归为相机标定失效。
- 处理：保留全体原始数据及拒绝原因，分别统计接收组与仅诊断组；未放宽阈值、未改标定。
- 复验：Windows真实采集与保存已完成；内外参精度、多姿态稳定性、实体边界对齐仍未完成，不能标记已解决。
- 证据：camera_calibration/REVIEW_20261015_164319.md及review_windows_20261015_164319_478_v1；建议相机/板放稳后补有效样本。
'''
    }
    with (a.root / '.records.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            for name, content in entries.items():
                target = a.root / name
                if marker not in target.read_text(encoding='utf-8'):
                    with target.open('a', encoding='utf-8') as f:
                        f.write('\n' + marker + '\n' + content)
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    print('Real checkerboard review appended without changing previous records')


if __name__ == '__main__':
    main()
