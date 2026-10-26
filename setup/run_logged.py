#!/usr/bin/env python3
"""Run one argv command with local records; compatible with Python 3.8.

Arguments, caller notes and command output are recorded. Do not pass secrets in
arguments or notes, or print them from the child. Inherited stdin is not recorded.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid


DEFAULT_ROOT = (Path(__file__).resolve().parent.parent if os.name == "nt"
                else Path("/data/ZJC/foundationPos"))
ENV_KEYS = (
    "CUDA_HOME", "CUDA_VISIBLE_DEVICES", "TORCH_CUDA_ARCH_LIST", "MAX_JOBS",
    "CONDA_PREFIX", "VIRTUAL_ENV", "PYOPENGL_PLATFORM", "PYTHONUNBUFFERED",
    "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES",
    "LD_PRELOAD",
)
# Explicitly selected source files; never copy arbitrary command arguments.
SOURCE_NAMES = (
    'export_public_snapshot.py',
    'review_cup_return_trial.py',
    'review_live_handle_failure.py', 'review_saved_camera_motion.py', 'compare_cup_handle_yaw.py', 'cup_handle_yaw.py', 'verify_cup_dashboard_image_race.py', 'verify_cup_yaw_worker.py',
    'stage_ubuntu_viewer.py', 'install_realsense_viewer_user.py', 'run_realsense_viewer_ubuntu.sh',
    'cup_mesh_selection.py', 'verify_cup_mesh_selection.py', 'run_cup_live_redcup72.sh', 'stage_redcup_live.py', 'analyze_redcup_live_trial.py',
    'audit_cup_handle_samples.py', 'verify_mesh_color_render.py', 'stage_cup_appearance_review.py',
    'audit_reviewed_cup_masks.py', 'prepare_reviewed_cup_reference.py',
    'stage_reviewed_reconstruction.py', 'stage_geometric_comparison.py',
    'manual_mask_editor.py', 'run_manual_mask_editor.ps1', 'launch_manual_mask_editor.ps1',
    'verify_manual_mask_editor.py', 'verify_mask_proposals.py', 'prepare_sam_assisted_masks.py',
    'sam_offline_drafts.py', 'stage_offline_sam_drafts.py', 'preview_sam_drafts.py',
    'review_rgbd_capture_rois.py', 'compose_rgbd_retake.py',
    'filter_cup_reference_stability.py',
    'verify_cup_dashboard_restart.py',
    'review_saved_cup_aruco.py', 'verify_cup_review_download.py',
    'verify_cup_aruco_id6.py', 'analyze_cup_aruco_id6.py', 'finalize_cup_aruco_id6.py',
    'inspect_cup_aruco_scene.py', 'run_cup_live_aruco_id6.sh', 'cup_live_control.py', 'configure_cup_aruco_id6.py',
    'cup_reacquisition.py', 'cup_sam2_mask.py', 'cup_sam2_worker.py', 'provision_cup_sam2.py', 'verify_cup_reacquisition.py', 'compare_cup_sam2.py', 'inspect_reacquisition.py',
    'retry_sam2_sparse.py', 'cleanup_orphan_sam2_transports.py', 'inspect_sam2_progress.py', 'review_reacquisition_frames.py',
    'download_sam2_torch_wheel.py', 'stop_exact_sam2_transfer.py',
    'sam2_runtime_environment.py', 'append_reacquisition_note.py',
    'archive_reacquisition_evidence.py',
    'finalize_reacquisition_evidence.py',
    "project_git_state.py", "manage_project_git.py", "verify_project_git.py", "append_git_workflow_note.py",
    "cup_sam_mask.py", "cup_sam_worker.py", "provision_cup_sam.py", "verify_cup_sam.py", "inspect_sam_environment.py",
    "append_cup_sam_note.py", "archive_cup_sam_verification.py", "verify_sam_evidence_download.py", "check_cup_sam_sources.py",
    "windows_storage_policy.json", "verify_windows_e_storage.py",
    "run_cup_live_fast.py", "run_cup_live_fast.sh", "cup_pose_quality.py", "cup_aruco_reference.py",
    "benchmark_cup_live_acceleration.py", "verify_aruco_reference.py", "verify_cup_live_fast.py",
    "summarize_cup_aruco_session.py", "archive_cup_fast_aruco.py",
    "analyze_cup_live_drift.py", "replay_cup_live_segment.py", "compare_cup_live_reinitialization.py", "archive_cup_live_drift.py",
    "run_cup_live.py", "run_cup_live_worker.py", "cup_live_dashboard.py", "run_cup_live.sh",
    "verify_cup_live_bridge.py", "append_cup_live_environment_note.py",
    "summarize_cup_live_verification.py",
    "summarize_cup_pose_pilot.py", "stage_cup_pose_session.py",
    "review_rgbd_alignment.py", "run_rgbd_alignment_check.ps1",
    "probe_d435i_depth_options.py",
    "compare_d435i_depth_presets.py",
    "clear_recent_obj_captures.ps1",
    "get_windows_capture_directory.ps1", "windows_capture_storage.json",
    "launch_obj_recapture_on_E.ps1",
    "review_side72_depth_samples.py",
    "archive_side72_review.ps1",
    "review_new72_regions.py",
    "package_external_captures.py", "import_external_capture_package.py",
    "review_candidate_mask_sequence.py", "prepare_external_reference_inputs.py",
    "reconstruct_cup_geometric_tsdf.py", "diagnose_reference_tracking.py", "make_masked_rgb_reference_variant.py",
    "audit_geometric_cup_mesh.py",
    "archive_new72_reconstruction_results.ps1",
    "install_realsense_viewer_windows.ps1",
    "preview_rgbd_photo_sequence.py",
    "verify_obj_environment.py", "run_obj_environment_check.sh", "start_obj_photos.ps1",
    "realsense_capture_options.py", "verify_obj_windows_options.py",
    "finalize_obj_setup.py", "append_obj_environment_note.py",
    "prepare_cup_stage_payload.py",
    "prepare_d435i_windows.ps1", "finalize_transfer.py", "import_windows_run_records.py", "append_manual_records.py",
    "run_logged.py", "run_logged.sh", "capture_d435i.py", "check_capture_files.py",
    "run_d435i_capture.sh", "verify_d435i.py", "run_d435i_check.sh",
    "run_d435i_format_check.sh", "verify_environment.py", "verify_demo.py",
    "run_d435i_check.ps1", "run_d435i_capture.ps1", "run_d435i_format_check.ps1",
    "start_cup_trial.ps1", "assess_cup_snapshot.py", "assess_rgbd_regions.py",
    "assess_cup_sequence_regions.py",
    "review_capture_timing.py",
    "review_manual_capture_timing.py",
    "capture_d435i_photos.py", "start_cup_photos.ps1",
    "make_cup_masks_grabcut.py",
    "merge_cup_mask_geometry.py",
    "finalize_cup_reference_readiness.py", "review_cup_mask_depth.py",
    "prepare_cup_pilot_inputs.py", "package_cup_offline.py",
    "finalize_cup_delivery.py",
    "import_cup_offline_batch.py", "deploy_bundlesdf_isolated_20261013.py",
    "deploy_cup_stage_updates.py", "prepare_cup_stage_payload.py",
    "recover_cup_import_issue_newlines.py", "run_cup_bundlesdf_pilot.py",
    "run_cup_mesh_inference.py", "review_cup_reconstruction.py",
    "inspect_cup_v4_completion.py",
    "run_cup_bundlesdf_frozen_pose_pilot.py", "run_cup_mesh_inference_candidates.py",
    "review_cup_heldout_projection.py", "rerank_cup_candidates_mask.py",
    "preview_cup_mesh_cpu.py", "preview_cup_mesh_local.py",
    "audit_bundlesdf_pose_gauge_20261013.py", "prepare_cup_visual_artifact_manifests.py",
    "conda_run.sh", "enter_foundationpose.sh",
)
OUTPUT_FLAGS = {
    "--output", "--output-dir", "--output_dir", "--debug-dir", "--debug_dir",
    "--save-dir", "--save_dir", "--log-dir", "--log_dir",
}
ARTIFACT_NAMES = {
    "report.json", "metadata.json", "capture_report.json", "run_report.json",
    "environment_verification.json", "K.txt", "cam_K.txt", "depth_scale.txt",
}


# Windows E-drive storage policy: Linux execution is unchanged.
def windows_storage_environment():
    if os.name != "nt":
        return {}
    policy_path = Path(__file__).resolve().with_name("windows_storage_policy.json")
    if not policy_path.is_file():
        return {}
    allowed = {"TEMP", "TMP", "PIP_CACHE_DIR", "HF_HOME", "TORCH_HOME", "XDG_CACHE_HOME", "MPLCONFIGDIR", "NUMBA_CACHE_DIR", "CUDA_CACHE_PATH", "PYTHONPYCACHEPREFIX"}
    values = json.loads(policy_path.read_text(encoding="utf-8"))["environment"]
    if not set(values).issubset(allowed):
        raise ValueError("Unsupported storage environment key")
    result = {}
    for name, value in values.items():
        path = Path(value).resolve()
        if path.drive.upper() != "E:":
            raise ValueError("Windows storage policy requires an E-drive path: " + name)
        path.mkdir(parents=True, exist_ok=True)
        result[name] = str(path)
    return result


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def runner_message(run_dir, message):
    """Preserve runner failures in the same console evidence as child output."""
    try:
        with (run_dir / "console.log").open("ab") as console:
            console.write(("\n[run_logged] " + message + "\n").encode("utf-8", errors="replace"))
    except OSError as error:
        print("Unable to append console evidence: " + str(error), file=sys.stderr, flush=True)
    print(message, file=sys.stderr, flush=True)


def metadata_command(argv, cwd=None):
    """A failed or unavailable inspection must not block the actual command."""
    try:
        result = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=4, check=False)
        return {"argv": argv, "exit_code": result.returncode,
                "output": result.stdout[:131072].decode("utf-8", errors="replace"),
                "truncated": len(result.stdout) > 131072}
    except Exception as error:
        return {"argv": argv, "error": "{}: {}".format(type(error).__name__, error)}


def collect_metadata(root):
    metadata = {
        "platform": platform.platform(), "hostname": socket.gethostname(),
        "python": sys.version, "python_executable": sys.executable,
        "environment": {key: os.environ[key] for key in ENV_KEYS if key in os.environ},
    }
    if os.name == "nt":
        metadata["git"] = {}
        if shutil.which("git"):
            for name in ("FoundationPose", "FoundationPose-conda"):
                if (root / name / ".git").exists():
                    metadata["git"][name] = metadata_command(["git", "rev-parse", "HEAD"], str(root / name))
        metadata["nvidia_smi"] = (metadata_command(["nvidia-smi"]) if shutil.which("nvidia-smi")
                                  else {"available": False})
        camera_python = root / ".windows-camera-venv/Scripts/python.exe"
        metadata["pip_freeze"] = {
            "windows_camera": (metadata_command([str(camera_python), "-m", "pip", "freeze"])
                               if camera_python.is_file() else {"available": False, "python": str(camera_python)})
        }
        return metadata
    metadata.update({
        "git": {name: metadata_command(["git", "rev-parse", "HEAD"], str(root / name))
                for name in ("FoundationPose", "FoundationPose-conda")},
        "nvidia_smi": metadata_command(["nvidia-smi"]),
        "lsusb": metadata_command(["lsusb"]),
        "pip_freeze": {
            "conda": metadata_command([
                "/home/ni/anaconda3/envs/foundationpose/bin/python", "-m", "pip", "freeze"]),
            "camera": metadata_command([str(root / ".camera-venv/bin/python"), "-m", "pip", "freeze"]),
            "docker": metadata_command([
                "docker", "exec", "foundationpose", "/opt/conda/envs/my/bin/python", "-m", "pip", "freeze"]),
        },
    })
    return metadata


def snapshot_sources(run_dir):
    sources = []
    source_dir = Path(__file__).resolve().parent
    for name in SOURCE_NAMES:
        original = source_dir / name
        if not original.is_file() or original.resolve().parent != source_dir:
            continue
        try:
            if original.stat().st_size > 1048576:
                continue
            content = original.read_bytes()
            destination = run_dir / "source" / name
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(content)
            sources.append({"original": str(original), "snapshot": "source/" + name,
                            "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
        except Exception as error:
            sources.append({"original": str(original), "error": str(error)})
    return sources


def collect_outputs(argv, cwd, root, run_dir):
    outputs = []
    seen = set()
    docker_command = any(Path(value).name == "docker" for value in argv)
    for index, token in enumerate(argv):
        flag, separator, value = token.partition("=")
        if flag not in OUTPUT_FLAGS:
            continue
        if not separator:
            if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
                continue
            value = argv[index + 1]
        if value in seen:
            continue
        seen.add(value)
        entry = {"argument": flag, "requested": value, "artifacts": []}
        outputs.append(entry)
        if not value or value == "-" or "://" in value:
            entry.update(host_path=None, exists=False)
            continue
        try:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = cwd / path
            if not path.exists() and docker_command and value.startswith("/data/"):
                path = root / "foundationpose_data" / value[len("/data/"):]
                entry["mapped_from"] = value
            path = path.resolve()
            entry.update(host_path=str(path), exists=path.exists())
            candidates = [path] if path.is_file() else [path / name for name in sorted(ARTIFACT_NAMES)]
            for candidate in candidates:
                if candidate.name not in ARTIFACT_NAMES or not candidate.is_file():
                    continue
                if candidate.stat().st_size > 262144:
                    continue
                destination = run_dir / "artifacts" / ("{:02d}_".format(len(outputs)) + candidate.name)
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(str(candidate), str(destination))
                entry["artifacts"].append(str(destination.relative_to(run_dir)))
        except Exception as error:
            entry["error"] = str(error)
    return outputs


def indented(value):
    return "\n".join("    " + line for line in str(value).splitlines())


def append_records(root, run_dir, report, write_run_issue=True):
    relative = run_dir.relative_to(root).as_posix()
    label = report["label"].replace("\n", " ").replace("\r", " ")
    summary = ("\n### {started} · {label}\n\n"
               "- 状态：{status}；退出码：{code}；耗时：{duration:.3f} 秒。\n"
               "- 记录目录：`{relative}`；证据：`{relative}/run.json`、`{relative}/console.log`。\n"
               "- 工作目录：`{cwd}`。\n"
               "- 调用者备注：\n\n{note}\n\n- 命令：\n\n{command}\n").format(
                   started=report["start"], label=label, status=report["status"],
                   code=report["exit_code"], duration=report["duration_seconds"], relative=relative,
                   cwd=report["cwd"], note=indented(report["note"] or "未提供"),
                   command=indented(report["command"]))
    issue = ("\n### {started} · {label}\n\n"
             "- 状态：待排查；不自动标记已解决。\n"
             "- 现象：命令退出码为 {code}（子进程原始退出码：{child}）。\n"
             "- 调用者备注（验证记录应在此明确标注）：\n\n{note}\n\n"
             "- 证据：`{relative}/run.json`、`{relative}/console.log`。\n"
             "- 原因：待排查，以实际日志为准。\n"
             "- 处理：待补充。\n"
             "- 复验：待补充运行目录、结果与结论。\n").format(
                 started=report["start"], label=label, code=report["exit_code"],
                 child=report["child_exitcode"], note=indented(report["note"] or "未提供"), relative=relative)
    if report["exit_code"] != 0 and write_run_issue:
        (run_dir / "issues.md").write_text("# 本次运行问题记录\n" + issue, encoding="utf-8")
    # Platform locks protect concurrent appenders; existing documents are preserved.
    with (root / ".records.lock").open("a+b") as lock:
        if sys.platform.startswith("linux"):
            import fcntl
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        elif os.name == "nt":
            import msvcrt
            lock.seek(0, os.SEEK_END)
            if lock.tell() == 0:
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            documents = [("EXPERIMENT_LOG.md", "# 执行与实验记录\n", summary)]
            if report["exit_code"] != 0:
                documents.append(("ISSUES.md", "# 问题与处理记录\n", issue))
            for name, header, content in documents:
                path = root / name
                needs_header = not path.exists() or path.stat().st_size == 0
                with path.open("a", encoding="utf-8") as output:
                    if needs_header:
                        output.write(header)
                    output.write(content)
        finally:
            if sys.platform.startswith("linux"):
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            elif os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--note", default="", help="Caller description; do not include secrets.")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not argv:
        parser.error("Supply a command after --.")
    root = args.root.expanduser().resolve()
    cwd = args.cwd.expanduser().resolve()
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", args.label)[:80].strip("._") or "run"
    name = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + label + "_" + uuid.uuid4().hex[:8]
    run_dir = root / "foundationpose_data/runs" / name
    run_dir.mkdir(parents=True, exist_ok=False)
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    command_shell = "Windows native argv" if os.name == "nt" else "POSIX shlex"
    (run_dir / "command.txt").write_text(command + "\n", encoding="utf-8")
    report = {"schema_version": 1, "run_id": name, "label": args.label, "note": args.note, "start": utc_now(),
              "end": None, "cwd": str(cwd), "argv": argv, "command": command,
              "command_shell": command_shell,
              "status": "running", "child_exitcode": None, "exit_code": None,
              "duration_seconds": None, "outputs": [], "warnings": []}
    write_json(run_dir / "run.json", report)
    (run_dir / "notes.md").write_text(
        "# 人工运行条件与验收备注\n\n"
        "运行编号（run_id）：`" + name + "`\n\n"
        "调用者备注（原文，不应包含密码等秘密）：\n\n" + indented(args.note or "未提供") + "\n\n"
        "- 记录类型：待填写（实际实验 / 工具验证；预期失败验证需明确注明）。\n"
        "- 操作人、场景与目的：待填写。\n"
        "- 物体、光照、距离、相机安装等条件：待填写；不适用则注明。\n"
        "- 参数选择与人工操作：待填写。\n"
        "- 产物路径与人工验收标准：待填写。\n"
        "- 观察结果、问题与处理：待填写。\n"
        "- 结论与后续复验记录：待填写。\n", encoding="utf-8")
    print("Run records: " + str(run_dir), flush=True)
    started = time.monotonic()
    process = None
    interrupted = []
    timers = []

    def send_signal(number, force=False):
        if process is None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL if force else number)
            elif process.poll() is None:
                if force:
                    process.kill()
                elif number == signal.SIGINT:
                    try:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    except (OSError, ValueError):
                        process.terminate()
                else:
                    process.terminate()
        except ProcessLookupError:
            pass

    def on_signal(number, frame):
        interrupted.append(number)
        send_signal(number)
        # An unresponsive child (or grandchild holding the pipe) cannot hang cleanup.
        if len(interrupted) == 1:
            for delay, forwarded, force in ((15, signal.SIGTERM, False), (20, signal.SIGTERM, True)):
                timer = threading.Timer(delay, send_signal, args=(forwarded, force))
                timer.daemon = True
                timer.start()
                timers.append(timer)
        else:
            send_signal(signal.SIGTERM, force=True)

    old_handlers = {number: signal.signal(number, on_signal) for number in (signal.SIGINT, signal.SIGTERM)}
    exit_code = 1
    try:
        try:
            report["metadata"] = collect_metadata(root)
        except Exception as error:
            report["warnings"].append("Metadata inspection: " + str(error))
        report.setdefault("metadata", {}).update(run_id=name, status="running")
        try:
            from project_git_state import snapshot_project_git
            report['metadata']['project_git'] = snapshot_project_git(root, run_dir)
        except Exception as error:
            report['warnings'].append('Project Git inspection: ' + str(error))
        write_json(run_dir / "environment.json", report["metadata"])
        report["sources"] = snapshot_sources(run_dir)
        write_json(run_dir / "run.json", report)
        with (run_dir / "console.log").open("wb") as console:
            if interrupted:
                exit_code = 128 + interrupted[0]
            else:
                child_env = os.environ.copy()
                child_env.setdefault("PYTHONUNBUFFERED", "1")
                if os.name == "nt":
                    child_env.setdefault("PYTHONIOENCODING", "utf-8")
                    storage_environment = windows_storage_environment()
                    child_env.update(storage_environment)
                    report["windows_storage_environment"] = storage_environment
                process = subprocess.Popen(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, env=child_env,
                                           start_new_session=(os.name == "posix"),
                                           creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
                if interrupted:
                    send_signal(interrupted[0])
                live_output = getattr(sys.stdout, "buffer", None)
                while True:
                    chunk = process.stdout.read1(65536)
                    if not chunk:
                        break
                    console.write(chunk)
                    console.flush()
                    try:
                        if live_output is not None:
                            live_output.write(chunk)
                            live_output.flush()
                        else:
                            sys.stdout.write(chunk.decode("utf-8", errors="replace"))
                            sys.stdout.flush()
                    except (BrokenPipeError, OSError):
                        # Continue preserving the file even if the terminal disappears.
                        live_output = None
                report["child_exitcode"] = process.wait()
                exit_code = report["child_exitcode"]
                if exit_code < 0:
                    exit_code = 128 - exit_code
    except Exception as error:
        report["error"] = "{}: {}".format(type(error).__name__, error)
        if process is not None:
            send_signal(signal.SIGTERM, force=True)
            report["child_exitcode"] = process.wait()
        exit_code = 127 if isinstance(error, FileNotFoundError) else 1
        runner_message(run_dir, report["error"])
    finally:
        if interrupted:
            send_signal(signal.SIGTERM, force=True)
        for timer in timers:
            timer.cancel()
        for number, handler in old_handlers.items():
            signal.signal(number, handler)
        if interrupted:
            exit_code = 128 + interrupted[0]
        report.update(end=utc_now(), duration_seconds=time.monotonic() - started,
                      exit_code=exit_code, status=("interrupted" if interrupted else
                                                  "passed" if exit_code == 0 else "failed"))
        report["duration"] = report["duration_seconds"]
        report.setdefault("metadata", {}).update(run_id=name, status=report["status"])
        write_json(run_dir / "environment.json", report["metadata"])
        report["outputs"] = collect_outputs(argv, cwd, root, run_dir)
        write_json(run_dir / "run.json", report)
        try:
            append_records(root, run_dir, report)
        except Exception as error:
            report["warnings"].append("Markdown append failed: " + str(error))
            write_json(run_dir / "run.json", report)
            runner_message(run_dir, report["warnings"][-1])
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
