# 圖片資產與轉換

本文件說明 repository 內的圖片資產、整合式桌面上傳工具與批次流程；HTTP 上傳、認證、交易寫入與位元排列請以 [`IMAGE_API.md`](IMAGE_API.md) 為準。

## 資產目錄

所有裝置圖片位於 `src/image/`，以 1-bit bitmap 儲存。新工具一律輸出帶 PPC1 header 的 `.bin`；即使壓縮後稍大，也不會產生 `.bin.hlsb` sidecar：

| 路徑 | 用途 | 尺寸 |
|---|---|---:|
| `custom/` | 一般輪播圖片 | 128 × 128 |
| `events/birthday/` | 生日圖片 | 128 × 128 |
| `events/MMDD/` | 特定日期圖片，例如 `events/1225/` | 128 × 128 |
| `login/` | 啟動與連線過渡畫面 | 296 × 128 |
| `weather_icons/` | OpenWeatherMap 天氣圖示 | 32 × 32 |

事件資料夾使用四位數 `MMDD`；檔名使用 `.bin`。Weather icons 是系統資產，不透過圖片 API 修改。

## 整合 GUI 與 CLI

GUI 入口：

```powershell
.\.venv\Scripts\python.exe tools\pico_image_cli.py gui
```

GUI 由 `tools/pico_deploy/` 提供，分成序列部署、圖片批次與作業佇列；圖片轉檔與 WebUI client 仍由 `tools/pico_image_tool/` 提供。序列部署前請在「工作階段連線」選擇含有 `src/` 的專案目錄，按「掃描序列埠」後從下拉選單選擇 Pico；Release 的 Windows EXE 不會把客製設定與資源硬編進工具，因此也必須選擇 repository 或 GitHub source zip 解壓後的目錄。

WebUI 登入帳號固定為 `admin`，GUI 只要求輸入暫存於本次工作階段的管理密碼。按「掃描 LAN」會先探測目前欄位中的位址，再查 Windows ARP 快取，最後補掃本機 IPv4 `/24` 網段與預設 AP 位址；即使 Pico 尚未出現在 ARP 快取，也能透過網段掃描找到。掃描結果會放入 LAN/AP 位址選單，也可以手動輸入 IP。序列部署的預設行為是保守模式：預設不清理裝置、不覆寫 `config.json`，並在加入佇列前以 Tree 顯示本機路徑、遠端路徑、分類、檔案大小與總大小。遞迴清理會刪除裝置上未保存在本機的檔案，只有在明確勾選 config 並確認警告後才能使用。

圖片批次清單的每一項可獨立設定 collection、event、檔名、fit、dither、threshold、反相、覆寫與上傳後預覽。圖片會先在本機旁保存 PPC1 `.bin`，再以已登入的 WebUI session 上傳。

「完整同步」是額外的作業 macro：先完成 USB 資源部署並重啟，接著以 LAN/AP 位址輪詢裝置最多 60 秒，恢復連線後才執行圖片佇列；網路恢復失敗時會停止並保留未執行圖片。

Windows EXE 建置：

```powershell
.\tools\build_pico_deploy_tool.ps1
```

輸出 `dist\PicoPaperClockTool.exe`。也可直接使用 Python/CLI，不需要 PyInstaller。

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

- 新工具產生的 `.bin` 一律是 PPC1，header 會保存 HLSB bit order，不需要 sidecar；`tools/pico_deploy/upload_cli.py` 只部署 `.bin`。
- 韌體仍可讀取既有 raw `.bin` 與 `.bin.hlsb` 相容資產；這些舊資產需轉換成 PPC1 後才能符合「只有 `.bin`」的檔案規則。

圖片 API 目前支援 custom、login、events 三個 collection，尺寸與 byte length 請見 [`IMAGE_API.md`](IMAGE_API.md)。
