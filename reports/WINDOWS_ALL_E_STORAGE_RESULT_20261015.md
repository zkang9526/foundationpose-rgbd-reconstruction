# 2026-10-15 Windows全部项目文件迁到E盘

用户再次反映C盘接近满，明确要求后续保存文件统一E盘。已将整个项目和pip下载缓存迁移，验证后删除C盘原件，并建立兼容目录联接。实际新增代码、文档、数据、报告、日志、导出包及项目子进程临时/缓存文件统一写E。

| 项目 | E盘真实位置 | 迁移文件数 | 迁移体积 |
|---|---|---:|---:|
| 完整项目（含代码、venv、数据、报告、运行档案、导出包） | `E:\foundationPos` | 66864 | 4.766 GiB |
| pip下载缓存 | `E:\foundationPos_data\cache\pip` | 4055 | 10.995 GiB |

C盘可用空间从约 **3.29 GiB** 提升到 **19.25 GiB**（数值按记录时磁盘状态，后台程序会使可用空间小幅变化）。原 `C:\Users\YOUR_USER\Desktop\foundationPos` 与原AppData pip缓存目录均为联接，指向上述E盘目录；原命令可继续访问同一份E盘文件。新的本机操作优先使用E盘真实根目录。

## 校验和复验

源目录清单、E盘复制件、切换前源目录、兼容路径、删除前原件的逐文件SHA256和目录成员数均一致；每阶段成功/失败日志、完整校验清单保留在 `E:\foundationPos_storage_ops\20261015`。没有删除原始采集、失败档案或下载缓存内容，仅移除已验证的C盘原件。

旧C路径与E路径执行相机venv均成功，OpenCV4.11.0/NumPy1.26.4/pyrealsense2导入通过。新的实际子进程复验通过：TEMP/TMP、pip、HuggingFace、Torch、通用、Matplotlib、Numba、CUDA及Python字节码缓存路径均为E；实际临时文件和项目文件写入E，C兼容路径访问同一文件。记录器的新运行目录也在E。证据为 `WINDOWS_E_STORAGE_EXECUTION_CHECK_20261015.json`、`WINDOWS_ALL_E_STORAGE_PROOF_20261015.json`。

配置在 `setup/windows_storage_policy.json`，由Windows记录器为子进程加载；采集根目录仍为 `E:\foundationPos_data\windows_captures`。Windows环境说明已追加到AGENTS.md、REPRODUCTION_GUIDE.md和D435i_connection.md。Linux执行分支和Ubuntu项目根目录 `/data/ZJC/foundationPos` 继续使用Linux路径。

本轮已结束的 11 份独立迁移运行档案按唯一run_id、逐文件哈希追加到项目 `foundationpose_data/runs`；E盘独立操作档案保留。没有用旧日志覆盖项目记录。
