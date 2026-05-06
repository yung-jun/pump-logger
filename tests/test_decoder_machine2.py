"""machine2 12-channel voltage/current payload 解碼測試。

Fixture: request-example/daq_payload_machine2_seq3_*.bin
- 2,400,000 bytes = 12 channels × 100,000 samples × int16
"""

from pathlib import Path

import numpy as np
import pytest

from pump_monitor.decoder import decode_payload, split_machine2

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "request-example"
M2_FIXTURES = list(FIXTURE_DIR.glob("daq_payload_machine2_*.bin"))


@pytest.mark.skipif(not M2_FIXTURES, reason="machine2 .bin fixture not found")
def test_machine2_decodes_to_expected_shape():
    payload = M2_FIXTURES[0].read_bytes()
    assert len(payload) == 12 * 100_000 * 2  # 2,400,000

    volts = decode_payload(payload, n_channels=12, n_samples=100_000)
    assert volts.shape == (100_000, 12)
    assert volts.dtype == np.float32
    assert np.all(np.abs(volts) <= 10.0001)


@pytest.mark.skipif(not M2_FIXTURES, reason="machine2 .bin fixture not found")
def test_machine2_split_into_motor1_motor2_VI():
    """
    Channel 排列為配對 [m1_V×3, m1_I×3, m2_V×3, m2_I×3]，依 2026-05-06 修正。
    使用實際生產用的 gain (DNM-843=80, DNM-844=100) 驗證輸出範圍合理。
    """
    payload = M2_FIXTURES[0].read_bytes()
    volts = decode_payload(payload, 12, 100_000)
    motor1, motor2 = split_machine2(volts, dnm843_gain=80.0, dnm844_gain=100.0)
    # 各為 (n_samples, 6) — Va, Vb, Vc, Ia, Ib, Ic
    assert motor1.shape == (100_000, 6)
    assert motor2.shape == (100_000, 6)

    # 電壓 ×80 → 理論上限 ±800V；電流 ×100 → ±1000A
    assert np.all(np.abs(motor1[:, 0:3]) <= 800.01)
    assert np.all(np.abs(motor1[:, 3:6]) <= 1000.01)
    assert np.all(np.abs(motor2[:, 0:3]) <= 800.01)
    assert np.all(np.abs(motor2[:, 3:6]) <= 1000.01)
