"""02_2 flux offset S21 2D, direct DC control: for each DC205 bias voltage -> one VNA S21 sweep (no pump).

The DC205 is connected to the server (/dev/dc205). At every voltage it is read back directly
(output, voltage, range, overload, error registers) after setting and again after the sweep; the
readbacks are saved. The VNA's own DC sources are disabled. The DC205 is not polled during sweeps.
Same experiment as 02_2_flux_offset_S21_2d.py (which drives the DC205 through the VNA).

Cell 1: parameters. Cell 2: measurement (set voltage -> sweep, repeated). Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/02_2_flux_offset_S21_2d/<YYYYmmdd_HHMMSS>_direct/
The first voltage is set while the output is still OFF, the output is switched ON for the scan and OFF
afterwards; the voltage setting is left at the last measured voltage. Ctrl+C / interrupt keeps the rows measured so far.
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
DC205_PORT = "/dev/dc205"      # DC205 USB serial port (udev rule /etc/udev/rules.d/99-dc205.rules)
DC_RANGE = "RANGE1"            # "RANGE1" (±1.01 V) or "RANGE10" (±10.1 V); all voltages must fit
DC_SETTLE_S = 0.1              # wait after each voltage change, before the sweep [s]
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
    "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "psg": PSG_IP,
    "dc_control": "direct", "dc205_port": DC205_PORT, "dc_range": DC_RANGE, "dc_settle_s": DC_SETTLE_S,
}
print(f"{EXPERIMENT}  sample {SAMPLE}: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
      f"IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm, DC {VOLTAGE_MIN:g} -> {VOLTAGE_MAX:g} V ({VOLTAGE_POINTS} steps, {DC_RANGE}, direct)")

# %% 2. 量測：設定電壓（讀回確認）-> 掃 S21 -> 再讀回確認，重複
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="direct")
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = jc.SCPI(VNA_IP, VNA_PORT, name="VNA")
dc = None
freq, rows = None, []          # rows[i] = S21 at voltages[i]
rb_set, rb_after = [], []      # DC205 voltage read back after setting / after the sweep
try:
    meta["vna_idn"] = vna.query("*IDN?")
    print("  PSG check:")
    meta["psg"] = jc.check_psg_off(PSG_IP)
    mnum, meta["vna_readback"] = jc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS)
    jc.vna_dc_off(vna, CH)
    freq = jc.read_freq(vna, CH, mnum)
    print(f"  DC205 ({DC205_PORT}): {DC_RANGE}, first voltage {voltages[0]:g} V")
    dc = jc.DC205(DC205_PORT)
    meta["dc205_idn"] = dc.idn
    meta["dc205_before"] = dc.state()
    for v in (VOLTAGE_MIN, VOLTAGE_MAX):   # check the whole scan fits before switching anything on
        if abs(v) > dc.RANGE_V[DC_RANGE]:
            raise ValueError(f"{v} V is outside {DC_RANGE} (±{dc.RANGE_V[DC_RANGE]} V)")
    dc.set_range(DC_RANGE)
    if meta["dc205_before"]["output_on"]:
        dc.output(False, meta["dc205_before"]["volt_V"], DC_RANGE)   # start from output OFF
    dc.set_volt(float(voltages[0]), DC_RANGE)                          # set while OFF: no transient at old voltage
    v_now = float(voltages[0])
    try:
        dc.output(True, v_now, DC_RANGE)
        vna.verbose = dc.verbose = False   # one progress line per voltage; mismatches are still printed
        t0 = time.monotonic()
        for i, v in enumerate(voltages):
            v_now = float(v)
            rb_set.append(dc.set_volt(v_now, DC_RANGE)["volt_V"])
            time.sleep(DC_SETTLE_S)
            rows.append(jc.sweep_s21(vna, CH, mnum, timeout=SWEEP_TIMEOUT_S))
            rb_after.append(dc.check(True, v_now, DC_RANGE, f"after {v_now:+.4f}")["volt_V"])
            dt = jc.elapsed(t0)
            print(f"  [{i + 1:>3}/{len(voltages)}] V = {v_now:+.5f} V (DC205 read {rb_after[-1]:+.6f} V, ON)  "
                  f"elapsed {dt:6.1f} s, remaining ~{dt / (i + 1) * (len(voltages) - i - 1):6.1f} s")
    finally:
        vna.verbose = dc.verbose = True
        try:
            meta["dc205_end"] = dc.output(False, v_now, DC_RANGE)
            meta["dc_output_off_confirmed"] = True
        except Exception as e:
            meta["dc_output_off_confirmed"] = False
            print(f"  !! DC205 output OFF NOT confirmed: {e}  -> CHECK THE DC205 FRONT PANEL")
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED after {len(rows)}/{len(voltages)} voltages: {type(e).__name__}: {e}"
    raise
finally:
    meta["end"] = jc.now()
    meta["voltages_measured"] = len(rows)
    vna.close()
    if dc is not None:
        dc.close()
    if rows:
        n = len(rows)
        after = np.full(n, np.nan)
        after[:len(rb_after)] = rb_after[:n]
        np.savez(run_dir / "data.npz", freq_Hz=freq, voltage_V=voltages[:n], s21=np.array(rows),
                 dc_volt_readback_set_V=np.array(rb_set[:n]), dc_volt_readback_after_sweep_V=after)
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

title = f"{SAMPLE}  DC direct  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
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
