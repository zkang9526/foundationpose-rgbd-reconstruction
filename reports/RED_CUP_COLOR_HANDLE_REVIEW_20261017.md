# 杯子颜色与杯把缺陷检查（2026-10-17）

当前几何候选已经保存颜色。此前展示`geometry_views_8.png`使用统一配色，且旧预览器忽略OBJ的顶点RGB扩展；两者使用户无法从旧预览判断颜色。现已修正预览器，并在现有FoundationPose容器完成实际彩色渲染。**这是外观读取验证，模型几何/6D精度仍未验收。**

## 颜色和后续渲染

- 原OBJ：`E:\foundationPos_data\derived\redcup_geometric_comparison_20261017_2050\redcup_geometric_clean_v1_20261017_2050\cup_clean.obj`，SHA256=`88e127e4cd4388bedcd77e7a0fb2cd5bde31c0557f861a7b60f8250bdac32f53`，本轮未修改。
- 每行顶点含`v x y z r g b`，23796顶点、9331种顶点RGB；PLY也保留顶点颜色。当前是融合后的顶点颜色，没有高分辨率UV贴图，不能据此宣称精细纹理重建完成。部分OBJ查看器不支持这种颜色扩展，可使用同目录PLY检查。
- `setup/preview_cup_mesh_local.py`新增顶点RGB读取。彩色预览使用三角面顶点RGB均值；有UV纹理时仍优先采样UV。统一法向着色的形状图继续单独保存；`textured_views_8.png`为兼容旧入口的彩色图别名，report明确记录外观来源。
- 新预览：`E:\foundationPos_data\derived\redcup_color_delivery_20261017_2106\redcup_vertex_color_preview_20261017_2106\color_views_8.png`。旧预览、原OBJ、原PLY均保留。
- 现有`foundationpose`容器，FoundationPose commit `a1b694b83e633c2cb6115b9063d940a687759392`，`Utils.py` SHA256=`ab77518df7a6c41bef82cb32579d06ccff5d435ee5ad716a8c1fef0c72f05ad4`，trimesh4.2.0、torch2.0.0+cu118。直接调用现有`make_mesh_tensors`和`nvdiffrast_render`，实际进入`vertex_color`分支，三视角均有非恒定RGB输出。渲染支持顶点颜色，带UV的模型也有纹理分支；后续并非仅使用统一颜色的形状图。
- 实际渲染：`E:\foundationPos_data\derived\redcup_color_delivery_20261017_2106\redcup_foundationpose_color_render_20261017_2106`，有000000/000018/000036原RGB与渲染并排图、独立渲染PNG和报告。输入为重建估计姿态，不是新推理结果或GT，图中错位不能直接换算6D物理误差。
- 官方实现参考：<https://github.com/NVlabs/FoundationPose/blob/main/Utils.py>。本次结论还由上述本机容器源码版本与实际输出直接验证，不依赖主分支始终不变。

## 杯把：Mask、深度与配准分别检查

只在原RGB上选择三个可见杯把材料小矩形，再检查相同坐标的人工Mask和原始毫米深度；未修改用户标注。它们是稀疏样本，不能当作整只杯把的像素GT或所有72帧统计。

| 帧 | 原图样本ROI，右下不含 | 像素数 | 被Mask保留 | 原始非零深度 | 350–520mm保留 |
|---|---|---:|---:|---:|---:|
| 000000 | [246,373,255,392] | 171 | 97.08% | 98.83% | 98.83% |
| 000018 | [347,385,357,411] | 260 | 100.00% | 100.00% | 100.00% |
| 000036 | [423,310,432,332] | 198 | 97.47% | 24.24% | 23.74% |

000036所取右侧杯把样本75.76%原始深度为0，0.51%返回超过520mm。其轮廓大部分已被Mask保留，RGB可见而深度缺失是直接证据。其他样本也说明杯把并非普遍没有深度。非零深度不等于准确深度；接头、轮廓仍有小范围Mask偏差。

证据：`E:\foundationPos_data\derived\redcup_handle_samples_20261017_2106\handle_mask_depth_samples.png`和`report.json`，含九个原文件SHA、ROI、数值，结束后复核原文件均未改变。黄线为人工Mask，蓝色为Mask内原始depth=0，红色为本次重建深度区间外的正深度。

当前候选另外使用49帧可见杯把方向和23帧插值姿态，TSDF体素1.5mm；上一阶段轮廓叠图已有错位。配准/插值误差、深度缺失及有限分辨率都可能影响细杯把融合，现有检查没有证明某一因素为唯一根因。原SDK内外参物理准确性仍按用户选择暂缓验证。

## 修复建议与范围

杯把已有实测支撑的表面可以去孤立毛刺、保守平滑，并在改进配准后重新融合；小的Mask漏边也可按RGB修正。当前最需要区别处理的是有深度但没有对齐的点，以及原始就没有深度的区域。

连续缺失且各视角均无有效观测的区域，需要补拍杯把外侧、内侧及接头的有效RGB-D，或按实物尺寸建立有明确假设的CAD补面。仅放大Mask或直接补洞不能验证恢复了真实形状；杯把中间的真实通孔必须保留。建议先提高配准和观测支持，再做表面清理、UV贴图，以免把当前形变固定到模型中。

本轮仅修正预览、验证渲染和诊断杯把；未给候选添加假想几何，未覆盖实时FoundationPose模型，未改相机参数、原始数据或人工Mask。现有模型可用于外观/算法试跑，不能标记为精确CAD。

## 运行记录

- Windows：`20261017_210619_813602_redcup_handle_surface_sample_audit_bef73a83`、`20261017_210635_060604_redcup_appearance_code_stage_e83148aa`、`20261017_210653_876707_redcup_corrected_color_preview_5a45c0a6`、`20261017_210654_039682_redcup_installed_renderer_check_799959af`、`20261017_210712_311194_redcup_color_preview_delivery_0bd22b18`。
- Ubuntu：`20261017_210636_974189_redcup_appearance_code_directory_7618e7e9`、`20261017_210638_185360_redcup_appearance_code_sha_c34ce730`、`20261017_210655_787284_redcup_vertex_rgb_cpu_preview_b00297a6`、`20261017_210655_889827_redcup_installed_foundationpose_vertex_color_render_9cf2f854`、`20261017_210714_173818_redcup_appearance_delivery_archive_ec4e2965`。
- 新冻结源码：两端`foundationpose_data/derived/redcup_appearance_code_20261017_2106`；传输SHA校验通过。回传彩色预览和独立渲染PNG均按报告SHA核验。
