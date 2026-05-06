"""
集中所有可調參數。實地校驗後直接編輯本檔即可，不引入 yaml/toml 解析依賴。

物理量轉換係數採用「合理預設值」(預設 DNM-843=600V、DNM-844=20A、SG-3227 gain=×1、
accelerometer 603C01 = 100 mV/g)。使用者上機後若發現峰值不合理，請依據
memory/hardware_constants.md 的對照表調整 DNM843_GAIN / DNM844_GAIN / IEPE_G_PER_V。
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PumpMonitorConfig:
    # ── 網路位址 ──────────────────────────────
    M1_IP: str = "192.168.1.12"          # 振動 + 壓力
    M2_IP: str = "192.168.1.13"          # 電壓 + 電流
    DAQ_PORT: int = 9000
    ET2215H_IP: str = "192.168.1.6"
    MODBUS_TCP_PORT: int = 502

    # ── 採樣排程 ──────────────────────────────
    TPOLL_SEC: int = 600                 # 兩次 capture 起始間隔 (10 分鐘)
    SEC: int = 10                        # 每次 START_CAPTURE 持續秒數
    # 每通道採樣率 (Hz)。machine1 (4 ch 振動) 全速 10 kHz；
    # machine2 (12 ch) 受 I-8014W Magic Scan aggregate 上限約 80~90 kS/s 限制，
    # 12×10kHz=120 kS/s 必爆 FIFO，故降至 5 kHz (= 60 kS/s 安全帶)。
    # (2026-05-06 實測：CH=12 RATE=8000 fail、RATE=5000 ok)
    M1_RATE: int = 10000
    M2_RATE: int = 5000

    # ── machine1 RTU (壓力) slave id ─────────
    # machine2 不接 RTU，main loop 一律送 RTU1=0, RTU2=0 (DISABLED)
    M1_RTU1_ADDR: int = 1                # motor1 壓力
    M1_RTU2_ADDR: int = 2                # motor2 壓力

    # ── 通道配置 ──────────────────────────────
    M1_CH_COUNT: int = 4
    M2_CH_COUNT: int = 12
    # machine1 4 通道 → 兩台馬達各取 X/Y 軸振動
    M1_CHANNEL_NAMES: tuple = (
        "motor1_x", "motor1_y",
        "motor2_x", "motor2_y",
    )
    # machine2 12 通道 → 配對排列：每台馬達 V×3 + I×3
    # (2026-05-06 首輪試跑指紋分析後修正，原假設 [V×6, I×6] 與資料不符)
    M2_CHANNEL_NAMES: tuple = (
        "motor1_Va", "motor1_Vb", "motor1_Vc",   # ch0~2  → DNM-843 ×80
        "motor1_Ia", "motor1_Ib", "motor1_Ic",   # ch3~5  → DNM-844 ×100
        "motor2_Va", "motor2_Vb", "motor2_Vc",   # ch6~8  → DNM-843 ×80
        "motor2_Ia", "motor2_Ib", "motor2_Ic",   # ch9~11 → DNM-844 ×100
    )

    # ── ET-2215H ──────────────────────────────
    # 現場只接 ch0 / ch1 兩顆 PT100 (ch2~7 永久空接)，故 FC04 只讀 count=2
    # 若日後增接更多 PT100，將此值改回 8 即會自動帶動 low_freq.csv 加欄
    ET_NUM_CHANNELS: int = 2
    ET_OPEN_CIRCUIT_RAW: int = -32768    # 同 temp_receiver.py:57
    ET_TIMEOUT_SEC: float = 3.0          # 同 temp_receiver.py:176

    # ── 物理量轉換係數 (實地校驗後可改) ──────
    ADC_FULL_SCALE_V: float = 10.0       # I-8014W gain=0 → ±10V
    ADC_FULL_SCALE_RAW: int = 32768      # 16-bit signed half-range

    # 振動鏈 (V_ADC → g)：訊號路徑為 加速規 → SG-3227 → I-8014W
    # IEPE_G_PER_V 由下兩個值推算，外部呼叫仍可用 cfg.IEPE_G_PER_V 取得
    ACCEL_SENSITIVITY_MV_PER_G: float = 100.0   # 603C01 datasheet 標稱 (定值)
    SG3227_GAIN: float = 1.0                    # SG-3227 DIP switch (×1 / ×10 / ×100)
    # 註：SG-3227 的其他 DIP 設定 (DC/AC 耦合、IEPE 驅動電流 2/4/6/10 mA) 不影響
    #     轉換係數，僅影響低頻響應與訊號穩定性，故不在此處列。請依現場接線手冊設定。

    DNM843_GAIN: float = 80.0            # DNM-843VI-800V: ±10V ↔ ±800V
    DNM844_GAIN: float = 100.0           # DNM-844-1000A:  ±10V ↔ ±1000A

    # ── 輸出路徑 ──────────────────────────────
    OUT_BASE: Path = Path(r"C:\Users\USER\Desktop\data")

    # ── socket 安全帶 ─────────────────────────
    DAQ_SOCKET_TIMEOUT_SEC: int = 60     # 同 request-example.py:31

    # ── 衍生係數 ──────────────────────────────
    @property
    def IEPE_G_PER_V(self) -> float:
        """V_ADC → g 的乘數。
        例：100 mV/g 加速規 + SG-3227 ×1 → 1 / (0.1 V/g × 1) = 10 g/V"""
        sens_v_per_g = (self.ACCEL_SENSITIVITY_MV_PER_G / 1000.0) * self.SG3227_GAIN
        return 1.0 / sens_v_per_g

    # ── 衍生路徑 ──────────────────────────────
    @property
    def m1_dir(self) -> Path:
        return self.OUT_BASE / "machine1"

    @property
    def m2_dir(self) -> Path:
        return self.OUT_BASE / "machine2"

    @property
    def low_freq_path(self) -> Path:
        return self.OUT_BASE / "low_freq_sensor.csv"

    @property
    def log_dir(self) -> Path:
        return self.OUT_BASE / "logs"
