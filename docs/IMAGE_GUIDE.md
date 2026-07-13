# 圖片資產與轉換

本文件說明 repository 內的圖片資產與桌面轉檔工具；HTTP 上傳、認證、交易寫入與位元排列請以 [`IMAGE_API.md`](IMAGE_API.md) 為準。

## 資產目錄

所有裝置圖片位於 `src/image/`，使用無檔頭 1-bit bitmap：

| 路徑 | 用途 | 尺寸 |
|---|---|---:|
| `custom/` | 一般輪播圖片 | 128 × 128 |
| `events/birthday/` | 生日圖片 | 128 × 128 |
| `events/MMDD/` | 特定日期圖片，例如 `events/1225/` | 128 × 128 |
| `login/` | 啟動與連線過渡畫面 | 296 × 128 |
| `weather_icons/` | OpenWeatherMap 天氣圖示 | 32 × 32 |

事件資料夾使用四位數 `MMDD`；檔名使用 `.bin`。Weather icons 是系統資產，不透過圖片 API 修改。

## GUI 與 CLI

GUI 入口：

```powershell
.\.venv\Scripts\python.exe tools\image_to_bin.py
```

CLI 範例：

```powershell
.\.venv\Scripts\python.exe tools\pico_image_cli.py discover
.\.venv\Scripts\python.exe tools\pico_image_cli.py convert photo.png --type custom
.\.venv\Scripts\python.exe tools\pico_image_cli.py upload photo.png --device 192.168.1.50 --type custom --preview
.\.venv\Scripts\python.exe tools\pico_image_cli.py upload holiday.png --device 192.168.1.50 --type events --event 1225
```

工具支援 Floyd–Steinberg、Atkinson、Bayer 4x4、固定 threshold，以及 `cover`、`contain`、`stretch` 縮放策略；透明圖會先合成白底並套用 EXIF 方向。GUI/CLI 預設在原圖旁保留 `.bin`，方便在裝置清理後重新部署。

## 格式與部署注意事項

新工具與圖片 API 使用 canonical `MONO_HLSB`：每個 packed byte 的 bit 0 是最左側像素。工具與 API 會建立 `.hlsb` sidecar；使用 `upload.py` 或手動複製時，必須連同 sidecar 部署。沒有 marker 的既有資產仍按舊版 MSB-left 解碼，不需要批次重轉。

圖片 API 目前支援 custom、login、events 三個 collection，尺寸與 byte length 請見 [`IMAGE_API.md`](IMAGE_API.md)。
