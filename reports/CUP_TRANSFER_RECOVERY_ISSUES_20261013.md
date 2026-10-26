## 导入历史档案换行变化（2026-10-13）

- 事实：整包及成员验证通过，文件导入与日志追加已执行；最终复验20份Windowsrun issues.md与源SHA不符。RGB-D、Mask和其它输出未见差异。
- 原因：索引导入复用append_records，默认生成问题单，在Linux重写导致CRLF→LF；逐文件字节比较证实仅换行变化。
- 处理：初始失败report/run不变，20份LF副本先备份，再从已验证ZIP payload恢复原字节。日志不覆盖、不重复追加。源接口加入write_run_issue=False用于历史导入。
- 复验：专用恢复run `20261013_213931_599894_cup_import_newline_recovery_4215c027` 退出0，6380项输出及来源SHA全部通过，失败report哈希保持。恢复问题已解决；补丁的服务器部署另需实际验证。
