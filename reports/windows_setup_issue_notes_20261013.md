## TOOL-20261013-WIN-001：初次 Windows 设备列表查询被权限限制

- 现象：受限工具环境中 `Get-CimInstance Win32_PnPEntity` 返回 Access Denied，HRESULT `0x80041003`。
- 处理：通过工具的权限放行机制重试该只读查询。
- 复验：系统查询成功，结果为空；另有 RealSense SDK 查询设备列表为空。此时相机仍由 Ubuntu 枚举到。
- 状态：诊断查询问题已解决。该现象不代表 RealSense 采集必须以管理员身份运行。
- 证据：Windows 设置摘要（原始附件未随公开快照提供）；初次查询的原始输出在本轮工具结果中，未伪造为独立的历史 console.log。

## OBS-20261013-WIN-002：Windows 实际取帧待验证

- 已验证 SDK、依赖、入口与跨平台保存格式；尚未在 Windows 打开彩色/深度流。
- 原因：本次检查时相机仍接在 Ubuntu。
- 状态：待用户将 D435i 接到 Windows，然后以新目录执行相机检查。
- 这属于待完成的物理接入步骤，不记为 SDK 或硬件故障。
