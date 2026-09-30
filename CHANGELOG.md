# Changelog

所有此專案的顯著變更將會記錄在此檔案。

格式遵循 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
且本專案遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。

## [2.7.0] - 2026-10-01

本版本把天氣資料來源從 OpenWeatherMap 換成 Open-Meteo。起因是 OpenWeatherMap API 在部分網路環境下連不上，天氣頁因此長期停在 fallback；Open-Meteo 不需要 API Key，設定改為每個 profile 填經緯度。設定檔 schema 升為 v4，舊設定會在開機時自動遷移。

### Changed

- 天氣資料改由 Open-Meteo 提供：單一 request 同時取得目前溫度／WMO 天氣代碼與 5 天每日預報（平均溫度、WMO 代碼、最大降雨機率），兩者都解析成功才原子更新快取，失敗時沿用上一份有效資料。WMO 代碼對應到既有的天氣圖示，顯示端不變。預報日期以 profile 的固定 `timezone_offset` 換算成 `Etc/GMT` 時區送給 API，與裝置日期一致。
- 設定檔 schema v3 → v4：移除 `global.weather_api_key`；`profile.weather_location`（城市名稱）改為 `profile.weather_latitude`／`profile.weather_longitude`（範圍 −90～90／−180～180）。開機時自動遷移：內建範例城市會離線對應成座標；無法對應的舊值保存在 `legacy_weather_location` 作為人工恢復提示，並先使用台北預設座標，需到設定頁填入正確座標。Web UI 設定頁同步改為經緯度欄位。

### Added

- 設定頁新增地圖選點：可點擊地圖或拖曳標記來選擇天氣查詢位置，經緯度欄位同步更新。地圖（Leaflet 與 OpenStreetMap 圖磚）由瀏覽器直接載入，不儲存在 Pico W、也不經由 Pico W 代理；瀏覽器連不到地圖服務時仍可直接輸入座標。
- 部署工具（`tools/pico_deploy/upload_cli.py` 與 GUI）預設**不再上傳或刪除**裝置上的 `config.json`，需明確指定 `--include-config` 才會以本機設定覆寫，避免重新部署時蓋掉裝置上的設定。

### Fixed

- 修正設定頁每次載入都掃描 Wi-Fi、拖慢頁面的問題：載入時只顯示目前 profile 的 SSID，需要換網路時再按「掃描」。
- 降低啟動時天氣模組的 heap 壓力：天氣改為單一 bundle request；未設定 Discord webhook 時不再載入 notifier 模組，也不對 pending queue 做無效的 flush。

## [2.6.1] - 2026-07-28

本版本把 v2.6.0 引入的 Discord 保底自動重啟機制修到堪用：縮短離席時的恢復延遲、補上三個會讓保底重啟失效或反而害死主程式的容錯缺陷，並停止把重啟換來的唯一 TLS 窗口浪費在重發使用者早已知道的 IP 上。

### Fixed

- 修正在無光環境重新開機後，電子紙停留在開機畫面且**永遠不進入睡眠**的問題。`main.py` 會在建立 controller 前無條件畫出開機畫面，而主迴圈原本只在偵測到「在席→離席」的轉換時才清屏睡眠；暗處開機時第一輪就已是離席狀態，不存在該轉換，於是開機畫面留在面板上、電子紙持續保持喚醒直到使用者開燈。面板長時間不睡眠是 Waveshare 明確不建議的用法，比畫面卡住本身更需要處理。此路徑原本罕見，但 Discord 記憶體保底重啟使「暗處開機」成為常態（離席＝變暗＝觸發通知＝送不出去＝約 2 分鐘後重啟），兩者相乘後每晚都會發生。修法是把離席顯示收斂由轉換驅動改為**狀態驅動**：`AppState` 新增 `display_asleep` 旗標（初值 `False`，因為開機畫面已經畫上面板），主迴圈只要處於離席且旗標未設就清屏睡眠並設起旗標，在席時清掉旗標，使所有進入離席的路徑收斂到同一個終態。
- 修正圖片預覽的 early return 會短路整輪主迴圈的問題。`consume_preview()` 命中時原本會立刻 `return`，因此客戶端只要每輪送一次 `preview=true`（批次上傳做得到），就能讓 `presence.update()`（連帶離席 debounce）、環境取樣、按鈕處理與 `_check_discord_stall()` 在整段期間完全不執行；離席期間畫上的預覽也會讓面板一直醒著。現在預覽改為在迴圈開頭消耗、在在席分支繪製，**只取代該輪的頁面渲染**，迴圈其餘部分照常跑完；預覽不更新 `last_minute`／`partial_update`，下一個觸發點即恢復正常頁面。離席時預覽直接丟棄不繪製——面板已睡眠且環境無光，畫上去看不見，只會把面板叫醒。

