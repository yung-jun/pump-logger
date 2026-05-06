"""
PT100 資料記錄器 - (P)ET-2215H / (P)ET-2215H-16
使用 Modbus TCP 讀取溫度，儲存為 .bin 檔案

依據：ET-2200 使用手冊 第 6.4.1 節 + 實測驗證
  - 溫度值暫存器：30000 ~ 30015  (0-based: 0 ~ 15)
  - 功能碼：FC04 (Read Input Registers)
  - 資料格式：16-bit signed integer，÷100 = 溫度 (°C)
    (Type 0x86 範圍 -10000~30000 對應 -100~300°C，故 ÷100)
  - 斷線時 raw = -32768 (0x8000)，網頁顯示 -9999.9
  - 斷線狀態位：Coil 00096 ~ 00111

安裝依賴：
    pip install pymodbus

.bin 檔案格式（每筆記錄固定 40 bytes）：
    [timestamp: float64 (8 bytes)] [CH0~CH7: float32 x 8 (32 bytes)]
    NaN 表示該通道斷線或讀取失敗
"""

import struct
import time
import os
import math
from datetime import datetime

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("請先安裝 pymodbus：pip install pymodbus")
    exit(1)

# ╔══════════════════════════════════════════╗
# ║              使用者設定區                ║
# ╚══════════════════════════════════════════╝
IP_ADDRESS   = "192.168.1.6"    # ET-2215H 的 IP 位址
PORT         = 502               # Modbus TCP Port（預設 502）
NUM_CHANNELS = 8                 # 通道數：ET-2215H = 8 / ET-2215H-16 = 16
INTERVAL_SEC = 600.0             # 採樣間隔（秒）：每10分鐘 (600秒) 存一次資料

# 儲存路徑與建立資料夾
SAVE_DIR     = r"C:\Users\USER\Desktop\data\temp"
os.makedirs(SAVE_DIR, exist_ok=True)  # 自動建立資料夾

_ts_str      = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE  = os.path.join(SAVE_DIR, f"pt100_data_{_ts_str}.bin")  # 輸出 .bin 檔案名稱

# ╔══════════════════════════════════════════╗
# ║           Modbus 暫存器定義              ║
# ║  依據手冊 6.4.1 節，位址皆為 0-based    ║
# ╚══════════════════════════════════════════╝
# FC04 Input Register：溫度值 (30000~30015 → 0-based: 0~15)
TEMP_REG_ADDR    = 0

# 斷線判斷閾值：raw = -32768 (0x8000) 代表斷線
# 網頁顯示 -9999.9，但 Modbus raw 值為 -32768
OPEN_CIRCUIT_RAW = -32768

# ╔══════════════════════════════════════════╗
# ║           .bin 檔案格式定義              ║
# ╚══════════════════════════════════════════╝
# 每筆記錄：[float64 timestamp] + [float32 x NUM_CHANNELS]
RECORD_FORMAT = ">" + "d" + "f" * NUM_CHANNELS
RECORD_SIZE   = struct.calcsize(RECORD_FORMAT)


# ══════════════════════════════════════════
def read_temperatures(client: ModbusTcpClient) -> list:
    """
    使用 FC04 一次讀取全部通道的溫度值。
    手冊 6.4.1：位址 30000~30015，0-based = 0~15
    資料格式：16-bit signed int，除以 100 = 攝氏溫度
    (Type 0x86: raw -10000~30000 對應 -100~300°C)
    斷線時 raw = -32768，回傳 float('nan')
    """
    for attempt in range(2):
        try:
            result = client.read_input_registers(
                address=TEMP_REG_ADDR,
                count=NUM_CHANNELS
            )
            break  # 讀取成功，跳出重試迴圈
        except Exception as e:
            if attempt == 0:
                # 可能是因為長時間閒置 (10分鐘) 導致設備主動斷開 TCP，嘗試重連
                try:
                    client.close()
                    client.connect()
                except:
                    pass
            else:
                print(f"  [錯誤] Modbus 重新連線後讀取仍失敗: {e}")
                return [float("nan")] * NUM_CHANNELS

    if result.isError():
        print(f"  [警告] FC04 讀取失敗：{result}")
        return [float("nan")] * NUM_CHANNELS

    temps = []
    for ch in range(NUM_CHANNELS):
        raw = result.registers[ch]

        # 16-bit unsigned to signed
        if raw >= 0x8000:
            raw -= 0x10000

        # 斷線判斷
        if raw == OPEN_CIRCUIT_RAW:
            temps.append(float("nan"))
        else:
            temps.append(raw / 100.0)

    return temps


