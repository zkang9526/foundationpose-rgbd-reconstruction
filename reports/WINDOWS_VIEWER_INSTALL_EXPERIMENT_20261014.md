## Windows RealSense Viewer安装与启动（2026-10-14）

用户明确要求在本机Windows安装realsense-viewer，延续此前允许直接执行的授权。采用官方2.55.1独立便携Viewer，在项目tools/realsense-viewer/2.55.1/realsense-viewer.exe配置使用。

安装run：20261014_141026_488445_windows_realsense_viewer_install_b7aaf11e。报告：reports/windows_viewer_setup_20261014_141028_110.json。安装前后SHA256均为ced0bd623f2df2e86f074ff8ee0fd89637c92f25f44fbf2d24262a325a8990c0，Authenticode签名Valid、签发主体Intel Corporation。版本依据官方发布包和窗口标题；Windows VersionInfo.FileVersion资源读取出现不可用字符，不依其判版本，原报告如实保留。

桌面与当前用户开始菜单已创建并回读验证“Intel RealSense Viewer 2.55.1.lnk”，指向上述项目exe。未安装驱动/固件，没有在安装脚本中修改相机配置。

已使用computer-use技能的sky.launch_app({app:'C:\\Users\\YOUR_USER\\Desktop\\foundationPos\\tools\\realsense-viewer\\2.55.1\\realsense-viewer.exe'})启动；sky.list_windows返回唯一窗口id135156，标题Intel RealSense Viewer v2.55.1。后续界面状态获取被自动审批拒绝：Computer Use was not approved to use Intel RealSense Viewer 2.55.1。未继续输入、点击或通过其它方式绕过界面授权；不能由此声称GUI内相机识别、流显示或预设配置已验证。

用户随后询问启动命令，已给出等价PowerShell命令：& "C:\Users\YOUR_USER\Desktop\foundationPos\tools\realsense-viewer\2.55.1\realsense-viewer.exe"。安装和窗口启动完成，用户可从桌面/开始菜单使用；界面验证限制独立保留。Windows安装和问题记录留在本机，后续随数据批次打包，不覆盖Ubuntu历史。
