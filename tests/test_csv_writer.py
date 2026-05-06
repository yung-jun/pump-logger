import math
from pathlib import Path

import numpy as np
import pytest

from pump_monitor.csv_writer import (
    VIBRATION_HEADER,
    ELECTRICAL_HEADER,
    append_low_freq_row,
    low_freq_header,
    write_electrical_csv,
    write_vibration_csv,
)


def test_vibration_roundtrip(tmp_path: Path):
    """合併 motor1 + motor2 → 5 cols：t_s, m1_x, m1_y, m2_x, m2_y"""
    n = 1000
    t = np.arange(n, dtype=np.float64) / 10000.0
    m1 = np.column_stack([np.sin(t), np.cos(t)]).astype(np.float32)
    m2 = np.column_stack([np.cos(t), np.sin(t)]).astype(np.float32)
    out = tmp_path / "vibration.csv"
    write_vibration_csv(out, t, m1, m2)

    first_line = out.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == VIBRATION_HEADER
    assert first_line.split(",") == [
        "t_s", "motor1_x_g", "motor1_y_g", "motor2_x_g", "motor2_y_g"]

    data = np.loadtxt(out, delimiter=",", skiprows=1)
    assert data.shape == (n, 5)
    np.testing.assert_allclose(data[:, 0], t, atol=1e-6)
    np.testing.assert_allclose(data[:, 1:3], m1, atol=1e-5)
    np.testing.assert_allclose(data[:, 3:5], m2, atol=1e-5)


def test_electrical_roundtrip(tmp_path: Path):
    """合併 motor1 + motor2 → 13 cols：t_s + 6 + 6"""
    n = 500
    t = np.arange(n, dtype=np.float64) / 10000.0
    rng = np.random.RandomState(0)
    m1 = rng.uniform(-300, 300, (n, 6)).astype(np.float32)
    m2 = rng.uniform(-50, 50, (n, 6)).astype(np.float32)
    out = tmp_path / "electrical.csv"
    write_electrical_csv(out, t, m1, m2)

    first_line = out.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == ELECTRICAL_HEADER

    data = np.loadtxt(out, delimiter=",", skiprows=1)
    assert data.shape == (n, 13)
    np.testing.assert_allclose(data[:, 1:7], m1, atol=1e-3)
    np.testing.assert_allclose(data[:, 7:13], m2, atol=1e-3)


def test_vibration_shape_validation(tmp_path: Path):
    t = np.arange(10, dtype=np.float64)
    bad = np.zeros((10, 3), dtype=np.float32)
    ok = np.zeros((10, 2), dtype=np.float32)
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        write_vibration_csv(tmp_path / "x.csv", t, bad, ok)
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        write_vibration_csv(tmp_path / "x.csv", t, ok, bad)


def test_electrical_shape_validation(tmp_path: Path):
    t = np.arange(10, dtype=np.float64)
    bad = np.zeros((10, 5), dtype=np.float32)
    ok = np.zeros((10, 6), dtype=np.float32)
    with pytest.raises(ValueError, match=r"\(n, 6\)"):
        write_electrical_csv(tmp_path / "x.csv", t, bad, ok)
    with pytest.raises(ValueError, match=r"\(n, 6\)"):
        write_electrical_csv(tmp_path / "x.csv", t, ok, bad)


def test_low_freq_header():
    cols = low_freq_header(8)
    assert cols[0] == "timestamp"
    assert cols[1] == "pressure_motor1_bar"
    assert cols[2] == "pressure_motor2_bar"
    assert cols[3:] == [f"temp_ch{i}_C" for i in range(8)]


def test_low_freq_writes_header_only_once(tmp_path: Path):
    p = tmp_path / "low_freq.csv"
    append_low_freq_row(p, "2026-05-06T12:00:00", 1.23, 1.45, [25.0] * 8)
    append_low_freq_row(p, "2026-05-06T12:10:00", 1.30, 1.40, [25.5] * 8)
    append_low_freq_row(p, "2026-05-06T12:20:00", math.nan, 1.42,
                        [math.nan] * 8)

    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 3  # header + 3 rows
    assert lines[0].startswith("timestamp,pressure_motor1_bar")
    # 第 4 列 (index 3) 應該有 NaN
    assert "NaN" in lines[3]


def test_low_freq_nan_format(tmp_path: Path):
    p = tmp_path / "low_freq.csv"
    append_low_freq_row(p, "2026-05-06T12:00:00", math.nan, math.nan,
                        [math.nan] * 8)
    row = p.read_text(encoding="utf-8").splitlines()[1]
    # 應有 2 (壓力) + 8 (溫度) = 10 個 NaN
    assert row.count("NaN") == 10
