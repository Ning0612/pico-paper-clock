# Release assets

大型硬體／韌體二進位檔不再提交到 source tree，避免一般 clone 下載不必要的大檔。建立 GitHub Release 時，請從本地 `dist/release-assets/` 附加下列檔案：

| 檔案 | 用途 | SHA-256 |
|---|---|---|
| `RPI_PICO_W-20241129-v1.24.1.uf2` | 專案驗證過的 Pico W MicroPython 韌體 | `BF869821B59A13DE3F7FA0C3CC1592F9AF4BD41CE571D919C2577D47B6CE540E` |
| `clock.SLDPRT` | 3D 外殼 SolidWorks 原始檔 | `2BB9FB533CD4C6A7B59561831973F2EBCBD6719641FA0E25ED296561AE3A0503` |
| `clock_v3.SLDPRT` | 3D 外殼 v3 SolidWorks 原始檔 | `0D42FFE36997F96E270AA36FB4F4212C47BAA31FE8A894331782D00D039FCC7D` |

對應 Release 建立並發布後，使用者可從 [GitHub Releases](https://github.com/Ning0612/pico-paper-clock/releases) 下載 release assets；UF2 也可直接使用 [MicroPython 官方 Pico W 下載頁](https://micropython.org/download/RPI_PICO_W/) 的版本。

## 發布檢查表

1. 建立版本 tag 與 GitHub Release。
2. 將 `dist/release-assets/` 中的三個檔案附加到該 Release。
3. 發布後確認 UF2 與兩個 `.SLDPRT` 連結可下載。
4. 若更換韌體版本或 CAD 檔，更新本文件、README 與 CHANGELOG 的檔名。

`dist/` 已被 `.gitignore` 忽略；請勿將這些檔案重新放回 `firmware/` 或 `hardware/` 後提交。