- 修正離席清屏睡眠失敗會終止整個主程式的問題。`main.py` 以 `while True: controller.run_main_loop()` 裸迴圈驅動、未包 try/except，因此 `clear_display_and_sleep()` 拋出的例外（低 heap、電子紙 I/O 失敗）會直接結束程式；而它正好位於 `_check_discord_stall()` 之前，於是最需要保底重啟的時刻反而永遠等不到重啟。現在改為捕捉例外並以 `DISPLAY_SLEEP_RETRY_MS`（60 秒）退避後重試——完整清屏加面板初始化太昂貴，每秒重試會排擠 LAN polling、presence 更新與 stall 檢查。此路徑在本次改動後更關鍵：暗處重開機必定會走一次離席分支。
- 修正 `discord_autoreset.log` 讀取失敗或內容損毀時冷卻機制失效的問題。原本任何讀取例外都回傳「允許重啟」，等同放棄唯一的 boot-loop 防護；離席門檻縮短為約 2 分鐘後，這會退化成每次 uptime gate 到期就重開一次。現在只有「檔案不存在」（ENOENT，代表從未自動重啟過）維持放行，其餘讀取錯誤與時鐘不可用一律拒絕；檔案存在但內容不可用（不可解析或 `<= 0`）時則重寫一個新的時間戳並拒絕本次重啟，重寫也失敗就設起 `auto_reset_blocked`，與呼叫端寫入失敗時的處置一致。
- 修正 NTP 同步失敗的開機會讓保底自動重啟被永久封鎖的問題。Pico W 沒有電池供電的 RTC，NTP 失敗時 `time.time()` 會從 port epoch 重新起算，而 `discord_autoreset.log` 內是由已同步開機寫下的大 epoch 值，兩者相減恆為負，冷卻判斷因此永遠不成立——保底重啟一路失效到 NTP 再次成功為止。現在偵測到時間戳比當下時鐘還新時，改為重寫成當下時基並拒絕本次重啟（等滿一次冷卻）；直接視為「已到期」則會每輪放行，而每次重啟又重置時基，形成 boot loop。

### Changed

