## 2026-10-18 Ubuntu安装原生RealSense Viewer

用户反馈看不到实际相机视角，请求先在Ubuntu安装Viewer。正常停止本次暂停的位姿会话保存1178帧记录并释放相机；检查Ubuntu20.04无原生Viewer且sudo非交互不可用，采用官方focal/amd64 SDK2.55.1私有目录安装，无需密码。

厂商InRelease返回BADSIG，保留v1；v2官方Release.gpg独立签名及索引SHA验证通过，三个官方Debian包SHA/长度通过后解包到数据盘用户目录。动态链接依赖齐全，桌面入口已建立。Viewer在ni的DISPLAY=:0持续运行，原生SDK枚举D435i序列238222071455成功；尚未通过GUI目视确认两路流已打开，不宣称物理标定或对齐通过。

启动命令`bash setup/run_realsense_viewer_ubuntu.sh`，项目启动器通过记录器留档。SDK包/证据在Ubuntu数据盘；Windows回执和代码在E盘。系统APT/dpkg、内核、udev、固件和现有Python/位姿环境均未修改。完整路径、SHA和run见`reports/UBUNTU_REALSENSE_VIEWER_20261018.md`。调整构图后先关Viewer再运行新模型位姿入口。
