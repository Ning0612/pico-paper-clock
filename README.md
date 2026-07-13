# Pico Paper Clock - 基於 Pico W 與 E-Paper 的 IoT 時鐘

[![MicroPython](https://img.shields.io/badge/MicroPython-1.22+-blue.svg)](https://micropython.org/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Hardware](https://img.shields.io/badge/Hardware-Raspberry%20Pi%20Pico%20W-red.svg)](https://www.raspberrypi.com/products/raspberry-pi-pico-w/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

本專案是一個基於 Raspberry Pi Pico W 和 Waveshare 2.9 吋電子紙顯示器的 IoT 智慧時鐘。它不僅能顯示時間，還能連接網路獲取天氣資訊、輪播自訂圖片，並具備光線感應與觸控功能。

![Project Demo](DEMO.jpg)

---

## ✨ 主要功能

- **即時天氣顯示**：自動從網路獲取並顯示指定地點的天氣狀況與預報資訊，包含當前天氣圖示、溫度及未來 3 日天氣預報。
- **本地溫濕度監測**：透過 DHT22 感測器（連接於 GPIO 19）即時讀取並顯示室內環境溫度與濕度，數據每分鐘更新一次，提供精確的本地環境監測（溫度精度 ±0.5°C，濕度精度 ±2%）。本地資料與網路天氣資料並列顯示，讓您同時掌握室內外環境狀況。
- **時間與日期顯示**：透過 NTP 協定自動同步網路時間，確保時間精準。
- **自訂圖片輪播**：可依設定的時間間隔，輪播 `src/image/custom` 資料夾中的圖片。
- **特殊事件圖片**：在特定日期（如生日或自訂日期）顯示專屬的慶祝圖片，並支援觸控切換。
- **載入頁面圖片隨機顯示**：裝置啟動時，載入頁面的圖片將隨機顯示，增加趣味性。
- **網路圖片管理**：LAN/AP 模式提供版本化圖片 API 與 `/images` 管理頁；桌面 Pico Image Tool 可完成轉檔、LAN 掃描、上傳、覆寫及立即預覽。
- **環境光感測**：在光線昏暗時自動關閉螢幕，節省電力並避免夜間光害。
- **觸控與按鈕操作**：透過點擊電子紙螢幕進行互動（如切換圖片）。**長按任一實體按鈕 5 秒可進入 AP 設定模式**，方便隨時調整設定。
- **定時響聲功能**：可設定整點或每半小時透過蜂鳴器發出提示音，音調與音量可調整。
- **🆕 多設定檔支援 (v2.0)**：
  - **多地點設定**：支援建立多個設定檔，每個設定檔對應不同地點（如家裡、公司、咖啡廳）。
  - **智能自動切換**：系統會自動掃描網路並根據 WiFi SSID 切換到對應的設定檔。
  - **獨立設定**：每個設定檔可設定專屬的天氣地點、光感臨界值、圖片間隔、響聲設定等。
  - **優先連接邏輯**：優先嘗試上次成功連接的設定檔，其他按信號強度排序。
- **AP 模式設定**：當無法連接 Wi-Fi 或透過長按按鈕進入設定模式時，系統會啟用 AP 模式。
  - **網頁介面**：讓使用者透過手機或電腦連線至裝置 (`http://192.168.4.1`)，管理多個設定檔。
  - **設定檔管理**：可新增、編輯、刪除設定檔，切換活動設定檔。
  - **完全重置功能**：透過網頁介面可執行完全重置（需輸入確認文字 `RESET`），恢復出廠設定。
  - **動態超時**：網頁設定期間若有操作，會自動延長等待時間；超時後使用最後連接的設定檔並重啟。
  - **快速進入**：在 AP 模式下長按按鈕會重啟系統並再次進入 AP 模式。
- **穩定性與錯誤處理**：強化了網路連線、API 請求（包含重試機制）及圖片載入的錯誤處理，確保系統在異常情況下仍能穩定運行。

---

## 🛠️ 硬體需求

1.  **Raspberry Pi Pico W** - 內建 Wi-Fi 的主控制器。
2.  **[Waveshare 2.9inch Touch e-Paper HAT](https://www.waveshare.net/wiki/Pico-CapTouch-ePaper-2.9)** - 296x128 解析度，支援觸控的電子紙模組。
3.  **光敏電阻 (Photoresistor)** - 用於偵測環境亮度，連接至 Pico 的 ADC Pin 26 引腳。
4.  **DHT22 溫濕度感測器** - 用於監測環境溫度與濕度，連接至 Pico 的 GPIO 19 引腳。
5.  **無源蜂鳴器 (Passive Buzzer)** - 連接至 Pico w 的 Pin 20，用於定時響聲功能。
6.  **電子紙模組內建按鈕** - 專案使用的三顆按鈕是電子紙顯示器模組提供的，分別連接於 Pin 2, Pin 3 和 Pin 15。
7.  **連接線與麵包板** - 或直接焊接在 Pico w 板子上。
7.  **(選用) 3D 列印外殼**：外殼的 SolidWorks `.SLDPRT` 檔案隨 GitHub Release 提供，下載方式請見 [`docs/RELEASE_ASSETS.md`](docs/RELEASE_ASSETS.md)。

---

### 🔌 電路接法說明

以下為光敏電阻、DHT22 溫濕度感測器與無源蜂鳴器的建議接法：

#### 🌞 光敏電阻（LDR）

透過分壓電路方式讀取光線強度：

```
3.3V ---- 33KΩ 電阻 ----+---- GP26 (ADC 輸入腳位)
                        |
                        |
                    光敏電阻
                        |
                        |
                       GND
```

* 使用 33KΩ 電阻與光敏電阻組成電壓分壓器，將中間節點連接至 Pico 的 GP26 腳位進行 ADC 讀取。
* 光線越強，LDR 阻值越小，輸出電壓越低；反之則輸出越高。

#### 🌡️ DHT22 溫濕度感測器

```
3.3V ---- DHT22 VCC 腳位
GP19 ---- DHT22 Data 腳位 (需加 4.7KΩ~10KΩ 上拉電阻至 3.3V)
GND  ---- DHT22 GND 腳位
```

* DHT22 是數位溫濕度感測器，使用單線協定通訊。
* **重要**：Data 腳位與 VCC 之間需要加上 4.7KΩ 至 10KΩ 的上拉電阻，確保訊號穩定。
* 感測器讀取間隔建議至少 2 秒，避免過度頻繁讀取導致錯誤。
* 測量範圍：溫度 -40°C ~ 80°C (±0.5°C)，濕度 0% ~ 100% (±2%)。

#### 🔔 無源蜂鳴器

```
GP20 (PWM 輸出) ---- 無源蜂鳴器 + 腳  
GND -------------- 無源蜂鳴器 - 腳
```

* 使用 Pico 的 GP20 腳位產生 PWM 訊號，控制無源蜂鳴器發聲。
* 須搭配 `PWM` 函數控制輸出頻率與占空比，以產生不同音調與音量。

---

## 🖼️ 圖片資源說明

本專案的所有圖片資源都存放在 `src/image/` 目錄下，並使用 `.bin` 格式。您可以替換或增加這些圖片來自訂您的時鐘。

- **`image/custom/`**
  - **用途**：存放使用者自訂的輪播圖片。
  - **格式**：建議為 `128x128` 像素的 1-bit 黑白圖片。
  - **說明**：您可以將自己喜歡的圖片（如動漫、風景、迷因等）轉換後放入此處，系統會定時輪播。

- **`image/events/`**
  - **用途**：存放日期特定事件的圖片。除了 `birthday/` 子目錄用於生日圖片外，您還可以創建以 `MMDD` 格式命名的子目錄（例如 `1030` 代表 10 月 30 日），並在其中放入該日期專屬的圖片。系統會自動偵測並顯示這些圖片，並支援觸控切換。
  - **格式**：建議為 `128x128` 像素的 1-bit 黑白圖片。
  - **說明**：您可以為特定節日、紀念日或任何您想標記的日期準備專屬圖片。

- **`image/login/`**
  - **用途**：在裝置啟動、嘗試連接 Wi-Fi 時顯示的過渡畫面。
  - **格式**：建議為 `296x128` 像素的 1-bit 黑白圖片。

- **`image/weather_icons/`**
  - **用途**：顯示天氣狀況的圖示。
  - **格式**：建議為 `32x32` 像素的 1-bit 黑白圖片。
  - **說明**：檔名必須對應 OpenWeatherMap API 回傳的天氣狀況。目前專案內建的圖示檔名如下：
    - `Clear.bin`
    - `Clouds.bin`
    - `Rain.bin`
    - `Drizzle.bin`
    - `Snow.bin`
    - `Thunderstorm.bin`
    - `Tornado.bin`
    - `Squall.bin`
    - `Dust.bin`
    - `Sand.bin`
    - `Mist.bin`, `Fog.bin`
    - `Smoke.bin`, `Haze.bin`


---

## 🚀 軟體安裝與設定

### 0. 環境準備

本專案的開發環境需要 Python 3。請確保您的系統已安裝 Python 3 及 `pip`。

安裝專案所需的 Python 套件：
```bash
pip install -r requirements.txt
```

### 1. 安裝 MicroPython 韌體

- 前往 [MicroPython 官網](https://micropython.org/download/RPI_PICO_W/) 下載最新的 `.uf2` 韌體檔案。
- 對應版本發布後，也可以從本專案的 [GitHub Releases](https://github.com/Ning0612/pico-paper-clock/releases) 下載經專案驗證的版本。
- 按住 Raspberry Pi Pico W 上的 `BOOTSEL` 按鈕，同時將其連接到電腦。
- 電腦會將 Pico 識別為一個名為 `RPI-RP2` 的隨身碟。
- 將下載的 `.uf2` 韌體檔案拖曳至此隨身碟中，Pico 將自動更新並重新啟動。

### 2. 上傳專案檔案

本專案建議使用 `mpremote` 工具進行檔案上傳。

#### 安裝 mpremote
```bash
  pip install mpremote
```

專案內已包含 `upload.py` 腳本，用來自動化將專案檔案部署至 Raspberry Pi Pico W。它提供以下功能與特性：

#### ✅ 上傳檔案範圍

* 自動上傳 `src/` 目錄下的所有 `.py`、`.json` 檔案。
* 同時包含 `src/image/` 目錄中的所有 `.bin` 圖片檔案（可透過 `--no-images` 關閉）。
* 自動建立對應的遠端目錄結構（使用 `mpremote fs mkdir`）。

#### 🧹 清除功能

* 預設會先清除 Pico 上既有的 `.py` 和 `.json` 檔案，若要跳過清除步驟，可加上 `--no-clean` 參數。
* 可選擇使用 `--recursive-clean` 參數，**遞迴清除整個裝置所有檔案與資料夾**。這也會刪除只存在裝置上的網路上傳圖片，執行前請保留本地 `.bin`。

#### 🔄 上傳流程

1. 執行前先列出並刪除目標檔案（視設定而定）。
2. 建立必要目錄後，上傳所有指定檔案，並顯示進度條與檔案大小。
3. 上傳完成後，自動重啟 Pico 裝置。
4. 最後自動進入互動式 REPL 模式（按 `Ctrl+X` 退出），可用於監控 Pico w 裝置行為。

#### ▶️ 使用方式：

```bash
python upload.py
```

#### 🔧 可用參數：

| 參數                  | 說明                  |
| ------------------- | ------------------- |
| `--no-images`       | 不上傳圖片檔案             |
| `--recursive-clean` | 遞迴清除整個裝置（包含所有目錄與檔案） |
| `--no-clean`        | 跳過清除步驟              |

---


### 3. 進行裝置設定

設定裝置最方便的方式是使用 AP 模式。系統支援多設定檔管理，可為不同地點建立專屬設定。

#### a) 使用 AP 模式網頁介面 (建議方式)

**進入 AP 模式的方式：**
1. **自動進入**：當裝置無法連接到任何已知 Wi-Fi 時，會自動建立一個 Wi-Fi 熱點。
2. **手動進入**：長按電子紙模組的任一按鈕 5 秒，系統會重啟並進入 AP 模式（**不會刪除已有設定檔**）。

**設定步驟：**
- SSID 和 Password 會顯示在時鐘螢幕上（預設：`Pi_Clock_AP` / `12345678`）。
- 使用您的手機或電腦連接到此熱點。
- 打開瀏覽器，訪問 `http://192.168.4.1`。
- **左側欄**顯示所有設定檔列表，點擊可切換編輯。
- **右側主區域**可編輯當前設定檔的所有參數：
  - 設定檔名稱
  - Wi-Fi SSID 和密碼
  - 天氣地點
  - 個人化設定（生日、光感臨界值、圖片間隔、時區）
  - 定時響聲設定
  - 全局設定（Weather API Key、AP 模式 SSID/密碼）
- **設定檔管理**：
  - 點擊「➕ 新增設定檔」可建立新設定檔（會複製當前設定檔的非 WiFi 設定）
  - 點擊「🗑️ 刪除設定檔」可刪除當前設定檔（至少需保留一個）
  - 點擊「💾 儲存並重啟」會將當前設定檔設為活動設定檔並重啟
- **完全重置**：在「⚠️ 危險區域」可執行完全重置（需輸入 `RESET` 確認），刪除所有設定檔並恢復出廠設定。
- 網頁會即時顯示光感應器數值，並每 3 秒自動更新。

![AP Mode DEMO Demo](AP_Mode_DEMO.png)

#### b) 手動設定 (進階)

您也可以在電腦上預先建立設定檔再上傳。此方式適合需要自訂多個設定檔的開發者。

1.  將 `src/config.json.example` 複製一份並改名為 `src/config.json`。
2.  打開 `src/config.json` 並依據您的需求填寫。請參考 [`docs/CONFIG_GUIDE.md`](docs/CONFIG_GUIDE.md) 了解新的多設定檔格式。
3.  執行 `python upload.py`，腳本會將 `src` 目錄下的所有檔案（包含您的 `config.json`）上傳到裝置。

**注意**：如果您上傳的是舊版 config.json（v1.x 格式），系統會在首次啟動時自動轉換為新的多設定檔格式，並建立名為「預設」的設定檔。

---

## 📊 可調設定參數

從 v2.0 開始，設定參數採用新的多設定檔格式儲存在 `config.json` 中，並可透過 AP 模式網頁介面進行管理。

### 設定檔結構

```json
{
  "global": {
    "ap_mode": { "ssid": "...", "password": "..." },
    "weather_api_key": "..."
  },
  "profiles": [
    {
      "name": "設定檔名稱",
      "wifi": { "ssid": "...", "password": "..." },
      "weather_location": "...",
      "user": { ... },
      "chime": { ... }
    }
  ],
  "active_profile": "目前活動的設定檔名稱",
  "last_connected_profile": "最後連接的設定檔名稱"
}
```

### 全局設定（所有設定檔共用）

| 參數路徑                  | 說明                     | 類型   | 範例值              |
|---------------------------|--------------------------|--------|---------------------|
| `global.ap_mode.ssid`     | AP 模式 SSID             | 字串   | `"Pi_Clock_AP"`     |
| `global.ap_mode.password` | AP 模式密碼              | 字串   | `"12345678"`        |
| `global.weather_api_key`  | OpenWeatherMap API Key   | 字串   | `"your_api_key"`    |

### 設定檔專屬設定（每個設定檔獨立）

| 參數路徑                      | 說明                     | 類型   | 範例值        |
|-------------------------------|--------------------------|--------|---------------|
| `profile.name`                | 設定檔名稱               | 字串   | `"家裡"`      |
| `profile.wifi.ssid`           | Wi-Fi SSID               | 字串   | `"MyHomeWiFi"`|
| `profile.wifi.password`       | Wi-Fi 密碼               | 字串   | `"password"`  |
| `profile.weather_location`    | 天氣地點                 | 字串   | `"Taipei"`    |
| `profile.user.birthday`       | 生日日期（MMDD）         | 字串   | `"0101"`      |
| `profile.user.timezone_offset`| UTC 時間偏移（小時）     | 數字   | `8`           |
| `profile.user.light_threshold`| ADC 光感臨界值           | 整數   | `56000`       |
| `profile.user.image_interval_min` | 圖片換圖間隔（分鐘） | 整數   | `2`           |
| `profile.chime.enabled`       | 啟用定時響聲             | 布林值 | `true`        |
| `profile.chime.interval`      | 響聲間隔                 | 字串   | `"hourly"` 或 `"half_hourly"` |
| `profile.chime.pitch`         | 音調頻率（Hz）           | 整數   | `880`         |
| `profile.chime.volume`        | 音量（0~100）            | 整數   | `80`          |

**詳細說明**：請參閱 [`docs/CONFIG_GUIDE.md`](docs/CONFIG_GUIDE.md) 了解完整的設定檔格式、使用方式和最佳實踐。

**向後兼容**：舊版 config.json 會在首次啟動時自動轉換為新格式，無需手動修改。

---

## 🕹️ 使用說明

- **正常運作**：成功連上 Wi-Fi 後，裝置會自動顯示時間、天氣和輪播圖片。
- **觸控互動**：輕觸螢幕可以觸發預設的動作（例如：手動更換圖片）。
- **低光模式**：當環境光線高於 `light_threshold` 設定值時，螢幕會自動進入休眠狀態。
- **多地點使用**：
  - 啟動時系統會自動掃描網路並嘗試連接已知的 WiFi
  - 優先連接上次成功的設定檔
  - 其他設定檔按信號強度排序嘗試
  - 連接成功後自動切換到對應的設定檔
  - 每個地點的設定（光感、響聲、圖片間隔等）完全獨立
- **進入設定模式**：長按任一實體按鈕 5 秒，系統會重啟並進入 AP 模式，可管理所有設定檔（**不會刪除任何設定**）。
- **完全重置**：透過 AP 模式網頁介面的「⚠️ 危險區域」執行，需輸入 `RESET` 確認，會刪除所有設定檔並恢復出廠設定。

---

### 圖片轉換

圖片上傳 API 採無檔頭 1-bit `framebuf.MONO_HLSB`：每列水平打包，bit 0 代表每組 8 像素中最左側像素。裝置會為 API 上傳檔建立 `.hlsb` 格式 sidecar；沒有 marker 的既有 repository／舊版 runtime 圖片仍以 MSB-left 解碼，因此升級不必批次重轉。目標尺寸固定為 custom/events `128x128`、login `296x128`；weather icons 是系統資產，不開放網路修改。

圖形介面：

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

支援 Floyd–Steinberg、Atkinson、Bayer 4x4、固定 threshold，以及 cover、contain、stretch 三種縮放策略。透明圖片會先合成白底並套用 EXIF 方向。GUI/CLI 預設在原圖旁保留 `.bin`，避免裝置清理後無法復原。完整 API 請見 [`docs/IMAGE_API.md`](docs/IMAGE_API.md)。

#### 圖片處理說明（轉換原理）

* 圖片載入後依 target preset 裁切或縮放至固定尺寸。
* 接著轉為灰階並套用所選的誤差擴散、ordered dithering 或 threshold。
* 此演算法會將像素的灰階誤差擴散至周圍像素，以黑白點的排列方式模擬出灰階效果，即使是只有黑與白的 ePaper 裝置，也能呈現出較為平滑的漸層與細節。
* 最終由工具明確重新打包成 bit 0 在左的 `framebuf.MONO_HLSB`，儲存時會同時建立 `<name>.bin.hlsb` sidecar。透過 `upload.py` 部署或手動複製時必須連同 sidecar；圖片 API 則由裝置自動建立 marker。無 marker 的舊 MSB-left 資產仍可直接顯示。

---

### 專案結構

- `src/`: 主程式碼目錄。

#### 程式碼功能分解

- `src/main.py`: 程式進入點，負責初始化與協調各模組。
- `src/app_controller.py`: 應用程式主邏輯控制器，處理應用程式的核心邏輯，如觸控、按鈕事件、顯示更新等。
- `src/app_state.py`: 管理應用程式的各種狀態，例如最後更新時間、圖片偏移量、天氣資料等。
- `src/chime.py`: 定時響聲功能模組，控制蜂鳴器發出提示音。
- `src/config_manager.py`: 設定檔讀寫管理，提供統一的設定存取介面，處理 `config.json` 的載入與儲存。
- `src/display_manager.py`: 顯示邏輯管理，負責畫面繪製與更新，根據應用程式狀態選擇顯示不同的頁面（天氣、時間、生日等）。
- `src/display_utils.py`: 以 native rotated canvas、逐列圖片讀取與小型 glyph buffer 完成低記憶體顯示。
- `src/image_manager.py`: 圖片路徑驗證、交易式上傳／復原、低記憶體目錄列舉與輪播選圖。
- `src/epaper.py`: 電子紙驅動程式 (請勿修改)，提供與電子紙螢幕硬體互動的介面。
- `src/file_manager.py`: 檔案操作相關工具，用於列出檔案、隨機排序檔案、獲取圖片路徑等。
- `src/hardware_manager.py`: 硬體相關操作，負責讀取 ADC 值（光線感測器）、按鈕狀態、觸控事件和 DHT22 溫濕度感測器資料。
- `src/netutils.py`: 網路工具函數，包含 Wi-Fi 連線、NTP 時間同步、載入/儲存 Wi-Fi 配置等。
- `src/weather.py`: 天氣資料獲取與處理，從 OpenWeatherMap API 獲取當前天氣和天氣預報。
- `src/wifi_manager.py`: Wi-Fi 連線與 AP 模式管理，包含 Web 設定介面，用於使用者配置 Wi-Fi 和其他參數。
- `src/image/`: 存放所有 `.bin` 圖片資源。
- `tools/image_to_bin.py`: 相容的 GUI 入口；`tools/pico_image_tool/` 是共用轉檔、網路 client、GUI 與 CLI 核心。
- `hardware/`: 可提交於 source tree 的硬體檔案（大型 SolidWorks `.SLDPRT` 檔案改由 [GitHub Releases](https://github.com/Ning0612/pico-paper-clock/releases) 提供）。
- `docs/RELEASE_ASSETS.md`: UF2 與 CAD release asset 的檔名、位置與發布檢查表。
- `upload.py`: 用於部署檔案至 Pico 的腳本。

---

## 📚 參考資料與授權資訊

本專案部分程式碼與資源來自第三方開源專案，以下列出引用來源與其授權方式，並已依據相關條款合法使用與標示：

### 1. Waveshare 官方範例程式碼

- **來源**：  
  [waveshareteam/Pico_CapTouch_ePaper](https://github.com/waveshareteam/Pico_CapTouch_ePaper/blob/main/python/Pico_CapTouch_ePaper_Test_2in9.py)

- **用途**：  
  部分驅動程式碼參考自上述範例，用於控制 2.9 吋電子紙顯示器與觸控模組，並根據實際需求進行重構與調整。

- **授權方式**：  
  該檔案內含 MIT License 授權聲明，允許自由使用、修改與再散佈。已於本專案中保留原始授權區塊並遵循授權條款。


### 2. 天氣圖示資源（weather-icons）

- **來源**：  
  [erikflowers/weather-icons](https://github.com/erikflowers/weather-icons)

- **用途**：  
  `src/image/weather_icons/` 資料夾中的 `.bin` 圖示為基於該專案的 `.svg` 圖示修改與重新繪製後，先匯出為 `.png`，再透過本專案自製工具轉換為 1-bit `.bin` 格式，以配合電子紙顯示需求使用。

- **授權方式**：  
  原始圖示遵循 [SIL Open Font License 1.1 (OFL-1.1)](http://scripts.sil.org/OFL) 授權。根據授權條款，這些修改後的圖示仍依相同條款公開，並未用於任何商業行為或單獨銷售。

---

## 📄 本專案授權條款

本專案原創 source code 採用 [MIT License](LICENSE)。

授權邊界：

- 原創程式碼：MIT。
- Waveshare 範例衍生／參考程式碼：保留其 MIT notice。
- `src/image/weather_icons/`：衍生自 `erikflowers/weather-icons`，維持 OFL-1.1。
- `DEMO.jpg`、`AP_Mode_DEMO.png`、自訂圖片、CAD 檔與 firmware binary：不包含在 source-code MIT 授權範圍內，除非另有明確聲明。

第三方與素材細節請見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 與 [ASSET_CREDITS.md](ASSET_CREDITS.md)。

---
