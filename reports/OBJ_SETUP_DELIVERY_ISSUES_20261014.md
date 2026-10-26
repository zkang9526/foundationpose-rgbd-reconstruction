## OBJ证据打包问题复验（2026-10-14）

事实：首次用PowerShell把数千证据路径逐项作为`--files`传给Python，系统返回`The filename or extension is too long`；记录器尚未启动，未创建那个拟用批次。脱敏调用与终端结果单独保存在`reports/OBJ_DELIVERY_PRELOGGER_ERROR_20261014.md`。

处理：新增兼容旧参数的`--ended-runs-since`筛选，文件枚举转到Python内部执行，不更改原始数据或历史run。复验：`20261014_133808_821122_obj_setup_delivery_stage_retry_a163f490`退出0并生成2923文件manifest；Ubuntu完整SHA及部署复验退出0，导入48份Windowsrun。该次命令行长度问题已验证解决，原失败说明保留；证据为`reports/OBJ_SETUP_DEPLOYMENT_RECEIPT_20261014.json`及服务器部署run`20261014_133951_226436_obj_setup_delivery_ubuntu_deploy_4055a89e`。

此修复仅涉及留档传输入口，不改变实物几何QA或BundleSDF退出139的待处理状态。
