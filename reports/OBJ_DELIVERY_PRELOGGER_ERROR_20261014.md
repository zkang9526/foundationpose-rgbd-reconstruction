# 2026-10-14 环境证据打包：记录器启动前的Windows参数长度失败

事实：将本次已结束run中的所有文件逐项放入`--files`，再用PowerShell的`@ObjDeliveryFiles`传递给Python记录器，操作系统拒绝启动python.exe。工具终端结果：`Program 'python.exe' failed to run: The filename or extension is too long`。记录器本身没有启动，因此没有该次失败的run目录；没有执行打包helper、创建该次批次或发送文件。

脱敏调用形式：`.windows-camera-venv/Scripts/python.exe -u setup/run_logged.py --root . --label obj_setup_delivery_stage -- <camera-python> -B setup/prepare_cup_stage_payload.py --root . --output foundationpose_data/exports/obj_setup_delivery_20261014_1338 --files <本次最终脚本、说明、报告和已结束Windows run全部文件列表>`。没有密码/令牌参数。

处理：在`prepare_cup_stage_payload.py`增加`--ended-runs-since YYYYMMDD_HHMMSS`，由Python在内部选择本次已结束run，沿用`--include-ended-runs`和原文件安全/哈希校验，避免把数千路径放到Windows命令行。失败证据随下一新批次归档。复验结果见最终同步回执及对应新run；修改不覆盖旧档案，原有参数继续支持。
