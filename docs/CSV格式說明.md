# CSV 格式說明

本文件說明 [pump_monitor](../pump_monitor/) 產生的 3 種 CSV 檔案的欄位、單位、取樣率與載入方式，方便後續深度學習訓練腳本介接。

> **2026-05-06 更新**：高頻 CSV 由原本「每 motor 一檔」改為「每 cycle 一檔」（兩台馬達合併以欄位區分），減少檔案數與檔名解析。

## 檔案總覽

每跑一輪 `Tpoll = 600 s` 的 cycle，pipeline 會產出：

| 檔案 | 路徑 | 模式 | 列數 / cycle | 欄位數 |
|---|---|---|---|---|
| `vibration_sensor_<ts>.csv` | `data\machine1\` | 每 cycle 新檔 | 100,000 (10 kHz) | 5 |
| `electrical_sensor_<ts>.csv` | `data\machine2\` | 每 cycle 新檔 | 50,000 (5 kHz)  | 13 |
| `low_freq_sensor.csv` | `data\` | append（全程同一檔） | +1 | 5 |

`<ts>` 為 `YYYYMMDD_HHMMSS`（cycle 起始時刻），兩個高頻檔共用同一個 `<ts>`，方便配對。

**通用約定：**
- 第 1 列為欄位定義 (header)，第 2 列起為資料
- 編碼 UTF-8、`,` 分隔、無引號、`\n` 換行（[csv.writer](https://docs.python.org/3/library/csv.html) 預設）
- 缺值寫字串 `NaN`（pandas/numpy 預設可解析回 `nan`）
- 浮點數預設 `%.6f`（小數 6 位）

---

## 1. `vibration_sensor_<ts>.csv`

machine1 取得的振動 CSV，**單檔含兩台馬達 X/Y 共 4 軸**。

### 欄位

| 欄位 | 單位 | 說明 |
|---|---|---|
| `t_s` | 秒 | 取樣內**相對時間**，從 0 起步、間隔 1 / `actual_sample_rate_hz`（理論 `1e-4 s`） |
| `motor1_x_g` | g（9.81 m/s²） | motor1 X 軸加速度，正方向同感測器標示 |
| `motor1_y_g` | g | motor1 Y 軸加速度 |
| `motor2_x_g` | g | motor2 X 軸加速度 |
| `motor2_y_g` | g | motor2 Y 軸加速度 |

### 範例

```csv
t_s,motor1_x_g,motor1_y_g,motor2_x_g,motor2_y_g
0.000000,0.079346,0.103760,0.399780,0.091553
0.000096,0.079346,0.088501,0.204468,0.137329
0.000192,0.058593,0.072021,0.143433,0.131226
...
```

### 訊號鏈與轉換

`raw_int16 → V_ADC → accel_g`：

$$\text{accel}_g = \text{raw}_{\text{int16}} \times \frac{10}{32768} \times \frac{1}{(\text{ACCEL\_SENSITIVITY\_MV\_PER\_G}/1000) \times \text{SG3227\_GAIN}}$$

預設假設 603C01 = 100 mV/g、SG-3227 DIP gain = ×1，故衍生係數 `IEPE_G_PER_V = 10.0`。可在 [config.py](../pump_monitor/config.py) 透過 `ACCEL_SENSITIVITY_MV_PER_G` 與 `SG3227_GAIN` 調整。

### 取樣率

`M1_RATE = 10000 Hz/ch`（4 通道 → aggregate 40 kS/s 對 I-8014W 寬鬆）。實測 actualSampleRate ≈ 10417 Hz（I-8014W 多通道下無法精準鎖到 10kHz；header 已誠實回報，CSV 的 `t_s` 已用 actual rate 計算）。每 cycle 100,000 樣本（10 秒）。

### 絕對時間

由檔名 `<ts>` 提供。若需要每筆樣本的 UNIX timestamp，可在 loader 端用：

```python
from datetime import datetime
ts0 = datetime.strptime(filename.split('_')[-2] + filename.split('_')[-1].split('.')[0],
                        "%Y%m%d%H%M%S").timestamp()
