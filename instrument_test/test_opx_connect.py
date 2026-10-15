"""Minimal test: Linux server -> (LAN) -> QM router -> OPX+ / Octave. Nothing is output.

Section 1 connects and prints the server versions. Section 2 builds the QUA config from
experiments/opx_common.SETUP and simulates a short program on the server simulator (no QM is
opened, so no hardware output changes). The plot shows what the OPX analog outputs would play:
pump and readout IF tones on AO1-4, the flux offset on the flux output.
"""
# %% 參數
SIM_DURATION_NS = 4_000        # simulated time
SHOW_PLOT = True

import sys
from pathlib import Path

try:
    _here = Path(__file__).resolve().parent
except NameError:              # VS Code interactive window
    _here = Path.cwd()
_root = next(p for p in [_here, *_here.parents] if (p / "experiments" / "opx_common.py").exists())
sys.path.insert(0, str(_root / "experiments"))
import opx_common as oc

p = oc.params()
if "XX" in p["host"]:
    raise SystemExit("Set SETUP['host'] and SETUP['cluster_name'] in experiments/opx_common.py first.")

# %% 1. 連線
print("=== 1. Connect ===")
qmm = oc.connect(p)

# %% 2. 模擬 (不輸出)
print("\n=== 2. Simulate (server simulator, no output) ===")
from qm import SimulationConfig
from qm.qua import program, play, align, wait

config = oc.build_config(p)
with program() as prog:
    play("cw", "pump")
    play("cw", "ro")
    align()
    wait(100, "ro")
    play("readout", "ro")

job = qmm.simulate(config, prog, SimulationConfig(duration=SIM_DURATION_NS // 4))
samples = job.get_simulated_samples()
con = getattr(samples, p["con"])
for port in sorted(con.analog, key=lambda k: int(k.split("-")[0]) if isinstance(k, str) else k):
    wf = con.analog[port]
    print(f"    AO {port}: {len(wf)} samples, min {min(wf):+.4f} V, max {max(wf):+.4f} V")
if SHOW_PLOT:
    import matplotlib.pyplot as plt
    con.plot()
    plt.title("Simulated OPX outputs")
    plt.show()
print("\nConnection and simulation OK.")
