# 圖片資產與轉換

本文件說明 repository 內的圖片資產與桌面轉檔工具；HTTP 上傳、認證、交易寫入與位元排列請以 [`IMAGE_API.md`](IMAGE_API.md) 為準。

## 資產目錄

所有裝置圖片位於 `src/image/`，以 1-bit bitmap 儲存。新工具會在 PPC1 壓縮後較小時使用壓縮格式；無法縮小時才保留 raw payload：

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

工具支援 Floyd–Steinberg、Atkinson、Bayer 4x4、固定 threshold，以及 `cover`、`contain`、`stretch` 縮放策略；透明圖會先合成白底並套用 EXIF 方向。GUI/CLI 預設在原圖旁保留 PPC1 `.bin`，方便在裝置清理後重新部署。

## 格式與部署注意事項

raw payload 的 canonical `MONO_HLSB` 是每個 packed byte 的 bit 0 代表最左側像素。PPC1 header 會自行保存 bit order，裝置以 256-byte history、512-byte input buffer 與 row buffer 逐列解壓，不會配置整張圖片。

- raw 圖片會使用 `.hlsb` sidecar 標記 HLSB；沒有 marker 的既有 raw 資產仍按舊版 MSB-left 解碼。
- PPC1 檔案仍使用 `.bin` 副檔名，不需要 sidecar；`upload.py` 會直接部署 payload。

圖片 API 目前支援 custom、login、events 三個 collection，尺寸與 byte length 請見 [`IMAGE_API.md`](IMAGE_API.md)。
