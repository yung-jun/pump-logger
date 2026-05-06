"""
進入點。建 ET-2215H 連線、設定 logging、進入主迴圈，每 Tpoll_SEC 跑一輪 cycle。

主迴圈以 time.monotonic() 對齊到 Tpoll 邊界，避免漂移；cycle 超時則 resync 不雙重觸發。
Ctrl-C 收到後優雅關閉 modbus 連線。

使用：
    python -m pump_monitor.main
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import time
from datetime import datetime

from . import pipeline, temp_client
from .config import PumpMonitorConfig


def _setup_logging(cfg: PumpMonitorConfig) -> logging.Logger:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = cfg.log_dir / f"pump_monitor_{datetime.now().strftime('%Y%m%d')}.log"

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 清掉重複 handlers (反覆啟動時)
    root.handlers.clear()

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    return logging.getLogger("pump_monitor.main")


def main() -> int:
    cfg = PumpMonitorConfig()
    log = _setup_logging(cfg)

    log.info("=" * 60)
    log.info("pump_monitor 啟動")
    log.info("Tpoll=%ds  SEC=%ds  M1_RATE=%dHz  M2_RATE=%dHz",
             cfg.TPOLL_SEC, cfg.SEC, cfg.M1_RATE, cfg.M2_RATE)
    log.info("machine1 = %s (vib + RTU)", cfg.M1_IP)
    log.info("machine2 = %s (electrical)", cfg.M2_IP)
    log.info("ET-2215H = %s", cfg.ET2215H_IP)
    log.info("輸出根目錄 = %s", cfg.OUT_BASE)
    log.info("=" * 60)

    # ── ET-2215H Modbus-TCP 連線 (失敗仍啟動，溫度欄持續 NaN) ──
    modbus = temp_client.connect(cfg.ET2215H_IP, cfg.MODBUS_TCP_PORT,
                                 cfg.ET_TIMEOUT_SEC)
    if not modbus.connect():
        log.error("ET-2215H 無法連線；本機仍會啟動，溫度欄會持續 NaN")
        modbus = None
    else:
        log.info("ET-2215H 連線成功")

    # ── 主迴圈 ──
    next_tick = time.monotonic()
    try:
        while True:
            cycle_start_wall = time.time()
            t0 = time.monotonic()
            try:
                pipeline.run_one_cycle(cfg, modbus, cycle_start_wall)
            except Exception as e:
                log.exception("run_one_cycle 未預期錯誤：%s", e)
            elapsed = time.monotonic() - t0
            log.info("cycle wall-time = %.2fs", elapsed)

            next_tick += cfg.TPOLL_SEC
            delay = next_tick - time.monotonic()
            if delay < 0:
                log.warning("cycle overran %.1fs; resyncing", -delay)
                next_tick = time.monotonic()
            else:
                time.sleep(delay)
    except KeyboardInterrupt:
        log.info("Ctrl-C 收到，正在關閉…")
        return 0
    finally:
        if modbus is not None:
            try:
                modbus.close()
            except Exception:
                pass
            log.info("Modbus 連線已關閉")


if __name__ == "__main__":
    sys.exit(main() or 0)
