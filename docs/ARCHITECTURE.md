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

啟動時先連線、同步 NTP 時間；只有設定 Discord webhook 時才 lazy import notifier、發送 LAN IP 通知並在載入控制器、顯示與感測器工作路徑前利用低記憶體窗口 flush pending queue。之後復原圖片交易檔並建立 LAN server。LAN 與 AP 共用路由；AP 額外保留按鈕長按、閒置 timeout、profile fallback 與 reboot 工作。

`main.py` 會在建立 controller 之前無條件畫出開機畫面，因此主迴圈接手時面板一定是醒著且有內容的。離席時的顯示收斂據此設計為**狀態驅動**：`state.display_asleep` 初值為 `False`，主迴圈只要看到 presence 不在席且旗標未設，就清屏、送入睡眠並設起旗標。之所以不能只監聽在席→離席的轉換，是因為在暗處開機時根本不存在該轉換（第一輪就已是離席），開機畫面會因此永遠留在面板上、電子紙也不會睡眠——而 Discord 記憶體保底重啟正好讓「暗處開機」成為常態路徑（見下方記憶體邊界）。圖片預覽也一併改為在迴圈開頭消耗、在在席分支繪製，**只取代該輪的頁面渲染而不短路整輪迴圈**；離席時預覽丟棄不繪製，面板維持睡眠。原本在迴圈開頭 `return` 的寫法讓客戶端只要每輪送一次 `preview=true`，就能使 `presence.update()`（連帶離席 debounce）、環境取樣、按鈕處理與 `_check_discord_stall()` 永遠不執行。

## 記憶體邊界