abs_unix = ts0 + df['t_s']
```

---

## 2. `electrical_sensor_<ts>.csv`

machine2 取得的三相電壓 / 電流 CSV，**單檔含兩台馬達各 3 相 V + 3 相 I 共 12 個訊號**。

### 欄位

| 欄位 | 單位 | 說明 |
|---|---|---|
| `t_s` | 秒 | 同振動 |
| `motor1_V_a_V`, `motor1_V_b_V`, `motor1_V_c_V` | V | motor1 三相電壓（DNM-843，預設 ×80，量程 ±800V） |
| `motor1_I_a_A`, `motor1_I_b_A`, `motor1_I_c_A` | A | motor1 三相電流（DNM-844，預設 ×100，量程 ±1000A） |
| `motor2_V_a_V`, `motor2_V_b_V`, `motor2_V_c_V` | V | motor2 三相電壓 |
| `motor2_I_a_A`, `motor2_I_b_A`, `motor2_I_c_A` | A | motor2 三相電流 |

### 範例

```csv
t_s,motor1_V_a_V,motor1_V_b_V,motor1_V_c_V,motor1_I_a_A,motor1_I_b_A,motor1_I_c_A,motor2_V_a_V,motor2_V_b_V,motor2_V_c_V,motor2_I_a_A,motor2_I_b_A,motor2_I_c_A
0.000000,574.78,0.90,-576.64,-126.62,15.05,15.17,0.49,-0.34,-2.69,999.97,999.97,999.97
0.000096,...
```

### 訊號鏈與轉換

```
V = raw_int16 × (10 / 32768) × DNM843_GAIN   # 預設 80 (DNM-843VI-800V)
I = raw_int16 × (10 / 32768) × DNM844_GAIN   # 預設 100 (DNM-844-1000A)
```

I-8014W 12 通道排列為配對 `[m1_V, m1_I, m2_V, m2_I]`（[decoder.split_machine2](../pump_monitor/decoder.py)）。如更換 DNM 變體，調整 `DNM843_GAIN` / `DNM844_GAIN`。

### 取樣率

`M2_RATE = 5000 Hz/ch`（12 通道 → aggregate 60 kS/s；I-8014W 在 12 ch × 10 kHz = 120 kS/s 會 FIFO overflow，5 kHz 為安全帶）。實測 actualSampleRate ≈ 5208 Hz。每 cycle 50,000 樣本（10 秒）。

> **注意**：machine2 的列數是 50,000，比振動 CSV 的 100,000 少一半，因為 RATE 較低。讀檔時應以 `t_s` 欄為準，不可假設與振動同樣列數。

---

## 3. `low_freq_sensor.csv`

全程 append 模式的單一檔，每 cycle 多一列。記錄壓力（DCT 531）+ 溫度（ET-2215H 8 通道）。

### 欄位

| 欄位 | 單位 | 說明 |
|---|---|---|
| `timestamp` | ISO-8601 字串 | cycle 起始時刻，e.g. `2026-05-06T16:43:16` |
| `pressure_motor1_bar` | bar | machine1 RTU1（slave id 1）讀回的 motor1 出口壓力；RTU 失敗 → `NaN` |
| `pressure_motor2_bar` | bar | machine1 RTU2（slave id 2）讀回的 motor2 出口壓力；同上 |
| `temp_ch0_C`, `temp_ch1_C` | °C | ET-2215H ch0 / ch1 PT100 溫度；斷線（raw=-32768）→ `NaN`；FC04 失敗 → 全部 NaN（現場其餘 ch2~7 永久空接，不寫入 CSV；如增接，於 [config.py](../pump_monitor/config.py) 將 `ET_NUM_CHANNELS` 改大即會自動加欄） |

### 範例

```csv
timestamp,pressure_motor1_bar,pressure_motor2_bar,temp_ch0_C,temp_ch1_C,temp_ch2_C,temp_ch3_C,temp_ch4_C,temp_ch5_C,temp_ch6_C,temp_ch7_C
2026-05-06T16:43:16,1.234000,1.567000,25.000000,26.500000,24.800000,25.100000,25.300000,NaN,25.700000,26.000000
2026-05-06T16:53:16,1.241000,1.572000,25.100000,26.530000,24.820000,25.130000,25.310000,NaN,25.720000,26.030000
```

### 取樣率

每 600 s 一列。連續運行 24 小時 → 144 列。

### 注意事項

- pressure 已由 agent 端解 Modbus-RTU 取得 IEEE754 float（[daq_agent_wince.cpp:496-515](../daq-cpp-code/daq_agent_wince.cpp#L496-L515)），單位由 DCT 531 的 register `0x44` 決定，預設 bar；若現場改設成 MPa 或 PSI 請於文件中追記
- 溫度通道對應的 PT100 安裝位置（哪顆對應 motor1 軸承 / motor2 馬達線圈等）請依現場接線記錄為附錄
- 即使三任務全部失敗，`low_freq_sensor.csv` 仍會 append 一列 `timestamp + NaN×10`，保留時間軸連續性

---

## 載入範例

### numpy（高頻 CSV）

```python
import numpy as np

