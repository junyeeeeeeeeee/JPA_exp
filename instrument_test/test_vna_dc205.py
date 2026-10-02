"""Minimal test: Linux server -> (LAN SCPI) -> Keysight E5080B -> External DC Source "DC205" (SRS DC205).

Run cell by cell (VS Code "Run Cell") to locate a problem step by step, or run the whole file.
Control cells only act when APPLY = True. Never sends *RST, never touches RF frequency/power,
never sends SOUT ON/OFF to the DC205.
"""
# %% 參數
VNA_IP = "192.168.1.23"
VNA_PORT = 5025
CH = 1                    # VNA channel
SOURCE = "DC205"          # External DC Source name configured in the VNA
DC_VOLT = 0.0             # Start = Stop voltage for the test sweep [V]
TIMEOUT = 10.0            # per-query timeout [s]
SWEEP_TIMEOUT = 120.0     # single-sweep *OPC? timeout [s]
APPLY = False             # False: read-only. True: set 0 V and run one single sweep

# %% 工具函式
import socket
import time


class VNA:
    def __init__(self, ip, port, timeout):
        self.timeout = timeout
        self.sock = socket.create_connection((ip, port), timeout=5.0)
        self.sock.settimeout(timeout)
        self.buf = b""

    def close(self):
        self.sock.close()

    def write(self, cmd):
        t0 = time.monotonic()
        self.sock.sendall((cmd + "\n").encode("ascii"))
        print(f"  >> {cmd}    ({time.monotonic() - t0:.3f} s)")

    def query(self, cmd, timeout=None):
        self.sock.settimeout(timeout or self.timeout)
        t0 = time.monotonic()
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
            while b"\n" not in self.buf:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise ConnectionError("VNA closed the connection")
                self.buf += chunk
        finally:
            self.sock.settimeout(self.timeout)
        line, self.buf = self.buf.split(b"\n", 1)
        reply = line.decode("ascii", "replace").strip()
        print(f"  >> {cmd}\n  << {reply}    ({time.monotonic() - t0:.3f} s)")
        return reply

    def errors(self):
        """Drain SYST:ERR? and return the non-zero entries as raw strings."""
        errs = []
        for _ in range(50):
            r = self.query("SYST:ERR?")
            if r.lstrip("+").split(",")[0] == "0":
                break
            errs.append(r)
        return errs

    def checked(self, cmd):
        """Write a setting; raise with the raw VNA error text if the error queue is non-empty."""
        self.write(cmd)
        errs = self.errors()
        if errs:
            raise RuntimeError(f"VNA reported error(s) after '{cmd}': {errs}")


changed = []      # (setting, value before test) for everything this script modified
failed = None     # first exception in the control cells; later control cells are skipped

# %% 1. VNA 連線
print(f"\n=== 1. VNA connection {VNA_IP}:{VNA_PORT} ===")
vna = VNA(VNA_IP, VNA_PORT, TIMEOUT)
vna.query("*IDN?")
errs = vna.errors()
print(f"  error queue: {errs or 'empty'}  (raw; may be left over from earlier use)")

# %% 2. VNA-DC205 連線（只讀）
print(f"\n=== 2. VNA <-> {SOURCE} status (read-only) ===")
names = [s.strip().strip('"') for s in vna.query(f"SOUR{CH}:DC:CAT?").strip('"').split(",")]
if SOURCE not in names:
    raise SystemExit(f'ERROR: "{SOURCE}" not found in SOUR{CH}:DC:CAT? -> {names}. Stopping.')
before = {
    "enab": vna.query(f"SOUR{CH}:DC:ENAB?"),
    "stat": vna.query(f'SOUR{CH}:DC:STAT? "{SOURCE}"'),
    "star": vna.query(f'SOUR{CH}:DC:STAR? "{SOURCE}"'),
    "stop": vna.query(f'SOUR{CH}:DC:STOP? "{SOURCE}"'),
    "mode": vna.query(f"SENS{CH}:SWE:MODE?"),
}
errs = vna.errors()
print(f"  error queue: {errs or 'empty'}")
if not APPLY:
    print("\n  APPLY = False: read-only, nothing will be changed. Set APPLY = True to run the 0 V test.")

