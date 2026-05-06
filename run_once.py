"""
單輪取樣，不進入主迴圈。用於上機驗證 / 分析報告的一次性 capture。
"""

import logging
import sys
import time

from pump_monitor import pipeline, temp_client
from pump_monitor.config import PumpMonitorConfig


def main() -> int:
    cfg = PumpMonitorConfig()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("run_once")
    log.info("== 單輪試跑 ==")
    log.info("Tpoll=%ds (本次只跑 1 輪) SEC=%ds M1_RATE=%dHz M2_RATE=%dHz",
             cfg.TPOLL_SEC, cfg.SEC, cfg.M1_RATE, cfg.M2_RATE)
    log.info("DNM843_GAIN=%s, DNM844_GAIN=%s, IEPE_G_PER_V=%s",
             cfg.DNM843_GAIN, cfg.DNM844_GAIN, cfg.IEPE_G_PER_V)

    modbus = temp_client.connect(cfg.ET2215H_IP, cfg.MODBUS_TCP_PORT,
                                 cfg.ET_TIMEOUT_SEC)
    if not modbus.connect():
        log.error("ET-2215H 無法連線；溫度欄將為 NaN")
        modbus = None

    t0 = time.monotonic()
    try:
        pipeline.run_one_cycle(cfg, modbus, time.time())
    finally:
        if modbus is not None:
            modbus.close()
    log.info("一輪 wall-time = %.2f s", time.monotonic() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
