"""02_1 flux offset S21, OPX+ flux + ZNB: one OPX flux bias -> one ZNB S21 sweep (no pump).

Wiring: flux = OPX AO SETUP["flux_ao"] (DC offset) -> DC side of the bias tee. Pump = Octave RF out
SETUP["pump_rf_out"], kept OFF. S21 = ZNB port 1 -> fridge input line -> JPA -> output chain -> ZNB port 2.
Same experiment as ../DC205_E5080B/02_1_flux_offset_S21.py, with the OPX+ as flux source and the ZNB as VNA.

Opening the QM closes every other QM on the cluster (so no pump program keeps playing); both Octave RF outputs
start "always_off" and are never switched on here. The flux offset is set and read back, held during the sweep,
and returns to 0 V when the QM closes at the end.

Cell 1: parameters. Cell 2: measurement. Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/02_1_flux_offset_S21/<YYYYmmdd_HHMMSS>_opx_znb/
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

VNA_POWER_DBM = -20.0          # ZNB source power [dBm]
FREQ_MIN_HZ = 2.0e9
FREQ_MAX_HZ = 10.0e9
IF_BW_HZ = 1.0e3
POINTS = 2001
SPARAM = "S21"                 # ZNB20 has 4 ports: S<out><in>
FLUX_V = 0.0                   # OPX flux offset [V], |V| <= 0.5
FLUX_SETTLE_S = 0.1            # wait after setting the flux, before the sweep [s]

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope; or a fixed value [s]
BACKGROUND_NPZ = None          # data.npz of a reference run on the same frequency grid (e.g. resonance out of band;
                               # a 2D run gives its complex median): extra plot of S21 / background; None: no plot

VNA_IP, VNA_PORT, CH = "192.168.1.123", 5025, 1
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
import opx_common as oc
import znb_common as zc
import json
import time
import numpy as np

EXPERIMENT = "02_1_flux_offset_S21"
jpa = jc.load_jpa_params(SAMPLE)
p = oc.params(flux_V=FLUX_V)
params = {
    "experiment": EXPERIMENT, "instruments": "OPX+ flux, ZNB", "sample": SAMPLE,
    "vna_power_dBm": VNA_POWER_DBM, "freq_min_Hz": FREQ_MIN_HZ, "freq_max_Hz": FREQ_MAX_HZ,
    "if_bandwidth_Hz": IF_BW_HZ, "points": POINTS, "sparam": SPARAM, "flux_V": FLUX_V,
    "flux_settle_s": FLUX_SETTLE_S, "electrical_delay_s": ELECTRICAL_DELAY_S, "background_npz": BACKGROUND_NPZ,
    "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "opx_setup": p,
}
print(f"{EXPERIMENT} (OPX+ flux, ZNB)  sample {SAMPLE}: {SPARAM} {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, "
      f"{POINTS} pts, IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm, flux {FLUX_V:g} V")

# %% 2. 量測
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="opx_znb")
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = qm = None
freq = s21 = None
try:
    vna = jc.SCPI(VNA_IP, VNA_PORT, name="ZNB")
    meta["vna_idn"] = vna.query("*IDN?")
    trace, meta["vna_readback"] = zc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS,
                                               SPARAM)
    print("  OPX+:")
    qmm = oc.connect(p)
    meta["opx_versions"] = str(qmm.version())
    qm = oc.open_qm(qmm, oc.build_config(p))      # RF outputs OFF (pump never switched on here)
    meta["flux_readback_V"] = oc.set_flux(qm, FLUX_V)
    time.sleep(FLUX_SETTLE_S)
    t0 = time.monotonic()
    print(f"  sweeping (ZNB estimate {meta['vna_readback']['sweep_time_s']:.1f} s) ...")
    s21 = zc.sweep_s21(vna, CH, trace, SWEEP_TIMEOUT_S)
    freq = zc.read_freq(vna, CH)
    print(f"  sweep done in {jc.elapsed(t0):.1f} s, {len(freq)} points")
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED: {type(e).__name__}: {e}"
    raise
finally:
    if qm is not None:
        qm.close()                 # flux offset back to 0 V
        print("  QM closed: RF outputs OFF, flux offset 0 V.")
    if vna is not None:
        vna.close()
    meta["end"] = jc.now()
    if s21 is not None:
        np.savez(run_dir / "data.npz", freq_Hz=freq, s21=s21, flux_V=FLUX_V)
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

title = f"{SAMPLE}  ZNB {SPARAM}  flux {float(d['flux_V']):g} V (OPX)  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
fig1, ax1 = plt.subplots(figsize=(8, 4))
ax1.plot(freq / 1e9, amp_db)
ax1.set(xlabel="Frequency [GHz]", ylabel=f"|{SPARAM}| [dB]", title=title)
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

if BACKGROUND_NPZ:
    s21_n = s21 / jc.load_background(BACKGROUND_NPZ, freq)
    fig3, (ax3a, ax3b) = plt.subplots(2, 1, sharex=True, figsize=(8, 6))
    ax3a.plot(freq / 1e9, 20 * np.log10(np.abs(s21_n)))
    ax3a.set(ylabel=f"|{SPARAM}| / background [dB]", title=f"{title}\nnormalized by {BACKGROUND_NPZ}")
    ax3b.plot(freq / 1e9, np.unwrap(np.angle(s21_n)))
    ax3b.set(xlabel="Frequency [GHz]", ylabel="Phase relative to background [rad]")
    for a in (ax3a, ax3b):
        a.grid(alpha=0.3)
    fig3.tight_layout()
    fig3.savefig(run_dir / "S21_norm.png", dpi=150)
plt.show()

np.savetxt(run_dir / "data.csv", np.column_stack([freq, s21.real, s21.imag, amp_db, phase]), delimiter=",",
           header="freq_Hz,S21_re,S21_im,S21_amp_dB,S21_phase_unwrapped_rad_delay_removed", comments="")
meta = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
meta["analysis"] = {"electrical_delay_s": tau, "delay_fitted": ELECTRICAL_DELAY_S is None,
                    "background_npz": str(BACKGROUND_NPZ) if BACKGROUND_NPZ else None,
                    "amp_dB_min": float(amp_db.min()), "freq_at_amp_min_Hz": float(freq[np.argmin(amp_db)])}
jc.save_json(run_dir / "params.json", meta)
print(f"  saved: {', '.join(sorted(p.name for p in run_dir.iterdir()))}")
print(f"  RESULT 3: OK -> {run_dir}")

# %%
