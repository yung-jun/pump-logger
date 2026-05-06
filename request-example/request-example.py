import socket
import struct
import time

PAC_IP = "192.168.1.13"
PAC_PORT = 9000

if PAC_IP == "192.168.1.12": # Acclerometer
    channel_count = 4
elif PAC_IP == "192.168.1.13": # Voltage and Current
    channel_count = 12
else:
    raise RuntimeError("Unknown PAC IP")

COMMAND = f"START_CAPTURE CH={channel_count} RATE=10000 SEC=10 RTU1=1 RTU2=2\n".encode()

HEADER_SIZE = 48
HEADER_FMT = "<4sHHBBBBIfIIIBBBBffI"


def recv_exact(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError(f"socket closed early: got {len(data)} / {n} bytes")
        data.extend(chunk)
    return bytes(data)


with socket.create_connection((PAC_IP, PAC_PORT), timeout=60) as s:
    s.settimeout(60)

    print("Sending command:", COMMAND.decode().strip())
    s.sendall(COMMAND)

    header_bytes = recv_exact(s, HEADER_SIZE)
    header = struct.unpack(HEADER_FMT, header_bytes)

    (
        magic,
        version,
        header_bytes_len,
        machine_id,
        status,
        channel_count,
        data_type,
        requested_sample_rate_hz,
        actual_sample_rate_hz,
        samples_per_channel,
        payload_bytes,
        seq_no,
        rtu_addr1,
        rtu_status1,
        rtu_addr2,
        rtu_status2,
        rtu_value1,
        rtu_value2,
        error_code,
    ) = header

    if PAC_IP == "192.168.1.12":
        machine_id = 1
    elif PAC_IP == "192.168.1.13":
        machine_id = 2
    else:
        raise RuntimeError("Unknown PAC IP")

    magic = magic.decode("ascii", errors="ignore")

    print("=== HEADER ===")
    print("magic:", magic)
    print("version:", version)
    print("headerBytes:", header_bytes_len)
    print("machineId:", machine_id)
    print("status:", status)
    print("channelCount:", channel_count)
    print("dataType:", data_type)
    print("requestedSampleRateHz:", requested_sample_rate_hz)
    print("actualSampleRateHz:", actual_sample_rate_hz)
    print("samplesPerChannel:", samples_per_channel)
    print("payloadBytes:", payload_bytes)
    print("seqNo:", seq_no)
    print("RTU1:", rtu_addr1, "status:", rtu_status1, "value:", rtu_value1)
    print("RTU2:", rtu_addr2, "status:", rtu_status2, "value:", rtu_value2)
    print("errorCode:", error_code)

    if magic != "DAQ1":
        raise RuntimeError("Invalid magic, not DAQ1 packet")

    if status != 0:
        print("PAC returned error. No payload will be saved.")
    else:
        print("Receiving payload...")
        payload = recv_exact(s, payload_bytes)

        out_name = f"daq_payload_machine{machine_id}_seq{seq_no}_{int(time.time())}.bin"
        with open(out_name, "wb") as f:
            f.write(payload)

        print("Saved:", out_name)
        print("Received bytes:", len(payload))