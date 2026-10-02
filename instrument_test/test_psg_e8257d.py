"""Minimal read-only test: Linux server -> (LAN SCPI via pyvisa) -> Keysight/Agilent PSG E8257D.

Only queries; never changes frequency, power or RF output state.
"""
# %% 參數
PSG_IP = "192.168.1.XX"   # TODO: fill in the PSG address
RESOURCE = f"TCPIP0::{PSG_IP}::5025::SOCKET"
TIMEOUT_MS = 10000

# %% 1. PSG 連線
import pyvisa

if "XX" in PSG_IP:
    raise SystemExit("Set PSG_IP at the top of this file first.")
rm = pyvisa.ResourceManager("@py")
psg = rm.open_resource(RESOURCE, read_termination="\n", write_termination="\n", timeout=TIMEOUT_MS)


def q(cmd):
    reply = psg.query(cmd).strip()
    print(f"  >> {cmd}\n  << {reply}")
    return reply


print(f"\n=== 1. PSG connection {RESOURCE} ===")
q("*IDN?")

# %% 2. PSG 狀態（只讀）
print("\n=== 2. PSG status (read-only) ===")
q("FREQ?")
q("POW?")
q("OUTP?")
q("OUTP:MOD?")
errs = []
for _ in range(50):
    r = q("SYST:ERR?")
    if r.lstrip("+").split(",")[0] == "0":
        break
    errs.append(r)
print(f"  error queue: {errs or 'empty'}")

# %% 3. 關閉連線
psg.close()
rm.close()
