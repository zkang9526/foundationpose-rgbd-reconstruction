# 2026-10-15 E盘统一存储迁移问题与处理

- 初始C盘仅约3.3GiB可用；事实：完整项目约4.766GiB，pip下载缓存约10.995GiB。已采用验证后迁移到E盘，C盘原路径目录联接兼容；实际释放结果以迁移报告的磁盘实测为准。
- 首次只读空间盘点把Temp中的所有reparse point都当符号链接，遇到 `ValueError: not a symbolic link`。保留失败脚本/运行目录，增加OSError/ValueError处理并不跟随reparse目标，重试成功；Temp中部分权限错误单独记录。未清空其它应用正在使用的临时文件。
- 首轮串行SHA清单因6.7万个文件耗时较长，结束只读校验任务并保留不完整清单；改为有界12线程分批校验，新的独立尝试完成。第一次任务尚在hash_source阶段，报告确认没有复制切换或删除原件。
- 用嵌套PowerShell内联命令结束只读校验时，变量被外层展开，导致保护检查语句报错，命令外层仍返回0；该异常不能当作保护检查通过。实际结束的是此前已确认的只读hash worker，首轮迁移报告source_removed=false/junction_created=false。后续文件迁移、路径检查、重命名与删除全部改用独立-File脚本，按明确目录和SHA复验执行；实际数据迁移通过。
- PowerShell针对“已存在空目录”的Junction测试失败；在新的不存在路径上创建联接的隔离测试通过。pip缓存采用原目录改名再创建旧路径联接的方法，成功复验后移除已校验原件。
- 项目根目录整体改名因 `The process cannot access the file because it is being used by another process` 失败，原件和已验证的E副本均保留。改用保留原目录节点的切换：先在隔离目录持有不共享删除的句柄，验证NTFS原位目录联接与目标读写通过；实际切换将已验证子项移到同卷明确备份目录，在空的原目录上设置mount-point reparse数据。切换后完整内容、旧/新路径venv、删除前备份复验通过；未强制关闭用户程序。
- 原位联接使用微软定义的FSCTL_SET_REPARSE_POINT与REPARSE_DATA_BUFFER MountPoint布局。实现与探针脚本、失败根目录改名记录均保留在E盘操作目录。方法依据：https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_set_reparse_point 和 https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/ntifs/ns-ntifs-_reparse_data_buffer 。
- C盘低空间问题已通过实际磁盘空闲量和文件内容校验复验；保存目录策略已通过真实子进程写文件、缓存环境变量和相机venv导入复验。没有以空间释放结果推断任何位姿或相机标定精度。
