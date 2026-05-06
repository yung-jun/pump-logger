import struct

import pytest

from pump_monitor.decoder import (
    HEADER_FMT,
    HEADER_SIZE,
    HDR_STATUS_OK,
    HDR_STATUS_BAD_COMMAND,
    RTU_OK,
    RTU_TIMEOUT,
    parse_header,
    rtu_value_or_nan,
    temp_raw_to_c,
)


def _build_header(
    magic=b"DAQ1",
    version=1,
    header_bytes=48,
    machine_id=1,
    status=HDR_STATUS_OK,
    channel_count=4,
    data_type=1,
    requested_sample_rate=10000,
    actual_sample_rate=10000.0,
    samples_per_channel=100000,
    payload_bytes=800000,
    seq_no=4,
    rtu_addr1=1,
    rtu_status1=RTU_OK,
    rtu_addr2=2,
    rtu_status2=RTU_OK,
    rtu_value1=1.23,
    rtu_value2=4.56,
    error_code=0,
):
    return struct.pack(
        HEADER_FMT,
        magic, version, header_bytes, machine_id, status,
        channel_count, data_type, requested_sample_rate, actual_sample_rate,
        samples_per_channel, payload_bytes, seq_no,
        rtu_addr1, rtu_status1, rtu_addr2, rtu_status2,
        rtu_value1, rtu_value2, error_code,
    )


def test_header_size_is_48():
    assert HEADER_SIZE == 48


def test_roundtrip_machine1_ok():
    buf = _build_header()
    h = parse_header(buf)
    assert h.magic == b"DAQ1"
    assert h.machine_id == 1
    assert h.status == HDR_STATUS_OK
    assert h.channel_count == 4
    assert h.samples_per_channel == 100000
    assert h.payload_bytes == 800000
    assert h.actual_sample_rate_hz == pytest.approx(10000.0)
    assert h.rtu_value1 == pytest.approx(1.23, rel=1e-5)
    assert h.rtu_value2 == pytest.approx(4.56, rel=1e-5)


def test_roundtrip_machine2_ok():
    buf = _build_header(
        machine_id=2, channel_count=12, payload_bytes=2_400_000,
        rtu_addr1=0, rtu_status1=4, rtu_addr2=0, rtu_status2=4,  # DISABLED
    )
    h = parse_header(buf)
    assert h.channel_count == 12
    assert h.payload_bytes == 2_400_000
    assert h.rtu_status1 == 4
    assert h.rtu_status2 == 4


def test_bad_magic_raises():
    buf = _build_header(magic=b"XXXX")
    with pytest.raises(ValueError, match="bad magic"):
        parse_header(buf)


def test_short_buffer_raises():
    with pytest.raises(ValueError, match="must be 48 bytes"):
        parse_header(b"\x00" * 47)


def test_bad_command_status_parses():
    buf = _build_header(status=HDR_STATUS_BAD_COMMAND, payload_bytes=0)
    h = parse_header(buf)
    assert h.status == HDR_STATUS_BAD_COMMAND
    assert h.payload_bytes == 0


def test_rtu_value_or_nan():
    import math
    assert rtu_value_or_nan(RTU_OK, 3.14) == 3.14
    assert math.isnan(rtu_value_or_nan(RTU_TIMEOUT, 3.14))
    assert math.isnan(rtu_value_or_nan(4, 0.0))  # DISABLED


def test_temp_raw_to_c_basics():
    import math
    assert temp_raw_to_c(2500) == 25.0           # 25.00 °C
    assert temp_raw_to_c(0xFFFF) == pytest.approx(-0.01)  # raw -1 → -0.01 °C
    assert math.isnan(temp_raw_to_c(0x8000))     # 斷線
