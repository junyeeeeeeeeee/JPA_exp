"""02_2 flux offset S21 2D, OPX+ flux + ZNB: for each OPX flux bias -> one ZNB S21 sweep (no pump).

Wiring: flux = OPX AO SETUP["flux_ao"] (DC offset) -> DC side of the bias tee. Pump = Octave RF out
SETUP["pump_rf_out"], kept OFF. S21 = ZNB port 1 -> fridge input line -> JPA -> output chain -> ZNB port 2.
Same experiment as ../DC205_E5080B/02_2_flux_offset_S21_2d.py, with the OPX+ as flux source and the ZNB as VNA.

Opening the QM closes every other QM on the cluster (so no pump program keeps playing); both Octave RF outputs
start "always_off" and are never switched on here. Every flux step is read back; the offset returns to 0 V
when the QM closes at the end. Ctrl+C / interrupt keeps the rows measured so far.

Cell 1: parameters. Cell 2: measurement (set flux -> sweep, repeated). Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/02_2_flux_offset_S21_2d/<YYYYmmdd_HHMMSS>_opx_znb/
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

VNA_POWER_DBM = -40.0          # ZNB source power [dBm]
FREQ_MIN_HZ = 4.0e9
FREQ_MAX_HZ = 8.0e9
IF_BW_HZ = 1.0e3
POINTS = 2001
SPARAM = "S21"                 # ZNB20 has 4 ports: S<out><in>
FLUX_MIN_V = -0.05              # OPX flux scan [V], |V| <= 0.5
FLUX_MAX_V = 0.05
FLUX_POINTS = 51
FLUX_SETTLE_S = 0.1            # wait after each flux step, before the sweep [s]

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope (one tau for all flux values); or a fixed value [s]

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

EXPERIMENT = "02_2_flux_offset_S21_2d"
jpa = jc.load_jpa_params(SAMPLE)
fluxes = np.linspace(FLUX_MIN_V, FLUX_MAX_V, FLUX_POINTS)
if np.abs(fluxes).max() > oc.FLUX_LIMIT_V:
    raise ValueError(f"flux scan {FLUX_MIN_V}..{FLUX_MAX_V} V exceeds +-{oc.FLUX_LIMIT_V} V")
p = oc.params(flux_V=float(fluxes[0]))
params = {
    "experiment": EXPERIMENT, "instruments": "OPX+ flux, ZNB", "sample": SAMPLE,
    "vna_power_dBm": VNA_POWER_DBM, "freq_min_Hz": FREQ_MIN_HZ, "freq_max_Hz": FREQ_MAX_HZ,
    "if_bandwidth_Hz": IF_BW_HZ, "points": POINTS, "sparam": SPARAM,
    "flux_min_V": FLUX_MIN_V, "flux_max_V": FLUX_MAX_V, "flux_points": FLUX_POINTS, "flux_settle_s": FLUX_SETTLE_S,
    "electrical_delay_s": ELECTRICAL_DELAY_S, "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "opx_setup": p,
}
print(f"{EXPERIMENT} (OPX+ flux, ZNB)  sample {SAMPLE}: {SPARAM} {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, "
      f"{POINTS} pts, IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm, flux {FLUX_MIN_V:g} -> {FLUX_MAX_V:g} V "
      f"({FLUX_POINTS} steps)")

# %% 2. 量測：設定 flux -> 掃 S21，重複
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="opx_znb")
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = qm = None
freq, rows, flux_rb = None, [], []      # rows[i] = S21 at fluxes[i]; flux_rb[i] = OPX readback
try:
    vna = jc.SCPI(VNA_IP, VNA_PORT, name="ZNB")
    meta["vna_idn"] = vna.query("*IDN?")
    trace, meta["vna_readback"] = zc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS,
                                               SPARAM)
    freq = zc.read_freq(vna, CH)
    print("  OPX+:")
    qmm = oc.connect(p)
    meta["opx_versions"] = str(qmm.version())
    qm = oc.open_qm(qmm, oc.build_config(p))      # RF outputs OFF (pump never switched on here)
    vna.verbose = False    # one progress line per flux value instead of every SCPI line
    t0 = time.monotonic()
    for i, v in enumerate(fluxes):
        flux_rb.append(oc.set_flux(qm, float(v)))
        time.sleep(FLUX_SETTLE_S)
        rows.append(zc.sweep_s21(vna, CH, trace, SWEEP_TIMEOUT_S))
        dt = jc.elapsed(t0)
        print(f"  [{i + 1:>3}/{len(fluxes)}] flux = {v:+.5f} V  done  "
              f"elapsed {dt:6.1f} s, remaining ~{dt / (i + 1) * (len(fluxes) - i - 1):6.1f} s")
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED after {len(rows)}/{len(fluxes)} flux values: {type(e).__name__}: {e}"
    raise
finally:
    if qm is not None:
        qm.close()                 # flux offset back to 0 V
        print("  QM closed: RF outputs OFF, flux offset 0 V.")
    if vna is not None:
        vna.close()
    meta["end"] = jc.now()
    meta["flux_values_measured"] = len(rows)
    if rows:
        np.savez(run_dir / "data.npz", freq_Hz=freq, flux_V=fluxes[:len(rows)],
                 flux_readback_V=np.array(flux_rb[:len(rows)]), s21=np.array(rows))
    jc.save_json(run_dir / "params.json", meta)
    print(f"\n  RESULT 2: {meta['status']}  -> {run_dir}")

# %% 3. 分析、畫圖與儲存
import matplotlib.pyplot as plt

print(f"\n=== 3. Analysis ===")
d = np.load(run_dir / "data.npz")
freq, flux, s21 = d["freq_Hz"], d["flux_V"], d["s21"]
s21_c, tau = jc.remove_delay(freq, s21, ELECTRICAL_DELAY_S)
amp_db = 20 * np.log10(np.abs(s21))
phase = np.unwrap(np.angle(s21_c), axis=1)     # unwrap along frequency, per flux value
print(f"  {len(flux)} flux values x {len(freq)} points; electrical delay removed: {tau * 1e9:.4f} ns "
      f"({'fitted, median over flux values' if ELECTRICAL_DELAY_S is None else 'fixed'})")

title = f"{SAMPLE}  ZNB {SPARAM}  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
figs = []
for z, label, fname in [(amp_db, f"|{SPARAM}| [dB]", "S21_amp.png"),
                        (phase, "Unwrapped phase [rad]", "S21_phase.png")]:
    fig, ax = plt.subplots(figsize=(8, 5))
    if len(flux) > 1:
        m = ax.pcolormesh(freq / 1e9, flux, z, shading="nearest", cmap="viridis")
        fig.colorbar(m, ax=ax, label=label)
        ax.set(ylabel="OPX flux offset [V]")
    else:                      # only one flux value measured (e.g. interrupted): plot it as a line
        ax.plot(freq / 1e9, z[0])
        ax.set(ylabel=label)
    extra = f"\nelectrical delay {tau * 1e9:.3f} ns removed" if "phase" in fname else ""
    ax.set(xlabel="Frequency [GHz]", title=title + extra)
    fig.tight_layout()
    fig.savefig(run_dir / fname, dpi=150)
    figs.append(fig)
plt.show()

meta = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
meta["analysis"] = {"electrical_delay_s": tau, "delay_fitted": ELECTRICAL_DELAY_S is None,
                    "flux_values_analysed": int(len(flux))}
jc.save_json(run_dir / "params.json", meta)
print(f"  saved: {', '.join(sorted(p.name for p in run_dir.iterdir()))}")
print(f"  RESULT 3: OK -> {run_dir}")

# %%
