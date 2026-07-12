# Changelog

所有此專案的顯著變更將會記錄在此檔案。

格式遵循 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
且本專案遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [Unreleased]

### Added
- 新增低記憶體圖片 API、`/images` 裝置管理頁與圖片交易復原。
- 新增 Pico Image Tool GUI/CLI、LAN 探索、四種抖動、三種 fit 與 Windows PyInstaller build 規格。
- 新增圖片格式與交易 golden tests。

### Changed
- AP/LAN Web server 共用同一 dispatcher；設定頁改用靜態 HTML 與版本化設定 API。
- 顯示改為單一 native framebuffer、逐列圖片讀取與批次 SPI 傳輸。
- 設定保存改為 schema v3 單次交易，presence pending queue 改為串流處理。

### Fixed
- `image_interval_min` 現在實際控制輪播間隔，日期事件圖片會依生日、MMDD、custom 優先序顯示。
- MONO_HLSB 明確採 bit 0 為左側像素，避免每 8 像素位元順序錯誤。

## [2.0.1] - 2025-12-31

### 安全性修復 (Security)
- **🔒 安全性強化**：針對系統安全性進行全面修復與強化，包含防止跨站腳本攻擊 (XSS)、跨站請求偽造 (CSRF) 及敏感資訊保護，提升系統整體的防護能力。


## [2.0.0] - 2025-12-31

### 重大變更 (Breaking Changes)
- **設定檔格式升級**：`config.json` 採用新的多設定檔架構，支援為不同地點建立獨立設定檔（向後兼容舊格式）。
- **長按按鈕行為變更**：長按按鈕改為進入 AP 模式（不再清除設定檔），可透過網頁介面管理或重置。

### 新增功能 (Added)
- **多設定檔系統**：
  - 支援建立多個設定檔（如家裡、公司），每個設定檔包含獨立的 WiFi、天氣地點及裝置參數。
  - 全局設定（AP Mode、Weather API Key）在所有設定檔間共用。
- **智能 WiFi 連接**：啟動時自動掃描並根據 SSID 信號強度優先連接合適的設定檔。
- **網頁端管理介面**：
  - 全新雙欄式響應設計，支援新增、編輯、刪除設定檔。
  - 即時顯示光感應器數值與活動狀態。
  - 提供「完全重置」功能（位於危險區域）。

### 改進與優化 (Improved & Optimized)
- **UI/UX 全面升級**：
  - **響應式設計**：針對手機與桌機優化佈局，手機版採用原生下拉選單與單欄設計。
  - **視覺統一**：導入 CSS 變數系統、統一按鈕樣式、增強互動反饋（Loading 狀態、倒數動畫）。
  - **操作體驗**：優化設定檔選擇邏輯，編輯時自動定位，並以清晰標記（● 編輯中、(啟用)）顯示狀態。
- **系統核心優化**：
  - **AP 模式記憶體優化**：重構 Web 伺服器採用分塊傳送 (Chunked Sending) 與靜態資源壓縮，大幅降低記憶體佔用。
  - **傳輸穩定性**：實作 `send_chunk()` 機制並加入延遲，解決 Pico W 緩衝區溢位導致的頁面載入不完整問題。
  - **架構重構**：`config_manager` 與 `wifi_manager` 深度重構，提升程式碼可維護性與錯誤處理能力。

---

## [1.6.0] - 2025-08-14

### 變更與重構 (Changed & Refactored)
- **統一按鈕長按與重置邏輯**：
  - 將按鈕長按偵測邏輯集中到 `hardware_manager.py`，移除了 `app_controller.py` 中的重複實作。
  - 新增 `wifi_manager.py:reset_wifi_and_reboot()` 函式，統一處理 Wi-Fi 和 AP 模式的設定重置與裝置重啟流程。
  - 現在，無論在正常模式或 AP 模式下，長按任一按鈕 3 秒都會觸發一致的重置行為。
- **AP 模式穩定性與體驗優化**：
  - **動態超時機制**：AP 模式的閒置超時會因使用者活動（如客戶端連線、提交表單）而自動延長，防止在設定過程中意外重啟。
  - **支援在 AP 模式下按鈕重置**：即使在 AP 模式的網頁設定介面下，使用者依然可以透過長按按鈕來重置裝置。

### 修正 (Fixed)
- **設定一致性**：修正了 AP 模式預設 SSID 在不同檔案中不一致的問題，統一為 `Pi_Clock_AP`。

## [1.5.1] - 2025-08-01

### 修正 (Fixed)
- **天氣預報日期格式修正**：在 `display_manager.py` 中，修正了日期格式化問題。確保在與天氣預報資料比對時，單位數的日期會補零（例如 `7` -> `07`），避免在每月的前九天可能發生的當日天氣無法正確顯示在預報列表中的錯誤。

## [1.5.0] - 2025-07-29

