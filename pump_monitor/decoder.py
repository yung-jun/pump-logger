"""
解 48-byte header、de-interleave 取樣、ADC raw → 物理量。

所有函式皆為純函式，不做 I/O，方便用 request-example/*.bin fixture 離線單元測試。
"""

from __future__ import annotations

import math
import struct
from typing import NamedTuple

import numpy as np

# 與 daq_agent_wince.cpp:84-114 的 #pragma pack(1) DaqPacketHeader 對齊
# 與 request-example/request-example.py:18 完全一致
HEADER_FMT = "<4sHHBBBBIfIIIBBBBffI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 48
assert HEADER_SIZE == 48, f"unexpected header size: {HEADER_SIZE}"

# Status 對照 (daq_agent_wince.cpp:64-71)
HDR_STATUS_OK = 0
HDR_STATUS_DAQ_ERROR = 1
HDR_STATUS_BUSY = 2
HDR_STATUS_BAD_COMMAND = 3

HDR_STATUS_TEXT = {
    0: "OK",
    1: "DAQ_ERROR",
    2: "BUSY",
    3: "BAD_COMMAND",
}

# RTU status 對照 (daq_agent_wince.cpp:73-79)
RTU_OK = 0
RTU_TIMEOUT = 1
RTU_CRC_ERROR = 2
RTU_ERROR = 3
RTU_DISABLED = 4

RTU_STATUS_TEXT = {
    0: "OK",
    1: "TIMEOUT",
    2: "CRC_ERROR",
    3: "ERROR",
    4: "DISABLED",
}


class DaqHeader(NamedTuple):
    magic: bytes
    version: int
    header_bytes: int
    machine_id: int
    status: int
    channel_count: int
    data_type: int
    requested_sample_rate_hz: int
    actual_sample_rate_hz: float
    samples_per_channel: int
    payload_bytes: int
    seq_no: int
    rtu_addr1: int
    rtu_status1: int
    rtu_addr2: int
    rtu_status2: int
    rtu_value1: float
    rtu_value2: float
    error_code: int


def parse_header(buf: bytes) -> DaqHeader:
    """解 48 bytes header → DaqHeader namedtuple。"""
    if len(buf) != HEADER_SIZE:
        raise ValueError(f"header must be {HEADER_SIZE} bytes, got {len(buf)}")
    h = DaqHeader(*struct.unpack(HEADER_FMT, buf))
    if h.magic != b"DAQ1":
        raise ValueError(f"bad magic: {h.magic!r} (expected b'DAQ1')")
    return h


def decode_payload(payload: bytes, n_channels: int, n_samples: int) -> np.ndarray:
    """
    int16 little-endian、sample-major interleaved → (n_samples, n_channels) float32 volts。

    參考 daq_agent_wince.cpp:19-22 的 layout 註解。I-8014W gain=0 (cpp:46) → ±10V。
    """
    expected = n_samples * n_channels * 2
    if len(payload) != expected:
        raise ValueError(
            f"payload size mismatch: got {len(payload)} bytes, "
            f"expected {expected} ({n_channels} ch × {n_samples} samples × 2)"
        )
    raw = np.frombuffer(payload, dtype="<i2").reshape(n_samples, n_channels)
    return raw.astype(np.float32) * (10.0 / 32768.0)


def split_machine1(volts: np.ndarray, iepe_g_per_v: float) -> tuple[np.ndarray, np.ndarray]:
    """
    machine1 4 通道 → (motor1_xy_g, motor2_xy_g)，shape 各 (n_samples, 2)。
    通道對應 config.M1_CHANNEL_NAMES。
    """
    if volts.shape[1] != 4:
        raise ValueError(f"machine1 expects 4 channels, got {volts.shape[1]}")
    accel_g = volts * iepe_g_per_v
    return accel_g[:, 0:2].copy(), accel_g[:, 2:4].copy()


def split_machine2(
    volts: np.ndarray, dnm843_gain: float, dnm844_gain: float
) -> tuple[np.ndarray, np.ndarray]:
    """
    machine2 12 通道 → (motor1_VI, motor2_VI)，shape 各 (n_samples, 6) = [Va,Vb,Vc,Ia,Ib,Ic]。

    Channel 排列為「配對」: ch0~2 = m1_V, ch3~5 = m1_I, ch6~8 = m2_V, ch9~11 = m2_I
    （依 2026-05-06 首輪試跑指紋分析後修正，原假設 [V×6, I×6] 與資料不符；
    詳見 docs/首輪試跑分析報告_20260506_補充.md）
    """
    if volts.shape[1] != 12:
        raise ValueError(f"machine2 expects 12 channels, got {volts.shape[1]}")
    m1_V = volts[:, 0:3]   * dnm843_gain
    m1_I = volts[:, 3:6]   * dnm844_gain
    m2_V = volts[:, 6:9]   * dnm843_gain
    m2_I = volts[:, 9:12]  * dnm844_gain
    motor1 = np.column_stack([m1_V, m1_I])
    motor2 = np.column_stack([m2_V, m2_I])
    return motor1, motor2


def rtu_value_or_nan(status: int, value: float) -> float:
    """RTU status 不為 OK → 回 NaN。"""
    if status == RTU_OK:
        return float(value)
    return math.nan


def temp_raw_to_c(raw_u16: int, open_circuit_raw: int = -32768) -> float:
    """
    ET-2215H FC04 input register raw → °C。鏡像 temp_receiver.py:99-111。

    raw_u16 是 pymodbus 回的 unsigned 16-bit；先 unsigned→signed，
    -32768 視為斷線回 NaN，其餘 raw/100.0 = °C。
    """
    raw = raw_u16
    if raw >= 0x8000:
        raw -= 0x10000
    if raw == open_circuit_raw:
        return math.nan
    return raw / 100.0
