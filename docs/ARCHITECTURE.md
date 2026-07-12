# 架構與資料夾地圖

## 裝置資料流

```text
main.py
  └─ AppController
       ├─ HardwareManager / PresenceManager
       ├─ ConfigManager（config.json，交易式 tmp/bak）
       ├─ ImageStore + ImageCatalog（串流列舉、輪播、預覽佇列）
       ├─ DisplayManager → RotatedCanvas90 → EPD_2in9
       └─ LanConfigServer / AP web server → wifi_manager dispatcher
```

啟動時先復原設定與圖片交易檔，再建立顯示與網路服務。LAN 與 AP 共用路由；AP 額外保留按鈕長按、閒置 timeout、profile fallback 與 reboot 工作。

## 記憶體邊界

- 顯示使用一份 native `128 × 296` framebuffer，透過 rotated canvas 提供原本的 `296 × 128` 邏輯座標。
- 圖片以固定列 buffer 讀取；網路上傳以 512-byte buffer 串流，不把整張圖片載入 RAM。
- SPI 傳送使用 buffer write，避免逐 byte 建立暫時物件。
- 長生命週期 controller、presence、image store/catalog 使用 `__slots__`。
- `/api/v1/device` 的 `heap_free` 可作為現場基線；完整 peak／長跑數據仍需接上指定 Pico 後量測。

## 圖片格式與相容性

- 新工具與圖片 API 的 canonical payload 是無檔頭 `MONO_HLSB`，每個 byte 的 bit 0 是最左像素。
- API 上傳與桌面工具保存會建立 `.hlsb` sidecar。
- 沒有 marker 的既有 repository／舊版 runtime `.bin` 仍按 MSB-left 解碼，避免升級時破壞既有圖片。
- `custom`／`events` 為 `128 × 128`、2048 bytes；`login` 為 `296 × 128`、4736 bytes。

## HTTP 邊界

- `/api/v1/device` 可匿名讀取，圖片變更操作需要 LAN Admin Basic Auth 與 `X-Pico-Clock-API: 1`。
- 設定頁與圖片頁在 LAN 需要 Basic Auth；AP 模式沿用同一 dispatcher。
- body 只接受單一 `Content-Length`，拒絕重複長度與 `Transfer-Encoding`。
- request 有總讀取 deadline；Pico W 正常圖片串流使用 8 秒上限。
- 圖片寫入採 `.part`、`.bak` 與 marker transaction，開機會復原未完成狀態。

## 資料夾地圖

| 路徑 | 用途 | 維護規則 |
|---|---|---|
| `src/` | MicroPython firmware | 不使用 CPython-only API |
| `src/image/` | 裝置圖片資產 | 保留既有圖片；API runtime 圖片由裝置管理 |
| `src/html/` | 生成後的 Web UI `.bin` | 由 `tools/html_src/` 建置 |
| `tools/html_src/` | 可讀 HTML/CSS/JS 來源 | UI 修改只改這裡 |
| `tools/pico_image_tool/` | 轉檔、抖動、client、GUI、CLI | 主機端 Python |
| `tests/` | 主機回歸與協議測試 | 使用專案 `.venv` |
| `docs/` | 長期文件與契約 | API／設定／架構同步更新 |
| `hardware/` | CAD、STL 與外殼檔案 | 不因程式整理刪除 |
| `firmware/` | Pico UF2 | 依硬體版本管理 |

## 部署與驗證

```powershell
.\.venv\Scripts\python.exe tools\build_html.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe upload.py --port COM6 --no-clean
```

桌面 EXE 由 `tools/build_image_tool.ps1` 建置。若使用 `--recursive-clean`，部署前要先保存裝置上只有 runtime 的圖片。
