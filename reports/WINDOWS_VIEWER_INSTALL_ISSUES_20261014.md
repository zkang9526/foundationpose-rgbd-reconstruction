## Viewer界面状态获取被自动审批拒绝

事实：官方签名/安装/快捷方式校验通过，sky.launch_app成功，sky.list_windows返回Intel RealSense Viewer v2.55.1窗口。对已返回窗口获取界面状态时，自动审批拒绝，原消息：Computer Use was not approved to use Intel RealSense Viewer 2.55.1。

原因：工具说明该应用未获Computer Use授权；不是Viewer安装失败的证据，也不能据此断言应用内部状态/相机显示正常。

处理：停止Viewer UI操作，未绕过批准边界；向用户说明工具限制，并给出真实启动方式及等价PowerShell命令。安装已完成，用户可自行使用桌面或开始菜单快捷方式。

复验：exe哈希、Intel签名与快捷方式目标已通过；GUI内部相机/流验证未执行，后续如需自动操作仍需工具层授权。不得把安装报告passed或窗口存在当作RGB-depth物理对齐验证通过。