- 縮短 Discord 通知堵塞後的恢復延遲：保底自動重啟門檻由「連續 30 次記憶體失敗」改為**依在席狀態選擇**——離席 `DISCORD_STALL_AWAY_FAILURES`（2 次，約 2 分鐘）、在席或狀態未知 `DISCORD_STALL_PRESENT_FAILURES`（10 次，約 10 分鐘）。依據為 2026-07-26 的實機複測：穩態下最大連續區塊僅約 10 KiB，只有 20 KiB 門檻的一半，且 `release_display_workspace()` 只增加 `mem_free`（56,512→61,584 B）而**完全不改變最大連續區塊**（前後同為 10,240 B）。既然等待不會改變結果，門檻改由「重開機當下的代價」決定：`presence_manager` 只在「離開書桌」的 transition 產生 pending session summary，因此幾乎所有待送通知誕生時裝置都正好離席、面板已清屏睡眠、使用者不在場，重開成本接近零；在席時重開則要讓使用者盯著開機畫面等 Wi-Fi 重連與 NTP 同步，故維持較慢的門檻。在席門檻刻意不設為「永不」——光感若把亮著的空房間誤判為在席，only-away 觸發會讓通知卡得比改動前更久。取捨已知：heap 若在第 3–9 次之間恢復，離席門檻會比舊門檻多一次重啟；上述量測取自單一裝置的 `.mpy` 部署，其他部署模式需重新量測。冷卻維持 2 小時以保留 boot-loop 防護，因此**吞吐上限未變**（冷卻為 per-reboot，且 `flush_startup_discord()` 每次開機最多清 8 筆），縮短的是單則通知的等待。
- 自動重啟的觸發判斷由「失敗數為門檻的整數倍」改為 `stall_checked_failures`／`stall_checked_threshold` latch：同一組（失敗數，門檻）只評估一次（冷卻檔因此仍維持每次失敗才讀一次，而非每輪主迴圈都讀），失敗數或門檻任一改變就重新評估。這是門檻可隨狀態變動的前提——使用者離開書桌使門檻下降時必須立即重評，而非等到下一次失敗；同時消除了原本「被 uptime gate 或冷卻擋掉一次就得等到下一個倍數、延遲加倍」的耦合。`DISCORD_STALL_MIN_UPTIME_MS` 維持 5 分鐘，但不再需要與門檻對齊，只需長於啟動通知窗口加一次重試。
- `discord_diag.log` 的 `autoreset` 記錄與對應 console 訊息加註觸發當下的在席狀態（`away`／`present`），否則事後無法把失敗次數對回是哪一個門檻。
- 因記憶體不足自動重開機後，若 LAN IP 與重啟前相同，開機不再送出「已上線」通知。那次重啟買到的是唯一一個可用的 TLS 窗口，而啟動階段原本第一件事就是重發一則使用者早已知道的 IP 通知，把窗口用掉、pending 在席通知只能再等下一次重啟（至少 2 小時）。現在 `_check_discord_stall()` 會在 `machine.reset()` 前把當下**已公告過**的 IP 寫入 `discord_autoreset_ip.log`，`main.py` 在啟動窗口讀取後立即刪除：IP 相同就跳過通知並標記為已送（避免 controller 每 30 秒重試），把窗口讓給 `flush_startup_discord()`。只有確實送出過的 IP 會被記錄——從未公告成功的位址仍照常嘗試，否則使用者根本無從得知裝置在哪；記錄採讀取即消費（且在「是否連上網路」判斷之外執行，避免一次沒連上線的開機把記錄留給後面某次本該公告的開機；刪除失敗時視為未消費並照常公告），因此手動斷電重開或 IP 真的改變時都會照常送出。

### Added

