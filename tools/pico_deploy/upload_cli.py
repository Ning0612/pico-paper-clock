import subprocess
import os
import argparse
import time
import shutil
import sys
from pathlib import Path

try:
    from tools.pico_deploy.deployer import (
        DeployOptions,
        MpremoteRunner,
        SerialDeployer,
        build_deploy_plan,
        format_bytes as format_deploy_bytes,
    )
except ModuleNotFoundError:
    # Allow `python tools/pico_deploy/upload_cli.py` from the repository root.
    from deployer import (
        DeployOptions,
        MpremoteRunner,
        SerialDeployer,
        build_deploy_plan,
        format_bytes as format_deploy_bytes,
    )

# 主控台編碼在非 UTF-8 locale（如繁體中文 Windows 的 cp950）下會讓含 emoji 的 print()
# 拋出 UnicodeEncodeError，導致腳本在清除舊檔案後、上傳新檔案前崩潰，讓裝置卡在檔案不全的狀態。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

# --- Configuration ---
SOURCE_DIR = "src"
INCLUDE_EXTENSIONS = [".py", ".json"]
UPLOAD_IMAGES = True
MPREMOTE_PORT = None
ENABLE_CLEAN = True
ENABLE_RECURSIVE_CLEAN = False  # 新增：是否遞迴清除所有檔案
NO_CONFIG = False  # 新增：是否跳過 config.json


def interactive_repl(base_cmd, retry_count=30, retry_delay=1.0, connected_exit_seconds=2.0):
    """
    Start mpremote repl using the current terminal for stable live output.
    """
    _clear_current_line()
    print("\nEntering device Terminal (REPL)... Press Ctrl+X to exit.")

    repl_command = base_cmd + ["repl"]
    connected = False
    for attempt in range(1, retry_count + 1):
        try:
            started_at = time.monotonic()
            return_code = subprocess.call(repl_command)
            elapsed = time.monotonic() - started_at
            if return_code == 0:
                connected = True
                break
            if elapsed >= connected_exit_seconds:
                print("REPL session ended with status {}.".format(return_code))
                connected = True
                break
            if attempt < retry_count:
                print("REPL connection failed, waiting for device in {}s ({}/{})...".format(
                    retry_delay, attempt, retry_count
                ))
                time.sleep(retry_delay)
        except FileNotFoundError:
            print("mpremote not found. Install it with: pip install mpremote")
            break
        except KeyboardInterrupt:
            print("\nExited REPL.")
            connected = True
            break

    if connected:
        print("REPL connection closed.")
    else:
        print("REPL connection failed.")
    return connected


def run_command(command, ignore_exists_error=False, display_output=False, capture_output_only=False):
    """
    執行命令並捕獲輸出。
    """
    try:
        result = subprocess.run(command, check=not capture_output_only, capture_output=True, text=True, encoding='latin-1') 
        
        if capture_output_only:
            return result.stdout.strip() if result.stdout else ""

        stdout_str = result.stdout.strip() if result.stdout else ""
        stderr_str = result.stderr.strip() if result.stderr else ""

        if display_output: 
            if stdout_str:
                print(stdout_str)
            if stderr_str and not (ignore_exists_error and "File exists" in stderr_str):
                print(f"[stderr] {stderr_str}")
        return True
    except FileNotFoundError:
        if display_output:
            print("❌ 找不到 mpremote，請執行：pip install mpremote")
        return False
    except subprocess.CalledProcessError as e:
        if display_output:
            print(f"❌ 指令失敗：{' '.join(command)}")
            print(f"[stdout]\n{e.stdout.strip()}")
            if not (ignore_exists_error and "File exists" in e.stderr):
                print(f"[stderr]\n{e.stderr.strip()}")
        return False
    except Exception as e:
        if display_output:
            print(f"❌ 執行命令時發生意外錯誤: {e}")
        return False

def get_mpremote_base():
    executable = shutil.which("mpremote")
    if not executable:
        candidate = os.path.join(os.path.dirname(sys.executable), "mpremote.exe")
        if os.path.exists(candidate):
            executable = candidate
    if not executable:
        executable = "mpremote"
    return [executable, "connect", MPREMOTE_PORT] if MPREMOTE_PORT else [executable]

def format_bytes(size):
    """
    格式化檔案大小顯示
    """
    return format_deploy_bytes(size)


def _project_root():
    source = Path(SOURCE_DIR)
    return source.parent if source.name.lower() == "src" else source

def collect_files():
    """
    收集要上傳的檔案，並統計檔案大小
    """
    options = DeployOptions(
        source_root=_project_root(),
        include_code=True,
        include_config=not NO_CONFIG,
        include_images=UPLOAD_IMAGES,
        include_webui=True,
        clean_mode="none",
        reset_after=True,
    )
    plan = build_deploy_plan(options)
    return [(str(entry.local_path), entry.remote_path, entry.size) for entry in plan.entries]

