"""01_S21 with the Keysight E5080B VNA: one S21 sweep, no pump, no DC bias driven.

The VNA's External DC Sources are disabled for the sweep (SOUR:DC:ENAB OFF), so the DC205 is not touched.
For S21 at a given flux bias use 02_flux_offset/DC205_E5080B/02_1_flux_offset_S21.py.

Cell 1: parameters. Cell 2: measurement. Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/01_S21/<YYYYmmdd_HHMMSS>_e5080b/
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

VNA_POWER_DBM = -20.0          # VNA port-1 output power [dBm]
FREQ_MIN_HZ = 4.0e9
FREQ_MAX_HZ = 8.0e9
IF_BW_HZ = 1.0e3
POINTS = 2001

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope; or a fixed value [s]

VNA_IP, VNA_PORT, CH = "192.168.1.23", 5025, 1
PSG_IP = "192.168.1.33"        # read only: the measurement stops if the pump RF output is ON; None = no check
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

EXPERIMENT = "01_S21"
jpa = jc.load_jpa_params(SAMPLE)
params = {
    "experiment": EXPERIMENT, "instrument": "E5080B", "sample": SAMPLE,
    "vna_power_dBm": VNA_POWER_DBM, "freq_min_Hz": FREQ_MIN_HZ, "freq_max_Hz": FREQ_MAX_HZ,
    "if_bandwidth_Hz": IF_BW_HZ, "points": POINTS, "electrical_delay_s": ELECTRICAL_DELAY_S,
    "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "psg": PSG_IP,
}
print(f"{EXPERIMENT} (E5080B)  sample {SAMPLE}: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
      f"IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm")

# %% 2. 量測
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="e5080b")
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = jc.SCPI(VNA_IP, VNA_PORT, name="VNA")
freq = s21 = None
try:
    meta["vna_idn"] = vna.query("*IDN?")
    if PSG_IP is not None:
        print("  PSG check:")
        meta["psg"] = jc.check_psg_off(PSG_IP)
    mnum, meta["vna_readback"] = jc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS)
    jc.vna_dc_off(vna, CH)
    t0 = time.monotonic()
    print(f"  sweeping (VNA estimate {meta['vna_readback']['sweep_time_s']:.1f} s) ...")
    s21 = jc.sweep_s21(vna, CH, mnum, None, SWEEP_TIMEOUT_S)
    freq = jc.read_freq(vna, CH, mnum)
    print(f"  sweep done in {jc.elapsed(t0):.1f} s, {len(freq)} points")
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED: {type(e).__name__}: {e}"
    raise
finally:
    meta["end"] = jc.now()
    vna.close()
    if s21 is not None:
        np.savez(run_dir / "data.npz", freq_Hz=freq, s21=s21)
    jc.save_json(run_dir / "params.json", meta)
    print(f"\n  RESULT 2: {meta['status']}  -> {run_dir}")

# %% 3. 分析、畫圖與儲存
import matplotlib.pyplot as plt

print(f"\n=== 3. Analysis ===")
d = np.load(run_dir / "data.npz")
freq, s21 = d["freq_Hz"], d["s21"]
s21_c, tau = jc.remove_delay(freq, s21, ELECTRICAL_DELAY_S)
amp_db = 20 * np.log10(np.abs(s21))
phase = np.unwrap(np.angle(s21_c))
print(f"  electrical delay removed: {tau * 1e9:.4f} ns ({'fitted' if ELECTRICAL_DELAY_S is None else 'fixed'})")

title = f"{SAMPLE}  E5080B  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
fig1, ax1 = plt.subplots(figsize=(8, 4))
ax1.plot(freq / 1e9, amp_db)
ax1.set(xlabel="Frequency [GHz]", ylabel="|S21| [dB]", title=title)
ax1.grid(alpha=0.3)
fig1.tight_layout()
fig1.savefig(run_dir / "S21_amp.png", dpi=150)

fig2, ax2 = plt.subplots(figsize=(8, 4))
ax2.plot(freq / 1e9, phase)
ax2.set(xlabel="Frequency [GHz]", ylabel="Unwrapped phase [rad]",
        title=f"{title}\nelectrical delay {tau * 1e9:.3f} ns removed")
ax2.grid(alpha=0.3)
fig2.tight_layout()
fig2.savefig(run_dir / "S21_phase.png", dpi=150)
plt.show()

np.savetxt(run_dir / "data.csv", np.column_stack([freq, s21.real, s21.imag, amp_db, phase]), delimiter=",",
           header="freq_Hz,S21_re,S21_im,S21_amp_dB,S21_phase_unwrapped_rad_delay_removed", comments="")
meta = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
meta["analysis"] = {"electrical_delay_s": tau, "delay_fitted": ELECTRICAL_DELAY_S is None,
                    "amp_dB_min": float(amp_db.min()), "freq_at_amp_min_Hz": float(freq[np.argmin(amp_db)])}
jc.save_json(run_dir / "params.json", meta)
print(f"  saved: {', '.join(sorted(p.name for p in run_dir.iterdir()))}")
print(f"  RESULT 3: OK -> {run_dir}")

# %%
