"""02_1 flux offset S21, direct DC control: one DC205 bias voltage -> one VNA S21 sweep (no pump).

The DC205 is connected to the server (/dev/dc205) and read back directly (output, voltage, range,
overload, error registers) before and after the sweep. The VNA's own DC sources are disabled.
Same experiment as 02_1_flux_offset_S21.py (which drives the DC205 through the VNA).

Cell 1: parameters. Cell 2: measurement. Cell 3: analysis, plots and saving.
Results: experiment_results/<SAMPLE>/02_1_flux_offset_S21/<YYYYmmdd_HHMMSS>_direct/
The voltage is set while the output is still OFF, the output is switched ON for the sweep and OFF
afterwards; the voltage setting is left at DC_VOLT. The DC205 is not polled during the sweep.
"""
# %% 1. 參數
SAMPLE = "LJPAL53B5d34"        # JPA_params/<SAMPLE>.json

VNA_POWER_DBM = -20.0          # VNA port-1 output power [dBm]
FREQ_MIN_HZ = 4.0e9
FREQ_MAX_HZ = 8.0e9
IF_BW_HZ = 1.0e3
POINTS = 2001
DC_VOLT = 0.0                  # DC205 output voltage [V]

ELECTRICAL_DELAY_S = None      # None: fit from the phase slope; or a fixed value [s]

VNA_IP, VNA_PORT, CH = "192.168.1.23", 5025, 1
DC205_PORT = "/dev/dc205"      # DC205 USB serial port (udev rule /etc/udev/rules.d/99-dc205.rules)
DC_RANGE = "RANGE1"            # "RANGE1" (±1.01 V) or "RANGE10" (±10.1 V)
DC_SETTLE_S = 0.1              # wait after switching the output ON, before the sweep [s]
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

EXPERIMENT = "02_1_flux_offset_S21"
jpa = jc.load_jpa_params(SAMPLE)
params = {
    "experiment": EXPERIMENT, "sample": SAMPLE,
    "vna_power_dBm": VNA_POWER_DBM, "freq_min_Hz": FREQ_MIN_HZ, "freq_max_Hz": FREQ_MAX_HZ,
    "if_bandwidth_Hz": IF_BW_HZ, "points": POINTS, "dc_volt_V": DC_VOLT,
    "electrical_delay_s": ELECTRICAL_DELAY_S,
    "vna": f"{VNA_IP}:{VNA_PORT} CH{CH}", "psg": PSG_IP,
    "dc_control": "direct", "dc205_port": DC205_PORT, "dc_range": DC_RANGE, "dc_settle_s": DC_SETTLE_S,
}
print(f"{EXPERIMENT}  sample {SAMPLE}: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
      f"IFBW {IF_BW_HZ:g} Hz, {VNA_POWER_DBM:g} dBm, DC {DC_VOLT:g} V ({DC_RANGE}, direct)")

# %% 2. 量測
print(f"\n=== 2. Measurement ===")
run_dir = jc.new_run_dir(SAMPLE, EXPERIMENT, tag="direct")
meta = {"params": params, "start": jc.now(), "jpa_params_snapshot": jpa}
vna = jc.SCPI(VNA_IP, VNA_PORT, name="VNA")
dc = None
freq = s21 = None
try:
    meta["vna_idn"] = vna.query("*IDN?")
    print("  PSG check:")
    meta["psg"] = jc.check_psg_off(PSG_IP)
    mnum, meta["vna_readback"] = jc.setup_s21(vna, CH, VNA_POWER_DBM, FREQ_MIN_HZ, FREQ_MAX_HZ, IF_BW_HZ, POINTS)
    jc.vna_dc_off(vna, CH)
    print(f"  DC205 ({DC205_PORT}): {DC_VOLT} V, {DC_RANGE}")
    dc = jc.DC205(DC205_PORT)
    meta["dc205_idn"] = dc.idn
    meta["dc205_before"] = dc.state()
    dc.set_range(DC_RANGE)
    if meta["dc205_before"]["output_on"]:
        dc.output(False, meta["dc205_before"]["volt_V"], DC_RANGE)   # start from output OFF
    dc.set_volt(DC_VOLT, DC_RANGE)                                     # set while OFF: no transient at old voltage
    try:
        dc.output(True, DC_VOLT, DC_RANGE)
        time.sleep(DC_SETTLE_S)
        t0 = time.monotonic()
        print(f"  sweeping (VNA estimate {meta['vna_readback']['sweep_time_s']:.1f} s) ...")
        s21 = jc.sweep_s21(vna, CH, mnum, timeout=SWEEP_TIMEOUT_S)
        freq = jc.read_freq(vna, CH, mnum)
        print(f"  sweep done in {jc.elapsed(t0):.1f} s, {len(freq)} points")
        meta["dc205_after_sweep"] = dc.check(True, DC_VOLT, DC_RANGE, "after sweep")
    finally:
        try:
            meta["dc205_end"] = dc.output(False, DC_VOLT, DC_RANGE)
            meta["dc_output_off_confirmed"] = True
        except Exception as e:
            meta["dc_output_off_confirmed"] = False
            print(f"  !! DC205 output OFF NOT confirmed: {e}  -> CHECK THE DC205 FRONT PANEL")
    meta["status"] = "ok"
except BaseException as e:
    meta["status"] = f"FAILED: {type(e).__name__}: {e}"
    raise
finally:
    meta["end"] = jc.now()
    vna.close()
    if dc is not None:
        dc.close()
    if s21 is not None:
        np.savez(run_dir / "data.npz", freq_Hz=freq, s21=s21, dc_volt_V=DC_VOLT,
                 dc_volt_readback_V=meta["dc205_after_sweep"]["volt_V"] if "dc205_after_sweep" in meta else np.nan)
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

title = f"{SAMPLE}  DC {DC_VOLT:g} V (direct)  {VNA_POWER_DBM:g} dBm  IFBW {IF_BW_HZ:g} Hz"
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