# 振動：5 cols
data = np.loadtxt(
    r"C:\Users\USER\Desktop\data\machine1\vibration_sensor_20260506_174846.csv",
    delimiter=",", skiprows=1
)
t = data[:, 0]
m1_x, m1_y = data[:, 1], data[:, 2]
m2_x, m2_y = data[:, 3], data[:, 4]

# 電氣：13 cols
data = np.loadtxt(
    r"C:\Users\USER\Desktop\data\machine2\electrical_sensor_20260506_174846.csv",
    delimiter=",", skiprows=1
)
t = data[:, 0]
m1_VI = data[:, 1:7]    # Va, Vb, Vc, Ia, Ib, Ic
m2_VI = data[:, 7:13]   # Va, Vb, Vc, Ia, Ib, Ic
```

### pandas（推薦於 EDA / dataset 組裝階段）

```python
import pandas as pd

df_vib = pd.read_csv(r"...\vibration_sensor_20260506_174846.csv")
df_ele = pd.read_csv(r"...\electrical_sensor_20260506_174846.csv")

# 取單一 motor 的子集
m1_cols = [c for c in df_ele.columns if c.startswith("motor1_") or c == "t_s"]
df_m1   = df_ele[m1_cols]

df_low = pd.read_csv(r"...\low_freq_sensor.csv", parse_dates=["timestamp"])
df_low.set_index("timestamp", inplace=True)
print(df_low[["pressure_motor1_bar", "temp_ch0_C"]].describe())
```

### 配對載入同一 cycle 的高頻 + 低頻

```python
from pathlib import Path
import pandas as pd

base = Path(r"C:\Users\USER\Desktop\data")
ts   = "20260506_174846"

vib = pd.read_csv(base / f"machine1/vibration_sensor_{ts}.csv")
ele = pd.read_csv(base / f"machine2/electrical_sensor_{ts}.csv")

# 確認兩檔對齊
assert (vib["t_s"].values == ele["t_s"].values).all()
```

### 批次組合所有 cycle

```python
from pathlib import Path
import pandas as pd

base = Path(r"C:\Users\USER\Desktop\data")

# 所有振動 cycle 串接（每段 100k 列；內部記憶體 5 cols × 100k × 8B = 4 MB / cycle）
all_vib = pd.concat(
    pd.read_csv(p) for p in sorted(base.glob("machine1/vibration_sensor_*.csv"))
)

low = pd.read_csv(base / "low_freq_sensor.csv", parse_dates=["timestamp"])
```

---

## 檔案大小估算（10 kHz × 10 s × `%.6f`）

| 檔案 | 欄位數 | 大小 |
|---|---|---|
| 振動 (合併) | 5 | ≈ 4.7 MB |
| 電氣 (合併) | 13 | ≈ 13 MB |

每 cycle 2 個高頻檔 → ≈ 17.7 MB；以 Tpoll=600s 算 24 小時 144 cycle → ≈ 2.55 GB / 天（與舊 4 檔分離版本 ~2.8 GB 接近，因 t_s 欄位省一份）。

若磁碟壓力大，可：
1. 把 `numpy.savetxt(..., fmt="%.6f")` 改 `"%.4f"`（節省 ~30%）
2. 改用 parquet（需引入 `pyarrow` 依賴；體積壓 1/2~1/3）
3. 在外部腳本將舊 CSV 月底 zip 歸檔

預設保持 CSV 原始格式以維持對學生 / 教學環境的可讀性。