- 顯示使用一份 native `128 × 296` framebuffer，透過 rotated canvas 提供原本的 `296 × 128` 邏輯座標。
- 顯示更新會重用 native framebuffer、rotated canvas、字型 glyph buffer 與常用圖片列 buffer；避免每次刷新重新配置約 4.7 KB framebuffer 與重複的小型暫存物件。進入一般 Discord 網路傳送前會釋放大型 display workspace，保留 TLS 所需的連續 heap 空間。
- 圖片以固定列 buffer 讀取；網路上傳以 512-byte buffer 串流，不把整張圖片載入 RAM。
- SPI 傳送使用 buffer write，避免逐 byte 建立暫時物件。
- 長生命週期 controller、presence、image store/catalog 使用 `__slots__`。
- Discord webhook 不使用 `urequests.Response` 路徑，改用 raw `ssl` socket：只建立固定大小的 HTTP headers/payload、處理 partial write、讀取 status line 後立即關閉 socket；送出前後執行 `gc.collect()`，並暫時調整 GC threshold 後恢復原值。NTP 會在第一次 TLS 呼叫前同步；目前 firmware tree 尚未附帶 CA trust anchor，因此此連線仍不能宣稱完成憑證鏈／hostname 驗證，正式部署前需補上 CA bundle，不能以不驗證的 TLS 取代。
- Discord JSON payload 以單一 `bytearray` 組裝，避免字串串接時留下額外完整 payload copy；Discord socket 在建立與 TLS 前會記錄 heap free/allocated telemetry。
- 啟動通知與 pending Discord queue 在 webhook 已設定時，於 `main.py` 的低依賴啟動階段先執行，避開 controller/weather 後續模組 import 與 display/hardware 工作物件建立造成的 heap 碎片；未設定 webhook 時不載入 notifier，也不對 pending queue 做無效的 flush。第一次失敗不阻塞主程式，controller 會在 45 秒後、每 30 秒重試，pending queue 則保留到下一次可用窗口（`presence_pending.log`／`presence_session_pending.log` 另有 7 天保留上限，超過天數的通知會被裁切捨棄，不會無限期等待重試，見下方「Flash 儲存邊界」）。
- **記憶體自動重啟後，IP 未變就不再送「已上線」通知**。那次重啟買到的是唯一一個可用的 TLS 窗口，而啟動階段原本第一件事就是重發一則使用者早已知道的 IP 通知，把窗口用掉、pending 在席通知只能再等下一次重啟（至少 2 小時）。`_check_discord_stall()` 因此在 `machine.reset()` 前把當下**已公告過**的 IP 寫入 `discord_autoreset_ip.log`，`main.py` 在啟動窗口讀取後立即刪除：IP 相同就跳過通知並標記為已送（避免 controller 每 30 秒重試），窗口留給 `flush_startup_discord()`。只記錄確實送出過的 IP——從未公告成功的位址仍要照常嘗試，否則使用者無從得知裝置在哪。記錄採**讀取即消費**，所以手動斷電重開、或 IP 真的變了，都會照常送出；消費在「是否連上網路」的判斷之外執行，否則一次沒連上線的開機會把記錄留給後面某次本該公告的開機。刪除失敗時視為「沒有消費到任何東西」並照常公告——殘留的記錄否則會在每一次相同 IP 的開機持續抑制通知，多送一則遠優於從此靜默。「IP 沒變」的定義就是 IPv4 字串相同：換到另一個網路卻拿到相同位址時同樣會被抑制，但公告過的 URL 在該網路上仍然可用，且記錄只存活於「自動重啟 → 它造成的那次開機」之間，搬移裝置必然經過斷電而清掉記錄。
- Discord `ENOMEM` 會回傳可重試結果；presence queue 在記憶體壓力後暫停一個 flush interval，之後自動恢復嘗試，不丟棄 pending session/summary。
- **TLS 需要的是連續區塊，不是可用總量**。`ssl.wrap_socket` 的成敗門檻量測（MicroPython 1.24.1，2026-07-25，純 `.py` 部署）：最大連續區塊 17,920 B 時直接 `OSError [Errno 12] ENOMEM`，23,120 B 時成功。`TLS_MIN_CONTIGUOUS_BYTES` = 20 KiB 即取自這段區間。實測清除天氣快取與重複 `gc.collect()` 對最大連續區塊完全無效。
- **目前的 heap 基線見下方 2026-07-26 複測，不是上一行的 17.9 KB**。上一行只用於界定 TLS 的成敗門檻；當時記錄的「運行中最大連續區塊約 17.9 KB」已被後續量測取代，勿再引為現況基線。
- **`release_display_workspace()` 增加的是 `mem_free`，不是最大連續區塊**。2026-07-26 於 `.mpy` 部署、開機約 3 分鐘的實機複測：呼叫後 `mem_free` 由 56,512 B 升至 61,584 B（+5,072 B），但最大連續區塊在呼叫前後**同為 10,240 B，完全沒有移動**——釋放出的空間不在關鍵位置。同次量測的穩態為 `mem_free` 56,512 B／`mem_alloc` 133,440 B，最大連續區塊約 10 KiB，**只有 20 KiB 門檻的一半**；裝置端 `discord_diag.log` 同期記錄的 `largest=10240`／`13312` 與此一致。因此在這個部署下，穩態送不出去是常態而非暫時性壓力，而**目前唯一觀察到能成功送出的時機**是重開機後、模組尚未載入的低記憶體啟動窗口（`main.py` 的 `flush_startup_discord()`）。此結論的證據是單一裝置、單一韌體與 `.mpy` 部署下的量測，其他部署模式（純 `.py`、不同韌體、模組數量變動）需重新量測才能沿用。不要再把 `release_display_workspace()` 當成能救回這條路徑的手段。
- `flush_discord()` 因此在釋放 display workspace 之後、送信之前執行 pre-flight 檢查（`has_tls_headroom()`，門檻 `TLS_MIN_CONTIGUOUS_BYTES` = 20 KiB）。不足時跳過本次嘗試並累計失敗計數，避免把約 3 秒耗在必定失敗的 handshake 上。失敗原因與當下最大連續區塊寫入 `discord_diag.log`（第 1 次與其後每 10 次），失敗診斷因此能在斷電後保留。
- **記憶體探針之前必須先問「這則訊息本來就送得出去嗎」**：`delivery_blocked()` 會先判斷 webhook 是否設定、STA 是否連線，回傳 `nowebhook`／`offline`／`""`。順序反過來的話，「沒設定 webhook」或「斷網」會被記成記憶體不足，累積後觸發一個根本幫不上忙的重開機。三個 `send_*` 函式共用同一份判斷，避免兩處條件漂移。
- 碎片化一旦讓連續區塊長期不足，**只有重開機能取回連續 heap**。`app_controller` 在**記憶體類失敗**（`lowmem`／`enomem`，由 `presence.discord_mem_failures` 單獨計數）達門檻、仍有 pending、且開機滿 `DISCORD_STALL_MIN_UPTIME_MS`（5 分鐘）時執行 `machine.reset()`。HTTP 錯誤或斷網會把該計數歸零，**因此這類失敗本身不會觸發任何重啟**——這正是歸零的目的：重開機修不好一個被刪除的 webhook，少了這道區分才會退化成每 2 小時重啟一次。
- **門檻依在席狀態而定，因為它衡量的是重開機當下的代價，不是堵塞已持續多久**（`_stall_reset_threshold()`）。離席時 `DISCORD_STALL_AWAY_FAILURES`（2 次，約 2 分鐘）：`presence_manager` 只在「離開書桌」的 transition 產生 pending session summary，所以幾乎所有待送通知誕生時面板都已清屏睡眠、使用者不在場，重開幾乎沒有可感知的代價。在席或狀態未知（`current_state` 為 `None`，第一次 presence 判定之前）時 `DISCORD_STALL_PRESENT_FAILURES`（10 次，約 10 分鐘），因為重開會讓使用者盯著開機畫面等 Wi-Fi 重連與 NTP。**在席門檻不可改成「永不」**：光感若把亮著的空房間讀成在席，only-away 觸發就永遠不會發生，通知會卡得比引入這個機制之前更久。
- 觸發判斷採 `stall_checked_failures`／`stall_checked_threshold` latch，不是「失敗數為門檻的整數倍」。同一組（失敗數，門檻）只評估一次，因此冷卻檔仍維持每次失敗才讀一次（約 60 秒），不會每輪主迴圈都讀 flash；而失敗數或門檻任一改變就重新評估，所以使用者離開書桌使門檻下降時會立即重評，被 uptime gate 或冷卻擋掉的檢查也只延後到下一次失敗（約 60 秒），不像倍數寫法會直接延到第 2N 次而使延遲加倍。這也解除了 gate 與門檻的耦合：`DISCORD_STALL_MIN_UPTIME_MS` 只需長於啟動通知窗口（`STARTUP_DISCORD_DELAY_MS` 加一次 `STARTUP_DISCORD_RETRY_MS`），由 `test_uptime_gate_outlasts_the_startup_window` 把關。失敗數在送出成功後歸零時 latch 一併重設，避免計數重新爬回同一個值時漏掉一次評估。
- 門檻降低**不保證**「每批 backlog 只花一次重啟」：pending 是以 `_append_line` 累積、`_drop_first_line` 消耗的佇列，而 `flush_startup_discord()` 每次開機最多清 8 筆，冷卻是 per-reboot 而非 per-backlog。目前每天約 2–6 筆的量遠低於此上限，但 backlog 一旦深於 8 筆，清空就需要跨多次重開機。
- 自動重啟的保險：pending 未能寫入 flash（`pending_persist_failed`）時放棄重啟，否則會遺失只存在於 RAM 的通知；冷卻時間戳寫入失敗時放棄重啟並封鎖本次開機（fail-safe，不重啟優於 boot loop）；`discord_autoreset.log` 於執行期即時評估，冷卻可在運行中自然到期。**冷卻檔只有「檔案不存在」是 fail-open，其餘一律 fail-closed**：不存在代表從未自動重啟過，第一次不可被擋；其他讀取錯誤（`OSError` 非 ENOENT）與時鐘不可用則直接拒絕，因為此時冷卻狀態是「未知」，而未知不能讀成「允許」——間歇性的 flash 讀取失敗否則每失敗一次就放行一次重啟。檔案存在但內容不可用（截斷寫入、區塊損毀、`<= 0` 的數值）則重寫一個新的時間戳並拒絕本次重啟；若連重寫都失敗就設起 `auto_reset_blocked`，與呼叫端寫入失敗時的處置一致。**時間戳比當下時鐘還新時同樣走重寫路徑**：Pico W 沒有電池供電的 RTC，NTP 同步失敗的那次開機會讓 `time.time()` 從 port epoch 重新起算，於是由已同步開機寫下的時間戳永遠落在未來、差值恆為負；把它讀成「冷卻未到期」會讓保底重啟一路被封鎖到 NTP 再次成功，讀成「已到期」則會每輪都放行、而每次重啟又重置時基。重寫成當下時基並等滿一次冷卻是唯一不會卡死也不會失控的處置。把損毀讀成「從未重啟過」等於放棄唯一的 boot-loop 防護，而在離席門檻（約 2 分鐘）下那會退化成每次 uptime gate 到期就重開一次。
- **離席分支的清屏睡眠必須包在 try/except 內**：`main.py` 以 `while True: controller.run_main_loop()` 裸迴圈驅動、未包例外處理，而 `clear_display_and_sleep()` 位於 `_check_discord_stall()` 之前，因此它拋出的例外會終止整個主程式，並讓最需要保底重啟的時刻永遠等不到重啟。失敗時不設起 `display_asleep`，但改以 `DISPLAY_SLEEP_RETRY_MS`（60 秒）退避後再試——完整清屏加面板初始化的成本太高，每秒重試一次會排擠 LAN polling、presence 更新與 stall 檢查並灌爆 UART log。「開機滿 5 分鐘」以 latch 記錄而非每次重算——`ticks_ms()` 為 30-bit、`ticks_diff()` 僅在約 ±6.2 天內有效，而這個故障正好出現在約 12 天的連續運行之後。
- DHT22 使用 2500 ms 最小讀取間隔；讀取失敗改用 10 秒 backoff，保留上一筆快取值，避免感測器錯誤反覆消耗 heap 與刷 serial log。
- 天氣資料改由 Open-Meteo 提供：單一 bundle request 同時取得 current 溫度/WMO condition code 與 daily 5 天平均溫度、WMO condition code、最大降雨機率；以 `response.json()` 解析小型 5-day payload，只有兩者都成功才原子更新 last-known-good snapshot，失敗時保留既有資料並回收 heap。既有 display icon 名稱由 WMO code mapping 保持不變。
- 天氣 bundle request 前、response 取得後與 parse 後會記錄 heap telemetry；API 的 `timezone` 由 profile 的固定 `timezone_offset` 轉成 IANA `Etc/GMT` zone，使預報日期與裝置日期一致。Presence API 的記憶體讀取介面只保留最近 128 筆事件與 366 筆 daily lines，且單行最多讀取 256 字元；完整串流 API 仍逐行送出。
- `/api/v1/device` 的 `heap_free` 可作為現場基線；完整 peak／長跑數據仍需接上指定 Pico 後量測。