- `tests/test_app_controller.py` 新增 `test_a_touch_landing_on_a_preview_pass_is_not_swallowed`，斷言預覽輪的觸控仍會傳給 `handle_touch()`。`get_touch_state()` 會從驅動層取走事件且不會在下一輪重播，因此改為每輪讀取觸控之後，觸控處理必須與渲染分支解耦，否則預覽剛好落在同一輪時會吞掉一次圖片切換。
- `tests/test_app_controller.py` 新增保底重啟的防迴歸測試：`test_no_reset_at_the_away_threshold_while_present` 與 `test_unknown_presence_uses_the_present_threshold`（在席與狀態未知時不得套用離席門檻）、`test_reset_still_fires_while_present_at_the_slower_threshold`（在席安全網仍在，光感誤判時不會永遠卡住）、`test_leaving_the_desk_re_evaluates_a_count_already_checked`（門檻下降立即重評，不等下一次失敗）、`test_cooldown_file_is_read_once_per_failed_attempt` 與 `test_a_count_that_restarts_from_zero_is_checked_again`（latch 的節流與重置語意）、`test_reset_does_not_wait_for_a_multiple_of_the_threshold`（非倍數的失敗數同樣會觸發）、`test_a_pending_session_alone_is_enough_to_reboot`、`test_a_failing_panel_does_not_take_the_stall_check_down_with_it`（清屏失敗不得終止主迴圈）。`test_uptime_gate_outlasts_the_startup_window` 取代原本的倍數餘裕斷言，改為要求 uptime gate 長於啟動通知窗口加一次重試。
- `tests/test_app_controller.py` 新增四個顯示收斂的防迴歸測試：`test_starting_up_already_away_clears_and_sleeps_the_panel_once`（暗處開機時沒有轉換也要清屏睡眠，且只做一次）、`test_previews_arriving_while_away_never_bypass_the_away_branch`（離席期間的連續預覽不得喚醒已睡眠的面板）、`test_previews_while_present_do_not_starve_the_housekeeping`（在席期間的連續預覽不得讓 presence 更新、環境取樣與 stall 檢查停擺）、`test_unknown_presence_state_is_treated_as_away`（`current_state` 為 `None` 時 fail closed）。

## [2.6.0] - 2026-07-25

本版本修復 Discord 通知在裝置長時間運行後永久堵塞的問題，並將專案顯示名稱統一為 Pico Paper Clock。

### Fixed

- 修正 Discord 通知在裝置連續運行多日後永久送不出去、只有重開機才能恢復的問題。根因為 heap 碎片化：TLS handshake 需要一塊約 18–23 KiB 的**連續**記憶體，而裝置運行時 `gc.mem_free()` 雖有約 57 KiB，最大連續區塊卻僅約 17.9 KiB。實機量測顯示最大連續區塊為 17,920 B 時 `ssl.wrap_socket` 直接拋出 `OSError [Errno 12] ENOMEM`，23,120 B 時才成功；既有的 `release_display_workspace()` 僅能多騰出約 5.2 KiB，安全邊際極薄。舊版 `flush_discord()` 在 ENOMEM 後只會每 60 秒無限重試，沒有任何逃生路徑。
- 修正 `send_presence_summary()` 丟棄 Discord HTTP 錯誤回應內容的問題，失敗時無法得知實際原因；現與其他兩個送信函式一致會記錄回應內容。

### Added

- `discord_notifier.py` 新增 TLS 記憶體探針 `has_tls_headroom()` 與 `largest_contiguous_block()`。`presence_manager.flush_discord()` 在釋放顯示工作區之後、送信之前執行 pre-flight 檢查，連續記憶體低於 `TLS_MIN_CONTIGUOUS_BYTES`（20 KiB）時直接跳過本次嘗試，避免耗費約 3 秒在必定失敗的 TLS handshake 上。記憶體探針之前會先以新增的 `delivery_blocked()` 判斷 webhook 是否設定、網路是否連線，確保「未設定 webhook」或「斷網」不會被誤記為記憶體不足而觸發幫不上忙的重開機；三個送信函式共用同一份判斷。
- 新增持久化診斷日誌 `discord_diag.log`（上限 6 KiB，超過時以串流方式捨棄較舊的一半，並比照既有 `_commit_tmp` 以 `.bak` 交換，斷電時必留一份可讀副本）。記錄送信失敗原因、當下可用記憶體與最大連續區塊，讓失敗不再只 `print` 到 UART 而在斷電後遺失。記錄採節流策略：第 1 次失敗與其後每 10 次各記一筆。失敗原因分為 `lowmem`／`enomem`（記憶體）與 `http<狀態碼>`／`offline`／`nowebhook`／`badformat`／`baddata`（非記憶體），可直接判讀故障類型。
- 新增保底自動重啟：**僅限記憶體類失敗**（pre-flight `lowmem` 與送信 `ENOMEM`）連續達 30 次、仍有 pending 通知、且開機已滿 10 分鐘時執行 `machine.reset()`，藉由重開機取回連續 heap。HTTP 錯誤、斷網、未設定 webhook 等非記憶體失敗會將此計數歸零，不會觸發重啟——重開機無法修好一個被刪除的 webhook。多重防護：pending 通知未能寫入 flash 時放棄重啟（避免遺失）；冷卻時間戳無法持久化時同樣放棄重啟（fail-safe，避免退化成 boot loop）；`discord_autoreset.log` 的時間戳在執行期即時評估，2 小時內不重複自動重啟。開機滿 10 分鐘的判定採用 latch，因為 MicroPython 的 `ticks_diff()` 僅在約 ±6.2 天內有效，而本次故障正好出現在約 12 天的運行之後。

