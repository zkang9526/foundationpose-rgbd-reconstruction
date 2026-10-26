"""Append SAM usage/storage facts without replacing platform-specific guides."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--root', required=True, type=Path)
args = p.parse_args()
marker = '<!-- CUP-SAM-INITIALIZATION-20261015 -->'
note = '''
## SAM 初始化分割（2026-10-15）

Ubuntu `/data/ZJC/foundationPos` 执行：
```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_fast.sh --duration-seconds 600 --max-frames 3000
```
页面 `http://127.0.0.1:8765`，重新启动入口并刷新页面后生效。
默认 `--mask-backend sam`，官方 SAM ViT-B；旧 `run_cup_live.sh` 仍是 GrabCut。
冻结 → 拖框包含杯身和杯把 → 生成 SAM Mask → 按需要加前景点/背景点 → 再生成 → 确认初始化。
绿色点表示杯子前景，红色点表示背景。把手空隙属于背景；可见杯子内壁属于物体，不能为了深度缺失而全部删掉。
改点/改框后确认按钮禁用，重新生成后才能初始化。Mask 黄色半透明显示；需人工检查，没有可靠GT。
保持相机和杯子不动，直到初始化结束并开始跟踪。SAM仅在生成/修正Mask时运行，进程结束释放GPU，不逐跟踪帧运行。
每次尝试保留在会话 `mask_attempts/`：原始RGB NPY、框和提示点、二值Mask PNG、SHA、SAM预测IoU、耗时和失败日志。
SAM预测IoU不是实际分割或6D精度。位姿输入仍使用同一冻结RGB-D；原始深度、网格缺陷与失跟问题仍需分别检查。
SAM源码 `/data/ZJC/foundationPos/foundationpose_data/tools/segment-anything`；权重 `checkpoints/sam/sam_vit_b_01ec64.pth`；来源与SHA见同目录 `installation.json`。
没有升级FoundationPose的PyTorch/torchvision或Windows相机环境。Ubuntu产物保存在Ubuntu数据盘；传回Windows的产物统一E盘。
显式GrabCut对照：在快速入口追加 `--mask-backend grabcut`；SAM失败不会静默回退。
'''
for name in ['REPRODUCTION_GUIDE.md', 'AGENTS.md', 'Ubuntu_environment.md' if __import__('os').name != 'nt' else 'D435i_connection.md']:
    target = args.root / name
    existing = target.read_text(encoding='utf-8') if target.exists() else ''
    if marker not in existing:
        with target.open('a', encoding='utf-8') as stream:
            stream.write('\n' + marker + '\n' + note)
print('SAM usage note appended without replacing existing guides')
