"""Append branch-specific recovery operation notes without replacing host documents."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=Path)
args = p.parse_args()
marker = '<!-- CUP-AUTO-REACQUISITION-SAM2-20261015 -->'
note = '''
## 自动找回目标实验分支（2026-10-15）

分支 `fix/reacquisition-sam2-eval`，不合并main。Ubuntu启动：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000 --auto-reacquire
```
首次仍需冻结、框选、确认目标Mask；后续意外失跟自动全图搜索，无需再次人工框选。目标重新进入画面时请短暂停稳，供新RGB-D注册和连续3帧验证。
首帧对照默认 `--mask-backend sam`；试SAM2首帧追加 `--mask-backend sam2`；禁用自动找回追加 `--no-auto-reacquire`。
SAM2.1 Hiera Tiny在独立 `foundationpose_data/environments/sam2` 环境，源码与权重分别位于 `foundationpose_data/tools/sam2` 和 `foundationpose_data/checkpoints/sam2`；不升级FoundationPose容器或相机环境。
恢复流程：深度/初始目标颜色检查失败→隐藏无效位姿→SAM2全图候选→初始外观与深度尺度筛选→新帧检查→FoundationPose全局注册→Mask/深度检查→连续3新帧确认。
没有匹配或存在多个分离的相似候选时继续等待。该外观与尺度匹配不是语义杯子检测器，也不保证区分同色同尺寸的另一只杯子。
每次全图搜索保留RGB、深度、SDK/主机时间戳、候选Mask、目标筛选、SHA和失败日志。每次注册另存官方top1、前8候选及自定义几何选择，不能冒称所有输出都是未修改的官方top1。
当前连续跟踪FPS按分段统计，搜索/暂停/重新初始化耗时单列，不再混入跟踪FPS。原始事件仍保留，完整运行吞吐需另算。
首帧可用SAM2，但更换首帧分割器本身不构成自动重获。模型几何缺陷、真实移动相机的恢复成功率与6D精度需继续现场/ArUco评测，不把回放或合成消失测试当物理GT。
'''
for name in ['AGENTS.md', 'REPRODUCTION_GUIDE.md', 'Ubuntu_environment.md']:
    path = args.root / name
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    if marker not in existing:
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + marker + '\n' + note)
print('Branch-specific automatic reacquisition notes appended')