### 記憶體問題的處理原則

```text
啟動 Wi-Fi
  └─ webhook 已設定時才載入 raw HTTPS Discord webhook
       ├─ 成功：記錄已送出，釋放 socket
       └─ ENOMEM：保留可重試狀態，不阻塞主迴圈
            ↓
載入 display / HardwareManager / AppController
  └─ 天氣 bundle 以單一 5-day JSON payload 解析並立即釋放
  └─ DHT22 依時間節流，失敗使用 backoff 與快取
```

這些策略的目標是降低「單次配置峰值」與重複配置頻率，而不是宣稱裝置 heap 永遠不會耗盡。現場診斷應同時查看 serial 的 `ENOMEM`、`Memory before/after ...` telemetry、DHT22 錯誤與 `/api/v1/device` 的 `heap_free`。**Discord 送不出去時優先查裝置上的 `discord_diag.log`**：`lowmem` 事件附帶當下的最大連續區塊，可直接判斷是碎片化還是 webhook 本身的問題（後者記錄為 `http<狀態碼>`）。注意 `heap_free` 充足並不代表 TLS 可用——關鍵指標是最大連續區塊。

## Flash 儲存邊界

`presence_manager.py` 與 `env_manager.py` 的 log 檔案都存在裝置的內部 flash 檔案系統上，與韌體、`config.json`、`src/image/` 圖片資產共用同一個有限空間（在一台已使用一段時間、圖片庫已有內容的裝置上，剩餘可用空間可能只有約 100 KiB 等級）：

