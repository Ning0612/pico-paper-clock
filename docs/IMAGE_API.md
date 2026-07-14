# Pi Paper Clock Image API v1

API 只透過區域 HTTP 提供。`GET /api/v1/device` 允許未驗證探索；裝置完成首次設定後，所有圖片清單與異動都需要 WebUI session cookie。`PUT`、`POST`、`DELETE` 另需 `X-Pico-Clock-API: 1` 與 session CSRF token。Server 不提供 CORS 或 TLS，只應暴露在可信任的 AP/LAN。

首次設定時，瀏覽器先以 `GET /api/v1/auth/status` 取得 per-boot CSRF token，再以 `POST /api/v1/auth/login` 設定固定帳號 `admin` 的管理密碼或登入。成功後回傳 `HttpOnly; SameSite=Strict` 的 `session` cookie 與 session CSRF token。裝置只保留一組 server-side session slot；新登入會使舊 session 失效，閒置 30 分鐘或絕對時間 24 小時後過期，重開機、登出或變更密碼也會失效。

## 探索

`GET /api/v1/device` 回傳固定的 `device: "pi-paper-clock"`、整數 `api_version: 1`、可用 heap/storage 與圖片尺寸。Client 必須拒絕未知 device 或 API 版本。

## Collections

| Collection | Resource | 大小 |
|---|---|---:|
| custom | `/api/v1/images/custom/{name}.bin` | 2,048 bytes |
| login | `/api/v1/images/login/{name}.bin` | 4,736 bytes |
| events | `/api/v1/images/events/{MMDD|birthday}/{name}.bin` | 2,048 bytes |

名稱由 1–48 個 ASCII 字母、數字、`_`、`-` 加上 `.bin` 組成。Payload 是無檔頭 `MONO_HLSB`，每個 packed byte 的 bit 0 代表最左側像素。裝置會以內部 `.hlsb` sidecar 標記 API 上傳檔；桌面工具另存時也會產生 `<name>.bin.hlsb`，serial／手動部署須一併複製。無 marker 的既有圖片仍按舊版 MSB-left 讀取，不需要破壞性遷移。

## 圖片操作

- `GET /api/v1/images?collection=custom|login|events&event=MMDD|birthday` 串流回傳 JSON `items`、`fs_free`、`catalog_generation`。
- `PUT <resource>?overwrite=0|1&preview=0|1` 需要 `application/octet-stream` 與精確 `Content-Length`。裝置先寫 `.part`、sync，再以 `.bak` 替換；開機會復原中斷交易。
- `DELETE <resource>` 刪除一張圖片並立即使 catalog 失效。
- `POST <resource>/preview` 排入一次電子紙預覽，不改變輪播順序。

錯誤 body 為包含 `error` 與 `message` 的短 JSON；常見 status 為 `400`、`401`、`404`、`409`、`411`、`413`、`500`、`507`。

## 設定 Web API

- `GET /api/v1/config[?profile=name]` 回傳已遮蔽的 profile、profile 名稱、active profile、CSRF token 與「secret 已設定」布林值，永不回傳儲存的密碼、API key 或 webhook。
- `GET /api/v1/networks` 執行即時 Wi-Fi 掃描並回傳可見網路；掃描失敗回 `500`，不會修改既有設定。
- `POST /api/v1/config` 接受最多 4 KiB `application/x-www-form-urlencoded`，需要 CSRF token，驗證數字範圍，單次交易保存後排程重啟。空白 secret 欄位會保留原值。

所有受保護的 LAN/AP 設定 API 都需要 session cookie。設定異動、圖片異動與危險操作只接受 POST/PUT/DELETE，並驗證 `X-CSRF-Token`；圖片異動仍必須帶 `X-Pico-Clock-API: 1`。HTTP 沒有傳輸加密，session token 與 CSRF token 可能被同網段攻擊者攔截重放，請限制在可信任的隔離網路。
