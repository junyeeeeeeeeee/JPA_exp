"""Output test: CW pump / readout tones from the Octave and the DC flux offset from the OPX.

Check the outputs with a spectrum analyzer (RF) and a voltmeter / scope (flux), NOT the fridge.
Read-only unless APPLY = True. With APPLY = True:
  1. (optional, CALIBRATE = True) Octave automatic mixer calibration of "pump" and "ro"
     at their current LO/IF (LO leakage + image), saved to opx_calibration/.
  2. The flux offset is set to FLUX_V and read back.
  3. A CW program plays the selected tones; their RF outputs are switched ON for HOLD_S seconds,
     with the IF changed half-way (STEP_IF_HZ) to show live retuning, then OFF.
  4. The QM is closed: RF outputs OFF, flux back to 0 V.

What to read on the spectrum analyzer for an element at LO + IF:
  wanted tone LO + IF, LO leakage at LO, image at LO - IF  (after calibration both should be
  well below the wanted tone). Note the measured power vs (amp, gain): that table is the
  Octave power calibration the pump-power scans will need.
"""
# %% 參數
APPLY = False
CALIBRATE = False
ELEMENTS = ["pump"]            # any of "pump", "ro"
HOLD_S = 20.0
STEP_IF_HZ = 10e6              # IF change applied after HOLD_S / 2 (0 = no change)
FLUX_V = 0.0                   # DC offset on the flux output [V], |V| <= 0.5
SETUP_OVERRIDES = dict(
    pump_lo_Hz=11.15e9, pump_if_Hz=50e6, pump_amp_V=0.10, pump_gain_dB=0.0,
    ro_lo_Hz=5.60e9, ro_if_Hz=50e6, ro_amp_V=0.05, ro_gain_dB=0.0,
)

import sys
import time
from pathlib import Path

try:
    _here = Path(__file__).resolve().parent
except NameError:              # VS Code interactive window
    _here = Path.cwd()
_root = next(p for p in [_here, *_here.parents] if (p / "experiments" / "opx_common.py").exists())
sys.path.insert(0, str(_root / "experiments"))
import opx_common as oc

p = oc.params(flux_V=FLUX_V, **SETUP_OVERRIDES)
if "XX" in p["host"]:
    raise SystemExit("Set SETUP['host'] and SETUP['cluster_name'] in experiments/opx_common.py first.")
for el in ELEMENTS:
    lo, if_ = p[f"{el}_lo_Hz"], p[f"{el}_if_Hz"]
    print(f"{el}: tone {(lo + if_)/1e9:.6f} GHz (LO {lo/1e9:g} GHz + IF {if_/1e6:g} MHz), "
          f"image {(lo - if_)/1e9:.6f} GHz, amp {p[f'{el}_amp_V']} V, gain {p[f'{el}_gain_dB']} dB")
print(f"flux: {FLUX_V} V on AO{p['flux_ao']}")
if not APPLY:
    raise SystemExit("APPLY = False: nothing sent. Connect a spectrum analyzer / meter, then set APPLY = True.")

# %% 1-4. 輸出
qmm = oc.connect(p)
qm = oc.open_qm(qmm, oc.build_config(p))
job = None
try:
    if CALIBRATE:
        print("\n=== 1. Mixer calibration ===")
        for el in ELEMENTS:
            oc.calibrate(qm, el)

    print("\n=== 2. Flux offset ===")
    oc.set_flux(qm, FLUX_V)

    print(f"\n=== 3. CW for {HOLD_S:g} s ===")
    job = qm.execute(oc.cw_program(ELEMENTS))
    for el in ELEMENTS:
        oc.rf_on(qm, el)
    time.sleep(HOLD_S / 2)
    if STEP_IF_HZ:
        for el in ELEMENTS:
            oc.set_if(qm, el, p[f"{el}_if_Hz"] + STEP_IF_HZ)
    time.sleep(HOLD_S / 2)
finally:
    print("\n=== 4. Off ===")
    for el in ELEMENTS:
        oc.rf_off(qm, el)
    if job is not None:
        job.halt()
    qm.close()
    print("    QM closed: RF outputs OFF, flux offset back to 0 V.")
    print("    PLEASE CHECK on the analyzer / meter that the outputs are really off.")
