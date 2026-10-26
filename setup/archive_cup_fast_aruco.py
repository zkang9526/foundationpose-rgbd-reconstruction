#!/usr/bin/env python3
"""Archive verified compact speed/reference evidence and append local guides."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--profile', type=Path)
    p.add_argument('--replay', type=Path)
    p.add_argument('--controls', type=Path)
    p.add_argument('--synthetic', type=Path)
    p.add_argument('--compact', action='store_true', help='Verify already copied server compact evidence and append local guides')
    args = p.parse_args()
    if not args.compact and not all((args.profile, args.replay, args.controls, args.synthetic)):
        p.error('All four evidence directories are required without --compact')
    root = args.root.resolve(strict=True)
    values = {}
    for label, folder in (('PROFILE', args.profile), ('REPLAY', args.replay), ('CONTROLS', args.controls), ('SYNTHETIC', args.synthetic)):
        target = root / 'reports' / ('CUP_FAST_ARUCO_' + label + '_20261014.json')
        data = target.read_bytes() if args.compact else (folder / 'report.json').read_bytes()
        report = json.loads(data)
        if not report.get('passed'):
            raise ValueError('Unverified evidence: ' + label)
        values[label] = report
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Prior evidence retained: ' + str(target))
        if not target.exists():
            target.write_bytes(data)
    profile, replay = values['PROFILE'], values['REPLAY']
    gpu = profile['variants']['gpu_overlay_2iter']
    rejected = sum(not row['heuristic_consistent'] for row in gpu['original_drift_depth_quality'])
    accepted = sum(row['quality']['heuristic_consistent'] for row in gpu['metrics'])
    original_mesh_sha = profile['model_sha256']
    if original_mesh_sha != '5b52c3fd9904aaac2b155960d6faabb72be9330e8bb6741c470ec1f4dae4d9de':
        raise ValueError('Selected original metric mesh differs')
    if replay['official_tracking_iterations'] != 2 or replay['repo_commit'] != 'a1b694b83e633c2cb6115b9063d940a687759392':
        raise ValueError('Official inference configuration changed')
    # Compare full saved matrices rather than trace angles of float32 rotations.
    matrix_max = 0.
    if args.compact:
        prior = json.loads((root / 'reports/CUP_FAST_ARUCO_VERIFICATION_20261014.json').read_text())
        for label in values:
            if hashlib.sha256((root / 'reports' / ('CUP_FAST_ARUCO_' + label + '_20261014.json')).read_bytes()).hexdigest() != prior['evidence_sha256'][label]:
                raise ValueError('Compact server evidence differs: ' + label)
        matrix_max = prior['gpu2_vs_cpu2_max_saved_matrix_absolute_difference']
    for base in ((args.profile / 'baseline_cpu_2iter').glob('*.txt') if not args.compact else []):
        candidate = args.profile / 'gpu_overlay_2iter' / base.name
        a = [float(v) for v in base.read_text().split()]; b = [float(v) for v in candidate.read_text().split()]
        matrix_max = max(matrix_max, max(abs(x - y) for x, y in zip(a, b)))
    summary = dict(passed=True, live_camera_speed_validated=False, physical_accuracy_validated=False,
                   final_replay_fps=replay['steady_processing_fps'], final_replay_input_to_result_median_ms=replay['median_host_latency_ms'],
                   final_replay_input_to_result_p95_ms=replay['p95_host_latency_ms'], repeated_saved_frames=replay['completed'],
                   gpu2_vs_cpu2_max_saved_matrix_absolute_difference=matrix_max,
                   original_drift_heuristic_rejected=rejected, original_drift_checked=len(gpu['original_drift_depth_quality']),
                   fresh_control_heuristic_accepted=accepted, fresh_control_checked=len(gpu['metrics']),
                   absolute_object_gt_available=False, official_tracking_iterations=2,
                   evidence_sha256={name: hashlib.sha256((root / 'reports' / ('CUP_FAST_ARUCO_' + name + '_20261014.json')).read_bytes()).hexdigest()
                                    for name in values})
    (root / 'reports/CUP_FAST_ARUCO_VERIFICATION_20261014.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    text = f'''# 2026-10-14 实时加速、桌面ArUco独立参考与误差记录

用户要求给约9FPS的杯子实时跟踪提速，并准备固定桌面ArUco后移动相机测量误差。已部署 `setup/run_cup_live_fast.sh`；保留原入口，官方源码/预训练权重/米制网格不改，初始化5次、跟踪2次。

- 实际RTX3090的60帧分段计时：CPU完整轮廓版本worker-only约17.52FPS；GPU原始网格轮廓版本约26.81FPS。这不是端到端/实时相机测速。
- 最终源码版本的30Hz重复保存图像回放：{replay['completed']}帧，端到端稳态约{replay['steady_processing_fps']:.2f}FPS；输入收到到结果中位{replay['median_host_latency_ms']:.2f}ms、P95 {replay['p95_host_latency_ms']:.2f}ms。前两次同类回放分别约27.64和22.60FPS，显示机器负载/文件写入会影响结果。真实移动相机的新版帧率尚待用户贴码后实测。
- 自动检查无损NPY输入像素/哈希、所有估计矩阵、唯一递增采集序号、源码快照、缺码误差为空。冻结/Mask/初始化/跟踪/暂停/重新初始化/推理中停止与最后响应留档的控制测试通过。正常停止自动汇总配对覆盖率、拒绝率、误差、FPS及延迟。
- GPU2次与CPU2次对照，保存矩阵最大逐元素差 {matrix_max:.8g}；原计时报告直接用float32近似旋转矩阵的trace计算产生约0.056度数值底噪，不应当作真实旋转变化或精度误差。正式误差计算先投影SO(3)。1次细化对照存在约3.96mm/7.59度输出变化，未设为默认，均非GT误差。
- 初始化前后画面变化门限、可用码显示初始化期间的相机运动门限、每帧深度一致性保护均已实现。原漂移记录{len(gpu['original_drift_depth_quality'])}帧中{rejected}帧被粗门限拒绝，重新初始化对照{len(gpu['metrics'])}帧中{accepted}帧粗一致性通过；门限仍漏过4帧，不能宣称全部失跟都能识别。候选坏姿态仍保存并暂停跟踪，重新框选恢复；没有自动全局检测。
- 同原始RGB独立解算DICT_4X4_50 ID0，可记录相机相对运动误差、首帧对齐后的杯子原点漂移；重新初始化不清零首帧参考。打印后必须填写实测黑色外边长。看不到码、平面歧义、码质量失败或跟踪拒绝时不编造误差。
- 合成图和独立已知变换验证通过；真实桌面码尚未采集，无独立码→原始OBJ标定，不能标记绝对6D位姿准确度通过。孔洞/黑色材质深度/杯把朝向仍是候选模型与推理限制。

运行、印码和评测说明：[CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md](CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md)。四份原始紧凑报告与验证摘要保存在本reports目录；大体积回放/原始像素保留Ubuntu和E盘，C盘仅代码/小记录。所有执行通过记录器，失败重试保留原证据。
'''
    (root / 'reports/CUP_FAST_ARUCO_RESULT_20261014.md').write_text(text, encoding='utf-8')
    marker = '<!-- CUP-FAST-ARUCO-20261014 -->'
    line = ('2026-10-14已部署可选 `bash setup/run_cup_live_fast.sh --aruco-marker-length-m 实测米值 --aruco-id 0 --aruco-fixed-scene`。固定杯子/码，只移动相机；同帧RGB参考、无损NPY原图/毫米深度/SDK时间戳/估计矩阵/误差CSV/源码和权重证据均留档；正常结束自动汇总。保留官方2次细化与原入口。回放端到端约%.2fFPS，真实新版移动相机帧率与物理精度未实测；首帧对齐误差消除初始偏差，绝对误差需要独立码→原始OBJ变换。初步网格孔洞/杯把问题与部分失跟漏检仍未解决。见[操作说明](reports/CUP_ARUCO_ACCURACY_PROTOCOL_20261014.md)及[验证结果](reports/CUP_FAST_ARUCO_RESULT_20261014.md)。' % replay['steady_processing_fps'])
    for name in ('AGENTS.md', 'REPRODUCTION_GUIDE.md', 'D435i_connection.md', 'POSE_AND_TRAINING_GUIDE.md'):
        path = root / name
        old = path.read_text(encoding='utf-8') if path.exists() else ''
        if marker not in old:
            with path.open('a', encoding='utf-8') as stream:
                stream.write('\n' + marker + '\n' + line + '\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
