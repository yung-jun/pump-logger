"""
ET-2215H Modbus-TCP 溫度讀取。語意鏡像 temp_receiver.py:68-113。

不直接 import temp_receiver.py 以維持其檔案獨立可執行；本檔複製其讀取邏輯，
使用同一份 pymodbus 客戶端與相同參數 (port=502, timeout=3, 2-attempt + reconnect)。
"""

from __future__ import annotations

import math
from typing import List

from pymodbus.client import ModbusTcpClient

from .decoder import temp_raw_to_c


def connect(ip: str, port: int, timeout: float) -> ModbusTcpClient:
    """建立 Modbus-TCP 客戶端。同 temp_receiver.py:176。"""
    return ModbusTcpClient(ip, port=port, timeout=timeout)


def read_temperatures(
    client: ModbusTcpClient,
    n_channels: int = 8,
    open_circuit_raw: int = -32768,
) -> List[float]:
    """
    一次讀取 n_channels 個 PT100 通道，回攝氏度 list。失敗或斷線回 NaN。

    流程鏡像 temp_receiver.py:68-113：
      - FC04 read_input_registers，address=0，count=n_channels
      - 失敗時 close + connect 重試一次
      - raw == -32768 → NaN (斷線)；其餘 raw/100.0 = °C
    """
    result = None
    for attempt in range(2):
        try:
            result = client.read_input_registers(address=0, count=n_channels)
            break
        except Exception:
            if attempt == 0:
                # 長閒置可能被 ET-2215H 主動斷 TCP，嘗試 reconnect 一次
                # 同 temp_receiver.py:84-92
                try:
                    client.close()
                    client.connect()
                except Exception:
                    pass
            else:
                return [math.nan] * n_channels

    if result is None or result.isError():
        return [math.nan] * n_channels

    return [temp_raw_to_c(raw, open_circuit_raw) for raw in result.registers]