### Changed

- 專案顯示名稱統一為 Pico Paper Clock，移除文件、Web UI 頁面、桌面工具與 Discord 上線通知中殘留的舊名 Pi Paper Clock。
- `GET /api/v1/device` 回傳的裝置識別字串由 `pi-paper-clock` 改為 `pico-paper-clock`。桌面圖片工具同時接受新舊兩種識別字串，因此尚未更新韌體的裝置仍可正常連線。

## [2.5.0] - 2026-07-22

### Added

- 新增環境（溫濕度）歷史記錄功能：`env_manager.py` 預設每 15 分鐘（可透過 `global.env_log.interval_min` 調整）取樣一次 DHT22，原始樣本保留 7 天、每日彙總保留 366 天，離開書桌、螢幕休眠時仍持續記錄；比照 `presence_manager.py` 的交易式寫入與視窗式裁切模式。
- 新增獨立的環境紀錄 WebUI 頁面 `/environment`，含日/週/月/年趨勢圖切換、今日溫濕度統計卡片與每日統計表格，以及對應的 `/api/env/status`、`/api/env/samples`、`/api/env/daily` 串流 API（見 `docs/ENV_LOG_API.md`）。
- 新增 `tools/pico_deploy/upload_cli.py --mpy` opt-in 部署選項：部署前用 `mpy-cross` 將 `.py` 預編譯為 `.mpy` bytecode 節省裝置 flash（`epaper.py`／`main.py`／`config.json` 除外），同步加入桌面 GUI 勾選框；實測裝置剩餘 flash 從 88.0 KiB 提升到 204.0 KiB。
- Discord pending 通知佇列（`presence_pending.log`／`presence_session_pending.log`）新增 7 天保留視窗裁切，避免 webhook 長期失效時無限累積。

## [2.4.1] - 2026-07-21

### Fixed

- 修正 Discord 書桌前時段與每日統計通知在主迴圈建立 pending queue 後，被空 queue 的 cooldown 錯誤延後 flush 的問題。

## [2.3.0] - 2026-07-17

### Added

- 新增整合式 Pico Paper Clock 桌面 GUI，合併 USB/`mpremote` 資源部署、LAN/AP 圖片批次上傳、manifest 預覽與作業佇列。
- 新增完整同步流程：序列部署重啟後輪詢裝置網路，恢復連線後再執行圖片上傳。

### Changed

- 序列部署 manifest 與 mpremote 執行核心可由 GUI 與 `upload.py` 共用；GUI 預設不清理裝置、不覆寫 `config.json`。
- GUI 序列埠改為掃描後以下拉選單選取，WebUI 帳號固定為 `admin`；LAN discovery 改用 ARP 候選逐一探測並排除 link-local 網段，降低 Pico WebUI 被掃描壓垮的風險。
- 完整同步加入 Pico 重啟後的啟動寬限期與短 timeout 網路重試，適配實機 Wi-Fi／WebUI 初始化時間。
- PyInstaller 桌面工具改名為 `PicoPaperClockTool`，並保留 Python/CLI 入口。

### Fixed

