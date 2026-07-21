# Pi Paper Clock Environment Log API

環境（溫濕度）歷史記錄 API，架構與認證模型與 [`IMAGE_API.md`](IMAGE_API.md) 一致：只透過區域 HTTP 提供，皆為 **GET-only、唯讀**，只需 WebUI session cookie，不需要 CSRF token（因為不會異動任何狀態）。Server 不提供 CORS 或 TLS，只應暴露在可信任的 AP/LAN。

## 資料來源

DHT22 感測器每 `env_log.interval_min`（預設 15 分鐘，設定於 `global.env_log`，見 [`CONFIG_GUIDE.md`](CONFIG_GUIDE.md)）取樣一次，寫入 `env_events.log`（原始樣本）；每日 00:00 換日時彙總成一筆 `env_daily.log`（每日 min/max/avg），同時裁切掉 7 天前的原始樣本與 366 天前的每日彙總。裁切只在換日當下執行，不是即時保證——裝置斷電/關機一段時間後重開機，`env_events.log` 中舊資料要等到下一次換日才會被裁掉，這段期間查詢可能看到超過 7 天的資料。取樣獨立於在席狀態與畫面更新，離開書桌、螢幕休眠時仍會持續記錄。

## Collections

| Path | 方法 | 說明 |
|---|---|---|
| `/environment` | GET | 環境紀錄 WebUI 頁面（gzip 過的靜態頁面） |
| `/api/env/status` | GET | 目前溫濕度與今日 min/max/avg 統計 |
| `/api/env/samples` | GET | 原始樣本串流（保留視窗 7 天，於每日換日時裁切，非即時保證，見下方「資料來源」） |
| `/api/env/daily` | GET | 每日彙總串流（保留視窗 366 天，同上） |

## `/api/env/status`

```json
{
  "temp": 24.5, "hum": 55.2,
  "current_date": "20260721",
  "t_min": 22.1, "t_max": 26.8, "t_avg": 24.3,
  "h_min": 48.0, "h_max": 60.5, "h_avg": 54.1,
  "count": 18,
  "now_epoch": 1784712000
}
```

裝置尚未完成第一次取樣時，`temp`/`hum`/`t_min`/`t_max`/`t_avg`/`h_min`/`h_max`/`h_avg` 為 `null`、`count` 為 `0`。

## `/api/env/samples`、`/api/env/daily`

與 presence 的 `/api/desk/timeline`、`/api/desk/daily` 相同，使用 bounded streaming（逐行讀取＋512 bytes chunk 傳送），不會把整份 log 讀進記憶體。

`/api/env/samples` 回傳陣列，每筆為單一原始樣本：
```json
{"d":"20260721","tm":"1415","t":25.4,"h":58.0,"e":1784721300}
```

`/api/env/daily` 回傳陣列，每筆為單日彙總：
```json
{"d":"20260721","tmin":22.1,"tmax":29.8,"tavg":25.6,"hmin":45.0,"hmax":61.0,"havg":53.2,"n":96}
```

損壞或欄位不足的 log 行會被跳過，不會中斷串流。

## 錯誤與認證

未登入存取任何 `/api/env/*` 端點回傳 `401 {"error":"auth_required"}`；存取 `/environment` 頁面則導向 `/login`。裝置管理員密碼尚未設定時，所有端點皆視為需要先完成首次設定。
