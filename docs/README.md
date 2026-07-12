# Pi Paper Clock 文件索引

這個目錄收納需要長期維護的設定、API 與架構文件；根目錄的 `README.md` 保留給首次使用者，`AGENTS.md` 與 `CLAUDE.md` 保留給開發流程。

## 文件

- [架構與資料夾地圖](ARCHITECTURE.md) — 裝置資料流、記憶體邊界、圖片格式相容策略與維護規則。
- [設定指南](CONFIG_GUIDE.md) — schema v3、多設定檔、範圍與交易式保存。
- [圖片 API](IMAGE_API.md) — 裝置圖片列表、上傳、預覽、刪除與認證契約。

## 來源與生成物

- Web UI 原始碼位於 `tools/html_src/`。
- 執行 `tools/build_html.py` 生成 `src/html/*.bin`；不要直接編輯生成物。
- 桌面圖片工具核心位於 `tools/pico_image_tool/`，入口為 `tools/pico_image_cli.py` 與 `tools/pico_image_gui.py`。

## 維護原則

1. API、設定欄位或資料夾變更時，同步更新本目錄文件與根目錄 README 的入口連結。
2. 測試、PyInstaller 與 HTML 建置產物不放進 Git；`dist/` 僅作為本機交付物保留。
3. 既有使用者圖片、硬體 CAD 與網路上傳圖片不可因整理文件而刪除。
