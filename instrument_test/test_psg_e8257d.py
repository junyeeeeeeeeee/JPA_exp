"""Minimal test: Linux server -> (LAN SCPI via pyvisa) -> Keysight/Agilent PSG E8257D.

Sections 1-2 only query. Section 3 sets frequency and power and reads them back
(not restored). Section 4 turns RF output (pumping) ON for RF_ON_S seconds, then OFF.

Every check reads the PSG itself (settings + hardware status) and compares it with what was
commanded: OUTP/FREQ/POW readback, plus STAT:QUES:POW:COND? (non-zero = RF unleveled /
power problem) and STAT:QUES:FREQ:COND? (non-zero = synthesizer / reference unlocked).
Note: this proves the PSG is set and locked/leveled, not that the pump reaches the JPA.
"""
# %% 參數
PSG_IP = "192.168.1.33"
RESOURCE = f"TCPIP0::{PSG_IP}::5025::SOCKET"
TIMEOUT_MS = 10000
TEST_FREQ_HZ = 11.0e9     # section 3 測試頻率
TEST_POW_DBM = -130.0     # section 3 測試功率
RF_ON_S = 5               # section 4 RF ON 持續秒數
POLL_S = 0.5              # section 4 監控間隔

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


def snapshot():
    """Read the PSG's actual state (no printing of each query, one line per call)."""
    return {
        "outp": psg.query("OUTP?").strip() in ("1", "ON"),
        "freq": float(psg.query("FREQ?")),
        "pow": float(psg.query("POW?")),
        "ques_pow": int(psg.query("STAT:QUES:POW:COND?")),
        "ques_freq": int(psg.query("STAT:QUES:FREQ:COND?")),
    }


def check(expect_outp, freq_hz, pow_dbm, tag=""):
    """Compare the PSG's actual state with what was commanded; print one line, return True if OK."""
    st = snapshot()
    bad = []
    if st["outp"] != expect_outp:
        bad.append(f"OUTP={'ON' if st['outp'] else 'OFF'} (expected {'ON' if expect_outp else 'OFF'})")
    if abs(st["freq"] - freq_hz) >= 1:
        bad.append(f"FREQ={st['freq']:.9g} (expected {freq_hz:.9g})")
    if abs(st["pow"] - pow_dbm) >= 0.01:
        bad.append(f"POW={st['pow']:.2f} (expected {pow_dbm:.2f})")
    if expect_outp and st["ques_pow"]:
        bad.append(f"QUES:POW={st['ques_pow']} (unleveled / power fault)")
    if st["ques_freq"]:
        bad.append(f"QUES:FREQ={st['ques_freq']} (synth/ref unlocked)")
    print(f"  {tag:>8} OUTP={'ON ' if st['outp'] else 'OFF'} FREQ={st['freq']:.9g} Hz POW={st['pow']:.2f} dBm "
          f"QUES:POW={st['ques_pow']} QUES:FREQ={st['ques_freq']} -> {'OK' if not bad else 'FAIL: ' + '; '.join(bad)}")
    return not bad


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

# %% 3. 調整 frequency / amplitude
print("\n=== 3. PSG set frequency / amplitude ===")
psg.write(f"FREQ {TEST_FREQ_HZ}")
psg.write(f"POW {TEST_POW_DBM}")
q("*OPC?")
outp_now = q("OUTP?") in ("1", "ON")
ok3 = check(outp_now, TEST_FREQ_HZ, TEST_POW_DBM, "set")
print(f"  error: {q('SYST:ERR?')}")
print(f"  RESULT 3: {'OK' if ok3 else 'FAIL - PSG state does not match the commanded values'}")

# %% 4. RF output (pumping) ON -> RF_ON_S 秒（持續監控）-> OFF
import time

print(f"\n=== 4. PSG RF output ON for {RF_ON_S} s (poll every {POLL_S} s), then OFF ===")
freq_set, pow_set = float(psg.query("FREQ?")), float(psg.query("POW?"))
fails = 0
try:
    psg.write("OUTP ON")
    q("*OPC?")
    t0 = time.monotonic()
    while True:
        t = time.monotonic() - t0
        fails += not check(True, freq_set, pow_set, f"{t:5.1f} s")
        if t >= RF_ON_S:
            break
        time.sleep(POLL_S)
finally:
    psg.write("OUTP OFF")
    q("*OPC?")
fails += not check(False, freq_set, pow_set, "off")
print(f"  error: {q('SYST:ERR?')}")
print(f"  RESULT 4: {'OK' if not fails else f'FAIL - {fails} check(s) did not match'}")

# %% 5. 關閉連線
psg.close()
rm.close()

# %%