def ensure_remote_dirs(path, created_dirs):
    """
    確保遠端目錄存在，使用字典記錄已建立的路徑
    """
    base_cmd = get_mpremote_base()
    parts = path.split("/")
    current = ""
    
    for part in parts:
        if not part:
            continue
        current = f"{current}/{part}" if current else part
        
        # 檢查是否已經建立過此路徑
        if current not in created_dirs:
            subprocess.run(base_cmd + ["fs", "mkdir", f":{current}"], capture_output=True, text=True, encoding='latin-1')
            created_dirs[current] = True

def _clear_current_line():
    print("\r" + " " * 150 + "\r", end="", flush=True)

def _print_progress_line(current_command, progress, file_size=None, total_width=50):
    """
    顯示進度條，包含檔案大小資訊
    """
    done_width = int(progress / 100 * total_width)
    bar = "█" * done_width + "-" * (total_width - done_width)
    
    size_info = f" ({format_bytes(file_size)})" if file_size else ""
    command_text = f"{current_command}{size_info}"
    
    print(f"\r[{bar}] {progress:.1f}% | {command_text.ljust(80)}", end="", flush=True)

def clean_device():
    """
    清除裝置上的檔案
    """
    if ENABLE_RECURSIVE_CLEAN:
        print("遞迴清除裝置上的所有檔案...")
        clean_all_files()
    else:
        print("清除裝置上指定類型的檔案 {}...".format(INCLUDE_EXTENSIONS))
        clean_specific_files()

def clean_all_files():
    """
    遞迴清除裝置上的所有檔案和目錄
    """
    print("⚠️  --recursive-clean 會刪除透過網路上傳、且只存在裝置上的所有圖片。")
    print("   請先使用 Pico Image Tool 保留本地 .bin；此操作不會自動備份裝置內容。")
    base_cmd = get_mpremote_base()
    
    def delete_directory_recursively(dir_path):
        """遞迴刪除目錄及其內容，返回上層時才刪除目錄本身"""
        # 列出目錄內容
        proc = subprocess.run(base_cmd + ["fs", "ls", f":{dir_path}"], capture_output=True, text=True, encoding='latin-1')
        if proc.returncode != 0:
            # 目錄可能已經不存在，為空或無法存取
            current_command_text = f"刪除目錄: {dir_path} (可能為空)"
            print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
            return run_command(base_cmd + ["fs", "rmdir", f":{dir_path}"], display_output=False)
        
        # 遍歷目錄內容，立即處理每個項目
        for line in proc.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) < 2:
                continue
                
            item_name = parts[-1].rstrip('/')
            if not item_name or item_name in ['', '.', '..']:
                continue
            
            full_path = f"{dir_path}/{item_name}"
            is_directory = parts[0].startswith('d') or line.endswith('/')
            
            if is_directory:
                # 如果是目錄，遞迴進入處理
                current_command_text = f"進入子目錄: {full_path}"
                print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
                
                # 遞迴呼叫，處理子目錄的所有內容
                success = delete_directory_recursively(full_path)
                if not success:
                    print(f"\n❌ 處理子目錄失敗: {full_path}")
                    
                # 遞迴回到這裡時，子目錄已經被刪除了
                
            else:
                # 如果是檔案，直接刪除
                if NO_CONFIG and item_name == "config.json":
                    continue
                current_command_text = f"刪除檔案: {full_path}"
                print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
                success = run_command(base_cmd + ["fs", "rm", f":{full_path}"], display_output=False)
                
        
        # 當前目錄的所有內容都處理完了，現在刪除這個空目錄
        current_command_text = f"刪除已清空的目錄: {dir_path}"
        print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
        success = run_command(base_cmd + ["fs", "rmdir", f":{dir_path}"], display_output=False)
        if not success:
            print(f"\n❌ 刪除目錄失敗: {dir_path}")
        
        return success
    
    # 獲取根目錄的檔案和目錄列表
    proc = subprocess.run(base_cmd + ["fs", "ls", ":"], capture_output=True, text=True, encoding='latin-1')
    if proc.returncode != 0:
        print("Warning: 無法列出根目錄檔案。裝置可能為空或未連接。")
        return
    
    root_files = []
    root_dirs = []
    
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if len(parts) < 2:
            continue
        
        item_name = parts[-1].rstrip('/')
        if not item_name or item_name in ['', '.', '..', ':']:
            continue
        
        if parts[0].startswith('d') or line.endswith('/'):
            root_dirs.append(item_name)
        else:
            root_files.append(item_name)
    
    total_items = len(root_files) + len(root_dirs)
    
    if total_items == 0:
        print("沒有找到要清除的檔案或目錄。")
        return

    print(f"找到 {len(root_files)} 個檔案和 {len(root_dirs)} 個目錄要刪除。")
    
    # 先刪除根目錄下的所有檔案
    for f in root_files:
        if NO_CONFIG and f == "config.json":
            continue
        current_command_text = f"刪除根目錄檔案: {f}"
        print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
        
        success = run_command(base_cmd + ["fs", "rm", f":{f}"], display_output=False)
        if not success:
            print(f"\n❌ 刪除檔案失敗: {f}")
    
    # 遞迴處理所有根目錄
    for d in root_dirs:
        current_command_text = f"開始處理目錄樹: {d}"
        print(f"\r{current_command_text.ljust(80)}", end="", flush=True)
        
        # 呼叫遞迴函數，會在處理完所有子內容後刪除目錄
        success = delete_directory_recursively(d)
        if not success:
            print(f"\n❌ 處理目錄樹失敗: {d}")
    
    _clear_current_line()
    print("✅ 檔案清除完成。\n")

