"""Append Git rules while keeping independent platform notes intact."""
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--root', type=Path, required=True)
args = p.parse_args()
marker = '<!-- PROJECT-GIT-TRACEABILITY-20261015 -->'
note = '''
## Git版本与回溯（2026-10-15）

项目根目录已纳入Git。Windows真实路径 `E:\\foundationPos` 的main分支与Ubuntu `/data/ZJC/foundationPos` 的ubuntu分支共用基线历史，保留各端真实差异；不公开上传，不覆盖对方实时总日志。
后续代码/配置修改按有意义的阶段提交，并更新对应可提交报告；当前基线不能冒充之前各阶段的Git历史。
记录器自动保存 `project_git.json`（HEAD/分支/dirty/路径/差异SHA），有已跟踪改动时保存patch；继续保存原有源码快照、数据SHA、失败与中断证据。
大数据、模型、虚拟环境、缓存和逐次原始运行档案不进Git；实时 `EXPERIMENT_LOG.md` / `ISSUES.md` 继续在磁盘追加，初始化快照分别在 `history/windows/` 与 `history/ubuntu/`，阶段报告纳入Git。
操作示例、bundle交换与回溯方法见 `GIT_WORKFLOW.md`。代码版本回溯不能替代数据、权重和物理精度验证。
'''
for name in ['AGENTS.md', 'REPRODUCTION_GUIDE.md']:
    path = args.root / name
    existing = path.read_text(encoding='utf-8') if path.exists() else ''
    if marker not in existing:
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n' + marker + '\n' + note)
print('Git workflow note appended')
