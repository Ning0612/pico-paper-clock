import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk

from .client import DeviceClient, discover
from .conversion import ConversionOptions, convert_image, save_bin


class PicoImageTool(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pico Image Tool")
        self.geometry("1040x720")
        self.minsize(900, 620)
        self.source_path = None
        self.result = None
        self.original_photo = None
        self.preview_photo = None
        self._build()

    def _build(self):
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Georgia", 24, "bold"))
        style.configure("Sub.TLabel", foreground="#526068")
        shell = ttk.Frame(self, padding=18)
        shell.pack(fill="both", expand=True)
        ttk.Label(shell, text="Pico Image Tool", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(shell, text="裁切、抖動、MONO_HLSB 轉檔與網路上傳", style="Sub.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 14))

        controls = ttk.LabelFrame(shell, text="轉檔與裝置", padding=12)
        controls.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        preview = ttk.LabelFrame(shell, text="1-bit 預覽", padding=12)
        preview.grid(row=2, column=1, sticky="nsew")
        shell.columnconfigure(0, weight=0)
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(2, weight=1)

        self.vars = {
            "type": tk.StringVar(value="custom"), "event": tk.StringVar(value="0101"),
            "fit": tk.StringVar(value="cover"), "dither": tk.StringVar(value="floyd-steinberg"),
            "threshold": tk.IntVar(value=128), "invert": tk.BooleanVar(value=False),
            "focus_x": tk.DoubleVar(value=0.5), "focus_y": tk.DoubleVar(value=0.5),
            "device": tk.StringVar(value="192.168.4.1"), "username": tk.StringVar(value="admin"),
            "password": tk.StringVar(value=""), "name": tk.StringVar(value="image.bin"),
            "overwrite": tk.BooleanVar(value=False), "preview": tk.BooleanVar(value=False),
            "status": tk.StringVar(value="請先選取圖片"),
        }
        row = 0
        ttk.Button(controls, text="選取圖片", command=self.choose).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 8)); row += 1
        row = self._combo(controls, row, "目標", "type", ("custom", "events", "login"))
        row = self._entry(controls, row, "Event", "event")
        row = self._combo(controls, row, "Fit", "fit", ("cover", "contain", "stretch"))
        row = self._combo(controls, row, "Dither", "dither", ("floyd-steinberg", "atkinson", "bayer4", "threshold"))
        row = self._scale(controls, row, "Threshold", "threshold", 0, 255)
        row = self._scale(controls, row, "Focus X", "focus_x", 0, 1, .01)
        row = self._scale(controls, row, "Focus Y", "focus_y", 0, 1, .01)
        ttk.Checkbutton(controls, text="反相", variable=self.vars["invert"], command=self.refresh).grid(row=row, column=0, columnspan=2, sticky="w"); row += 1
        ttk.Separator(controls).grid(row=row, column=0, columnspan=2, sticky="ew", pady=8); row += 1
        row = self._entry(controls, row, "裝置", "device")
        ttk.Button(controls, text="掃描 LAN", command=self.scan).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6)); row += 1
        row = self._entry(controls, row, "帳號", "username")
        row = self._entry(controls, row, "密碼", "password", show="•")
        row = self._entry(controls, row, "檔名", "name")
        ttk.Checkbutton(controls, text="允許覆寫", variable=self.vars["overwrite"]).grid(row=row, column=0, sticky="w")
        ttk.Checkbutton(controls, text="上傳後預覽", variable=self.vars["preview"]).grid(row=row, column=1, sticky="w"); row += 1
        actions = ttk.Frame(controls); actions.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(actions, text="儲存 .bin", command=self.save).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(actions, text="轉檔並上傳", command=self.upload).pack(side="left", fill="x", expand=True, padx=(4, 0))
        controls.columnconfigure(1, weight=1)

        preview_grid = ttk.Frame(preview)
        preview_grid.pack(fill="both", expand=True)
        preview_grid.columnconfigure(0, weight=1)
        preview_grid.columnconfigure(1, weight=1)
        preview_grid.rowconfigure(1, weight=1)
        ttk.Label(preview_grid, text="原圖", anchor="center").grid(row=0, column=0, sticky="ew")
        ttk.Label(preview_grid, text="1-bit", anchor="center").grid(row=0, column=1, sticky="ew")
        self.original_label = ttk.Label(preview_grid, text="No image", anchor="center")
        self.original_label.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        self.preview_label = ttk.Label(preview_grid, text="No image", anchor="center")
        self.preview_label.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        ttk.Label(preview, textvariable=self.vars["status"], anchor="w").pack(fill="x", pady=(8, 0))
        for key in ("type", "event", "fit", "dither", "threshold", "focus_x", "focus_y"):
            self.vars[key].trace_add("write", lambda *_: self.after_idle(self.refresh))

    def _entry(self, parent, row, label, key, **kwargs):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Entry(parent, textvariable=self.vars[key], **kwargs).grid(row=row, column=1, sticky="ew", pady=3)
        return row + 1

    def _combo(self, parent, row, label, key, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        ttk.Combobox(parent, textvariable=self.vars[key], values=values, state="readonly").grid(row=row, column=1, sticky="ew", pady=3)
        return row + 1

    def _scale(self, parent, row, label, key, start, end, resolution=1):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=3)
        tk.Scale(parent, variable=self.vars[key], from_=start, to=end, resolution=resolution, orient="horizontal", showvalue=True).grid(row=row, column=1, sticky="ew")
        return row + 1

    def options(self):
        return ConversionOptions(
            target=self.vars["type"].get(), fit=self.vars["fit"].get(), dither=self.vars["dither"].get(),
            threshold=self.vars["threshold"].get(), invert=self.vars["invert"].get(),
            focus_x=self.vars["focus_x"].get(), focus_y=self.vars["focus_y"].get(),
        )

    def choose(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.webp")])
        if not path:
            return
        self.source_path = Path(path)
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", self.source_path.stem).strip("_") or "image"
        self.vars["name"].set(name[:48] + ".bin")
        with Image.open(self.source_path) as source:
            original = ImageOps.exif_transpose(source).convert("RGB")
        original.thumbnail((300, 500))
        self.original_photo = ImageTk.PhotoImage(original)
        self.original_label.configure(image=self.original_photo, text="")
        self.refresh()

    def refresh(self):
        if not self.source_path:
            return
        try:
            self.result = convert_image(self.source_path, self.options())
            preview = self.result.preview.copy()
            preview.thumbnail((620, 520))
            self.preview_photo = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_photo, text="")
            self.vars["status"].set(f"{self.result.width}×{self.result.height} / {len(self.result.data)} bytes")
        except Exception as exc:
            self.vars["status"].set(str(exc))

    def save(self):
        if not self.result:
            messagebox.showwarning("尚未轉檔", "請先選取圖片。")
            return
        path = filedialog.asksaveasfilename(defaultextension=".bin", initialfile=self.vars["name"].get(), filetypes=[("BIN", "*.bin")])
        if path:
            save_bin(path, self.result.data)
            self.vars["status"].set("已儲存 " + path)

    def scan(self):
        self.vars["status"].set("正在掃描 LAN…")
        def work():
            try:
                devices = discover()
                self.after(0, lambda: self._scan_done(devices))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("掃描失敗", str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self, devices):
        if devices:
            self.vars["device"].set(devices[0].host)
            self.vars["status"].set("找到 " + ", ".join(item.host for item in devices))
        else:
            self.vars["status"].set("未找到裝置；可手動輸入 IP 或使用 192.168.4.1")

    def upload(self):
        if not self.result or not self.source_path:
            messagebox.showwarning("尚未轉檔", "請先選取圖片。")
            return
        local_path = self.source_path.with_suffix(".bin")
        save_bin(local_path, self.result.data)
        data = self.result.data
        device = self.vars["device"].get()
        username = self.vars["username"].get()
        password = self.vars["password"].get()
        collection = self.vars["type"].get()
        filename = self.vars["name"].get()
        event = self.vars["event"].get()
        overwrite = self.vars["overwrite"].get()
        preview = self.vars["preview"].get()
        self.vars["status"].set("上傳中…")
        def progress(sent, total):
            self.after(0, lambda: self.vars["status"].set(f"上傳中 {sent}/{total} bytes"))
        def work():
            try:
                client = DeviceClient(device, username, password)
                response = client.upload(data, collection, filename, event, overwrite, preview, progress)
                self.after(0, lambda: self.vars["status"].set("上傳完成；本地保留 " + str(local_path)))
                self.after(0, lambda: messagebox.showinfo("完成", "圖片已上傳到 " + response.get("path", "device")))
            except Exception as exc:
                self.after(0, lambda exc=exc: messagebox.showerror("上傳失敗", str(exc)))
        threading.Thread(target=work, daemon=True).start()


def run_gui():
    PicoImageTool().mainloop()
