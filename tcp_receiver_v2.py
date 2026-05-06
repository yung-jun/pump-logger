"""
tcp_receiver.py

Python rewrite of tcpreceiver.java.

TCP server that receives binary burst data from ICPDAS WP-8121 PAC controllers
and saves them to binary files. Source is identified by client IP address:
  - 192.168.1.12 -> machine_B (vibration / accelerometer)
  - 192.168.1.13 -> machine_A (voltage / current)

Each burst is saved with a timestamp-based filename (never overwritten):
  data/<machine>/<machine>_YYYYMMDD_HHMMSS_ffffff.bin
"""

import os
import socket
import threading
import logging
from datetime import datetime
from pathlib import Path

# ====== Config ======
PORT = 9000
BIND = "0.0.0.0"
OUT_DIR = Path(r"C:\Users\USER\Desktop\data")

# Map source IP -> machine label (folder name)
IP_TO_MACHINE: dict[str, str] = {
    "192.168.1.12": "machine_B",   # vibration / accelerometer
    "192.168.1.13": "machine_A",   # voltage / current
}
DEFAULT_MACHINE = "unknown"

SOCKET_TIMEOUT_SEC = 30         # 30s read timeout
MAX_BYTES = 256 * 1024 * 1024   # 256 MB safety cap
BUFFER_SIZE = 64 * 1024         # 64 KB read buffer

# ====== Logging ======
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def handle_client(conn: socket.socket, addr: tuple[str, int]) -> None:
    """Receive a binary burst from a single client and save to file."""
    client_ip = addr[0]
    client = f"{client_ip}:{addr[1]}"
    machine = IP_TO_MACHINE.get(client_ip, DEFAULT_MACHINE)

    machine_dir = OUT_DIR / machine
    machine_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    tmp_path = machine_dir / f"{machine}_{ts}.tmp"
    bin_path = machine_dir / f"{machine}_{ts}.bin"

    try:
        conn.settimeout(SOCKET_TIMEOUT_SEC)
        log.info("Accepted %s (machine=%s)", client, machine)

        with open(tmp_path, "wb") as f:
            total: int = 0
            while True:
                try:
                    chunk = conn.recv(BUFFER_SIZE)
                except TimeoutError:
                    log.info(
                        "Timeout while reading from %s (received %d bytes). Abort.",
                        client, total,
                    )
                    return

                if not chunk:   # client closed connection -> end of stream
                    break

                f.write(chunk)
                total += len(chunk)  # pyre-ignore[internal-error]

                if total > MAX_BYTES:
                    log.info(
                        "Too large payload from %s (%d bytes). Abort.",
                        client, total,
                    )
                    return

        # Atomic-ish replace (works on Windows via os.replace)
        os.replace(tmp_path, bin_path)
        log.info("Saved %d bytes -> %s", total, bin_path.resolve())

    except Exception as exc:
        log.error("Error %s: %s", client, exc)
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
    finally:
        conn.close()


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for machine in IP_TO_MACHINE.values():
        (OUT_DIR / machine).mkdir(parents=True, exist_ok=True)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((BIND, PORT))
        server.listen(50)
        log.info("Listening on %s:%d ...", BIND, PORT)

        while True:
            conn, addr = server.accept()
            thread = threading.Thread(
                target=handle_client,
                args=(conn, addr),
                name=f"rx-{addr[1]}",
                daemon=True,
            )
            thread.start()


if __name__ == "__main__":
    main()
