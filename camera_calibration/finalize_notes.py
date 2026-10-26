"""Append the prepared checkerboard workflow without replacing live journals."""
import argparse
import os
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    a = p.parse_args()
    marker = '<!-- D435I-CHECKERBOARD-TOOL-20261015 -->'
    note = '''
## D435i棋盘格验证工具（2026-10-15）

独立目录 `camera_calibration/`；棋盘格按用户提供12×7方格、20mm格距，配置11×6内角点。
用户选择之后接Windows实测，本阶段仅工具准备和Ubuntu设备/原始取帧检查，不能宣称内外参或物理RGB-D对齐精度已验收。
Windows双击 `camera_calibration/start_windows.cmd`，或执行
`powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\camera_calibration\\run_windows.ps1`；
相机就绪后浏览器 `http://127.0.0.1:8766`，停稳逐组保存25–35个多姿态视角；完成按钮释放相机并自动分析。
Windows原始/结果均在E盘项目的 `camera_calibration/sessions/` 和 `camera_calibration/results/`；执行仍由项目记录器留档。
保存RGB、原生/对齐深度、双目红外、SDK内外参/深度尺度、时间戳、角点、拒绝记录、代码快照及SHA。
可手工标实体板外轮廓，测逐边深度边界偏移；不得用棋盘黑白格纹理线当深度台阶。
详细操作/限制见 [独立说明](camera_calibration/README.md)，证据/验证见 [阶段报告](camera_calibration/STATUS_20261015.md)。
不修改设备标定或旧数据K；候选只保存到新的分析报告。现有Windows/Ubuntu相机环境没有升级。
'''
    facts = '''
### 2026-10-15 棋盘格工具准备阶段

- 用户提供12×7方格、20 mm格距，解释为11×6内角点；决定等接Windows后实测。
- 相机当前在Ubuntu：D435i 238222071455/USB3.2；真实RGB-D和IR1/IR2取帧及SDK对齐参数一致性通过。
- 当前画面无棋盘；Windows入口分析该试拍得到0有效视角、物理验收false，没有拟合或改写设备标定。
- 数学/25视角合成流程验证通过，不作为真实相机精度。独立工具与证据在camera_calibration/，详细运行目录见STATUS_20261015.md。
- 下一步：Windows连接相机，拍25–35个停稳多姿态视图和板实体轮廓，再评估验证集内外参误差、原生深度平面及RGB-D边界偏移。
'''
    issues = '''
### 2026-10-15 棋盘格任务问题与复验范围

- 事实：Windows枚举为空，用户确认相机接Ubuntu；Ubuntu枚举与独立取帧成功。Windows现场实测仍待接入，不能标记物理精度已解决。
- 事实：第一次嵌套SSH命令被PowerShell引号解析打断，未进入记录器/远端；改为独立Python检查脚本后成功。未编造运行编号。
- 事实：SSH known_hosts自动更新受限；后续UpdateHostKeys=no保持既有身份校验并连接成功，不是相机问题。
- 事实：当前帧无棋盘，原生/对齐深度有孔洞；保存原始证据，不将孔洞直接归因于标定。
- 处理与已复验：新工具两端合成流程、Windows离线报告、Ubuntu原始取帧已验证；待复验：Windows现场采集、多视角内外参、物理板边缘对齐精度。
- 证据：camera_calibration/STATUS_20261015.md及其中run_id；所有重试和中断证据保留。
'''
    lock_path = a.root / '.records.lock'
    with lock_path.open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b'0')
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            for name, content in [('REPRODUCTION_GUIDE.md', note), ('EXPERIMENT_LOG.md', facts), ('ISSUES.md', issues)]:
                target = a.root / name
                text = target.read_text(encoding='utf-8') if target.exists() else ''
                if marker not in text:
                    with target.open('a', encoding='utf-8') as out:
                        out.write('\n' + marker + '\n' + content)
        finally:
            if os.name == 'nt':
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    print('Checkerboard workflow/results/issues appended; existing journals preserved')


if __name__ == '__main__':
    main()