# ══════════════════════════════════════════
def write_record(f, timestamp: float, temps: list):
    """將一筆記錄寫入 .bin 檔案"""
    data = struct.pack(RECORD_FORMAT, timestamp, *temps)
    f.write(data)
    f.flush()


# ══════════════════════════════════════════
def read_bin_file(filepath: str):
    """讀取並顯示 .bin 檔案內容（驗證用）"""
    if not os.path.exists(filepath):
        print(f"  找不到檔案：{filepath}")
        return

    file_size   = os.path.getsize(filepath)
    num_records = file_size // RECORD_SIZE
    remainder   = file_size % RECORD_SIZE

    print(f"\n{'='*75}")
    print(f"  檔案：{filepath}")
    print(f"  大小：{file_size} bytes | 筆數：{num_records} 筆"
          + (f"  (尾端 {remainder} bytes 不完整，已略過)" if remainder else ""))
    print(f"{'='*75}")

    header = f"{'時間':<20}" + "".join(f"  CH{i:>2}" for i in range(NUM_CHANNELS))
    print(header)
    print("-" * 75)

    with open(filepath, "rb") as f:
        for _ in range(num_records):
            raw_bytes = f.read(RECORD_SIZE)
            if len(raw_bytes) < RECORD_SIZE:
                break

            values = struct.unpack(RECORD_FORMAT, raw_bytes)
            ts     = values[0]
            temps  = values[1:]

            dt_str   = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            temp_str = "".join(
                f"  {'NaN':>5}" if math.isnan(t) else f"  {t:>5.1f}"
                for t in temps
            )
            print(f"{dt_str}{temp_str}")

    print("-" * 75)


# ══════════════════════════════════════════
def main():
    print("=" * 55)
    print(f"  PT100 資料記錄器  |  (P)ET-2215H")
    print(f"  IP       : {IP_ADDRESS}:{PORT}")
    print(f"  通道數   : {NUM_CHANNELS} ch")
    print(f"  採樣間隔 : {INTERVAL_SEC} 秒")
    print(f"  輸出檔案 : {OUTPUT_FILE}")
    print(f"  記錄格式 : {RECORD_SIZE} bytes / 筆")
    print("=" * 55)

    client = ModbusTcpClient(IP_ADDRESS, port=PORT, timeout=3)

    if not client.connect():
        print("\n❌ 無法連接！請確認：")
        print("   1. IP 位址是否正確")
        print("   2. 模組電源是否開啟")
        print("   3. 網路連通（先 ping 192.168.1.6）")
        return

    print(f"\n✅ 連接成功！按 Ctrl+C 停止記錄\n")

    # 標題列
    header = f"{'時間':^10}" + "".join(f"    CH{i}" for i in range(NUM_CHANNELS))
    print(header)
    print("-" * (12 + NUM_CHANNELS * 9))

    record_count = 0
    try:
        with open(OUTPUT_FILE, "ab") as f:
            while True:
                ts    = time.time()
                temps = read_temperatures(client)
                write_record(f, ts, temps)
                record_count += 1

                dt_str   = datetime.fromtimestamp(ts).strftime("%H:%M:%S")
                temp_str = "".join(
                    f"  {'斷線':>5}" if math.isnan(t) else f"  {t:>6.1f}"
                    for t in temps
                )
                print(f"[{dt_str}] #{record_count:04d}  {temp_str}")

                time.sleep(INTERVAL_SEC)

    except KeyboardInterrupt:
        print(f"\n\n⏹  已停止，共記錄 {record_count} 筆")

    finally:
        client.close()
        print("   Modbus 連線已關閉\n")
        read_bin_file(OUTPUT_FILE)


if __name__ == "__main__":
    main()