def clean_specific_files():
    """
    清除指定類型的檔案
    """
    base_cmd = get_mpremote_base()

    proc = subprocess.run(base_cmd + ["fs", "ls", "-r", ":"], capture_output=True, text=True, encoding='latin-1')
    if proc.returncode != 0:
        print("Warning: 無法列出檔案。裝置可能為空或未連接。")
        return

    all_remote_files_raw = proc.stdout.strip().splitlines()
    
    files_to_delete = []
    for line in all_remote_files_raw:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split()
        if len(parts) < 2:
            continue
            
        # 取最後一個部分作為檔案名
        file_name = parts[-1]
        
        # 跳過目錄和無效檔案名
        if (not file_name or 
            file_name == ':' or 
            file_name.endswith('/') or 
            file_name in ['', '.', '..'] or
            parts[0].startswith('d')):
            continue

        # 檢查檔案副檔名
        if any(file_name.endswith(ext) for ext in INCLUDE_EXTENSIONS):
            if NO_CONFIG and file_name == "config.json":
                continue
            files_to_delete.append(file_name)

    if not files_to_delete:
        print("沒有找到符合條件的檔案要清除。")
        return

    print(f"找到 {len(files_to_delete)} 個檔案要刪除。")
    for i, f in enumerate(files_to_delete):
        progress_percent = ((i + 1) / len(files_to_delete)) * 100
        current_command_text = f"刪除檔案: {f}"
        _print_progress_line(current_command_text, progress_percent)

        success = run_command(base_cmd + ["fs", "rm", f":{f}"], display_output=False)
        if not success:
            _clear_current_line()
            print(f"❌ 刪除失敗: {f}")
    
    _clear_current_line()
    print("✅ 檔案清除完成。\n")

def reset_device():
    _clear_current_line()
    print("\n🔄 重啟裝置...")
    base_cmd = get_mpremote_base()
    run_command(base_cmd + ["reset"], display_output=True)

def upload_files():
    options = DeployOptions(
        source_root=_project_root(),
        include_code=True,
        include_config=not NO_CONFIG,
        include_images=UPLOAD_IMAGES,
        include_webui=True,
        clean_mode="none",
        reset_after=True,
    )
    plan = build_deploy_plan(options)
    print(f"📦 共 {len(plan.entries)} 個檔案要上傳，總大小: {format_bytes(plan.total_size)}")
    try:
        SerialDeployer(MpremoteRunner(MPREMOTE_PORT)).deploy(plan, options, log=print)
    except Exception as exc:
        print(f"❌ 上傳失敗：{exc}")
        return False

    # Keep the historical CLI behavior: enter REPL after a successful reset.
    base_cmd = get_mpremote_base()
    if not interactive_repl(base_cmd):
        return False
    return True

def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Upload files to Pico W.")
    parser.add_argument("--port", default=None, help="mpremote serial port, e.g. COM7.")
    parser.add_argument("--no-images", action="store_false", dest="upload_images", default=True, help="Do not upload image files.")
    parser.add_argument("--recursive-clean", action="store_true", dest="recursive_clean", default=False, help="遞迴清除裝置上的所有檔案 (包含目錄)")
    parser.add_argument("--no-clean", action="store_false", dest="enable_clean", default=True, help="跳過清除檔案步驟")
    parser.add_argument("--no-config", action="store_true", dest="no_config", default=False, help="不要上傳也不要刪除 config.json")
    return parser.parse_args(argv)

def main(argv=None):
    global UPLOAD_IMAGES, ENABLE_RECURSIVE_CLEAN, ENABLE_CLEAN, NO_CONFIG, MPREMOTE_PORT
    args = parse_args(argv)

    UPLOAD_IMAGES = args.upload_images
    ENABLE_RECURSIVE_CLEAN = args.recursive_clean
    ENABLE_CLEAN = args.enable_clean
    NO_CONFIG = args.no_config
    MPREMOTE_PORT = args.port

    print("--- Pico W 自動部署開始 ---")

    if ENABLE_CLEAN:
        clean_device()

    if not upload_files():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
