"""machine1 4-channel vibration payload 解碼測試。

Fixture: request-example/daq_payload_machine1_seq4_*.bin
- 800,000 bytes = 4 channels × 100,000 samples × int16
- payload-only (沒有 48-byte header)
"""

from pathlib import Path

import numpy as np
import pytest

from pump_monitor.decoder import decode_payload, split_machine1

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "request-example"
M1_FIXTURES = list(FIXTURE_DIR.glob("daq_payload_machine1_*.bin"))


@pytest.mark.skipif(not M1_FIXTURES, reason="machine1 .bin fixture not found")
def test_machine1_decodes_to_expected_shape():
    payload = M1_FIXTURES[0].read_bytes()
    assert len(payload) == 4 * 100_000 * 2  # 800,000

    volts = decode_payload(payload, n_channels=4, n_samples=100_000)
    assert volts.shape == (100_000, 4)
    assert volts.dtype == np.float32

    # I-8014W ±10V → 任何值不可超出 ±10.0 (含浮點誤差)
    assert np.all(volts >= -10.0001)
    assert np.all(volts <= 10.0001)


@pytest.mark.skipif(not M1_FIXTURES, reason="machine1 .bin fixture not found")
def test_machine1_split_motor_xy():
    payload = M1_FIXTURES[0].read_bytes()
    volts = decode_payload(payload, 4, 100_000)
    motor1, motor2 = split_machine1(volts, iepe_g_per_v=10.0)
    assert motor1.shape == (100_000, 2)
    assert motor2.shape == (100_000, 2)
    # × 10 後的加速度，極端 ±10V → ±100 g (理論上限，實務遠小於此)
    assert np.all(np.abs(motor1) <= 100.0001)
    assert np.all(np.abs(motor2) <= 100.0001)


@pytest.mark.skipif(not M1_FIXTURES, reason="machine1 .bin fixture not found")
def test_machine1_payload_size_mismatch_raises():
    """size 不對應該明顯失敗。"""
    payload = M1_FIXTURES[0].read_bytes()[:-2]  # 少 1 個 sample
    with pytest.raises(ValueError, match="payload size mismatch"):
        decode_payload(payload, 4, 100_000)
