"""
TCP framing + START_CAPTURE。對齊 daq-cpp-code/daq_agent_wince.cpp 的 wire format。

agent 為 single-client / one-command-per-connection (cpp:18, 869-915)，每呼叫一次
request_capture 即建立並關閉一條連線。兩台機器有不同 IP，故 pipeline 可在兩個 thread
裡同時呼叫，達到真正並行。
"""

from __future__ import annotations

import socket
from typing import Tuple

from .decoder import HEADER_SIZE, parse_header, DaqHeader


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """
    保證從 socket 收到 exactly n bytes。直接搬自 request-example.py:21-28。
    對方提早關連線 → ConnectionError。
    """
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError(f"socket closed early: got {len(data)} / {n} bytes")
        data.extend(chunk)
    return bytes(data)


def request_capture(
    ip: str,
    port: int,
    ch: int,
    rate: int,
    sec: int,
    rtu1: int,
    rtu2: int,
    timeout: float,
) -> Tuple[DaqHeader, bytes]:
    """
    對 agent 發送 START_CAPTURE，回 (header, payload)。

    參數對齊 daq_agent_wince.cpp:208-249 的 ParseStartCaptureCommand：
      - 1 ≤ ch ≤ 12
      - 1 ≤ rate ≤ 100000
      - 1 ≤ sec ≤ 60
      - 0 ≤ rtu1, rtu2 ≤ 247  (0 = DISABLED)

    若 header.status != HDR_STATUS_OK，agent 不會送 payload (cpp:842-854)，
    本函式回 (header, b"") 並由呼叫端決定如何處理。
    """
    cmd = f"START_CAPTURE CH={ch} RATE={rate} SEC={sec} RTU1={rtu1} RTU2={rtu2}\n"
    with socket.create_connection((ip, port), timeout=timeout) as s:
        s.settimeout(timeout)
        s.sendall(cmd.encode("ascii"))

        header_bytes = recv_exact(s, HEADER_SIZE)
        header = parse_header(header_bytes)

        if header.status != 0:
            return header, b""

        payload = recv_exact(s, header.payload_bytes)
        return header, payload
