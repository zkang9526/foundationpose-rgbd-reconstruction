## 文档同步SSH引号解析问题：已复验修正（2026-10-14）

- 事实：首次部署note内分号经嵌套引号解析成为远程shell分隔符，出现 `Supply a command after --` 及两条command-not-found，部署helper未执行。
- 原因：命令构造中的SSH/nativeshell引号处理；不属于相机、内参或深度故障。
- 处理：远程note改为单个无shell分隔符的安全词，新stage与新run重试，不覆盖旧失败证据。
- 复验：服务器重试run `20261014_125231_224042_cup_camera_calibration_updates_deploy_retry1_12b76576` 退出0，175文件部署SHApassed并保留3份Windows档案。文档同步问题已复验修正。
- 限制：该成功只证明文档部署；设备物理边缘/距离精度仍待检查，可靠杯子几何和重建退出139仍未解决。