- 修正 Pico WebUI 登入回應中 `Set-Cookie` header 變數覆蓋 JSON body，導致圖片工具收到 cookie 字串而無法建立 session 的問題。
- 修正 Linux CI runner 執行 Windows subprocess console-hide 測試時缺少 `STARTUPINFO` 造成的跨平台失敗。

## [2.2.0] - 2026-07-17

本版本聚焦於圖片工作流程、Pico W 記憶體穩定性、儲存空間使用量與 WebUI 使用體驗。

### Added

- 新增書桌前分析儀表板，提供即時在席狀態、24 小時/30 天統計、年度熱力圖、每日紀錄與最近時段。
- 新增登入、設定、書桌前分析與圖片庫的完整裝置 WebUI 流程。

### Changed

- 更新 Pico Image Tool 的圖片轉換、壓縮、預覽與認證上傳流程，並與裝置端圖片 API 的交易寫入和復原機制整合。
- 以可重用 buffer、串流處理、低記憶體 Discord queue flush 與 ENOMEM retry 降低啟動、網路、天氣和圖片操作的記憶體峰值。
- 新增 PPC1 圖片壓縮格式與 WebUI gzip 資產壓縮，降低圖片、天氣圖示與裝置 WebUI 的儲存空間使用量。
- 重新設計 AP/LAN WebUI，統一設定、圖片庫與分析頁面的視覺風格，並加入深色/淺色主題切換與更完整的響應式版面。
- 改善天氣預報顯示與書桌前分析的日期、熱力圖導覽及資料序列化。

### Documentation

- 更新 README 的專案定位與 WebUI 預覽，並歸檔四張 WebUI 截圖。

## [2.1.1] - 2026-07-13

- 修正 v3 外殼 STL Release asset，確保附件與 Git 歷史中追蹤的 `hardware/clock_v3.STL` 完全一致。
- 同步 Release asset 文件中的檔名、SHA-256 與下載連結。

## [2.1.0] - 2026-07-13

本版本發布目前 `Unreleased` 中的功能、穩定性修正與主機端圖片工具；UF2 與 v3 外殼的 STEP、STL、SLDPRT 檔案改由 GitHub Release assets 提供。

### Added
- 新增低記憶體圖片 API、`/images` 裝置管理頁與圖片交易復原。
- 新增 Pico Image Tool GUI/CLI、LAN 探索、四種抖動、三種 fit 與 Windows PyInstaller build 規格。
- 新增圖片格式與交易 golden tests。

### Changed
- AP/LAN Web server 共用同一 dispatcher；設定頁改用靜態 HTML 與版本化設定 API。
- 顯示改為單一 native framebuffer、逐列圖片讀取與批次 SPI 傳輸。
- 設定保存改為 schema v3 單次交易，presence pending queue 改為串流處理。
- 啟動網路流程改為先完成 Discord webhook，再載入顯示、硬體、天氣與 controller 工作路徑，降低 Pico W TLS 的記憶體配置峰值。
- Discord webhook 改用低配置 raw HTTPS socket，並在 partial write、socket close、GC 與 ENOMEM retry 上加入防護。
- DHT22 讀取加入 2500 ms 節流、失敗 10 秒 backoff 與舊值快取；天氣預報改用 256-byte buffer 和 `readinto()` 串流解析。
- 大型 UF2 與 CAD（`.SLDPRT`、`.step`、`.stl`）檔案移出 source tree，改由 GitHub Release assets 發布。

### Fixed
- `image_interval_min` 現在實際控制輪播間隔，日期事件圖片會依生日、MMDD、custom 優先序顯示。
- MONO_HLSB 明確採 bit 0 為左側像素，避免每 8 像素位元順序錯誤。
- 修復 Pico W 在 Discord webhook 與 presence 發送時的 `ENOMEM`：失敗不再中止啟動流程或永久丟棄 pending presence，並可在冷卻後重試。

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
