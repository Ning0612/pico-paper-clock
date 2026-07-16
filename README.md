# Pico Paper Clock

[![CI](https://github.com/Ning0612/pico-paper-clock/actions/workflows/ci.yml/badge.svg)](https://github.com/Ning0612/pico-paper-clock/actions/workflows/ci.yml)
[![MicroPython](https://img.shields.io/badge/MicroPython-1.22+-blue.svg)](https://micropython.org/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Hardware](https://img.shields.io/badge/Hardware-Raspberry%20Pi%20Pico%20W-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-pico-w/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

基於 Raspberry Pi Pico W 與 Waveshare 2.9 吋觸控電子紙的 IoT 時鐘。它定位成放在書桌前、低干擾常駐的小顯示器：讓人抬頭即可看到日期、時間、目前天氣、室內溫濕度與喜歡的圖片，也能透過環境光感測器估算並追蹤在書桌前的時間。裝置同時透過 Wi-Fi 提供設定、圖片管理與在席統計頁面。

![Project Demo](DEMO.jpg)

## Web UI 預覽

裝置在 AP 或 LAN 模式提供 Web UI，讓日常使用不必重新刷寫韌體即可管理顯示內容與查看書桌前活動：

- **裝置設定**：管理 Wi-Fi profile、天氣地點、圖片輪播、感測器與提示音，以及 AP 管理選項。
- **書桌前分析**：查看目前在席狀態、最近 24 小時與 30 天統計、年度熱力圖、每日紀錄和最近時段。
- **圖片庫**：瀏覽 custom、events、login 圖片，預覽或刪除裝置上的素材；圖片上傳由 Pico Image Tool 處理。

<table>
  <tr>
    <td align="center"><img src="docs/screenshots/webui/settings.png" alt="裝置設定頁" width="480"><br><sub>裝置設定</sub></td>
    <td align="center"><img src="docs/screenshots/webui/desk-analytics-overview.png" alt="書桌前分析總覽" width="480"><br><sub>書桌前分析：即時狀態與近期統計</sub></td>
  </tr>
  <tr>
    <td align="center"><img src="docs/screenshots/webui/desk-analytics-history.png" alt="書桌前分析歷史資料" width="480"><br><sub>書桌前分析：年度熱力圖與歷史紀錄</sub></td>
    <td align="center"><img src="docs/screenshots/webui/image-library.png" alt="圖片庫頁面" width="480"><br><sub>圖片庫</sub></td>
  </tr>
</table>

## 功能概覽

- NTP 時間同步、目前天氣與未來預報。
- DHT22 溫濕度與環境光感測；低光時可讓電子紙進入休眠。
- 自訂圖片輪播、生日與 `MMDD` 事件圖片、觸控切換圖片。
- 多設定檔：依 Wi-Fi SSID 自動選擇家裡、公司等不同地點的設定。
- AP/LAN Web UI：管理設定檔、圖片、在席統計與裝置狀態。
- 定時蜂鳴器提示，支援整點或每半小時響聲。

## 快速開始

### 1. 建立主機環境

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

完整部署流程、韌體安裝與疑難排解請參閱 [`docs/SETUP_GUIDE.md`](docs/SETUP_GUIDE.md)。

### 2. 準備設定並部署

1. 將 `src/config.json.example` 複製為未納入 Git 的 `src/config.json`，填入 Wi-Fi、Weather API Key 與其他設定。
2. 將 Pico W 以 USB 接上電腦，確認已安裝 MicroPython 與 `mpremote`。
3. 執行部署（將 `COM7` 換成實際序列埠）：

   ```powershell
   .\.venv\Scripts\python.exe tools\pico_deploy\upload_cli.py --port COM7 --no-clean
   ```

4. 啟動後若無法連上已知 Wi-Fi，裝置會建立 AP；連線至螢幕顯示的 SSID，再開啟 `http://192.168.4.1` 完成設定。

`tools\pico_deploy\upload_cli.py` 會在完成後重啟裝置並進入 REPL；按 `Ctrl+X` 離開。`--recursive-clean` 會刪除裝置上只存在於 runtime 的檔案與圖片，使用前請先備份。

`tools\pico_deploy\upload_cli.py` 是無 GUI 的 headless USB 部署入口；根目錄 `upload.py` 只保留作為相容 wrapper，一般 Windows 使用者可改用 Release 的 `PicoPaperClockTool` GUI。

## 硬體

必要元件為 Raspberry Pi Pico W、[Waveshare 2.9inch Touch e-Paper HAT](https://www.waveshare.net/wiki/Pico-CapTouch-ePaper-2.9)、LDR、DHT22、無源蜂鳴器與連接線。完整 pin map、接線圖與注意事項請見 [`docs/HARDWARE.md`](docs/HARDWARE.md)。

可選的 3D 外殼 CAD 檔案不放在 source tree；STEP 適合一般 CAD 編輯、STL 適合列印、SLDPRT 適合 SolidWorks 使用者，下載方式請見 [`docs/RELEASE_ASSETS.md`](docs/RELEASE_ASSETS.md)。

## 使用與設定

- 長按任一實體按鈕約 3 秒可要求裝置重啟並進入 AP 設定模式；不會刪除設定檔。
- AP 頁面可新增、編輯、刪除與切換設定檔；完整欄位、範圍、遷移與重置說明請見 [`docs/CONFIG_GUIDE.md`](docs/CONFIG_GUIDE.md)。
- 自訂圖片的資料夾、尺寸、事件命名與 GUI/CLI 用法請見 [`docs/IMAGE_GUIDE.md`](docs/IMAGE_GUIDE.md)。
- 圖片 HTTP API、認證要求與 `MONO_HLSB` 格式請見 [`docs/IMAGE_API.md`](docs/IMAGE_API.md)。
- Windows 使用者可下載 Release 的 `PicoPaperClockTool` EXE；序列部署時在 GUI 選擇含有 `src/` 的 repository/source zip，掃描序列埠後用選單選擇 Pico，部署前可在 Tree 檢視 manifest；LAN/AP 掃描結果也可選取，圖片批次上傳則可直接選取本機圖片。WebUI 帳號固定為 `admin`。

完全重置會刪除所有設定檔，必須在 AP 頁面的危險區域輸入 `RESET` 確認；這項操作無法復原。

## 開發與文件

```powershell
.\.venv\Scripts\python.exe tools\build_html.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 會在 `main` push、pull request 與手動觸發時，以 Python 3.11/3.12 執行依賴安裝、HTML 生成物檢查、`compileall` 與 unittest。HTML 原始碼在 `tools/html_src/`，生成的 `src/html/*.bin` 不應手動編輯。專案資料流、記憶體限制與資料夾地圖請見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，所有文件入口在 [`docs/README.md`](docs/README.md)。

桌面工具可由 source tree 建置：

```powershell
.\tools\build_pico_deploy_tool.ps1
```

輸出為 `dist\PicoPaperClockTool.exe`。建置與下載方式、序列部署安全選項及圖片批次流程請見 [`docs/IMAGE_GUIDE.md`](docs/IMAGE_GUIDE.md)。

## 授權與第三方資產

原創 source code 採用 [MIT License](LICENSE)。Waveshare 驅動與 weather-icons 圖示的授權邊界請見 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) 與 [`ASSET_CREDITS.md`](ASSET_CREDITS.md)。
