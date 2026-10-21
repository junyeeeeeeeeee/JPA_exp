"""02_2 flux offset S21 2D: for each DC205 bias voltage -> one VNA S21 sweep (no pump).

Cell 1: parameters. Cell 2: measurement (set voltage -> sweep, repeated). Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/02_2_flux_offset_S21_2d/<YYYYmmdd_HHMMSS>/
The DC205 output is switched ON (VNA Enable I/O) for the scan and OFF (Disable I/O) afterwards;
its voltage setting is left at the last measured voltage. Ctrl+C / interrupt keeps the rows measured so far.
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

VNA_POWER_DBM = -20.0          # VNA port-1 output power [dBm]
FREQ_MIN_HZ = 4.0e9
FREQ_MAX_HZ = 8.0e9
IF_BW_HZ = 1.0e3
POINTS = 2001
VOLTAGE_MIN = -0.5             # DC205 voltage scan [V]
VOLTAGE_MAX = 0.5
VOLTAGE_POINTS = 51

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope (one tau for all voltages); or a fixed value [s]
BACKGROUND = "median"          # extra plots of S21 / background: "median" (complex median over voltages),
                               # a voltage [V] (that row, e.g. resonance out of band), or None (no normalization)

VNA_IP, VNA_PORT, CH = "192.168.1.23", 5025, 1
DC_SOURCE = "DC205"            # External DC Source name in the VNA
PSG_IP = "192.168.1.33"        # read only: the measurement stops if the pump RF output is ON
SWEEP_TIMEOUT_S = 600.0

import sys
from pathlib import Path

try:
    _here = Path(__file__).resolve().parent
except NameError:              # VS Code interactive window
    _here = Path.cwd()
_root = next(p for p in [_here, *_here.parents] if (p / "experiments" / "jpa_common.py").exists())
sys.path.insert(0, str(_root / "experiments"))
import jpa_common as jc
import json
import time
import numpy as np

EXPERIMENT = "02_2_flux_offset_S21_2d"
jpa = jc.load_jpa_params(SAMPLE)
voltages = np.linspace(VOLTAGE_MIN, VOLTAGE_MAX, VOLTAGE_POINTS)
params = {
    "experiment": EXPERIMENT, "sample": SAMPLE,
    "vna_power_dBm": VNA_POWER_DBM, "freq_min_Hz": FREQ_MIN_HZ, "freq_max_Hz": FREQ_MAX_HZ,
    "if_bandwidth_Hz": IF_BW_HZ, "points": POINTS,
    "voltage_min_V": VOLTAGE_MIN, "voltage_max_V": VOLTAGE_MAX, "voltage_points": VOLTAGE_POINTS,
    "electrical_delay_s": ELECTRICAL_DELAY_S, "background": BACKGROUND,
    "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "dc_source": DC_SOURCE, "psg": PSG_IP,
}
print(f"{EXPERIMENT}  sample {SAMPLE}: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
      f"IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm, DC {VOLTAGE_MIN:g} -> {VOLTAGE_MAX:g} V ({VOLTAGE_POINTS} steps)")

# %% 2. 量測：設定電壓 -> 掃 S21，重複
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT)
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = jc.SCPI(VNA_IP, VNA_PORT, name="VNA")
freq, rows = None, []          # rows[i] = S21 at voltages[i]
try:
    meta["vna_idn"] = vna.query("*IDN?")
    print("  PSG check:")
    meta["psg"] = jc.check_psg_off(PSG_IP)
    print("  DC205 check:")
    jc.check_dc205(vna, DC_SOURCE, CH)
    mnum, meta["vna_readback"] = jc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS)
    freq = jc.read_freq(vna, CH, mnum)
    print(f"  DC bias {voltages[0]:g} V:")
    jc.set_dc(vna, CH, DC_SOURCE, float(voltages[0]))
    jc.dc_output_on(vna, DC_SOURCE)
    try:
        vna.verbose = False    # one progress line per voltage instead of every SCPI line
        t0 = time.monotonic()
        for i, v in enumerate(voltages):
            if i:
                jc.set_dc(vna, CH, DC_SOURCE, float(v))
            rows.append(jc.sweep_s21(vna, CH, mnum, DC_SOURCE, SWEEP_TIMEOUT_S))
            dt = jc.elapsed(t0)
            print(f"  [{i + 1:>3}/{len(voltages)}] V = {v:+.5f} V  done  "
                  f"elapsed {dt:6.1f} s, remaining ~{dt / (i + 1) * (len(voltages) - i - 1):6.1f} s")
    finally:
        vna.verbose = True
        meta["dc_output_off_confirmed"] = jc.dc_output_off(vna, DC_SOURCE)
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED after {len(rows)}/{len(voltages)} voltages: {type(e).__name__}: {e}"
    raise
finally:
    meta["end"] = jc.now()
    meta["voltages_measured"] = len(rows)
    vna.close()
    if rows:
        np.savez(run_dir / "data.npz", freq_Hz=freq, voltage_V=voltages[:len(rows)], s21=np.array(rows))
    jc.save_json(run_dir / "params.json", meta)
    print(f"\n  RESULT 2: {meta['status']}  -> {run_dir}")

# %% 3. 分析、畫圖與儲存
import matplotlib.pyplot as plt

print(f"\n=== 3. Analysis ===")
d = np.load(run_dir / "data.npz")
freq, volt, s21 = d["freq_Hz"], d["voltage_V"], d["s21"]
s21_c, tau = jc.remove_delay(freq, s21, ELECTRICAL_DELAY_S)
amp_db = 20 * np.log10(np.abs(s21))
phase = jc.unwrap_2d(s21_c)     # unwrap along frequency, rows aligned along voltage (no 2 pi jumps between rows)
print(f"  {len(volt)} voltages x {len(freq)} points; electrical delay removed: {tau * 1e9:.4f} ns "
      f"({'fitted, median over voltages' if ELECTRICAL_DELAY_S is None else 'fixed'})")

title = f"{SAMPLE}  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
figs = []
plots = [(amp_db, "|S21| [dB]", "S21_amp.png", ""),
         (phase, "Unwrapped phase [rad]", "S21_phase.png", f"\nelectrical delay {tau * 1e9:.3f} ns removed")]
if BACKGROUND is not None:
    s21_n = s21 / jc.background_trace(s21, BACKGROUND, volt)
    bg = "complex median over voltages" if BACKGROUND == "median" else f"row at {BACKGROUND:g} V"
    plots += [(20 * np.log10(np.abs(s21_n)), "|S21| / background [dB]", "S21_amp_norm.png", f"\nnormalized by {bg}"),
              (jc.unwrap_2d(s21_n), "Phase relative to background [rad]", "S21_phase_norm.png",
               f"\nnormalized by {bg}")]
for z, label, fname, extra in plots:
    fig, ax = plt.subplots(figsize=(8, 5))
    if len(volt) > 1:
        m = ax.pcolormesh(freq / 1e9, volt, z, shading="nearest", cmap="viridis")
        fig.colorbar(m, ax=ax, label=label)
        ax.set(ylabel="DC205 voltage [V]")
    else:                      # only one voltage measured (e.g. interrupted): plot it as a line
        ax.plot(freq / 1e9, z[0])
        ax.set(ylabel=label)
    ax.set(xlabel="Frequency [GHz]", title=title + extra)
    fig.tight_layout()
    fig.savefig(run_dir / fname, dpi=150)
    figs.append(fig)
plt.show()

meta = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
meta["analysis"] = {"electrical_delay_s": tau, "delay_fitted": ELECTRICAL_DELAY_S is None,
                    "phase_unwrap": "2d (frequency, then rows aligned along voltage)", "background": BACKGROUND,
                    "voltages_analysed": int(len(volt))}
jc.save_json(run_dir / "params.json", meta)
print(f"  saved: {', '.join(sorted(p.name for p in run_dir.iterdir()))}")
print(f"  RESULT 3: OK -> {run_dir}")

# %%
