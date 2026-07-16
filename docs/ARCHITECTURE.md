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

啟動時先連線、同步 NTP 時間並嘗試發送 Discord LAN IP 通知；在載入控制器、顯示與感測器工作路徑前，會利用低記憶體窗口 flush pending Discord queue，再復原圖片交易檔並建立 LAN server。LAN 與 AP 共用路由；AP 額外保留按鈕長按、閒置 timeout、profile fallback 與 reboot 工作。

## 記憶體邊界

- 顯示使用一份 native `128 × 296` framebuffer，透過 rotated canvas 提供原本的 `296 × 128` 邏輯座標。
- 顯示更新會重用 native framebuffer、rotated canvas、字型 glyph buffer 與常用圖片列 buffer；避免每次刷新重新配置約 4.7 KB framebuffer 與重複的小型暫存物件。進入一般 Discord 網路傳送前會釋放大型 display workspace，保留 TLS 所需的連續 heap 空間。
- 圖片以固定列 buffer 讀取；網路上傳以 512-byte buffer 串流，不把整張圖片載入 RAM。
- SPI 傳送使用 buffer write，避免逐 byte 建立暫時物件。
- 長生命週期 controller、presence、image store/catalog 使用 `__slots__`。
- Discord webhook 不使用 `urequests.Response` 路徑，改用 raw `ssl` socket：只建立固定大小的 HTTP headers/payload、處理 partial write、讀取 status line 後立即關閉 socket；送出前後執行 `gc.collect()`，並暫時調整 GC threshold 後恢復原值。NTP 會在第一次 TLS 呼叫前同步；目前 firmware tree 尚未附帶 CA trust anchor，因此此連線仍不能宣稱完成憑證鏈／hostname 驗證，正式部署前需補上 CA bundle，不能以不驗證的 TLS 取代。
- Discord JSON payload 以單一 `bytearray` 組裝，避免字串串接時留下額外完整 payload copy；Discord socket 在建立與 TLS 前會記錄 heap free/allocated telemetry。
- 啟動通知與 pending Discord queue 在 `main.py` 的低依賴啟動階段先執行，避開 controller/weather 後續模組 import 與 display/hardware 工作物件建立造成的 heap 碎片；第一次失敗不阻塞主程式，controller 會在 45 秒後、每 30 秒重試，pending queue 則保留到下一次可用窗口。
- Discord `ENOMEM` 會回傳可重試結果；presence queue 在記憶體壓力後暫停一個 flush interval，之後自動恢復嘗試，不丟棄 pending session/summary。
- DHT22 使用 2500 ms 最小讀取間隔；讀取失敗改用 10 秒 backoff，保留上一筆快取值，避免感測器錯誤反覆消耗 heap 與刷 serial log。
- 天氣預報使用 256-byte 固定串流 buffer 與 `readinto()`，逐筆解析 forecast entry；response、entry 暫存物件在處理後釋放並回收，避免一次載入完整 JSON 文件。
- 天氣 request 前、response 取得後與 forecast parse 後會記錄 heap telemetry；forecast 優先直接解析 bytes，只有 MicroPython 相容性需要時才 fallback 到 decode。Presence API 的記憶體讀取介面只保留最近 128 筆事件與 366 筆 daily lines，且單行最多讀取 256 字元；完整串流 API 仍逐行送出。
- `/api/v1/device` 的 `heap_free` 可作為現場基線；完整 peak／長跑數據仍需接上指定 Pico 後量測。

### 記憶體問題的處理原則

```text
啟動 Wi-Fi
  └─ raw HTTPS Discord webhook
       ├─ 成功：記錄已送出，釋放 socket
       └─ ENOMEM：保留可重試狀態，不阻塞主迴圈
            ↓
載入 display / HardwareManager / AppController
  └─ 天氣 forecast 以固定 buffer 串流解析
  └─ DHT22 依時間節流，失敗使用 backoff 與快取
```

這些策略的目標是降低「單次配置峰值」與重複配置頻率，而不是宣稱裝置 heap 永遠不會耗盡。現場診斷應同時查看 serial 的 `ENOMEM`、`Memory before/after ...` telemetry、DHT22 錯誤與 `/api/v1/device` 的 `heap_free`。

## 圖片格式與相容性

- raw 圖片 payload 的 canonical 格式是 `MONO_HLSB`，每個 byte 的 bit 0 是最左像素；新工具會優先寫入 PPC1 壓縮格式。
- PPC1 header 保存 bit order，裝置透過 256-byte history、512-byte input buffer 與既有 row buffer 逐列解壓，不把整張圖片載入 RAM。
- raw API 上傳與桌面工具保存會建立 `.hlsb` sidecar；PPC1 不需要 sidecar。
- 沒有 marker 的既有 repository／舊版 runtime raw `.bin` 仍按 MSB-left 解碼，避免升級時破壞既有圖片。
- `custom`／`events` 為 `128 × 128`、2048 bytes；`login` 為 `296 × 128`、4736 bytes。

## HTTP 邊界

- `/api/v1/device` 可匿名讀取；圖片與設定 API 在完成首次設定後需要 WebUI server-side 單一 session、CSRF token，圖片變更另需 `X-Pico-Clock-API: 1`。
- 設定頁、圖片頁、儀表板與感測資料在 LAN/AP 共用同一 session dispatcher；首次出廠 AP 允許完成首次密碼設定，之後即要求 session。
- session 使用 128-bit CSPRNG token、idle 30 分鐘／absolute 24 小時 monotonic timeout；重開機、登出與密碼變更會撤銷 session。管理密碼以 PBKDF2-HMAC-SHA256 儲存。
- 管理介面仍是 HTTP；請限制在可信任的隔離 LAN/AP，因 HTTP 無法防止 session token 被同網段攔截重放。
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
| `dist/release-assets/` | 本地發布暫存的 UF2、STEP、STL 與 `.SLDPRT` | 已被 Git 忽略；建立 Release 時手動附加；不放回 source tree |

## 部署與驗證

```powershell
.\.venv\Scripts\python.exe tools\build_html.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe upload.py --port COM6 --no-clean
```

本次記憶體路徑的最低驗證包括 host tests、`compileall`、`git diff --check`，以及 Pico W serial 中的 `Success: Discord LAN IP notification sent.`、DHT22 讀值與天氣請求成功。完整 peak heap 仍應以實際硬體長跑資料為準。

桌面 EXE 由 `tools/build_image_tool.ps1` 建置。若使用 `--recursive-clean`，部署前要先保存裝置上只有 runtime 的圖片。
