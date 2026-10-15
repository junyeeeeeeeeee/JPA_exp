"""Minimal test: Linux server -> (USB virtual COM port or RS-232, via pyvisa-py + pyserial) -> SRS DC205.

The DC205 must be connected to the server, not to the VNA. A USB cable shows up as /dev/ttyUSB* or /dev/ttyACM*.
Every value is read back from the DC205 itself and compared with the commanded value.

Run cell by cell (VS Code "Run Cell") to locate a problem step by step, or run the whole file.
Control cells only act when APPLY = True. Never sends *RST. The voltage setting is not restored;
cell 4 always switches the output OFF at the end, even if a check fails or the cell is interrupted.
Only RANGE1 (±1.01 V) and RANGE10 (±10.1 V) are allowed here; RANGE100 needs the interlock and is refused.
"""
# %% 參數
PORT = "/dev/dc205"        # udev symlink (/etc/udev/rules.d/99-dc205.rules); cell 1 lists the ports
BAUD = 115200             # DC205 RS-232 default
FLOW_CONTROL = "none"     # "none" (tested OK: DC205 does not assert CTS, so "rtscts" blocks) or "rtscts"
TIMEOUT_MS = 3000

RANGE = "RANGE1"          # "RANGE1" (±1.01 V) or "RANGE10" (±10.1 V)
TEST_VOLT = 0.0           # [V]
ON_S = 5                  # cell 4: output ON duration [s]
POLL_S = 0.5              # cell 4: monitoring interval [s]
APPLY = True              # False: read-only. True: set range/voltage (cell 3) and switch output ON/OFF (cell 4)

# %% 工具函式
import os
import time

import pyvisa
from pyvisa.constants import ControlFlow

RANGE_V = {"RANGE1": 1.01, "RANGE10": 10.1}
RANGE_CODES = {"0": "RANGE1", "1": "RANGE10", "2": "RANGE100"}   # RNGE? answers with the numeric code


def rnge():
    r = dc.query("RNGE?").strip().upper()
    return RANGE_CODES.get(r, r)


def q(cmd):
    reply = dc.query(cmd).strip()
    print(f"  >> {cmd}\n  << {reply}")
    return reply


def w(cmd):
    dc.write(cmd)
    print(f"  >> {cmd}")


def is_on(reply):
    return reply.strip().upper() in ("1", "ON")


def dc_errors():
    """LEXE? = last execution error, LCME? = last command error (0 = none). Reading them clears them."""
    lexe, lcme = int(dc.query("LEXE?")), int(dc.query("LCME?"))
    return [] if lexe == 0 and lcme == 0 else [f"LEXE={lexe} (execution error)", f"LCME={lcme} (command error)"]


def state(tag, expect_on, volt):
    """Read the DC205's actual state, compare with what was commanded, print one line; return problems."""
    st = {"sout": dc.query("SOUT?").strip(), "volt": float(dc.query("VOLT?")),
          "rnge": rnge(), "ovld": dc.query("OVLD?").strip()}
    bad = []
    if is_on(st["sout"]) != expect_on:
        bad.append(f"SOUT={st['sout']} (expected {'ON' if expect_on else 'OFF'})")
    if abs(st["volt"] - volt) > 2e-6 * RANGE_V[RANGE] + 1e-9:
        bad.append(f"VOLT={st['volt']:.6g} (expected {volt:.6g})")
    if st["rnge"] != RANGE:
        bad.append(f"RNGE={st['rnge']} (expected {RANGE})")
    if st["ovld"].upper() not in ("0", "OFF", "OK", "NO"):
        bad.append(f"OVLD={st['ovld']} (overload / current limit)")
    bad += dc_errors()
    print(f"  {tag:>8} SOUT={st['sout']:<3} VOLT={st['volt']:+.6f} V RNGE={st['rnge']} OVLD={st['ovld']} "
          f"-> {'OK' if not bad else 'FAIL: ' + '; '.join(bad)}")
    return bad


def result(cell, problems):
    problems = [p for p in problems if p]
    print(f"\n  RESULT {cell}: {'OK' if not problems else 'FAIL'}")
    for p in problems:
        print(f"    - {p}")


