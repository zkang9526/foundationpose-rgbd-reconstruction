# Ubuntu RealSense Viewer安装与启动（2026-10-18）

用户需要在Ubuntu上直观看相机视角后再调整构图。本次已完成官方Viewer2.55.1用户目录安装、桌面启动及原生SDK设备识别。**没有通过GUI目视确认RGB/深度已经流动，也不将设备识别作为对齐或标定通过。**

## 使用

已启动到Ubuntu `ni` 的当前桌面`DISPLAY=:0`，进程PID715054。应用列表可搜索 **RealSense Viewer (FoundationPos)**。

后续也可以在Ubuntu终端执行：

```bash
cd /data/ZJC/foundationPos
bash setup/run_realsense_viewer_ubuntu.sh
```

在Viewer中打开RGB Camera与Stereo Module开关；Stereo Module选择Depth。建议RGB与Depth均设640×480、30FPS，方便与本项目实际位姿输入的构图一致。保持完整杯身和杯把入镜；若测ArUco漂移，需要固定杯子和码，仅移动相机，码正面尽量朝向镜头，短边尽量达到40像素以上。实际是否能用于参考仍以检测门限和同帧结果为准。

调整完后关闭Viewer或停止其中全部相机流，再启动FoundationPose，避免相机资源冲突：

```bash
cd /data/ZJC/foundationPos
bash setup/run_cup_live_redcup72.sh --duration-seconds 600 --max-frames 3000
```

本次为预览角度而安装，没有启动任何厂商校准/恢复出厂/固件更新操作。

## 安装位置与版本

- Ubuntu20.04 focal，原先没有`realsense-viewer`或librealsense系统Debian包，APT未配置该软件源。`sudo -n true`未通过，未询问、记录或使用密码。
- 使用官方focal/amd64 Debian二进制包，在数据盘私有prefix解包，未修改系统dpkg数据库、系统APT源、udev、内核、固件、相机标定表或FoundationPose/Python环境。
- SDK运行库、工具、GL库版本均为`2.55.1-0~realsense.12473`。
- 实际文件：`/data/ZJC/foundationPos/foundationpose_data/tools/realsense_viewer_20261018_v2/root/usr/bin/realsense-viewer`。
- 私有动态库：同prefix下`root/usr/lib/x86_64-linux-gnu`；ldd无未找到的依赖。
- 项目启动器：`/data/ZJC/foundationPos/setup/run_realsense_viewer_ubuntu.sh`，通过记录器启动并限定本次Viewer的动态库路径。
- 用户桌面入口：`/home/ni/.local/share/applications/foundationpos-realsense-viewer.desktop`。桌面入口是用户配置；SDK和下载/证据在数据盘。
- 本轮SDK二进制采用原生V4L2后端。原生`rs-enumerate-devices -s`返回0并识别D435i `238222071455`、固件5.17.0.10，Viewer持续运行。未声称自动打开了两路流。

## 官方来源与校验

参考[厂商Linux包安装说明](https://github.com/realsenseai/librealsense/blob/master/doc/distribution_linux.md)，包源为`https://librealsense.realsenseai.com/Debian/apt-repo/`，公钥取自厂商同域名`/Debian/librealsenseai.asc`。

首次InRelease验证返回BADSIG，保留失败v1目录和run。v2仍保留原始InRelease失败证据，另获取官方`Release`和`Release.gpg`，独立签名验证通过；再按签名内容核验Packages.gz SHA，再按该索引逐个核验Debian包SHA和长度。没有跳过验签安装。

厂商RSA主钥指纹`5381 411D 24E6 59FB 1819 5FA5 FB0B 2489 5113 F120`；公钥包也含Intel旧公钥。独立验证具体输出保存在`detached_signature_verification.txt`。

| 文件 | SHA256 |
|---|---|
| Packages.gz | `3964bb853cd69910b6e5c74104362cafc85aa655d35ef7f0a115dd78ea2e61d6` |
| librealsense2 | `d1d060a766a254bfd909b43044249408635d769963522b51ff41e2ad29683d7a` |
| librealsense2-utils | `aca5014d7d35dcd61c69bca84d5b1132b86624964a98fe6759153fc1341a7057` |
| librealsense2-gl | `288e07dc8757c2dd2d879667c52eba1fa97ad05df32748cfed293cfdf4f17584` |

完整URL/大小/校验结果、原始索引和签名、包文件在私有prefix的downloads及repository.json、installation.json；GUI启动参数和所选桌面变量保留在launch.json。未转储全量环境、密码、令牌或Xauthority内容。

## 位姿会话交接

通过本项目HTTP `/stop`正常停止`redcup72_live_20261018_first`，让其保存已记录RGB-D/姿态/汇总并释放D435i。原1178帧静止测试和失败记录保留；未为了预览丢弃记录，也未同时重新启动占用相机的另一份位姿程序。

## 留档

- v1失败：`foundationpose_data/tools/realsense_viewer_20261018_v1`；冻结脚本`foundationpose_data/tools/viewer_installer_20261018`。
- v2成功：`foundationpose_data/tools/realsense_viewer_20261018_v2`；冻结脚本`foundationpose_data/tools/viewer_installer_20261018_v2`。
- Windows回执：`E:\foundationPos\reports\ubuntu_viewer_20261018_evidence`。较大的SDK包只留Ubuntu数据盘，Windows新增源码、文档、回执都在E盘。
- Ubuntu运行：检查`20261018_155932_256244_ubuntu_realsense_viewer_readiness_41980966`；正常停止位姿`20261018_160038_498756_redcup_live_control_stop_ac0c62d9`；v1失败`20261018_160209_244348_ubuntu_viewer_probe_786225d1`；v2校验`20261018_160439_185834_ubuntu_viewer_probe_2450abff`；安装`20261018_160554_183596_ubuntu_viewer_install_ca44f6b3`；GUI运行`20261018_160700_409588_ubuntu_realsense_viewer_gui_276d2466`；进程/原生识别验证`20261018_160824_358524_ubuntu_viewer_running_check_88d219e2`。

下一步由用户在Viewer中确认实际画面和调整构图；关闭Viewer后再重新初始化新模型并核对ID6参考，不将此前无有效码的静止记录当作ArUco精度。