- 兩個模組都採「事件/樣本檔＋每日彙總檔」的雙檔設計，並在每日換日時以 `_trim_by_date` 依日期視窗裁切——檔案大小會在保留視窗內收斂到穩定值，不會隨時間無限增長。
- `env_events.log`（15 分鐘取樣、7 天保留）穩態約 17 KiB；`env_daily.log`（每日彙總、366 天保留）穩態約 15 KiB；新增的 `environment.bin` WebUI 資產約 6.7 KiB（實測，`tools/build_html.py` 輸出）。三者合計約 40 KiB 是這次新增功能的穩態 flash 佔用。
- 裁切/換日時的 `.tmp`/`.bak` 交易寫入（`_commit_tmp`）會暫時需要被重寫檔案的一整份額外空間；`env_events.log` 裁切瞬間約需額外 17 KiB。
- `discord_diag.log` 上限 6 KiB，超過時串流捨棄較舊的一半（同樣使用 `.tmp` 交易寫入，瞬間額外需求不超過檔案本身）；`discord_autoreset.log` 只存一個 epoch 時間戳，`discord_autoreset_ip.log` 只存一個 IP 字串且讀取後即刪除，量級皆可忽略。
- **實測建議**：完成部署後應以裝置 REPL 執行 `os.statvfs('/')` 或呼叫 `GET /api/v1/device` 的 `fs_free` 欄位覆核實際剩餘空間，不要只依賴這裡的估算值。7 天保留的原始/事件 log（`env_events.log`、`presence_events.log`）約一個月內就會穩定在保留視窗內的穩態大小；366 天保留的每日彙總 log（`env_daily.log`、`presence_daily.log`）要接近一整年才會長到穩態上限，短期量測看到的每日彙總檔案會比長期穩態小很多，不能用一個月的量測值直接外推。若空間明顯吃緊，`env_manager.DAILY_RETENTION_DAYS`（預設 366，比照 `presence_manager.DAILY_RETENTION_DAYS`）可調降以換取空間。
- **`.py` 原始碼是目前最大宗的 flash 佔用來源**：一台已部署 presence／env 功能且圖片庫有內容的裝置，18 個 `.py` 檔案合計約 226 KB，佔裝置總佔用（307 KB）的 74%，遠超過圖片資產（~50KB）與 Web UI `.bin` 資產（~38KB）。`tools/pico_deploy/upload_cli.py --mpy` 可在部署前用 `mpy-cross` 把 `.py` 預編譯成 `.mpy` bytecode（`epaper.py`／`main.py`／`config.json` 除外，理由見 `CLAUDE.md`「部署至裝置」一節），是目前最有效的省空間手段。**實測**（2026-07-22，裝置 MicroPython 1.24.1）：18 個原始碼檔案從約 226 KB 壓到約 101 KB，裝置剩餘 flash 從 88.0 KiB 提升到 204.0 KiB（多出 116 KiB），比社群估計的 30–50% bytecode 縮減比例更好。**裝置剩餘空間吃緊時建議部署加上 `--mpy`**；這仍是 opt-in 選項而非預設行為——目前沒有部署前韌體版本檢查機制，`mpy-cross` 版號與裝置實際韌體版本漂移會讓 `.mpy` 模組 import 失敗，加上回滾（切回純 `.py`）流程尚未完整驗證，暫不建議設為預設。