### 新增功能 (Added)
- **AP 模式安全性強化**：
  - AP 模式的預設密碼長度提升至 8 個字元 (`12345678`)，並在 `config.json.example` 與 `config_manager.py` 中同步更新，增強初次設定的安全性。
- **AP 模式穩定性提升**：
  - **重構設定儲存邏輯**：在 `wifi_manager.py` 中，將原本分散的參數解析與設定儲存流程，重構為先將所有設定存入 `dict`，再統一寫入，提升程式碼可讀性與可維護性。
  - **新增錯誤處理頁面**：若使用者在 AP 設定頁面提交的表單資料不完整或格式錯誤，系統將顯示一個獨立的錯誤頁面，引導使用者返回修正，而不是直接崩潰或忽略錯誤。

## [1.4.0] - 2025-07-21

### 變更與重構 (Changed & Refactored)
- **程式碼品質提升**:
  - **全面英文化**：統一將所有模組 (`.py`) 中的註解與 `print()` 輸出訊息從中文改為英文，提升可讀性。
  - **新增 Docstrings**：為專案中所有主要類別與函式補上標準的 Docstrings，詳細說明其功能、參數與用途，大幅改善程式碼的可維護性。
- **Wi-Fi 與設定流程優化 (`wifi_manager.py`)**:
  - **重構設定儲存邏輯**：簡化 AP 模式下儲存設定的流程，改為直接呼叫 `config_manager.set()`，使程式碼更直觀且易於管理。
  - **縮短連線超時**：將 Wi-Fi 連線等待時間從 10 分鐘縮短至 1 分鐘，讓裝置在無法連線時能更快進入 AP 設定模式。
- **顯示邏輯整理 (`display_manager.py`)**:
  - 將 AP 模式的顯示邏輯從 `wifi_manager.py` 移至 `display_manager.py` 中，並建立 `update_display_AP` 函式，提高顯示相關程式碼的集中度。

### 清理 (Removed)
- **移除無用函式**：刪除了 `netutils.py` 中不再使用的 `load_wifi_config`, `save_wifi_config` 等輔助函式。
- **清理驅動程式碼**：移除了 `epaper.py` 中原廠提供但已註解的範例程式碼，保持檔案整潔。

## [1.3.1] - 2025-07-21

### 修正 (Fixed)
- **記憶體穩定性與系統優化**：
  - **天氣更新重構 (`weather.py`)**：徹底重構天氣預報 (`fetch_weather_forecast`) 的處理邏輯。改為分段讀取並逐塊解析 JSON 回應，僅提取必要欄位，避免一次性將大型資料載入記憶體，從根本上解決了 `MemoryError` 問題。
  - **積極的記憶體回收**：在 `weather.py` 和 `display_utils.py` 中的記憶體密集型操作（如 JSON 解析、圖片繪製）後，強制執行垃圾回收 (`gc.collect()`) 並手動釋放大型物件 (`del obj`, `obj = None`)，有效緩解了記憶體碎片化。
  - **優化更新調度 (`app_controller.py`)**：天氣更新由時間驅動，僅在固定間隔（當前天氣 3 分鐘，預報 30 分鐘）或資料不存在時觸發，避免了不必要的網路請求與計算，降低了系統負載。

## [1.3.0] - 2025-07-18

### 新增功能 (Added)
- **圖片管理增強**：
  - 新增日期特定事件圖片支援，可顯示與當前日期相關的圖片。
  - 觸控螢幕可循環切換圖片。
  - 載入頁面圖片現在會隨機顯示。

### 變更與重構 (Changed)
- **部署腳本優化 (`upload.py`)**：
  - 腳本已大幅重構，支援設備遞歸清理。
  - 上傳過程提供更詳細的進度報告（包含檔案大小）。
  - 改進目錄創建邏輯，避免重複的 `mkdir` 調用。
  - 移除 `get_device_space_info` 函數。
- **本地化與訊息統一**：
  - `src/app_controller.py` 和 `src/display_utils.py` 中的多處列印訊息和使用者介面字串已從中文改為英文。
- **工具改進 (`tools/image_to_bin.py`)**：
  - 轉換工具現在會保留原始檔案名稱作為預設儲存名稱。
- **版本控制忽略設定**：
  - `.gitignore` 已更新，忽略 `src/image` 目錄下的常見圖片格式 (`.jpg`, `.jpeg`, `.png`)。

## [1.2.0] - 2025-07-18

### 新增功能 (Added)
- **時區設定功能**：
  - 新增 `timezone_offset` 設定，允許使用者根據所在地區設定 UTC 時間偏移（-12 到 +14 小時）。
  - 可於 `config.json` 或 AP 模式設定頁面中進行設定。
  - 主畫面時間與天氣預報將根據此偏移量顯示正確的本地時間。

