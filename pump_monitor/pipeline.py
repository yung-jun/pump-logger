"""
一輪 Tpoll cycle 的 orchestration。

並行模型：concurrent.futures.ThreadPoolExecutor(max_workers=3)
  - thread A: machine1 START_CAPTURE (4ch vibration + RTU pressure)
  - thread B: machine2 START_CAPTURE (12ch voltage/current, RTU disabled)
  - thread C: ET-2215H FC04 read (8ch temperature)

三任務各自寫檔互不阻塞；任一任務失敗 → log + 跳過該檔 / 寫 NaN 占位。
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from . import csv_writer, daq_client, temp_client
from .config import PumpMonitorConfig
from .decoder import (
    HDR_STATUS_TEXT,
    RTU_OK,
    RTU_STATUS_TEXT,
    DaqHeader,
    decode_payload,
    rtu_value_or_nan,
    split_machine1,
    split_machine2,
)

log = logging.getLogger(__name__)


def _safe(future: Future, label: str):
    """取 future 結果，例外吞下並 log。回 (ok, value) 二元組。"""
    try:
        return True, future.result()
    except Exception as e:
        log.exception("[%s] task failed: %s", label, e)
        return False, e


def _capture_with_retry(
    ip: str, ch: int, rate: int, sec: int, rtu1: int, rtu2: int,
    timeout: float, label: str, max_attempts: int = 2,
) -> Tuple[DaqHeader, bytes]:
    """
    對 agent 發 START_CAPTURE，遇 FIFO overflow (err=203) 自動重試一次。
    其他失敗模式不重試 (連線拒絕、bad command 等多半要靠運維介入)。
    """
    import time
    header, payload = None, b""
    for attempt in range(max_attempts):
        header, payload = daq_client.request_capture(
            ip, 9000, ch, rate, sec, rtu1, rtu2, timeout
        )
        if header.status == 0:
            return header, payload
        if header.error_code == 203 and attempt + 1 < max_attempts:
            log.warning("[%s] FIFO overflow (err=203), retry after 5s",
                        label)
            time.sleep(5)
            continue
        break
    return header, payload


def _capture_machine1(cfg: PumpMonitorConfig) -> Tuple[DaqHeader, bytes]:
    return _capture_with_retry(
        cfg.M1_IP, cfg.M1_CH_COUNT, cfg.M1_RATE, cfg.SEC,
        cfg.M1_RTU1_ADDR, cfg.M1_RTU2_ADDR,
        timeout=cfg.SEC * 2 + 30, label="machine1",
    )


def _capture_machine2(cfg: PumpMonitorConfig) -> Tuple[DaqHeader, bytes]:
    return _capture_with_retry(
        cfg.M2_IP, cfg.M2_CH_COUNT, cfg.M2_RATE, cfg.SEC,
        rtu1=0, rtu2=0,                # machine2 沒接 RTU
        timeout=cfg.SEC * 2 + 30, label="machine2",
    )


def _t_axis(n_samples: int, header: DaqHeader, fallback_rate_hz: float) -> np.ndarray:
    """capture-relative 時間軸 (秒)，0 ~ SEC-1/rate。"""
    rate = header.actual_sample_rate_hz if header.actual_sample_rate_hz > 0 else fallback_rate_hz
    return (np.arange(n_samples, dtype=np.float64) / rate)


def _ts_filename(t: float) -> str:
    """檔名用時間戳：YYYYMMDD_HHMMSS。"""
    return datetime.fromtimestamp(t).strftime("%Y%m%d_%H%M%S")


def _ts_iso(t: float) -> str:
    """低頻列 timestamp 欄：ISO-8601 (秒精度)。"""
    return datetime.fromtimestamp(t).strftime("%Y-%m-%dT%H:%M:%S")


def _process_machine1(
    cfg: PumpMonitorConfig,
    header: DaqHeader,
    payload: bytes,
    ts_str: str,
) -> Tuple[float, float]:
    """
    解碼 + 拆 motor1/2 + 寫兩個 vibration CSV。
    回 (pressure_motor1_bar, pressure_motor2_bar) 給 low_freq 寫檔用。
    """
    p1 = rtu_value_or_nan(header.rtu_status1, header.rtu_value1)
    p2 = rtu_value_or_nan(header.rtu_status2, header.rtu_value2)
    if header.rtu_status1 != RTU_OK:
        log.warning("machine1 RTU1 status=%s (motor1 pressure → NaN)",
                    RTU_STATUS_TEXT.get(header.rtu_status1, header.rtu_status1))
    if header.rtu_status2 != RTU_OK:
        log.warning("machine1 RTU2 status=%s (motor2 pressure → NaN)",
                    RTU_STATUS_TEXT.get(header.rtu_status2, header.rtu_status2))

    if header.status != 0 or not payload:
        log.error("machine1 header status=%s; vibration CSV skipped",
                  HDR_STATUS_TEXT.get(header.status, header.status))
        return p1, p2

    volts = decode_payload(payload, cfg.M1_CH_COUNT, header.samples_per_channel)
    motor1, motor2 = split_machine1(volts, cfg.IEPE_G_PER_V)
    t = _t_axis(header.samples_per_channel, header, cfg.M1_RATE)

    csv_writer.write_vibration_csv(
        cfg.m1_dir / f"vibration_sensor_{ts_str}.csv", t, motor1, motor2)
    log.info("machine1 vibration CSV written (seq=%d)", header.seq_no)

    return p1, p2


def _process_machine2(
    cfg: PumpMonitorConfig,
    header: DaqHeader,
    payload: bytes,
    ts_str: str,
) -> None:
    """解碼 + 拆 motor1/2 + 寫兩個 electrical CSV。"""
    if header.status != 0 or not payload:
        log.error("machine2 header status=%s; electrical CSV skipped",
                  HDR_STATUS_TEXT.get(header.status, header.status))
        return

    volts = decode_payload(payload, cfg.M2_CH_COUNT, header.samples_per_channel)
    motor1, motor2 = split_machine2(volts, cfg.DNM843_GAIN, cfg.DNM844_GAIN)
    t = _t_axis(header.samples_per_channel, header, cfg.M2_RATE)

    csv_writer.write_electrical_csv(
        cfg.m2_dir / f"electrical_sensor_{ts_str}.csv", t, motor1, motor2)
    log.info("machine2 electrical CSV written (seq=%d)", header.seq_no)


def run_one_cycle(
    cfg: PumpMonitorConfig,
    modbus_client: Optional[object],
    cycle_start_wall: float,
) -> None:
    """
    執行一輪 cycle：並行三任務 → 各自寫檔 → 最後 append low_freq 一列。

    任一任務失敗皆不影響其他；low_freq 一律寫一列以保留時間軸連續，
    缺值欄寫 NaN。
    """
    ts_str = _ts_filename(cycle_start_wall)
    ts_iso = _ts_iso(cycle_start_wall)

    # ── 並行三任務 ──
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="cycle") as ex:
        f_m1 = ex.submit(_capture_machine1, cfg)
        f_m2 = ex.submit(_capture_machine2, cfg)
        if modbus_client is not None:
            f_temp = ex.submit(temp_client.read_temperatures,
                               modbus_client, cfg.ET_NUM_CHANNELS,
                               cfg.ET_OPEN_CIRCUIT_RAW)
        else:
            f_temp = None

        ok_m1, res_m1 = _safe(f_m1, "machine1")
        ok_m2, res_m2 = _safe(f_m2, "machine2")
        if f_temp is not None:
            ok_temp, res_temp = _safe(f_temp, "ET-2215H")
        else:
            ok_temp, res_temp = False, None

    # ── machine1 → vibration CSV + 取出壓力值 ──
    if ok_m1:
        header_m1, payload_m1 = res_m1
        p1, p2 = _process_machine1(cfg, header_m1, payload_m1, ts_str)
    else:
        p1, p2 = math.nan, math.nan

    # ── machine2 → electrical CSV ──
    if ok_m2:
        header_m2, payload_m2 = res_m2
        _process_machine2(cfg, header_m2, payload_m2, ts_str)

    # ── ET-2215H 溫度 ──
    if ok_temp and isinstance(res_temp, list):
        temps: List[float] = res_temp
    else:
        temps = [math.nan] * cfg.ET_NUM_CHANNELS

    # ── low_freq 一律 append ──
    csv_writer.append_low_freq_row(
        cfg.low_freq_path, ts_iso, p1, p2, temps,
    )
    log.info("low_freq row appended @ %s", ts_iso)
