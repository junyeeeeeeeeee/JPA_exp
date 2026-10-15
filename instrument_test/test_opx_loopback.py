"""Loopback test: Octave RF out (ro) -> cable + attenuator -> Octave RF in -> OPX AI1/AI2.

WIRING (not to the fridge): Octave RF out SETUP["ro_rf_out"] -> >= 20 dB attenuator ->
Octave RF in SETUP["ro_rf_in"]. Disconnect the pump output or terminate it with 50 ohm.

Read-only unless APPLY = True. With APPLY = True:
  - the readout RF output is switched ON only while the program runs, then OFF;
  - raw ADC traces of the readout pulse are averaged;
  - the script prints the time_of_flight and analog-input offsets to copy into
    SETUP in experiments/opx_common.py, and warns if the ADC is close to saturation.
"""
# %% 參數
APPLY = False
N_AVG = 200
RO_AMP_V = 0.05                # OPX amplitude for this test (with gain 0 dB)
RO_GAIN_DB = 0.0

import sys
from pathlib import Path

try:
    _here = Path(__file__).resolve().parent
except NameError:              # VS Code interactive window
    _here = Path.cwd()
_root = next(p for p in [_here, *_here.parents] if (p / "experiments" / "opx_common.py").exists())
sys.path.insert(0, str(_root / "experiments"))
import numpy as np
import opx_common as oc

p = oc.params(ro_amp_V=RO_AMP_V, ro_gain_dB=RO_GAIN_DB)
if "XX" in p["host"]:
    raise SystemExit("Set SETUP['host'] and SETUP['cluster_name'] in experiments/opx_common.py first.")
print(f"ro: LO {p['ro_lo_Hz']/1e9:g} GHz, IF {p['ro_if_Hz']/1e6:g} MHz, amp {p['ro_amp_V']} V, "
      f"gain {p['ro_gain_dB']} dB, pulse {p['ro_len_ns']} ns, current time_of_flight {p['time_of_flight_ns']} ns")
if not APPLY:
    raise SystemExit("APPLY = False: nothing sent. Check the loopback wiring, then set APPLY = True.")

# %% 1. 量測 raw ADC
print("\n=== 1. Raw ADC traces ===")
qmm = oc.connect(p)
qm = oc.open_qm(qmm, oc.build_config(p))
try:
    oc.rf_on(qm, "ro")
    job = qm.execute(oc.raw_adc_program(N_AVG))
    res = job.result_handles
    res.wait_for_all_values()
    adc1 = oc.raw2volts(res.get("adc1").fetch_all())
    adc2 = oc.raw2volts(res.get("adc2").fetch_all())
    adc1_single = oc.raw2volts(res.get("adc1_single").fetch_all())
    adc2_single = oc.raw2volts(res.get("adc2_single").fetch_all())
finally:
    oc.rf_off(qm, "ro")
    qm.close()

# %% 2. 分析
print("\n=== 2. Analysis ===")
peak = max(np.max(np.abs(adc1_single)), np.max(np.abs(adc2_single)))
print(f"    single-shot peak |ADC| = {peak:.3f} V (full scale 0.5 V)")
if peak > 0.4:
    print("    WARNING: close to ADC saturation -> lower RO_AMP_V / RO_GAIN_DB or add attenuation.")
if peak < 0.01:
    print("    WARNING: signal is very small -> check the loopback cable, or raise RO_AMP_V / ai_gain_dB.")
arrival, tof = oc.find_time_of_flight(adc1, adc2, p["time_of_flight_ns"])
print(f"    pulse arrives {arrival} ns into the trace")
print(f"    -> SETUP['time_of_flight_ns'] = {tof}")
print(f"    -> SETUP['ai_offsets_V'] = ({p['ai_offsets_V'][0] - np.mean(adc1):.6f}, "
      f"{p['ai_offsets_V'][1] - np.mean(adc2):.6f})")

import matplotlib.pyplot as plt
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
for a, (y1, y2), title in zip(ax, [(adc1_single, adc2_single), (adc1, adc2)], ["Single run", f"Average of {N_AVG}"]):
    a.plot(y1, label="AI1 (I)")
    a.plot(y2, label="AI2 (Q)")
    a.axvline(arrival, color="k", ls="--")
    a.set(title=title, xlabel="Time after time_of_flight [ns]", ylabel="ADC [V]")
    a.legend()
    a.grid(True)
plt.tight_layout()
plt.show()