### 變更與重構 (Changed)
- **天氣模組記憶體優化**：
  - 重構 `weather.py` 中的天氣預報功能 (`fetch_weather_forecast`)，採用分段處理 JSON 資料的方式，大幅降低記憶體使用量，解決在記憶體有限的 Pico W 上可能發生的 `MemoryError`。
  - 增強 `_make_request_with_retry` 的錯誤處理，加入 `OSError` 和 `MemoryError` 的捕獲，並在請求前後手動觸發垃圾回收 (`gc.collect()`)。
- **設定檔結構調整**：
  - 在 `config.json` 中，將 `light_threshold` 和 `image_interval_min` 移至 `user` 物件下，使設定檔結構更清晰。
- **程式碼邏輯優化**：
  - `display_manager.py` 中的畫面更新函數現在直接接收時間物件，避免重複呼叫 `get_local_time()`。

## [1.1.0] - 2025-07-17

### 新增功能 (Added)
- **定時響聲功能**：
  - 新增 `chime.py` 模組，可透過無源蜂鳴器 (Pin 20) 實現整點或半點報時。
  - 可於 `config.json` 或 AP 模式設定頁面中啟用/停用、調整音調與音量。
- **AP 模式功能擴充**：
  - 設定頁面新增「定時響聲」相關選項。
  - 設定頁面會即時顯示當前光感應器的 ADC 數值，每 3 秒自動更新。
  - 新增 `/adc` API endpoint 供前端非同步取得感測器數值。
  - **新增「測試響聲」按鈕**：在 AP 模式設定頁面中，音量設定旁新增測試按鈕，可即時測試蜂鳴器響聲。

### 變更與重構 (Changed)
- **應用程式架構重構**：
  - 將原有的 `main.py` 核心邏輯拆分為多個獨立模組，包含 `app_controller.py`, `app_state.py`, `hardware_manager.py` 等，提高模組化與可維護性。
  - 遵循單一職責原則，各模組功能更專一。
- **統一設定管理**：
  - 引入 `config_manager.py` 模組，集中處理 `config.json` 的讀取與寫入，提供統一的設定存取介面。
  - `config.json` 擴充了響聲、生日、光感門檻等設定。
- **Web 設定介面優化**：
  - AP 模式的 HTML 頁面 (`wifi_manager.py`) 進行了重構，以支援更多設定選項與即時數據顯示。
  - **優化設定儲存流程**：調整 AP 模式下設定儲存流程，先解析並儲存設定，再回傳包含已儲存設定（敏感資料已遮蔽）的成功頁面，最後才重啟裝置。
  - **增加重啟延遲**：將設定儲存後的重啟延遲從 3 秒增加到 5 秒，確保客戶端能完整接收成功頁面。
- **按鈕行為優化**：
  - 在 `app_controller.py` 中實現按鈕長按偵測，長按可觸發 Wi-Fi 重置並重啟設備。
  - `hardware_manager.py` 中 `get_button_states` 方法調整，將按鈕原始值反轉，使 `1` 表示按下，`0` 表示未按下。
- **顯示函數重構**：
  - `update_display_Restart` 函數從 `wifi_manager.py` 移至 `display_manager.py`，統一顯示相關邏輯。
- **錯誤修正**：
  - 修正 `wifi_manager.py` 中 `success_page_template` 因 CSS 樣式中的 `{}` 未正確跳脫導致的 `KeyError: 'font-family'` 錯誤。
- **穩定性提升**：
  - 增強了 Wi-Fi 連線、天氣 API 請求及圖片載入時的錯誤處理機制，加入重試與 fallback 邏輯。
  - 移除 `chime.py` 中不再使用的 `test_chime` 函數。
  - **網路與檔案操作穩定性強化**：
    - 為天氣 API 請求 (於 `src/weather.py`) 實作了更穩健的重試機制，並改進了錯誤日誌，同時確保在無網路連線時跳過請求。
    - 在 NTP 時間同步 (於 `src/netutils.py`) 前增加網路連線檢查。
    - 改進了圖片載入 (於 `src/display_utils.py` 和 `src/file_manager.py`) 的錯誤處理，並將錯誤訊息翻譯為英文。
  - **`NoneType` 錯誤修正**：強化了 `urequests` 回應物件可能為 `None` 的錯誤處理邏輯，確保安全地關閉回應物件。
- **錯誤修正**：
  - 修正 `wifi_manager.py` 中 `success_page_template` 因 CSS 樣式中的 `{}` 未正確跳脫導致的 `KeyError: 'font-family'` 錯誤。
  - **訊息統一**：所有 `print` 訊息皆已轉換為英文。
- **內部邏輯調整**：
  - `src/app_controller.py` 中 `_perform_chime` 的呼叫順序調整。
  - `upload.py` 處理了 `UnicodeDecodeError` 並新增了顯示設備空間資訊的功能。
