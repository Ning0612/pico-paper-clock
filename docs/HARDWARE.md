# 硬體與接線

本文件記錄目前韌體使用的硬體配置。顯示器的控制腳位與觸控匯流排以 `src/epaper.py` 為準，感測器與按鈕以 `src/hardware_manager.py` 為準。

## 元件

| 元件 | 用途 |
|---|---|
| Raspberry Pi Pico W | 主控制器與 Wi-Fi |
| [Waveshare 2.9inch Touch e-Paper HAT](https://www.waveshare.net/wiki/Pico-CapTouch-ePaper-2.9) | 296 × 128 電子紙與觸控 |
| LDR + 33 kΩ 電阻 | 環境光感測 |
| DHT22 | 溫度與濕度 |
| 無源蜂鳴器 | 定時提示音 |

## Pin map

| 功能 | Pico 腳位 |
|---|---:|
| 電子紙 SPI1 | 使用 `SPI(1)` 的硬體預設腳位 |
| 電子紙 RST / DC / CS / BUSY | GP12 / GP8 / GP9 / GP13 |
| 觸控 TRST / INT | GP16 / GP17 |
| 觸控 I2C1 SCL / SDA | GP7 / GP6 |
| HAT 按鈕 1 / 2 / 3 | GP2 / GP3 / GP15 |
| LDR ADC | GP26 / ADC0 |
| DHT22 data | GP19 |
| 無源蜂鳴器 PWM | GP20 |

## 外接元件接線

### LDR 分壓

```text
3.3V ---- 33 kΩ 電阻 ----+---- GP26 (ADC)
                         |
                       LDR
                         |
                        GND
```

光線越強時 LDR 阻值越小；實際 `light_threshold` 請在裝置頁面查看 ADC 值後調整。

### DHT22

```text
3.3V ---- DHT22 VCC
GP19 ---- DHT22 DATA ---- 4.7 kΩ–10 kΩ 上拉至 3.3V
GND  ---- DHT22 GND
```

DHT22 讀取間隔由韌體限制為至少 2.5 秒；讀取失敗時會暫停重試並保留上一筆快取值。

### 無源蜂鳴器

```text
GP20 (PWM) ---- 蜂鳴器 +
GND           ---- 蜂鳴器 -
```

使用無源蜂鳴器，音高由 PWM 頻率控制；若使用的模組需要額外驅動電路，請依模組規格加裝。

## 相關文件

- [安裝、部署與 AP 設定](SETUP_GUIDE.md)
- [設定檔格式](CONFIG_GUIDE.md)
- [架構與資料夾地圖](ARCHITECTURE.md)