# %% 3. VNA-DC205 控制：設定 Start/Stop = 0 V 並啟用
# E5080B expects the source name as the FIRST argument: SOUR:DC:STAR "<name>",<value>
if APPLY and failed is None:
    print(f"\n=== 3. Set {SOURCE} Start/Stop = {DC_VOLT} V in VNA ===")
    try:
        vna.checked(f"SENS{CH}:SWE:MODE HOLD")
        changed.append((f"SENS{CH}:SWE:MODE", before["mode"]))
        vna.checked(f'SOUR{CH}:DC:STAR "{SOURCE}",{DC_VOLT}')
        changed.append((f'SOUR{CH}:DC:STAR "{SOURCE}"', before["star"]))
        vna.checked(f'SOUR{CH}:DC:STOP "{SOURCE}",{DC_VOLT}')
        changed.append((f'SOUR{CH}:DC:STOP "{SOURCE}"', before["stop"]))
        vna.checked(f"SOUR{CH}:DC:ENAB ON")
        changed.append((f"SOUR{CH}:DC:ENAB", before["enab"]))
        vna.checked(f'SOUR{CH}:DC:STAT "{SOURCE}",ON')
        changed.append((f'SOUR{CH}:DC:STAT "{SOURCE}"', before["stat"]))
    except Exception as e:
        failed = e
        print(f"\n!! FAILED: {type(e).__name__}: {e}")

# %% 4. VNA-DC205 掃描：single sweep 並等待完成
if APPLY and failed is None:
    print(f"\n=== 4. Single sweep (timeout {SWEEP_TIMEOUT:.0f} s) ===")
    try:
        vna.write(f"SENS{CH}:SWE:MODE SING")
        t0 = time.monotonic()
        opc = vna.query("*OPC?", timeout=SWEEP_TIMEOUT)
        print(f"  sweep finished: *OPC? = {opc}, total {time.monotonic() - t0:.3f} s")
        errs = vna.errors()
        print(f"  error queue after sweep: {errs or 'empty'}")
        if errs:
            raise RuntimeError(f"VNA reported error(s) during sweep: {errs}")
        print("  VNA-side settings after sweep (NOT evidence of the DC205's actual voltage):")
        vna.query(f'SOUR{CH}:DC:STAR? "{SOURCE}"')
        vna.query(f'SOUR{CH}:DC:STOP? "{SOURCE}"')
    except Exception as e:
        failed = e
        print(f"\n!! FAILED: {type(e).__name__}: {e}")

# %% 5. 恢復與總結
print("\n=== 5. Restore / summary ===")
stat_key = f'SOUR{CH}:DC:STAT "{SOURCE}"'
restored = set()
try:
    if any(k == stat_key for k, _ in changed):
        state = "ON" if before["stat"].strip() in ("1", "ON") else "OFF"
        vna.write(f'SOUR{CH}:DC:STAT "{SOURCE}",{state}')
        vna.query(f'SOUR{CH}:DC:STAT? "{SOURCE}"')
        restored.add(stat_key)
    if changed:  # keep HOLD so nothing sweeps with half-restored settings
        vna.write(f"SENS{CH}:SWE:MODE HOLD")
        vna.query(f"SENS{CH}:SWE:MODE?")
    print(f"  error queue: {vna.errors() or 'empty'}")
except Exception as e:
    print(f"  !! cleanup error: {type(e).__name__}: {e}")
finally:
    vna.close()

print("\n  Settings changed by this test:")
if not changed:
    print("    (none)")
for key, old in changed:
    tag = "restored" if key in restored else "LEFT CHANGED - restore manually if needed"
    print(f"    {key:<28} before = {old:<14} -> {tag}")
if changed:
    print(f"    Sweep mode is left at HOLD (was {before['mode']}).")
if failed is not None:
    print(f"\n  RESULT: FAILED - {type(failed).__name__}: {failed}")
elif APPLY:
    print("\n  RESULT: commands accepted by VNA, sweep completed.")

if APPLY:
    print(
        "\n  PLEASE CHECK BY EYE:\n"
        f"    - VNA screen: DC source settings for {SOURCE} (Start/Stop = {DC_VOLT} V).\n"
        f"    - DC205 front panel: did the voltage SETTING change to {DC_VOLT} V?\n"
        "  Note: VNA Start/Stop readback only shows what the VNA stored, not what the DC205 did.\n"
        "  If the DC205 output was OFF, this test only confirms the set command was delivered;\n"
        "  it does NOT prove any actual output voltage (this script never sends SOUT ON/OFF)."
    )
