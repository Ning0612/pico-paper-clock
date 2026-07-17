# Release assets

大型硬體／韌體發行檔不再提交到 source tree，避免一般 clone 下載不必要的大檔。建立 GitHub Release 時，請從本地 `dist/release-assets/` 附加下列檔案：

| 檔案 | 用途 | SHA-256 |
|---|---|---|
| `pico-paper-clock-micropython-1.24.1.uf2` | 專案驗證過的 Pico W MicroPython 韌體 | `BF869821B59A13DE3F7FA0C3CC1592F9AF4BD41CE571D919C2577D47B6CE540E` |
| `pico-paper-clock-v3-case.SLDPRT` | 3D 外殼 v3 SolidWorks 原始檔 | `825F8771BFB83B546339FB9DD2A3BECAF4726A15A73193B73C40BA8F4E62ECCB` |
| `pico-paper-clock-v3-case.step` | 3D 外殼 v3 跨 CAD 編輯格式（通常相容性較佳） | `B7944ACD80E12A1994B8FEF3095A4F0243009CB6D9F242BA05F93782E54D6B6E` |
| `pico-paper-clock-v3-case.stl` | 3D 外殼 v3 列印／切片網格 | `4F5417BE263C1B98F8B7706EE529E4FB1154C11D15F5A0BFEFF1943EA877FC01` |
| `pico-paper-clock-tool-v2.3.0-windows-x64.exe` | Pico 部署工具 Windows x64 GUI | `A4706A0CE383AB3B8F6D2E6920B04E402BC27E4EE931ED709E0201108B921C1B` |

UF2 與三個 CAD 檔目前掛在 [v2.1.1 GitHub Release](https://github.com/Ning0612/pico-paper-clock/releases/tag/v2.1.1)；桌面部署工具 EXE 隨對應版本發布，目前掛在 [v2.3.0 GitHub Release](https://github.com/Ning0612/pico-paper-clock/releases/tag/v2.3.0)。UF2 也可直接使用 [MicroPython 官方 Pico W 下載頁](https://micropython.org/download/RPI_PICO_W/) 的版本。

## CAD 格式建議

- 一般 CAD 使用者優先下載 `.step`，通常能在不同 CAD 工具間保留較好的可編輯幾何。
- 要直接列印時下載 `.stl`，它是已離散化的三角網格，不適合精確修改尺寸。
- 使用 SolidWorks 且需要原生特徵樹時才下載 `.SLDPRT`。
- 三種 CAD 檔都只放在 Release assets；source tree 不保留大型發行檔。

## 桌面工具

v2.3.0 起可附加 Windows x64 桌面工具：

`pico-paper-clock-tool-v2.3.0-windows-x64.exe`

這個 EXE 提供序列資源部署與 LAN/AP 圖片批次上傳，但不內建使用者的 `config.json`、客製圖片或 repository 資源。使用序列部署前，使用者必須選擇含有 `src/` 的 repository/source zip 目錄。Release notes 應同時列出 EXE 的 SHA-256。

## 發布檢查表

1. 建立版本 tag 與 GitHub Release。
2. 將 `dist/release-assets/` 中該次發布涉及的檔案附加到該 Release（韌體/CAD 變更時附 UF2 與三個 CAD 檔；桌面工具變更時附對應版本的 EXE）。
3. 發布後確認附加的檔案連結可下載。
4. 若更換韌體版本、CAD 檔或桌面工具版本，更新本文件（含檔名、SHA-256 與對應 Release tag 連結）、README 與 CHANGELOG。

`dist/` 已被 `.gitignore` 忽略；請勿將這些檔案重新放回 `firmware/` 或 `hardware/` 後提交。
