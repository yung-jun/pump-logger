"""
高頻 (numpy.savetxt 一檔一寫) + 低頻 (csv.writer append) CSV 輸出。

高頻檔案結構：第 1 列 header，data 從第 2 列開始 (符合需求書)。
低頻檔案結構：首次寫檔自動補 header，之後每個 Tpoll cycle 多 append 一列。
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import List

import numpy as np


# ── 高頻 ─────────────────────────────────────────────────────────────────

VIBRATION_HEADER = "t_s,motor1_x_g,motor1_y_g,motor2_x_g,motor2_y_g"
ELECTRICAL_HEADER = (
    "t_s,"
    "motor1_V_a_V,motor1_V_b_V,motor1_V_c_V,"
    "motor1_I_a_A,motor1_I_b_A,motor1_I_c_A,"
    "motor2_V_a_V,motor2_V_b_V,motor2_V_c_V,"
    "motor2_I_a_A,motor2_I_b_A,motor2_I_c_A"
)


def write_vibration_csv(
    path: Path,
    t_s: np.ndarray,
    motor1_xy_g: np.ndarray,
    motor2_xy_g: np.ndarray,
) -> None:
    """
    寫一個 cycle 的振動 CSV，含兩台馬達的 X/Y 軸加速度。
    motor{1,2}_xy_g shape 各為 (n_samples, 2)。共 1 + 2 + 2 = 5 欄。
    """
    for name, arr in [("motor1_xy_g", motor1_xy_g), ("motor2_xy_g", motor2_xy_g)]:
        if arr.shape[1] != 2:
            raise ValueError(f"expected (n, 2) for {name}, got {arr.shape}")
        if len(t_s) != arr.shape[0]:
            raise ValueError(f"t_s and {name} row count mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.column_stack([t_s, motor1_xy_g, motor2_xy_g])
    np.savetxt(path, out, fmt="%.6f", delimiter=",",
               header=VIBRATION_HEADER, comments="")


def write_electrical_csv(
    path: Path,
    t_s: np.ndarray,
    motor1_VI: np.ndarray,
    motor2_VI: np.ndarray,
) -> None:
    """
    寫一個 cycle 的電氣 CSV，含兩台馬達的三相電壓與三相電流。
    motor{1,2}_VI shape 各為 (n_samples, 6) = [Va,Vb,Vc,Ia,Ib,Ic]。共 1 + 6 + 6 = 13 欄。
    """
    for name, arr in [("motor1_VI", motor1_VI), ("motor2_VI", motor2_VI)]:
        if arr.shape[1] != 6:
            raise ValueError(f"expected (n, 6) for {name}, got {arr.shape}")
        if len(t_s) != arr.shape[0]:
            raise ValueError(f"t_s and {name} row count mismatch")
    path.parent.mkdir(parents=True, exist_ok=True)
    out = np.column_stack([t_s, motor1_VI, motor2_VI])
    np.savetxt(path, out, fmt="%.6f", delimiter=",",
               header=ELECTRICAL_HEADER, comments="")


# ── 低頻 ─────────────────────────────────────────────────────────────────

def low_freq_header(n_temp_channels: int) -> List[str]:
    cols = ["timestamp", "pressure_motor1_bar", "pressure_motor2_bar"]
    cols += [f"temp_ch{i}_C" for i in range(n_temp_channels)]
    return cols


def append_low_freq_row(
    path: Path,
    timestamp_iso: str,
    pressure_motor1_bar: float,
    pressure_motor2_bar: float,
    temps_c: List[float],
) -> None:
    """
    Append 一列到 low_freq_sensor.csv。檔不存在或為空 → 自動寫 header。
    NaN 直接寫字串 "NaN" (numpy / pandas 預設可解析回 nan)。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = (not path.exists()) or path.stat().st_size == 0

    def _fmt(v: float) -> str:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "NaN"
        return f"{v:.6f}"

    row = [timestamp_iso, _fmt(pressure_motor1_bar), _fmt(pressure_motor2_bar)]
    row += [_fmt(t) for t in temps_c]

    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(low_freq_header(len(temps_c)))
        w.writerow(row)
