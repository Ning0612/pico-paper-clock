# 安裝、部署與 AP 設定

本文件描述從主機環境到 Pico W 的完整使用流程。`README.md` 只保留快速開始；設定欄位本身以 [`CONFIG_GUIDE.md`](CONFIG_GUIDE.md) 為準。

## 主機環境

專案主機工具使用 Python 3.11+ 與專案 `.venv`。PowerShell 執行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

執行主機測試或工具時都使用 `.venv` 裡的 Python，不要改用全域 Python。

## 安裝 MicroPython

1. 從 [MicroPython Pico W 下載頁](https://micropython.org/download/RPI_PICO_W/) 下載 `.uf2`；已驗證的版本也可能放在 [GitHub Releases](https://github.com/Ning0612/pico-paper-clock/releases)。
2. 按住 Pico W 的 `BOOTSEL`，再以 USB 接上電腦。
3. 將 Pico 顯示的 `RPI-RP2` 磁碟機開啟，把 `.uf2` 拖入其中。
4. 等待裝置自動重啟。

## 準備設定

`src/config.json` 可能含有 Wi-Fi 密碼與 API secret，已被 `.gitignore` 忽略。第一次使用時建立本地設定檔：

```powershell
if (!(Test-Path src\config.json)) { Copy-Item src\config.json.example src\config.json }
```

再編輯 `src/config.json`，至少填入一個 profile 的 Wi-Fi 設定；Weather API Key 為需要顯示天氣時的必要設定。完整 schema、數值範圍與 secret 欄位請見 [`CONFIG_GUIDE.md`](CONFIG_GUIDE.md)。

## 上傳韌體檔案

`upload.py` 需要 `mpremote`，會上傳 `src/` 中的 Python/JSON、圖片與目錄，完成後重啟裝置並開啟互動式 REPL：

```powershell
.\.venv\Scripts\python.exe upload.py --port COM7 --no-clean
```

常用參數：

| 參數 | 用途 |
|---|---|
| `--port COM7` | 指定 Pico W 序列埠；未指定時由 `mpremote` 自動偵測 |
| `--no-images` | 不上傳圖片 |
| `--no-config` | 不上傳也不刪除裝置上的 `config.json` |
| `--no-clean` | 跳過部署前清理 |
| `--recursive-clean` | 遞迴刪除裝置檔案與目錄後再部署 |

`--recursive-clean` 會刪除只存在裝置上的網路上傳圖片，除非已完成備份，否則不要使用。REPL 中按 `Ctrl+X` 離開。

## AP 模式設定

裝置在找不到任何已知 Wi-Fi 時會自動進入 AP 模式。正常運作時長按任一 HAT 按鈕約 3 秒，也會要求重啟並進入 AP 模式；這不會刪除 profile。

1. 查看電子紙顯示的 AP SSID、密碼與 IP。預設 IP 是 `192.168.4.1`，預設 SSID/密碼是 `Pi_Clock_AP` / `12345678`。
2. 用手機或電腦連線到該 AP。
3. 開啟 `http://192.168.4.1`。
4. 在設定頁選取或建立 profile，填入 Wi-Fi SSID、密碼、天氣地點、時區、光感門檻與響聲設定。
5. 按下儲存並重啟；裝置會將該 profile 設為 active profile。

AP 頁面也提供圖片庫、在席統計與完全重置入口。LAN 模式的設定與圖片管理受認證保護；不要把裝置服務暴露在不可信任的網路。

![AP Mode Web UI](../AP_Mode_DEMO.png)

## Web UI 建置

修改 AP 頁面時，只編輯 `tools/html_src/`，再生成裝置使用的 `.bin`：

```powershell
.\.venv\Scripts\python.exe tools\build_html.py
```

不要直接編輯 `src/html/*.bin`。完整 Web UI 工作流程另見專案的 `build-web-ui` skill。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m compileall tools tests upload.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

部署後應在 Pico W 上確認能顯示時間、連線天氣、讀取 DHT22/LDR，並可從 AP 或 LAN 頁面完成設定。
