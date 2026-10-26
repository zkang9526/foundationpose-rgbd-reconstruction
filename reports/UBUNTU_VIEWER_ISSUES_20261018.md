## 2026-10-18 Ubuntu Viewer安装与交接

- 已处理：Ubuntu20.04没有原生Viewer，ni无非交互sudo授权。通过厂商官方Debian二进制在数据盘私有prefix安装，ldd无缺失、程序持续运行、原生SDK枚举D435i成功。未索取密码，也未修改系统包或已有Python环境。
- 已处理并保留：同一官方源的InRelease签名失败BADSIG。v1失败目录/run保留；v2另取官方Release.gpg/Release，验证通过，再核对索引SHA及三个Debian包SHA和大小，没有忽略签名检查。故障仅限所获取InRelease，不据此推断厂商整体仓库异常。
- 已完成交接：自己的位姿会话经HTTP正常停止保存后才启动Viewer，避免相机争用。用户后续应关Viewer/停止全部流后再启动FoundationPose。
- 待用户现场确认：窗口内RGB/Depth流和新构图是否清晰；目前只验证Viewer运行与设备枚举。ID6识别和移动相机误差评测尚未继续，不能标记已解决。
