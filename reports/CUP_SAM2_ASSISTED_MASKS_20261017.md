# 2026-10-17 SAM2辅助杯子Mask标注

用户反馈逐张手画多边形耗时。已在保持原始RGB-D不变的条件下，利用现有Ubuntu SAM2.1 Hiera Tiny生成修正版72张机器草稿，Windows新页面自动载入草稿，用户只修边、补漏、挖孔并逐张预览确认。原先5张人工确认及历史版本按原SHA复制保留，没有把机器草稿计为人工完成。

## 当前使用

- 页面：**http://127.0.0.1:8768/**，已打开，启动状态5/72确认、第一张待处理为000005（页面第6张）。后续进度以当前页面/report.json为准。
- 输入：`E:\foundationPos_data\windows_captures\obj_side_20261017_184953_656_corrected_last_190116`。
- 新标注输出：`E:\foundationPos_data\manual_masks\red_cup72_sam2_assisted_20261017_1945`。
- 旧8767页和`red_cup72_20261017_191047_148`保持原样，未刷新或关闭，未保存的浏览器绘制不受影响。新输出是已提交人工版本的快照；后续集中在8768继续，避免分叉。
- 使用：前景画笔补可见杯子，背景橡皮擦/多边形去除杯外背景及把手孔；预览最终二值Mask→勾选→保存→下一张。机器草稿是起点，用户必须逐张检查。

完整恢复命令见[人工Mask说明](../MANUAL_CUP_MASKS.md)。当前Windows页面只加载已生成的本地草稿，不需要安装PyTorch或逐帧连接Ubuntu。

## 已做的真实试跑与选择

本机GTX1650Ti 4GB，Windows相机venv没有torch/onnxruntime/SAM；Ubuntu现有SAM、SAM2及RTX3090可用。只上传本轮72张RGB约30MB压缩包、提示和独立worker，不传Windows venv，不占相机，不升级任一环境。远端按唯一job目录保留源码、原始图片SHA、框/点、权重与来源信息。每张独立图像推理，未用planned_angle或传播结果当6D真值。[SAM官方](https://github.com/facebookresearch/segment-anything)、[SAM2官方](https://github.com/facebookresearch/sam2)。

1. job`redcup72_20261017_1936`：容器Git ownership检查失败，尚未分割；本机run`20261017_193505_607275_cup_sam_drafts_pilot_74fdea7b`，远端`20261017_193511_112174_offline_sam_pilot_3a38bf47`。
2. job`redcup72_20261017_1937`：单次命令指定该精确safe.directory仍返回128，保留失败；本机run`20261017_193543_862000_cup_sam_drafts_pilot_retry_0d457969`。未修改global Git配置。
3. 改成只读解析已知clone的HEAD/ref，并与installation.json的commit和权重SHA对照，job1938的5角度SAM完成。初始框+少量点在000018/000054明显漏杯身；增加杯身多位置点的job1940仍漏红色下沿/部分杯把。两个SAM结果保留为不推荐的机器草稿，没有交作已接受Mask。
4. job`redcup72_sam2_20261017_1942`用现有独立SAM2.1环境；5角度视觉检查后，整组72张完成并逐文件SHA回传验证。全批worker进程内总耗时3.74秒（包括模型准备及72张推理，不含网络/页面/人工复核，不作为标注效率或物理准确度）。

上述名字中的时间片段是唯一job标签；实际开始/结束时间以run记录为准。所有失败目录均保留，不用重试覆盖。

## 草稿质量与待修位置

已查看全部72张草稿的9张联系图：杯身和红色区域总体保留，但**没有逐张替用户确认**，也没有真实分割GT。

- 000006–000019附近红色下沿有多个漏分小孔，部分前侧杯把末端也漏分。
- 000021–000039杯把漏分/断裂较明显，需用前景画笔补完整可见把手；保留真实把手孔背景。
- 000044、000045左上侧混入透明尺子的一小部分，需要擦除。
- 其他角度也有红色下沿及把手接头处的小孔、轮廓偏差，所有照片均需检查。可见杯子内的假孔可用画笔补；不要把真实把手孔填满。

草稿是RGB分割，不是深度补洞。RGB中可见杯子即使原始深度为0仍属前景；原始深度、K及时间戳均未变。杯口内壁仍因本轮倒扣未拍到，辅助Mask不解决该覆盖问题，也不解决现有Mesh/标定/6D精度疑问。

## 保存与验证约束

新输出`proposals/`保存原始SAM2二值Mask、生成报告、源RGB/depthSHA及逐帧ID；ID绑定帧名和Mask SHA。页面从二值草稿叠加人工多边形/画笔，最终预览和保存使用同一服务端渲染；跨帧草稿或SHA变化拒绝使用。每次人工确认仍保存独立revision；操作记录包含proposal ID，annotation_method=`machine_draft_human_review`及机器来源，区别于从零人工绘制。原5张人工annotation.json及mask.png按原字节复制，`imported_from.json`列来源、state SHA和版本SHA；未伪造新的人工确认时间。

- 既有24项合成HTTP/文件系统回归通过：run`20261017_194210_866187_manual_mask_editor_regression_with_proposals_09326a87`。
- 新9项合成草稿回归通过：run`20261017_194210_849121_manual_mask_proposal_regression_bb4d1ec7`，覆盖精确二值预览、相同Mask的跨帧绑定、补孔/撤销、人工确认约束、来源留档和SHA篡改拒绝。合成测试不代表真实杯子标注精度。
- 真实72张索引和草稿验证、5张人工版本复制：run`20261017_194319_424770_cup_sam2_assisted_annotation_snapshot_8ef35bfa`。
- 页面真实启动与浏览器显示已检查：run`20261017_194326_250720_cup_sam2_assisted_editor_launch_c05e5f88`；编辑器独立run`20261017_194330_396937_manual_cup_mask_editor_4daa38f2`。助手没有在真实杯子页面执行保存/确认。

## 产物位置与重现

- 最终机器草稿/完整推理报告：`E:\foundationPos_data\sam_drafts\redcup72_sam2_20261017_1942\full`。
- 9张草稿联系图：`E:\foundationPos\foundationpose_data\reviews\sam2_drafts_full72_20261017`。
- 成功全批本机run`20261017_194048_772977_cup_sam2_drafts_full72_4566f590`，远端run`20261017_194050_782911_offline_sam_full_39299235`；远端job根`/data/ZJC/foundationPos/foundationpose_data/offline_masks/redcup72_sam2_20261017_1942`。
- 来源/权重：SAM2既有installation.json、官方commit和checkpoint SHA保存在生成report；未另装模型。代码`setup/sam_offline_drafts.py`与`setup/stage_offline_sam_drafts.py`，先prepare新唯一job，再pilot检查，再full；每步通过run_logged执行。当前框/点仅适用固定相机下本轮摆放，新批次必须重新检查。

首次SSH只读probe成功，但客户端自动更新C盘known_hosts时被权限拒绝；后续使用`UpdateHostKeys=no`避免该写入，仍保留正常主机密钥验证，不修改认证配置。记录器继续强制Windows E盘缓存/临时目录，源照片和所有旧标注保留。
