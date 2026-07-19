"""Tkinter desktop GUI for serial deployment and network image uploads."""

from __future__ import annotations

import re
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

try:
    from serial.tools import list_ports
except ModuleNotFoundError:
    list_ports = None

try:
    from pico_image_tool.client import DeviceClient, DeviceError, discover
    from pico_image_tool.conversion import ConversionOptions, ConversionResult, convert_image, save_compressed_bin
except ModuleNotFoundError:
    from tools.pico_image_tool.client import DeviceClient, DeviceError, discover
    from tools.pico_image_tool.conversion import ConversionOptions, ConversionResult, convert_image, save_compressed_bin
from .deployer import (
    CancellationToken,
    DeployOptions,
    DeployPlan,
    DeploymentError,
    DeploymentProgress,
    SerialDeployer,
    MpremoteRunner,
    build_deploy_plan,
    format_bytes,
)
from .jobs import Job, JobQueue


def _safe_filename(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", Path(value).stem).strip("_") or "image"
    return stem[:48] + ".bin"


@dataclass
class ImageJob:
    source_path: Path
    options: ConversionOptions
    filename: str
    event: str = "0101"
    overwrite: bool = False
    preview: bool = False
    queued: bool = False


class PicoDeployTool(tk.Tk):
    """Combined Pico Paper Clock desktop tool."""

    def __init__(self):
        super().__init__()
        self.title("Pico Paper Clock Tool")
        self.geometry("1180x820")
        self.minsize(980, 680)
        self.image_jobs: list[ImageJob] = []
        self.current_result: ConversionResult | None = None
        self.original_photo = None
        self.preview_photo = None
        self.deploy_plan: DeployPlan | None = None
        self._serial_port_map: dict[str, str] = {}
        self._ui_events = queue.Queue()
        self._build()
        self.queue = JobQueue(self._queue_update)
        self.refresh_serial_ports(silent=True)
        self.after(50, self._drain_ui_events)

    def _build(self):
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Georgia", 24, "bold"))
        style.configure("Sub.TLabel", foreground="#526068")

        shell = ttk.Frame(self, padding=16)
        shell.pack(fill="both", expand=True)
        shell.rowconfigure(2, weight=1)
        shell.columnconfigure(0, weight=1)

        ttk.Label(shell, text="Pico Paper Clock Tool", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            shell,
            text="USB 資源部署、圖片轉檔、LAN/AP 批次上傳與作業佇列",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        self._build_connection(shell)

        self.notebook = ttk.Notebook(shell)
        self.notebook.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        shell.rowconfigure(3, weight=1)
        self._build_deploy_tab()
        self._build_images_tab()
        self._build_queue_tab()

        self.status_var = tk.StringVar(value="準備完成")
        ttk.Label(shell, textvariable=self.status_var, anchor="w").grid(
            row=4, column=0, sticky="ew", pady=(8, 0)
        )

    def _build_connection(self, parent):
        frame = ttk.LabelFrame(parent, text="工作階段連線", padding=10)
        frame.grid(row=2, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(4, weight=1)
        self.vars = {
            "project_root": tk.StringVar(value=str(Path.cwd())),
            "serial_port": tk.StringVar(value=""),
            "device": tk.StringVar(value="192.168.4.1"),
            "password": tk.StringVar(value=""),
        }
        ttk.Label(frame, text="專案目錄").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(frame, textvariable=self.vars["project_root"]).grid(
            row=0, column=1, columnspan=4, sticky="ew"
        )
        ttk.Button(frame, text="瀏覽…", command=self.choose_project).grid(row=0, column=5, padx=(6, 0))
        ttk.Label(frame, text="序列埠").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        self.serial_combo = ttk.Combobox(
            frame,
            textvariable=self.vars["serial_port"],
            state="readonly",
            width=24,
        )
        self.serial_combo.grid(
            row=1, column=1, sticky="w", pady=(6, 0)
        )
        ttk.Button(frame, text="掃描序列埠", command=self.refresh_serial_ports).grid(
            row=1, column=2, padx=(6, 0), pady=(6, 0)
        )
        ttk.Label(frame, text="LAN/AP 位址").grid(
            row=1, column=3, sticky="w", padx=(14, 6), pady=(6, 0)
        )
        self.device_combo = ttk.Combobox(
            frame,
            textvariable=self.vars["device"],
            state="normal",
        )
        self.device_combo.grid(row=1, column=4, sticky="ew", pady=(6, 0))
        ttk.Button(frame, text="掃描 LAN", command=self.scan).grid(
            row=1, column=5, padx=(6, 0), pady=(6, 0)
        )
        ttk.Label(frame, text="密碼（admin）").grid(
            row=2, column=0, sticky="w", padx=(0, 6), pady=(6, 0)
        )
        ttk.Entry(frame, textvariable=self.vars["password"], show="•").grid(
            row=2, column=1, columnspan=4, sticky="ew", pady=(6, 0)
        )
        ttk.Button(frame, text="測試 LAN", command=self.test_device).grid(
            row=2, column=5, padx=(6, 0), pady=(6, 0)
        )

    def _build_deploy_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(1, weight=1)
        self.notebook.add(tab, text="序列部署")

        controls = ttk.LabelFrame(tab, text="部署選項", padding=10)
        controls.grid(row=0, column=0, sticky="nw", padx=(0, 12))
        self.deploy_vars = {
            "code": tk.BooleanVar(value=True),
            "config": tk.BooleanVar(value=False),
            "images": tk.BooleanVar(value=True),
            "webui": tk.BooleanVar(value=True),
            "clean": tk.BooleanVar(value=False),
            "recursive": tk.BooleanVar(value=False),
            "reset": tk.BooleanVar(value=True),
        }
        ttk.Checkbutton(controls, text="Python / JSON（保留 config 另行控制）", variable=self.deploy_vars["code"]).pack(anchor="w")
        ttk.Checkbutton(controls, text="覆寫 config.json（危險）", variable=self.deploy_vars["config"]).pack(anchor="w")
        ttk.Checkbutton(controls, text="裝置圖片（PPC1 .bin）", variable=self.deploy_vars["images"]).pack(anchor="w")
        ttk.Checkbutton(controls, text="生成 WebUI .bin", variable=self.deploy_vars["webui"]).pack(anchor="w")
        ttk.Separator(controls).pack(fill="x", pady=8)
        ttk.Checkbutton(controls, text="清理本次 manifest 舊檔", variable=self.deploy_vars["clean"]).pack(anchor="w")
        ttk.Checkbutton(controls, text="遞迴清理整台裝置（需 config）", variable=self.deploy_vars["recursive"]).pack(anchor="w")
        ttk.Checkbutton(controls, text="部署後重啟裝置", variable=self.deploy_vars["reset"]).pack(anchor="w")
        ttk.Button(controls, text="預覽 manifest", command=self.preview_manifest).pack(fill="x", pady=(12, 4))
        ttk.Button(controls, text="加入序列部署佇列", command=self.enqueue_serial).pack(fill="x", pady=4)
        ttk.Button(controls, text="加入完整同步佇列", command=self.enqueue_full_sync).pack(fill="x", pady=4)

        manifest_frame = ttk.LabelFrame(tab, text="部署前檢視", padding=8)
        manifest_frame.grid(row=0, column=1, rowspan=2, sticky="nsew")
        manifest_frame.rowconfigure(0, weight=1)
        manifest_frame.columnconfigure(0, weight=1)
        self.manifest_tree = ttk.Treeview(
            manifest_frame,
            columns=("category", "local", "remote", "size"),
            show="tree headings",
        )
        self.manifest_tree.heading("#0", text="檔案樹")
        self.manifest_tree.heading("category", text="分類")
        self.manifest_tree.heading("local", text="本機路徑")
        self.manifest_tree.heading("remote", text="裝置路徑")
        self.manifest_tree.heading("size", text="大小")
        self.manifest_tree.column("#0", width=240, minwidth=180)
        self.manifest_tree.column("category", width=90, stretch=False)
        self.manifest_tree.column("local", width=340)
        self.manifest_tree.column("remote", width=300)
        self.manifest_tree.column("size", width=100, stretch=False, anchor="e")
        self.manifest_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(manifest_frame, orient="vertical", command=self.manifest_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.manifest_tree.configure(yscrollcommand=scroll.set)
        self.manifest_status = tk.StringVar(value="尚未建立 manifest")
        ttk.Label(manifest_frame, textvariable=self.manifest_status, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

    def _build_images_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        tab.columnconfigure(0, weight=0)
        tab.columnconfigure(1, weight=1)
        tab.rowconfigure(0, weight=1)
        self.notebook.add(tab, text="圖片批次")

        list_frame = ttk.LabelFrame(tab, text="圖片清單", padding=8)
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        list_frame.rowconfigure(0, weight=1)
        self.image_list = tk.Listbox(list_frame, width=32, exportselection=False)
        self.image_list.grid(row=0, column=0, sticky="nsew")
        self.image_list.bind("<<ListboxSelect>>", lambda _event: self.load_selected_image())
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.image_list.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        self.image_list.configure(yscrollcommand=list_scroll.set)
        ttk.Button(list_frame, text="加入圖片…", command=self.choose_images).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 3))
        ttk.Button(list_frame, text="移除選取", command=self.remove_selected_image).grid(row=2, column=0, columnspan=2, sticky="ew", pady=3)
        ttk.Button(list_frame, text="加入所有圖片佇列", command=self.enqueue_images).grid(row=3, column=0, columnspan=2, sticky="ew", pady=3)

        editor = ttk.LabelFrame(tab, text="選取項目設定與預覽", padding=10)
        editor.grid(row=0, column=1, sticky="nsew")
        editor.columnconfigure(1, weight=1)
        editor.rowconfigure(9, weight=1)
        self.image_vars = {
            "type": tk.StringVar(value="custom"),
            "event": tk.StringVar(value="0101"),
            "fit": tk.StringVar(value="cover"),
            "dither": tk.StringVar(value="floyd-steinberg"),
            "threshold": tk.IntVar(value=128),
            "focus_x": tk.DoubleVar(value=0.5),
            "focus_y": tk.DoubleVar(value=0.5),
            "invert": tk.BooleanVar(value=False),
            "filename": tk.StringVar(value="image.bin"),
            "overwrite": tk.BooleanVar(value=False),
            "preview": tk.BooleanVar(value=False),
        }
        row = 0
        row = self._combo(editor, row, "目標", "type", ("custom", "events", "login"))
        row = self._entry(editor, row, "Event / birthday", "event")
        row = self._entry(editor, row, "遠端檔名", "filename")
        row = self._combo(editor, row, "Fit", "fit", ("cover", "contain", "stretch"))
        row = self._combo(editor, row, "Dither", "dither", ("floyd-steinberg", "atkinson", "bayer4", "threshold"))
        row = self._scale(editor, row, "Threshold", "threshold", 0, 255)
        row = self._scale(editor, row, "Focus X", "focus_x", 0, 1, .01)
        row = self._scale(editor, row, "Focus Y", "focus_y", 0, 1, .01)
        ttk.Checkbutton(editor, text="反相", variable=self.image_vars["invert"]).grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(editor, text="允許覆寫", variable=self.image_vars["overwrite"]).grid(row=row, column=0, sticky="w")
        ttk.Checkbutton(editor, text="上傳後預覽", variable=self.image_vars["preview"]).grid(row=row, column=1, sticky="w")
        row += 1
        button_row = ttk.Frame(editor)
        button_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        ttk.Button(button_row, text="更新項目與預覽", command=self.apply_image_settings).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(button_row, text="儲存 .bin", command=self.save_current_image).pack(side="left", fill="x", expand=True, padx=(4, 0))
        row += 1

        preview = ttk.Frame(editor)
        preview.grid(row=row, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        preview.columnconfigure(0, weight=1)
        preview.columnconfigure(1, weight=1)
        preview.rowconfigure(1, weight=1)
        ttk.Label(preview, text="原圖", anchor="center").grid(row=0, column=0, sticky="ew")
        ttk.Label(preview, text="1-bit 預覽", anchor="center").grid(row=0, column=1, sticky="ew")
        self.original_label = ttk.Label(preview, text="尚未選取圖片", anchor="center")
        self.original_label.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.preview_label = ttk.Label(preview, text="尚未轉檔", anchor="center")
        self.preview_label.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        self.image_status = tk.StringVar(value="請加入圖片")
        ttk.Label(editor, textvariable=self.image_status, anchor="w").grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

    def _build_queue_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        tab.rowconfigure(0, weight=1)
        tab.columnconfigure(0, weight=1)
        self.notebook.add(tab, text="作業佇列與紀錄")
        self.queue_tree = ttk.Treeview(tab, columns=("title", "status", "error"), show="headings")
        self.queue_tree.heading("title", text="作業")
        self.queue_tree.heading("status", text="狀態")
        self.queue_tree.heading("error", text="錯誤")
        self.queue_tree.column("title", width=360)
        self.queue_tree.column("status", width=100, stretch=False)
        self.queue_tree.column("error", width=520)
        self.queue_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.queue_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=scroll.set)
        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="開始佇列", command=self.start_queue).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="取消目前作業", command=self.cancel_queue).pack(side="left", padx=6)
        ttk.Button(actions, text="清除已完成", command=self.clear_queue).pack(side="left", padx=6)
        self.log_text = tk.Text(tab, height=8, state="disabled", wrap="word")
        self.log_text.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _entry(self, parent, row, label, key, **kwargs):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=self.image_vars[key], **kwargs).grid(row=row, column=1, sticky="ew", pady=3)
        return row + 1

    def _combo(self, parent, row, label, key, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        widget = ttk.Combobox(parent, textvariable=self.image_vars[key], values=values, state="readonly")
        widget.grid(row=row, column=1, sticky="ew", pady=3)
        widget.bind("<<ComboboxSelected>>", lambda _event: self.refresh_image_preview())
        return row + 1

    def _scale(self, parent, row, label, key, start, end, resolution=1):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        tk.Scale(
            parent,
            variable=self.image_vars[key],
            from_=start,
            to=end,
            resolution=resolution,
            orient="horizontal",
            showvalue=True,
            command=lambda _value: self.refresh_image_preview(),
        ).grid(row=row, column=1, sticky="ew")
        return row + 1

    def choose_project(self):
        path = filedialog.askdirectory(title="選擇含有 src/ 的專案目錄")
        if path:
            self.vars["project_root"].set(path)
            self.deploy_plan = None
            self.manifest_status.set("專案目錄已變更，請重新預覽")

    def _connection(self):
        return (
            self.vars["device"].get().strip(),
            "admin",
            self.vars["password"].get(),
        )

    def refresh_serial_ports(self, silent=False):
        if list_ports is None:
            self._serial_port_map = {}
            self.serial_combo["values"] = ()
            if not silent:
                messagebox.showerror("無法掃描序列埠", "目前 Python 環境沒有安裝 pyserial。")
            return

        try:
            ports = sorted(
                list_ports.comports(),
                key=lambda item: item.device,
            )
        except Exception as exc:
            if not silent:
                messagebox.showerror("無法掃描序列埠", str(exc))
            return

        values = []
        self._serial_port_map = {}
        pico_values = []
        current_port = self._selected_serial_port()
        for port in ports:
            description = port.description or "未知裝置"
            display = f"{port.device} — {description}"
            values.append(display)
            self._serial_port_map[display] = port.device
            if port.vid == 0x2E8A:
                pico_values.append(display)

        self.serial_combo["values"] = values
        selected = next(
            (display for display, device in self._serial_port_map.items() if device == current_port),
            None,
        )
        if selected is None and len(pico_values) == 1:
            selected = pico_values[0]
        if selected is None and len(values) == 1:
            selected = values[0]
        self.vars["serial_port"].set(selected or "")
        if not silent:
            if values:
                self.status_var.set(f"找到 {len(values)} 個序列埠，已選取 {selected or '請選擇'}")
            else:
                self.status_var.set("未找到序列埠；請確認 Pico 已透過 USB 連接")

    def _selected_serial_port(self):
        value = self.vars["serial_port"].get().strip()
        return self._serial_port_map.get(value, value if re.fullmatch(r"COM\d+", value, re.IGNORECASE) else "")

    def scan(self):
        self.status_var.set("正在掃描 LAN（先查 ARP，再補掃本機網段）…")
        current_host = self.vars["device"].get().strip()

        def work():
            try:
                devices = []
                if current_host and current_host != "192.168.4.1":
                    try:
                        devices = [DeviceClient(current_host, timeout=3.0).info()]
                    except Exception:
                        pass
                if not devices:
                    for attempt in range(2):
                        devices = discover(timeout=1.5, workers=8, first_only=True)
                        if devices or attempt == 1:
                            break
                        time.sleep(0.2)
                self._post_ui(lambda: self._scan_done(devices))
            except Exception as exc:
                self._post_ui(lambda exc=exc: messagebox.showerror("掃描失敗", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, devices):
        hosts = [item.host for item in devices]
        if hosts:
            self.device_combo["values"] = hosts
            self.vars["device"].set(hosts[0])
            self.status_var.set("找到裝置：" + ", ".join(hosts))
        else:
            self.device_combo["values"] = ()
            self.status_var.set("未找到裝置；請確認與 Pico 同一 LAN，或手動輸入 IP / 192.168.4.1")

    def test_device(self):
        host, username, password = self._connection()
        if not host:
            messagebox.showwarning("缺少位址", "請先輸入 LAN/AP 位址。")
            return
        self.status_var.set("正在檢查裝置…")

        def work():
            try:
                info = DeviceClient(host, username, password).info()
                message = f"裝置正常：API {info.api_version} / heap {info.heap_free} / flash {info.fs_free}"
                self._post_ui(lambda: self.status_var.set(message))
            except Exception as exc:
                self._post_ui(lambda exc=exc: messagebox.showerror("裝置檢查失敗", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _make_deploy_options(self) -> DeployOptions:
        clean_mode = "recursive" if self.deploy_vars["recursive"].get() else (
            "manifest" if self.deploy_vars["clean"].get() else "none"
        )
        return DeployOptions(
            source_root=Path(self.vars["project_root"].get()),
            include_code=self.deploy_vars["code"].get(),
            include_config=self.deploy_vars["config"].get(),
            include_images=self.deploy_vars["images"].get(),
            include_webui=self.deploy_vars["webui"].get(),
            clean_mode=clean_mode,
            reset_after=self.deploy_vars["reset"].get(),
        )

    def _plan_from_ui(self) -> tuple[DeployPlan, DeployOptions]:
        options = self._make_deploy_options()
        if options.clean_mode == "recursive":
            if not options.include_config:
                raise DeploymentError("遞迴清理前必須明確勾選覆寫 config.json。")
            if not messagebox.askyesno(
                "確認遞迴清理",
                "這會刪除裝置上的檔案後再部署，可能移除未保存在本機的圖片。確定繼續？",
            ):
                raise DeploymentError("使用者取消遞迴清理。")
        plan = build_deploy_plan(options)
        self.deploy_plan = plan
        return plan, options

    def preview_manifest(self):
        try:
            plan, _options = self._plan_from_ui()
        except Exception as exc:
            messagebox.showerror("Manifest 失敗", str(exc))
            return
        self._render_manifest(plan)
        self.manifest_status.set(f"{len(plan.entries)} 個檔案 / {format_bytes(plan.total_size)}")
        self.status_var.set("Manifest 已建立，請確認後加入佇列")

    def _render_manifest(self, plan):
        for item in self.manifest_tree.get_children():
            self.manifest_tree.delete(item)

        category_labels = {
            "code": "程式碼",
            "webui": "WebUI",
            "images": "圖片",
        }
        grouped = {category: [] for category in category_labels}
        for entry in plan.entries:
            grouped.setdefault(entry.category, []).append(entry)

        for category, entries in grouped.items():
            if not entries:
                continue
            label = category_labels.get(category, category)
            category_id = self.manifest_tree.insert(
                "",
                "end",
                text=label,
                values=(label, "", "", format_bytes(sum(entry.size for entry in entries))),
                open=True,
            )
            directory_ids = {}
            for entry in entries:
                parts = entry.remote_path.replace("\\", "/").split("/")
                parent_id = category_id
                remote_parts = []
                for directory in parts[:-1]:
                    remote_parts.append(directory)
                    key = (parent_id, directory)
                    directory_id = directory_ids.get(key)
                    if directory_id is None:
                        remote_path = "/".join(remote_parts) + "/"
                        directory_id = self.manifest_tree.insert(
                            parent_id,
                            "end",
                            text=directory,
                            values=(label, "", remote_path, ""),
                            open=True,
                        )
                        directory_ids[key] = directory_id
                    parent_id = directory_id
                self.manifest_tree.insert(
                    parent_id,
                    "end",
                    text=parts[-1],
                    values=(label, str(entry.local_path), entry.remote_path, format_bytes(entry.size)),
                )

    def _confirm_manifest(self, plan, options, action):
        self._render_manifest(plan)
        self.manifest_status.set(f"{len(plan.entries)} 個檔案 / {format_bytes(plan.total_size)}")
        warning = ""
        if options.clean_mode == "manifest":
            warning = "\n\n這會先刪除 manifest 對應的裝置檔案。"
        elif options.clean_mode == "recursive":
            warning = "\n\n警告：這會遞迴刪除裝置檔案。"
        return messagebox.askyesno(
            "確認部署",
            f"確定將 {len(plan.entries)} 個檔案加入{action}？\n總大小：{format_bytes(plan.total_size)}{warning}",
        )

    def _serial_action(self, plan: DeployPlan, options: DeployOptions, port):
        def action(token: CancellationToken, log):
            deployer = SerialDeployer(MpremoteRunner(port=port))
            deployer.deploy(
                plan,
                options,
                cancellation=token,
                progress=self._deployment_progress,
                log=log,
            )

        return action

    def enqueue_serial(self):
        port = self._selected_serial_port()
        if not port:
            messagebox.showwarning("未選擇序列埠", "請先掃描序列埠並從選單選擇 Pico。")
            return
        try:
            plan, options = self._plan_from_ui()
        except Exception as exc:
            messagebox.showerror("無法加入佇列", str(exc))
            return
        if not self._confirm_manifest(plan, options, "序列部署佇列"):
            return
        self.queue.add(Job(f"序列部署：{len(plan.entries)} 個檔案", self._serial_action(plan, options, port)))
        self.status_var.set("已加入序列部署佇列")
        self._refresh_queue_tree()

    def enqueue_full_sync(self):
        port = self._selected_serial_port()
        if not port:
            messagebox.showwarning("未選擇序列埠", "請先掃描序列埠並從選單選擇 Pico。")
            return
        selected = self._selected_image()
        if selected and not self.apply_image_settings():
            return
        try:
            plan, options = self._plan_from_ui()
        except Exception as exc:
            messagebox.showerror("無法加入佇列", str(exc))
            return
        pending = [item for item in self.image_jobs if not item.queued]
        if not pending:
            messagebox.showwarning("沒有圖片", "完整同步需要至少一張尚未加入佇列的圖片。")
            return
        host, username, password = self._connection()
        if not host:
            messagebox.showwarning("缺少位址", "完整同步需要 LAN/AP 位址。")
            return
        if not self._confirm_manifest(plan, options, "完整同步佇列"):
            return
        self.queue.add(Job(
            f"完整同步：序列 {len(plan.entries)} 檔案 + 網路 {len(pending)} 張圖片",
            self._full_sync_action(plan, options, pending, host, username, password, port),
        ))
        for item in pending:
            item.queued = True
        self.status_var.set("已加入完整同步佇列")
        self._refresh_queue_tree()

    def _full_sync_action(self, plan, options, items, host, username, password, port):
        serial_action = self._serial_action(plan, options, port)

        def action(token: CancellationToken, log):
            serial_action(token, log)
            log("等待裝置完成重啟與 Wi-Fi 初始化…")
            for _ in range(100):
                token.raise_if_cancelled()
                time.sleep(0.1)
            client = DeviceClient(host, username, password, timeout=3.0)
            deadline = time.monotonic() + 60
            while True:
                token.raise_if_cancelled()
                try:
                    info = client.info()
                    log(f"裝置重新連線：heap {info.heap_free} / flash {info.fs_free}")
                    break
                except Exception as exc:
                    if time.monotonic() >= deadline:
                        raise DeploymentError(f"裝置重啟後 60 秒內未恢復網路：{exc}") from exc
                    log("等待裝置網路恢復…")
                    for _ in range(20):
                        token.raise_if_cancelled()
                        time.sleep(0.1)
            for item in items:
                self._upload_image(item, client, token, log)

        return action

    def _deployment_progress(self, event: DeploymentProgress):
        if event.total_files:
            percent = event.completed_files * 100 / event.total_files
            self._post_ui(lambda: self.status_var.set(
                f"序列部署 {percent:.0f}%：{event.remote_path or event.message}"
            ))

    def choose_images(self):
        paths = filedialog.askopenfilenames(
            title="選擇圖片",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp")],
        )
        for value in paths:
            path = Path(value)
            options = self._image_options()
            self.image_jobs.append(ImageJob(path, options, _safe_filename(path.name), self.image_vars["event"].get()))
            self.image_list.insert("end", path.name)
        if paths:
            self.image_list.selection_clear(0, "end")
            self.image_list.selection_set(len(self.image_jobs) - 1)
            self.load_selected_image()
            self.status_var.set(f"已加入 {len(paths)} 張圖片")

    def remove_selected_image(self):
        selected = self.image_list.curselection()
        if not selected:
            return
        index = selected[0]
        if self.image_jobs[index].queued:
            messagebox.showwarning("無法移除", "已加入佇列的圖片不能移除。")
            return
        self.image_jobs.pop(index)
        self.image_list.delete(index)
        if self.image_jobs:
            self.image_list.selection_set(min(index, len(self.image_jobs) - 1))
            self.load_selected_image()
        else:
            self.original_label.configure(image="", text="尚未選取圖片")
            self.preview_label.configure(image="", text="尚未轉檔")

    def _image_options(self) -> ConversionOptions:
        return ConversionOptions(
            target=self.image_vars["type"].get(),
            fit=self.image_vars["fit"].get(),
            dither=self.image_vars["dither"].get(),
            threshold=self.image_vars["threshold"].get(),
            invert=self.image_vars["invert"].get(),
            focus_x=self.image_vars["focus_x"].get(),
            focus_y=self.image_vars["focus_y"].get(),
        )

    def _selected_image(self) -> ImageJob | None:
        selected = self.image_list.curselection()
        return self.image_jobs[selected[0]] if selected else None

    def load_selected_image(self):
        item = self._selected_image()
        if not item:
            return
        self.image_vars["type"].set(item.options.target)
        self.image_vars["event"].set(item.event)
        self.image_vars["filename"].set(item.filename)
        self.image_vars["fit"].set(item.options.fit)
        self.image_vars["dither"].set(item.options.dither)
        self.image_vars["threshold"].set(item.options.threshold)
        self.image_vars["focus_x"].set(item.options.focus_x)
        self.image_vars["focus_y"].set(item.options.focus_y)
        self.image_vars["invert"].set(item.options.invert)
        self.image_vars["overwrite"].set(item.overwrite)
        self.image_vars["preview"].set(item.preview)
        try:
            with Image.open(item.source_path) as source:
                original = ImageOps.exif_transpose(source).convert("RGB")
        except (OSError, ValueError) as exc:
            self.current_result = None
            self.image_status.set(f"圖片無法讀取：{exc}")
            self.original_label.configure(image="", text="圖片無法讀取")
            self.preview_label.configure(image="", text="尚未轉檔")
            return
        original.thumbnail((360, 480))
        self.original_photo = ImageTk.PhotoImage(original)
        self.original_label.configure(image=self.original_photo, text="")
        self.refresh_image_preview()

    def refresh_image_preview(self):
        item = self._selected_image()
        if not item:
            return
        try:
            result = convert_image(item.source_path, self._image_options())
            preview = result.preview.copy()
            preview.thumbnail((360, 480))
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text="")
            self.current_result = result
            self.image_status.set(f"{result.width}×{result.height} / {len(result.data)} bytes")
        except Exception as exc:
            self.current_result = None
            self.image_status.set(str(exc))

    def apply_image_settings(self):
        item = self._selected_image()
        if not item:
            return False
        candidate = ImageJob(
            item.source_path,
            self._image_options(),
            self.image_vars["filename"].get().strip() or _safe_filename(item.source_path.name),
            self.image_vars["event"].get().strip() or "0101",
            self.image_vars["overwrite"].get(),
            self.image_vars["preview"].get(),
            item.queued,
        )
        try:
            self._validate_image_job(candidate)
        except ValueError as exc:
            messagebox.showerror("圖片設定錯誤", str(exc))
            return False
        item.options = candidate.options
        item.event = candidate.event
        item.filename = candidate.filename
        item.overwrite = candidate.overwrite
        item.preview = candidate.preview
        self.refresh_image_preview()
        self.status_var.set(f"已更新 {item.source_path.name}")
        return True

    def save_current_image(self):
        item = self._selected_image()
        if not item or not self.current_result:
            messagebox.showwarning("尚未轉檔", "請先選取圖片並更新預覽。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".bin",
            initialfile=item.filename,
            filetypes=[("PPC1 / BIN", "*.bin")],
        )
        if path:
            save_compressed_bin(path, self.current_result.data)
            self.image_status.set("已儲存 " + path)

    def enqueue_images(self):
        item = self._selected_image()
        if item and not self.apply_image_settings():
            return
        pending = [item for item in self.image_jobs if not item.queued]
        if not pending:
            messagebox.showwarning("沒有新圖片", "請先加入尚未排程的圖片。")
            return
        host, username, password = self._connection()
        if not host:
            messagebox.showwarning("缺少位址", "請先輸入 LAN/AP 位址。")
            return
        for image in pending:
            self.queue.add(Job(
                f"圖片上傳：{image.source_path.name}",
                self._image_action(image, host, username, password),
            ))
            image.queued = True
        self.status_var.set(f"已加入 {len(pending)} 張圖片上傳佇列")
        self._refresh_queue_tree()

    def _image_action(self, item, host, username, password):
        def action(token: CancellationToken, log):
            self._upload_image(item, DeviceClient(host, username, password), token, log)

        return action

    def _upload_image(self, item, client, token, log):
        token.raise_if_cancelled()
        self._validate_image_job(item)
        result = convert_image(item.source_path, item.options)
        output = item.source_path.with_suffix(".bin")
        save_compressed_bin(output, result.data)
        data = output.read_bytes()

        def progress(sent, total):
            token.raise_if_cancelled()
            self._post_ui(lambda: self.status_var.set(
                f"上傳 {item.source_path.name}：{sent}/{total} bytes"
            ))

        response = client.upload(
            data,
            item.options.target,
            item.filename,
            item.event,
            item.overwrite,
            item.preview,
            progress,
        )
        log(f"圖片完成：{response.get('path', item.filename)}；本地保留 {output}")

    @staticmethod
    def _validate_image_job(item):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}\.bin", item.filename):
            raise ValueError("遠端檔名必須是 1–48 個 ASCII 字母、數字、_ 或 -，並以 .bin 結尾。")
        if item.options.target == "events" and not (
            item.event == "birthday" or re.fullmatch(r"\d{4}", item.event)
        ):
            raise ValueError("events 目標的 Event 必須是 birthday 或四位數 MMDD。")

    def start_queue(self):
        try:
            self.queue.start()
            self.status_var.set("作業佇列執行中…")
        except Exception as exc:
            messagebox.showerror("無法開始佇列", str(exc))

    def cancel_queue(self):
        self.queue.cancel()
        self.status_var.set("正在取消目前作業…")

    def clear_queue(self):
        try:
            self.queue.clear_finished()
            self._refresh_queue_tree()
        except Exception as exc:
            messagebox.showerror("無法清除佇列", str(exc))

    def _queue_update(self, _job):
        self._post_ui(self._refresh_queue_tree)

    def _post_ui(self, callback):
        self._ui_events.put(callback)

    def _drain_ui_events(self):
        try:
            while True:
                callback = self._ui_events.get_nowait()
                callback()
        except queue.Empty:
            pass
        self.after(50, self._drain_ui_events)

    def _refresh_queue_tree(self):
        if not hasattr(self, "queue_tree"):
            return
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        for index, job in enumerate(self.queue.jobs):
            self.queue_tree.insert("", "end", iid=str(index), values=(job.title, job.status, job.error))
        self._refresh_log()

    def _refresh_log(self):
        if not hasattr(self, "log_text"):
            return
        lines = []
        for job in self.queue.jobs:
            for line in job.logs:
                lines.append(f"[{job.title}] {line}")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("end", "\n".join(lines))
        self.log_text.configure(state="disabled")
        self.log_text.see("end")


def run_gui():
    PicoDeployTool().mainloop()


# Compatibility name for callers that imported the pre-2.3 image-only GUI.
PicoImageTool = PicoDeployTool
