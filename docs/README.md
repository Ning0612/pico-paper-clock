# Pi Paper Clock 文件索引

這個目錄收納需要長期維護的使用、設定、API 與架構文件；根目錄的 `README.md` 只保留專案介紹、快速開始與文件導覽，`AGENTS.md` 與 `CLAUDE.md` 保留給開發流程。

## 文件

- [架構與資料夾地圖](ARCHITECTURE.md) — 裝置資料流、記憶體邊界、圖片格式相容策略與維護規則。
- [硬體與接線](HARDWARE.md) — 元件、Pin map、感測器與蜂鳴器接線。
- [安裝、部署與 AP 設定](SETUP_GUIDE.md) — 主機環境、MicroPython、`upload.py`、AP Web UI 與驗證。
- [設定指南](CONFIG_GUIDE.md) — schema v3、多設定檔、範圍與交易式保存。
- [圖片資產與轉換](IMAGE_GUIDE.md) — 資產目錄、尺寸、事件命名與 GUI/CLI。
- [圖片 API](IMAGE_API.md) — 裝置圖片列表、上傳、預覽、刪除與認證契約。
- [Release assets](RELEASE_ASSETS.md) — GitHub Release 的 UF2、CAD 檔案與發布檢查表。

## 來源與生成物

- Web UI 原始碼位於 `tools/html_src/`。
- 執行 `tools/build_html.py` 生成 `src/html/*.bin`；不要直接編輯生成物。
- 圖片轉檔與 WebUI client 位於 `tools/pico_image_tool/`；Pico USB 部署核心與整合 GUI 位於 `tools/pico_deploy/`，入口為 `tools/pico_image_cli.py` 與 `tools/pico_image_gui.py`。

## 維護原則

1. API、設定欄位、硬體 pin 或資料夾變更時，更新對應詳細文件；根目錄 README 只維持摘要與入口連結。
2. 測試、PyInstaller 與 HTML 建置產物不放進 Git；`dist/` 僅作為本機交付物保留。
3. 既有使用者圖片、硬體 CAD 與網路上傳圖片不可因整理文件而刪除。