if RANGE not in RANGE_V:
    raise SystemExit(f"RANGE must be one of {list(RANGE_V)} (RANGE100 is not allowed in this test).")
if abs(TEST_VOLT) > RANGE_V[RANGE]:
    raise SystemExit(f"TEST_VOLT {TEST_VOLT} V is outside {RANGE} (±{RANGE_V[RANGE]} V).")

# %% 1. 本機 serial port 檢查（只讀）
import serial.tools.list_ports

print("\n=== 1. Serial ports on this server ===")
ports = [p for p in serial.tools.list_ports.comports() if not p.device.startswith("/dev/ttyS")]
for p in ports:
    print(f"  {p.device:<16} {p.description}  (VID:PID {p.vid and f'{p.vid:04x}:{p.pid:04x}'}, serial {p.serial_number})")
problems = []
if not ports:
    problems.append("no USB serial port found (/dev/ttyUSB*, /dev/ttyACM*): is the DC205 connected to the server?")
if not os.path.exists(PORT):
    problems.append(f"PORT {PORT} does not exist")
elif not os.access(PORT, os.R_OK | os.W_OK):
    problems.append(f"no permission on {PORT}: add yourself to the dialout group "
                    f"(sudo usermod -aG dialout $USER, then log out and in again)")
result(1, problems)

# %% 2. DC205 連線與狀態（只讀）
print(f"\n=== 2. DC205 connection {PORT} ({BAUD} baud, flow control {FLOW_CONTROL}) ===")
rm = pyvisa.ResourceManager("@py")
dc = rm.open_resource(f"ASRL{PORT}::INSTR", baud_rate=BAUD, data_bits=8, write_termination="\n",
                      read_termination="\n", timeout=TIMEOUT_MS,
                      flow_control=ControlFlow.rts_cts if FLOW_CONTROL == "rtscts" else ControlFlow.none)
problems = []
try:
    idn = q("*IDN?")
    if "DC205" not in idn:
        problems.append(f"*IDN? does not look like a DC205: {idn!r}")
    for cmd in ("SOUT?", "VOLT?", "RNGE?", "ISOL?", "SENS?", "ILOC?", "OVLD?"):
        q(cmd)
    errs = dc_errors()
    print(f"  DC205 error registers: {errs or 'clear'}  (may be left over from earlier use)")
except Exception as e:
    problems.append(f"{type(e).__name__}: {e}  (check PORT, BAUD and FLOW_CONTROL)")
result(2, problems)
if not APPLY:
    print("\n  APPLY = False: read-only, nothing will be changed. Set APPLY = True to run cells 3-4.")

# %% 3. 設定 range 與電壓（讀回比對）
if APPLY:
    print(f"\n=== 3. Set {RANGE}, VOLT {TEST_VOLT} V ===")
    problems = []
    try:
        if rnge() != RANGE:
            if is_on(q("SOUT?")):    # the DC205 only changes range with the output OFF
                raise RuntimeError(f"output is ON: switch it OFF before changing the range to {RANGE}")
            w(f"RNGE {RANGE}")
        w(f"VOLT {TEST_VOLT}")
        time.sleep(0.1)
        problems += state("set", is_on(dc.query("SOUT?")), TEST_VOLT)
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(3, problems)

# %% 4. Output ON -> ON_S 秒（持續監控）-> OFF
if APPLY:
    print(f"\n=== 4. DC205 output ON for {ON_S} s (poll every {POLL_S} s), then OFF ===")
    problems = []
    try:
        volt = float(dc.query("VOLT?"))
        try:
            w("SOUT ON")
            t0 = time.monotonic()
            while True:
                t = time.monotonic() - t0
                problems += state(f"{t:5.1f} s", True, volt)
                if t >= ON_S:
                    break
                time.sleep(POLL_S)
        finally:
            w("SOUT OFF")
        time.sleep(0.1)
        problems += state("off", False, volt)
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(4, problems)
    print("  PLEASE CHECK BY EYE (first time): DC205 front-panel OUTPUT light was on for ~"
          f"{ON_S} s and is off now.")

# %% 5. 關閉連線
dc.close()
rm.close()

# %%
