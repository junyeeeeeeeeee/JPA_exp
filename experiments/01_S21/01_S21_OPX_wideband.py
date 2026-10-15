"""01_S21 wide-band S21 with OPX+ / Octave: the band is split into LO segments, IF is swept inside each one.

Wiring: Octave RF out SETUP["ro_rf_out"] -> fridge input line -> JPA -> output chain -> Octave RF in
SETUP["ro_rf_in"]. Pump RF output stays OFF. Flux: OPX AO SETUP["flux_ao"] at FLUX_V, back to 0 V at the end.

Per segment: Octave LO -> LO (up- and down-converter), stored mixer calibration for that LO applied if it exists,
then one QUA program sweeps the IF list N_AVG times. The segments are stitched on one frequency grid; where
neighbours overlap, the joint mismatch (dB, deg) is saved, so LO-to-LO steps are visible.
CALIBRATE = True runs the Octave automatic calibration for every LO first (saved to opx_calibration/).

The amplitude is the demodulated amplitude at the OPX ADC [V] ("uncalibrated S21"): it includes the
Octave conversion gain, which changes with LO. Compare runs, or divide by a reference run.

Cell 1: parameters. Cell 2: measurement. Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/01_S21/<YYYYmmdd_HHMMSS>_opx/
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

F_START_HZ = 2.0e9
F_STOP_HZ = 10.0e9
DF_HZ = 0.5e6                  # frequency step (global grid); the delay fit needs delay < 1/(2 DF) (1 us at 0.5 MHz)
SIDES = "upper"                # "upper": IF_MIN..IF_MAX, LO below the segment; "both": LO in the middle, IF -IF_MAX..+IF_MAX
IF_MAX_HZ = 300e6              # OPX+ analog bandwidth ~ +-350 MHz
IF_MIN_HZ = 20e6               # |IF| < IF_MIN_HZ is skipped (keeps LO leakage / DC offsets out of the data)
OVERLAP_HZ = 20e6              # overlap between neighbouring segments (joint mismatch check)
CALIBRATE = True               # True: Octave auto-calibration at every LO before measuring

N_AVG = 200
RO_LEN_NS = 2_000              # integration time per point (~ 1/T = 500 kHz equivalent IF bandwidth per shot)
WAIT_NS = 1_000                # wait after each point (ring-down)
RO_AMP_V = 0.05                # OPX amplitude [V], 0 .. 0.5 (readout power, with RO_GAIN_DB)
RO_GAIN_DB = 0.0               # Octave RF out gain [dB], -20 .. +20 in 0.5 dB steps
FLUX_V = 0.0                   # OPX flux offset [V], |V| <= 0.5; None = flux output not touched

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope inside the segments; or a fixed value [s]
STITCH_ALIGN = "phase"         # "none" | "phase" | "phase+amp": align each segment to the previous one on the overlap
REANALYZE_DIR = None           # path of an earlier run: skip cell 2 and only redo the analysis (cell 3) on its data

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
import json
import time
import numpy as np

EXPERIMENT = "01_S21"
jpa = jc.load_jpa_params(SAMPLE)
plan = oc.segment_plan(F_START_HZ, F_STOP_HZ, DF_HZ, IF_MAX_HZ, IF_MIN_HZ, SIDES, OVERLAP_HZ)
cal_if = IF_MAX_HZ / 2 if SIDES == "both" else (IF_MIN_HZ + IF_MAX_HZ) / 2   # IF used for the image correction
p = oc.params(ro_lo_Hz=plan[0]["lo_Hz"], ro_if_Hz=cal_if, ro_len_ns=RO_LEN_NS, ro_amp_V=RO_AMP_V,
              ro_gain_dB=RO_GAIN_DB, **({} if FLUX_V is None else {"flux_V": FLUX_V}))
n_pts = sum(len(s["if_Hz"]) for s in plan)
est_s = n_pts * N_AVG * (RO_LEN_NS + WAIT_NS + 100) * 1e-9 + 3 * len(plan)
params = {
    "experiment": EXPERIMENT, "sample": SAMPLE,
    "f_start_Hz": F_START_HZ, "f_stop_Hz": F_STOP_HZ, "df_Hz": DF_HZ, "sides": SIDES,
    "if_max_Hz": IF_MAX_HZ, "if_min_Hz": IF_MIN_HZ, "overlap_Hz": OVERLAP_HZ, "calibrate": CALIBRATE,
    "calibration_if_Hz": cal_if, "n_avg": N_AVG, "ro_len_ns": RO_LEN_NS, "wait_ns": WAIT_NS,
    "ro_amp_V": RO_AMP_V, "ro_gain_dB": RO_GAIN_DB, "flux_V": FLUX_V,
    "electrical_delay_s": ELECTRICAL_DELAY_S, "stitch_align": STITCH_ALIGN, "opx_setup": p,
    "segments": [{"lo_Hz": s["lo_Hz"], "f_min_Hz": float(s["f_Hz"].min()), "f_max_Hz": float(s["f_Hz"].max()),
                  "n_points": len(s["if_Hz"])} for s in plan],
}
print(f"{EXPERIMENT}  sample {SAMPLE}: {F_START_HZ/1e9:g}-{F_STOP_HZ/1e9:g} GHz, step {DF_HZ/1e6:g} MHz, "
      f"{len(plan)} segments ({SIDES}, |IF| {IF_MIN_HZ/1e6:g}-{IF_MAX_HZ/1e6:g} MHz), {n_pts} points, "
      f"N_AVG {N_AVG}, ~{est_s/60:.1f} min" + (" + calibration" if CALIBRATE else ""))
for s in plan:
    print(f"    LO {s['lo_Hz']/1e9:8.4f} GHz: {s['f_Hz'].min()/1e9:.4f}-{s['f_Hz'].max()/1e9:.4f} GHz, "
          f"{len(s['if_Hz'])} pts")

# %% 2. 量測
if REANALYZE_DIR is not None:
    run_dir = Path(REANALYZE_DIR)
    print(f"\n=== 2. Skipped: re-analysing {run_dir} ===")
else:
    print(f"\n=== 2. Measurement ===")
    run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="opx")
    meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
    data = []
    qm = None
    try:
        qmm = oc.connect(p)
        meta["versions"] = str(qmm.version())
        qm = oc.open_qm(qmm, oc.build_config(p))
        if FLUX_V is not None:
            meta["flux_readback_V"] = oc.set_flux(qm, FLUX_V)
        if CALIBRATE:
            t0 = time.monotonic()
            print(f"  calibrating 'ro' at {len(plan)} LOs (IF {cal_if/1e6:g} MHz) ...")
            qm.calibrate_element("ro", {s["lo_Hz"]: [cal_if] for s in plan})
            meta["calibration_s"] = jc.elapsed(t0)
            print(f"  calibration done in {meta['calibration_s']:.0f} s")
        oc.rf_on(qm, "ro")
        t0 = time.monotonic()
        for k, s in enumerate(plan):
            oc.tune_ro_lo(qm, s["lo_Hz"])
            data.append(oc.measure_s21_segment(qm, s, N_AVG, RO_LEN_NS, WAIT_NS))
            print(f"  segment {k + 1}/{len(plan)}  LO {s['lo_Hz']/1e9:.4f} GHz done  ({jc.elapsed(t0):.0f} s)")
        meta["measure_s"] = jc.elapsed(t0)
        meta["status"] = "ok"
    except BaseException as e:
        meta["status"] = f"FAILED: {type(e).__name__}: {e}"
        raise
    finally:
        if qm is not None:
            try:
                oc.rf_off(qm, "ro")
            finally:
                qm.close()                 # flux offset back to 0 V
                print("  QM closed: RF outputs OFF, flux offset 0 V.")
        meta["end"] = jc.now()
        meta["segments_measured"] = len(data)
        if data:
            done = plan[:len(data)]
            np.savez(run_dir / "data_segments.npz",
                     seg=np.concatenate([np.full(len(s["if_Hz"]), k) for k, s in enumerate(done)]),
                     lo_Hz=np.array([s["lo_Hz"] for s in done]),
                     f_Hz=np.concatenate([s["f_Hz"] for s in done]),
                     if_Hz=np.concatenate([s["if_Hz"] for s in done]),
                     z_V=np.concatenate(data))
        jc.save_json(run_dir / "params.json", meta)
        print(f"\n  RESULT 2: {meta['status']}  -> {run_dir}")

# %% 3. 分析、畫圖與儲存
import matplotlib.pyplot as plt

print(f"\n=== 3. Analysis ===")
d = np.load(run_dir / "data_segments.npz")
seg_ids = np.unique(d["seg"])
plan_d = [{"lo_Hz": d["lo_Hz"][k], "f_Hz": d["f_Hz"][d["seg"] == k], "if_Hz": d["if_Hz"][d["seg"] == k]}
          for k in seg_ids]
data_d = [d["z_V"][d["seg"] == k] for k in seg_ids]
freq, s21, seg_idx, joints = oc.stitch(plan_d, data_d, STITCH_ALIGN)
tau = oc.fit_delay(freq, s21, seg_idx) if ELECTRICAL_DELAY_S is None else ELECTRICAL_DELAY_S
s21_c, tau = jc.remove_delay(freq, s21, tau)
amp_db = 20 * np.log10(np.abs(s21))
phase = np.unwrap(np.angle(s21_c))
print(f"  stitching: {STITCH_ALIGN}; electrical delay removed: {tau * 1e9:.4f} ns "
      f"({'fitted' if ELECTRICAL_DELAY_S is None else 'fixed'})")
print("  raw joint mismatch (next segment / previous one, before alignment):")
for j in joints:
    print(f"  joint {j['lo_a_Hz']/1e9:.3f} -> {j['lo_b_Hz']/1e9:.3f} GHz ({j['n_points']} pts @ {j['f_Hz']/1e9:.3f} GHz): "
          f"{j['dB_mean']:+.2f} dB, {j['deg_mean']:+.1f} deg")

rp = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))["params"]
title = (f"{SAMPLE}  OPX+/Octave  {len(plan_d)} LO segments  amp {rp['ro_amp_V']} V, gain {rp['ro_gain_dB']:g} dB  "
         f"N_AVG {rp['n_avg']}  cal {rp['calibrate']}  stitch {STITCH_ALIGN}")
fig1, ax1 = plt.subplots(figsize=(10, 4))
for k in seg_ids:
    m = seg_idx == k
    ax1.plot(freq[m] / 1e9, amp_db[m], ".", ms=2)
for lo in d["lo_Hz"]:
    ax1.axvline(lo / 1e9, color="0.8", lw=0.6, zorder=0)
ax1.set(xlabel="Frequency [GHz]", ylabel="|S21| uncalibrated [dB V]", title=title + "\n(grey lines: LO)")
ax1.title.set_fontsize(9)
ax1.grid(alpha=0.3)
fig1.tight_layout()
fig1.savefig(run_dir / "S21_amp.png", dpi=150)

fig2, ax2 = plt.subplots(figsize=(10, 4))
for k in seg_ids:
    m = seg_idx == k
    ax2.plot(freq[m] / 1e9, phase[m], ".", ms=2)
ax2.set(xlabel="Frequency [GHz]", ylabel="Unwrapped phase [rad]",
        title=f"{title}\nelectrical delay {tau * 1e9:.3f} ns removed")
ax2.title.set_fontsize(9)
ax2.grid(alpha=0.3)
fig2.tight_layout()
fig2.savefig(run_dir / "S21_phase.png", dpi=150)

if joints:
    fig3, ax3 = plt.subplots(1, 2, figsize=(10, 3.5))
    jf = np.array([j["f_Hz"] for j in joints]) / 1e9
    ax3[0].plot(jf, [j["dB_mean"] for j in joints], "o-")
    ax3[0].set(xlabel="Joint frequency [GHz]", ylabel="Step at joint [dB]", title="Segment joint mismatch (raw)")
    ax3[1].plot(jf, [j["deg_mean"] for j in joints], "o-")
    ax3[1].set(xlabel="Joint frequency [GHz]", ylabel="Step at joint [deg]")
    for a in ax3:
        a.grid(alpha=0.3)
    fig3.tight_layout()
    fig3.savefig(run_dir / "joints.png", dpi=150)
plt.show()

np.savez(run_dir / "data.npz", freq_Hz=freq, s21=s21, seg=seg_idx)
np.savetxt(run_dir / "data.csv", np.column_stack([freq, s21.real, s21.imag, amp_db, phase, seg_idx]), delimiter=",",
           header="freq_Hz,S21_re_V,S21_im_V,S21_amp_dBV,S21_phase_unwrapped_rad_delay_removed,segment", comments="")
meta = json.loads((run_dir / "params.json").read_text(encoding="utf-8"))
meta["analysis"] = {"electrical_delay_s": tau, "delay_fitted": ELECTRICAL_DELAY_S is None, "joints": joints,
                    "stitch_align": STITCH_ALIGN, "analysed": jc.now(),
                    "amp_dB_min": float(amp_db.min()), "freq_at_amp_min_Hz": float(freq[np.argmin(amp_db)])}
jc.save_json(run_dir / "params.json", meta)
print(f"  saved: {', '.join(sorted(p.name for p in run_dir.iterdir()))}")
print(f"  RESULT 3: OK -> {run_dir}")

# %%
