"""
快速可視化工具，方便上機後肉眼判斷 config.py 的轉換係數是否設對。

每張圖標題會印出 peak / p99 / RMS 三個統計值，並標 ✓ / ✗ 以對照「預期範圍」：
  - 振動：p99 約 0.4 ~ 5 g (運轉中)；< 0.05 g 太小、> 50 g 太大
  - 電壓：peak 約 200 ~ 600 V (220V 或 380V 三相系統)；明顯為 50/60 Hz 正弦
  - 電流：peak 隨負載；應在 DNM-844 量程內 (config.py DNM844_GAIN × 10 V) 不飽和
  - 壓力：0.5 ~ 10 bar 為水處理場域典型
  - 溫度：20 ~ 80 °C

使用：
    # 自動找最新一輪 cycle 的 5 個 CSV 並顯示 4 張圖
    python -m pump_monitor.viz

    # 指定特定 cycle (用檔名上的時間戳)
    python -m pump_monitor.viz --ts 20260506_164316

    # 不開 GUI、直接存 PNG (適合 SSH / 跑批次)
    python -m pump_monitor.viz --save --no-show
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np

from .config import PumpMonitorConfig


def _ts_to_local(ts_str: str) -> str:
    """
    把檔名上的 YYYYMMDD_HHMMSS 解成本機時間字串 'YYYY-MM-DD HH:MM:SS'。

    時間源頭一律是 home PC 的 time.time()（WP-8121 agent 的 header 沒有時間欄位），
    所以這裡只是格式化，不做時區換算。
    """
    try:
        dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return ts_str


# ── 預期範圍 (用於 ✓/✗ 判定，可調) ──────────────────────────────────────

VIB_P99_OK_MIN, VIB_P99_OK_MAX = 0.05, 50.0      # g
ELEC_V_PEAK_OK_MIN, ELEC_V_PEAK_OK_MAX = 100.0, 800.0   # V (220V 或 380V 系統)
ELEC_I_PEAK_OK_MAX_RATIO = 0.95                  # peak 不應 ≥ 95% × DNM-844 量程
PRESSURE_OK_MIN, PRESSURE_OK_MAX = 0.0, 10.0     # bar
TEMP_OK_MIN, TEMP_OK_MAX = -10.0, 100.0          # °C


# ── 工具 ────────────────────────────────────────────────────────────────

def _stats(arr: np.ndarray) -> dict:
    a = np.abs(arr)
    return {
        "peak": float(a.max()),
        "p99": float(np.percentile(a, 99)),
        "rms": float(np.sqrt(np.mean(arr ** 2))),
        "mean": float(arr.mean()),
    }


def _ok_marker(ok: bool) -> str:
    return "[OK]" if ok else "[FAIL]"


def _find_latest_ts(cfg: PumpMonitorConfig) -> Optional[str]:
    """掃 machine1 / machine2 兩個資料夾，找出兩邊都有的最新時間戳。"""
    pat = re.compile(r"^(?:vibration|electrical)_sensor_(\d{8}_\d{6})\.csv$")
    m1_ts = {m.group(1) for p in cfg.m1_dir.glob("vibration_sensor_*.csv")
             if (m := pat.match(p.name))}
    m2_ts = {m.group(1) for p in cfg.m2_dir.glob("electrical_sensor_*.csv")
             if (m := pat.match(p.name))}
    common = m1_ts & m2_ts
    if not common:
        return None
    return max(common)


def _load(path: Path) -> np.ndarray:
    return np.loadtxt(path, delimiter=",", skiprows=1)


# ── 圖 1: 振動 ──────────────────────────────────────────────────────────

def plot_vibration(cfg: PumpMonitorConfig, ts: str, save_dir: Optional[Path] = None):
    """新 CSV 格式：t_s, motor1_x_g, motor1_y_g, motor2_x_g, motor2_y_g (5 cols)"""
    path = cfg.m1_dir / f"vibration_sensor_{ts}.csv"
    if not path.exists():
        print(f"[skip vibration] missing {path}")
        return

    d = _load(path)
    t = d[:, 0]
    motors = [
        ("motor1 X", d[:, 1]), ("motor1 Y", d[:, 2]),
        ("motor2 X", d[:, 3]), ("motor2 Y", d[:, 4]),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(13, 7), sharex=True)
    fig.suptitle(f"振動檢查  cycle={ts}  本機時間 {_ts_to_local(ts)}    "
                 f"(IEPE_G_PER_V = {cfg.IEPE_G_PER_V})", fontsize=11)

    # 只畫前 0.5 s 才看得到細節
    head = t < 0.5
    for ax, (name, y) in zip(axes.flat, motors):
        ax.plot(t[head], y[head], lw=0.6)
        s = _stats(y)
        ok = VIB_P99_OK_MIN <= s["p99"] <= VIB_P99_OK_MAX
        ax.set_title(f"{name}  peak={s['peak']:.2f} g  p99={s['p99']:.2f} g  "
                     f"rms={s['rms']:.3f} g  {_ok_marker(ok)}",
                     fontsize=10, color="darkgreen" if ok else "darkred")
        ax.set_ylabel("g")
        ax.grid(alpha=0.3)
    for ax in axes[-1, :]:
        ax.set_xlabel("t (s)  — 顯示前 0.5 秒")
    fig.tight_layout()

    if save_dir is not None:
        out = save_dir / f"viz_vibration_{ts}.png"
        fig.savefig(out, dpi=120)
        print(f"  saved {out}")


# ── 圖 2 & 3: 電氣 (每 motor 一張) ──────────────────────────────────────

def _plot_electrical_one_motor(
    cfg: PumpMonitorConfig, ts: str, motor: int, save_dir: Optional[Path] = None,
    csv_data: Optional[np.ndarray] = None,
):
    """新 CSV 格式：t_s + motor1 V×3 + motor1 I×3 + motor2 V×3 + motor2 I×3 (13 cols)"""
    if csv_data is None:
        path = cfg.m2_dir / f"electrical_sensor_{ts}.csv"
        if not path.exists():
            print(f"[skip electrical motor{motor}] missing {path}")
            return
        d = _load(path)
    else:
        d = csv_data

    t = d[:, 0]
    # 欄位偏移：motor1 = cols 1-6, motor2 = cols 7-12
    base = 1 if motor == 1 else 7
    Va, Vb, Vc = d[:, base+0], d[:, base+1], d[:, base+2]
    Ia, Ib, Ic = d[:, base+3], d[:, base+4], d[:, base+5]

    fig, axes = plt.subplots(2, 2, figsize=(14, 7))
    fig.suptitle(
        f"電氣檢查 motor{motor}  cycle={ts}  本機時間 {_ts_to_local(ts)}    "
        f"(DNM843_GAIN={cfg.DNM843_GAIN}  DNM844_GAIN={cfg.DNM844_GAIN})",
        fontsize=11,
    )

    # 上左: V time (前 0.1 s = 5 個 50Hz 週期)
    ax = axes[0, 0]
    head = t < 0.1
    ax.plot(t[head], Va[head], label="V_a", lw=0.7)
    ax.plot(t[head], Vb[head], label="V_b", lw=0.7)
    ax.plot(t[head], Vc[head], label="V_c", lw=0.7)
    sV = _stats(np.concatenate([Va, Vb, Vc]))
    okV = ELEC_V_PEAK_OK_MIN <= sV["peak"] <= ELEC_V_PEAK_OK_MAX
    full_v = cfg.DNM843_GAIN * cfg.ADC_FULL_SCALE_V
    saturated = sV["peak"] >= 0.99 * full_v
    title = f"V (3-phase)  peak={sV['peak']:.0f}V  p99={sV['p99']:.0f}V  rms={sV['rms']:.0f}V  {_ok_marker(okV and not saturated)}"
    if saturated:
        title += "  [SATURATED]"
    ax.set_title(title, fontsize=10, color="darkgreen" if (okV and not saturated) else "darkred")
    ax.set_ylabel("V"); ax.set_xlabel("t (s)")
    ax.legend(loc="upper right", fontsize=8); ax.grid(alpha=0.3)

    # 上右: I time
    ax = axes[0, 1]
    ax.plot(t[head], Ia[head], label="I_a", lw=0.7)
    ax.plot(t[head], Ib[head], label="I_b", lw=0.7)
    ax.plot(t[head], Ic[head], label="I_c", lw=0.7)
    sI = _stats(np.concatenate([Ia, Ib, Ic]))
    full_a = cfg.DNM844_GAIN * cfg.ADC_FULL_SCALE_V
    saturated_I = sI["peak"] >= ELEC_I_PEAK_OK_MAX_RATIO * full_a
    okI = sI["peak"] > 0 and not saturated_I  # 至少有訊號、且不飽和
    title = f"I (3-phase)  peak={sI['peak']:.2f}A  p99={sI['p99']:.2f}A  rms={sI['rms']:.2f}A  {_ok_marker(okI)}"
    if saturated_I:
        title += "  [SATURATED]"
    elif sI["peak"] < 0.01 * full_a:
        title += "  [TOO SMALL]"
    ax.set_title(title, fontsize=10, color="darkgreen" if okI else "darkred")
    ax.set_ylabel("A"); ax.set_xlabel("t (s)")
    ax.legend(loc="upper right", fontsize=8); ax.grid(alpha=0.3)

    # 下左: V FFT
    fs = 1.0 / (t[1] - t[0]) if len(t) > 1 else cfg.M2_RATE
    n = len(Va)
    freq = np.fft.rfftfreq(n, d=1.0 / fs)
    fft_V = np.abs(np.fft.rfft(Va))
    ax = axes[1, 0]
    ax.semilogy(freq, fft_V + 1e-9, lw=0.7)
    peak_freq = freq[np.argmax(fft_V[1:]) + 1] if len(fft_V) > 1 else 0
    ok_freq = 45 <= peak_freq <= 65
    ax.set_title(f"V_a FFT  主頻 ~ {peak_freq:.1f} Hz  "
                 f"{_ok_marker(ok_freq)} (期望 50/60 Hz)",
                 fontsize=10, color="darkgreen" if ok_freq else "darkorange")
    ax.set_xlabel("頻率 (Hz)"); ax.set_ylabel("|FFT|")
    ax.set_xlim(0, 500); ax.grid(alpha=0.3)

    # 下右: I FFT
    fft_I = np.abs(np.fft.rfft(Ia))
    ax = axes[1, 1]
    ax.semilogy(freq, fft_I + 1e-9, lw=0.7)
    peak_freq_I = freq[np.argmax(fft_I[1:]) + 1] if len(fft_I) > 1 else 0
    ok_freq_I = 45 <= peak_freq_I <= 65
    ax.set_title(f"I_a FFT  主頻 ~ {peak_freq_I:.1f} Hz  "
                 f"{_ok_marker(ok_freq_I)} (期望 50/60 Hz)",
                 fontsize=10, color="darkgreen" if ok_freq_I else "darkorange")
    ax.set_xlabel("頻率 (Hz)"); ax.set_ylabel("|FFT|")
    ax.set_xlim(0, 500); ax.grid(alpha=0.3)

    fig.tight_layout()

    if save_dir is not None:
        out = save_dir / f"viz_electrical_motor{motor}_{ts}.png"
        fig.savefig(out, dpi=120)
        print(f"  saved {out}")


def plot_electrical(cfg: PumpMonitorConfig, ts: str, save_dir: Optional[Path] = None):
    # 一次載 CSV 共用兩張圖，省 IO
    path = cfg.m2_dir / f"electrical_sensor_{ts}.csv"
    if not path.exists():
        print(f"[skip electrical] missing {path}")
        return
    d = _load(path)
    _plot_electrical_one_motor(cfg, ts, 1, save_dir, csv_data=d)
    _plot_electrical_one_motor(cfg, ts, 2, save_dir, csv_data=d)


# ── 圖 4: 低頻 (壓力 + 溫度時間序列) ────────────────────────────────────

def plot_low_freq(cfg: PumpMonitorConfig, save_dir: Optional[Path] = None):
    path = cfg.low_freq_path
    if not path.exists():
        print(f"[skip low_freq] missing {path}")
        return

    # 不用 pandas 讓相依集最小；以原始字串解析
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if len(lines) < 2:
        print(f"[skip low_freq] only {len(lines)} line(s) in {path}")
        return

    header = lines[0].split(",")
    rows = [ln.split(",") for ln in lines[1:]]

    n_rows = len(rows)

    def col(name: str) -> np.ndarray:
        i = header.index(name)
        out = np.full(n_rows, np.nan)
        for j, r in enumerate(rows):
            try:
                out[j] = float(r[i])
            except (ValueError, IndexError):
                out[j] = np.nan
        return out

    # x 軸用本機時間 (low_freq.csv 的 timestamp 欄是 ISO-8601 本機時間，
    # 由 home PC 的 datetime.fromtimestamp(time.time()) 產生，無時區換算)
    ts_idx = header.index("timestamp")
    x: list = []
    for r in rows:
        try:
            x.append(datetime.strptime(r[ts_idx], "%Y-%m-%dT%H:%M:%S"))
        except (ValueError, IndexError):
            x.append(datetime(1970, 1, 1))   # 解析失敗給個 placeholder

    p1 = col("pressure_motor1_bar")
    p2 = col("pressure_motor2_bar")
    temps = [col(f"temp_ch{i}_C") for i in range(cfg.ET_NUM_CHANNELS)]

    fig, (ax_p, ax_t) = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    fig.suptitle(f"低頻檢查  共 {n_rows} cycles (約 {n_rows * cfg.TPOLL_SEC / 3600:.1f} 小時)  "
                 f"x 軸=本機時間",
                 fontsize=11)

    # 壓力
    ax_p.plot(x, p1, "o-", label="motor1 (bar)", ms=3, lw=0.8)
    ax_p.plot(x, p2, "o-", label="motor2 (bar)", ms=3, lw=0.8)
    sp1, sp2 = np.nanmean(p1), np.nanmean(p2)
    ok_p = (PRESSURE_OK_MIN <= np.nanmean([sp1, sp2]) <= PRESSURE_OK_MAX) and \
           not (np.all(np.isnan(p1)) and np.all(np.isnan(p2)))
    ax_p.set_title(f"壓力  motor1 mean={sp1:.2f}  motor2 mean={sp2:.2f}  bar  "
                   f"{_ok_marker(ok_p)}",
                   fontsize=10, color="darkgreen" if ok_p else "darkred")
    ax_p.set_ylabel("bar"); ax_p.legend(); ax_p.grid(alpha=0.3)

    # 溫度
    valid_temps = []
    for i, T in enumerate(temps):
        if np.all(np.isnan(T)):
            continue   # 跳過全斷線通道
        ax_t.plot(x, T, "o-", label=f"ch{i}", ms=2, lw=0.6)
        valid_temps.append(np.nanmean(T))
    if valid_temps:
        mean_t = np.mean(valid_temps)
        ok_t = TEMP_OK_MIN <= mean_t <= TEMP_OK_MAX
    else:
        mean_t, ok_t = float("nan"), False
    ax_t.set_title(f"溫度  全通道平均 mean={mean_t:.1f} °C  "
                   f"({sum(1 for T in temps if not np.all(np.isnan(T)))}/{cfg.ET_NUM_CHANNELS} 通道有值)  "
                   f"{_ok_marker(ok_t)}",
                   fontsize=10, color="darkgreen" if ok_t else "darkred")
    ax_t.set_ylabel("°C"); ax_t.set_xlabel("時間 (本機)")
    ax_t.legend(ncol=4, fontsize=8); ax_t.grid(alpha=0.3)

    # 本機時區的時間軸格式化；自動依 cycle 數選擇粒度
    locator = mdates.AutoDateLocator()
    formatter = mdates.ConciseDateFormatter(locator)
    ax_t.xaxis.set_major_locator(locator)
    ax_t.xaxis.set_major_formatter(formatter)
    fig.autofmt_xdate()

    fig.tight_layout()

    if save_dir is not None:
        out = save_dir / "viz_low_freq.png"
        fig.savefig(out, dpi=120)
        print(f"  saved {out}")


# ── CLI ─────────────────────────────────────────────────────────────────

def _setup_chinese_font():
    """嘗試用 Windows 內建的中文字型，避免 matplotlib 標題中文方塊。"""
    for font in ("Microsoft JhengHei", "Microsoft YaHei", "DFKai-SB",
                 "PMingLiU", "MingLiU", "SimHei"):
        try:
            plt.rcParams["font.sans-serif"] = [font, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return font
        except Exception:
            continue
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="可視化最新 cycle 的所有 CSV，方便檢驗 config 設定")
    parser.add_argument("--ts", help="指定 cycle 時間戳 (YYYYMMDD_HHMMSS)，"
                                     "省略則自動找最新")
    parser.add_argument("--save", action="store_true",
                        help="把圖存成 PNG (預設不存)")
    parser.add_argument("--save-dir", default=None,
                        help="PNG 輸出資料夾，預設為 OUT_BASE/viz")
    parser.add_argument("--no-show", action="store_true",
                        help="不開 GUI 視窗 (適合 SSH / 跑批次)")
    args = parser.parse_args(argv)

    _setup_chinese_font()
    cfg = PumpMonitorConfig()

    ts = args.ts or _find_latest_ts(cfg)
    if ts is None:
        print(f"找不到 cycle 檔案於 {cfg.m1_dir} 與 {cfg.m2_dir}")
        return 1
    print(f"使用 cycle: {ts}")

    save_dir: Optional[Path] = None
    if args.save:
        save_dir = Path(args.save_dir) if args.save_dir else (cfg.OUT_BASE / "viz")
        save_dir.mkdir(parents=True, exist_ok=True)
        print(f"PNG 將存到: {save_dir}")

    plot_vibration(cfg, ts, save_dir)
    plot_electrical(cfg, ts, save_dir)
    plot_low_freq(cfg, save_dir)

    if not args.no_show:
        plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