## 圖片格式與相容性

- raw 圖片 payload 的 canonical 格式是 `MONO_HLSB`，每個 byte 的 bit 0 是最左像素；新工具一律寫入帶 HLSB header 的 PPC1 `.bin`。
- PPC1 header 保存 bit order，裝置透過 256-byte history、512-byte input buffer 與既有 row buffer 逐列解壓，不把整張圖片載入 RAM。
- 新工具與 USB manifest 不建立或部署 `.hlsb` sidecar；PPC1 自帶 bit order metadata。
- 韌體仍接受 raw API／既有 raw 資產的 `.hlsb` marker，以維持升級相容性。
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
| `tools/pico_image_tool/` | 圖片轉檔、抖動、codec、WebUI client、圖片 CLI | 主機端 Python |
| `tools/pico_deploy/` | Pico USB/`mpremote` 部署核心、manifest、作業佇列與整合 GUI | 主機端 Python |
| `tests/` | 主機回歸與協議測試 | 使用專案 `.venv` |
| `docs/` | 長期文件與契約 | API／設定／架構同步更新 |
| `dist/release-assets/` | 本地發布暫存的 UF2、STEP、STL 與 `.SLDPRT` | 已被 Git 忽略；建立 Release 時手動附加；不放回 source tree |

## 部署與驗證

```powershell
.\.venv\Scripts\python.exe tools\build_html.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools\pico_deploy\upload_cli.py --port COM6 --no-clean
```

本次記憶體路徑的最低驗證包括 host tests、`compileall`、`git diff --check`，以及 Pico W serial 中的 `Success: Discord LAN IP notification sent.`、DHT22 讀值與天氣請求成功。完整 peak heap 仍應以實際硬體長跑資料為準。

Pico 部署工具 EXE 由 `tools/build_pico_deploy_tool.ps1` 建置。若使用遞迴清理，部署前要先保存裝置上只有 runtime 的圖片。
