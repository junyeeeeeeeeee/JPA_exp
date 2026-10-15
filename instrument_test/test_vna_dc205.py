"""Minimal test: Linux server -> (LAN SCPI) -> Keysight E5080B -> External DC Source "DC205" (SRS DC205).

Run cell by cell (VS Code "Run Cell") to locate a problem step by step, or run the whole file.
Control cells only act when APPLY = True. Never sends *RST, never touches RF frequency/power.
Settings are not restored afterwards. Section 5 toggles the VNA's I/O to the DC205 (Enable I/O sends SOUT ON, Disable I/O sends SOUT OFF).
"""
# %% 參數
VNA_IP = "192.168.1.23"
VNA_PORT = 5025
CH = 1                    # VNA channel
SOURCE = "DC205"          # External DC Source name configured in the VNA
DC_VOLT = -0.002             # Start = Stop voltage for the test sweep [V]
TIMEOUT = 10.0            # per-query timeout [s]
SWEEP_TIMEOUT = 120.0     # single-sweep *OPC? timeout [s]
DC_ON_S = 5               # section 5 DC output ON 持續秒數
APPLY = True             # False: read-only. True: set 0 V and run one single sweep

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


def is_on(reply):
    return reply.strip().strip('"').upper() in ("1", "ON")


def require_io():
    """The VNA silently accepts DC settings and sweeps even when its I/O to the DC205 is disabled
    (nothing is sent to the DC205). Fail loudly in that case."""
    if not is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{SOURCE}"')):
        raise RuntimeError(f"VNA I/O to {SOURCE} is DISABLED (IOEN=0): commands will NOT reach the {SOURCE}. "
                           f"Enable I/O first (cell 5, or the VNA External Device dialog).")


def expect(label, reply, want):
    """Compare a readback with the commanded value; return '' if OK, else a description."""
    ok = abs(float(reply) - want) < 1e-9 if isinstance(want, float) else is_on(reply) == want
    print(f"    {label:<28} read {reply:<22} expected {want!s:<10} -> {'OK' if ok else 'MISMATCH'}")
    return "" if ok else f"{label}: read {reply}, expected {want}"


def result(cell, problems):
    problems = [p for p in problems if p]
    print(f"\n  RESULT {cell}: {'OK (VNA side)' if not problems else 'FAIL'}")
    for p in problems:
        print(f"    - {p}")

# %% 1. VNA 連線
print(f"\n=== 1. VNA connection {VNA_IP}:{VNA_PORT} ===")
vna = VNA(VNA_IP, VNA_PORT, TIMEOUT)
vna.query("*IDN?")
errs = vna.errors()
print(f"  error queue: {errs or 'empty'}  (raw; may be left over from earlier use)")

# %% 2. VNA-DC205 連線與設定檢查（只讀）
print(f"\n=== 2. VNA <-> {SOURCE} status / configuration (read-only) ===")
if not is_on(vna.query(f'SYST:CONF:EDEV:EXIS? "{SOURCE}"')):
    raise SystemExit(f'ERROR: no External Device named "{SOURCE}" in the VNA '
                     f'(SYST:CONF:EDEV:CAT? -> {vna.query("SYST:CONF:EDEV:CAT?")}). Stopping.')
cfg = {
    "ioen": vna.query(f'SYST:CONF:EDEV:IOEN? "{SOURCE}"'),
    "active": vna.query(f'SYST:CONF:EDEV:STAT? "{SOURCE}"'),
    "init": vna.query(f'SYST:CONF:EDEV:DC:COMM:INIT? "{SOURCE}"').strip('"'),
    "exit": vna.query(f'SYST:CONF:EDEV:DC:COMM:EXIT? "{SOURCE}"').strip('"'),
    "set": vna.query(f'SYST:CONF:EDEV:DC:COMM:POIN:SET? "{SOURCE}"').strip('"'),
    "errq": vna.query(f'SYST:CONF:EDEV:DC:QUER:ERR? "{SOURCE}"').strip('"'),
}
# A device that is not Activated disappears from the channel's DC source list ("NO CATALOG").
names = [s.strip().strip('"') for s in vna.query(f"SOUR{CH}:DC:CAT?").strip('"').split(",")]
in_channel = SOURCE in names
if in_channel:
    cfg.update({
        "enab": vna.query(f"SOUR{CH}:DC:ENAB?"),
        "stat": vna.query(f'SOUR{CH}:DC:STAT? "{SOURCE}"'),
        "star": vna.query(f'SOUR{CH}:DC:STAR? "{SOURCE}"'),
        "stop": vna.query(f'SOUR{CH}:DC:STOP? "{SOURCE}"'),
    })
warn = []
if not is_on(cfg["ioen"]):
    warn.append(f"I/O to {SOURCE} is DISABLED: sweeps will NOT set the {SOURCE} (and its output is OFF).")
if not is_on(cfg["active"]):
    warn.append(f"{SOURCE} is NOT ACTIVATED in the VNA (SYST:CONF:EDEV:STAT = 0): check 'Activate' in the "
                f"External Device dialog. Cells 3-5 cannot work until it is activated.")
if not in_channel:
    warn.append(f"{SOURCE} is not in channel {CH}'s DC source list (SOUR{CH}:DC:CAT? -> {names}).")
if cfg["init"].upper() not in ("SOUT ON", "SOUT 1"):
    warn.append(f'Enable I/O command is "{cfg["init"]}", expected "SOUT ON".')
if cfg["exit"].upper() not in ("SOUT OFF", "SOUT 0"):
    warn.append(f'Disable I/O command is "{cfg["exit"]}", expected "SOUT OFF".')
if not cfg["set"].upper().startswith("VOLT"):
    warn.append(f'Set Point command is "{cfg["set"]}", expected "VOLT {{%f}}".')
if cfg["errq"]:
    # Optional. "LEXE?" made the VNA hang here (likely queried after every point and timing out), so it is left empty.
    print(f'  note: Error Query = "{cfg["errq"]}" (optional; clear it if the VNA hangs during sweeps)')
errs = vna.errors()
if errs:
    warn.append(f"VNA error queue: {errs}")
print(f"\n  RESULT 2: {'OK' if not warn else 'WARNING'}")
for w in warn:
    print(f"    - {w}")
if not APPLY:
    print("\n  APPLY = False: read-only, nothing will be changed. Set APPLY = True to run the control cells.")

# %% 3. VNA-DC205 控制：設定 Start/Stop = DC_VOLT 並啟用
# E5080B expects the source name as the FIRST argument: SOUR:DC:STAR "<name>",<value>
if APPLY:
    print(f"\n=== 3. Set {SOURCE} Start/Stop = {DC_VOLT} V in VNA ===")
    problems = []
    try:
        require_io()
        vna.checked(f"SENS{CH}:SWE:MODE HOLD")
        vna.checked(f'SOUR{CH}:DC:STAR "{SOURCE}",{DC_VOLT}')
        vna.checked(f'SOUR{CH}:DC:STOP "{SOURCE}",{DC_VOLT}')
        vna.checked(f"SOUR{CH}:DC:ENAB ON")
        vna.checked(f'SOUR{CH}:DC:STAT "{SOURCE}",ON')
        print("  readback (VNA-stored values):")
        problems += [
            expect("SOUR:DC:STAR", vna.query(f'SOUR{CH}:DC:STAR? "{SOURCE}"'), float(DC_VOLT)),
            expect("SOUR:DC:STOP", vna.query(f'SOUR{CH}:DC:STOP? "{SOURCE}"'), float(DC_VOLT)),
            expect("SOUR:DC:ENAB", vna.query(f"SOUR{CH}:DC:ENAB?"), True),
            expect("SOUR:DC:STAT", vna.query(f'SOUR{CH}:DC:STAT? "{SOURCE}"'), True),
        ]
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(3, problems)
    print(f"  Note: the {SOURCE} itself is only updated during the sweep in cell 4.")

# %% 4. VNA-DC205 掃描：single sweep 並等待完成（此時 VNA 送 VOLT 給 DC205）
if APPLY:
    print(f"\n=== 4. Single sweep (timeout {SWEEP_TIMEOUT:.0f} s) ===")
    problems = []
    try:
        require_io()
        vna.write(f"SENS{CH}:SWE:MODE SING")
        t0 = time.monotonic()
        opc = vna.query("*OPC?", timeout=SWEEP_TIMEOUT)
        print(f"  sweep finished: *OPC? = {opc}, total {time.monotonic() - t0:.3f} s")
        errs = vna.errors()
        if errs:
            problems.append(f"VNA error queue after sweep (incl. {SOURCE} Error Query): {errs}")
        if not is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{SOURCE}"')):
            problems.append(f"I/O to {SOURCE} became DISABLED during the sweep (communication problem?)")
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(4, problems)
    print(f"  PLEASE CHECK BY EYE: {SOURCE} front panel shows {DC_VOLT} V "
          f"(the VNA cannot read the {SOURCE}'s actual voltage).")

# %% 5. VNA-DC205 output ON -> DC_ON_S 秒 -> OFF
# VNA External Device (Edit Commands > Global): Enable I/O = "SOUT ON", Disable I/O = "SOUT OFF".
# Toggling I/O (SYST:CONF:EDEV:IOEN) makes the VNA send those commands to the DC205.
if APPLY:
    print(f"\n=== 5. {SOURCE} output ON for {DC_ON_S} s, then OFF (via Enable/Disable I/O) ===")
    problems = []
    try:
        vna.checked(f'SYST:CONF:EDEV:IOEN "{SOURCE}",OFF')   # start from a known OFF state
        try:
            vna.checked(f'SYST:CONF:EDEV:IOEN "{SOURCE}",ON')   # errors here = DC205 did not answer ID/Error Query
            problems.append(expect("IOEN after Enable I/O", vna.query(f'SYST:CONF:EDEV:IOEN? "{SOURCE}"'), True))
            print(f"  -> {SOURCE} OUTPUT should be ON now")
            time.sleep(DC_ON_S)
        finally:
            vna.write(f'SYST:CONF:EDEV:IOEN "{SOURCE}",OFF')
        problems.append(expect("IOEN after Disable I/O", vna.query(f'SYST:CONF:EDEV:IOEN? "{SOURCE}"'), False))
        print(f"  -> {SOURCE} OUTPUT should be OFF now")
        errs = vna.errors()
        if errs:
            problems.append(f"VNA error queue: {errs}")
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(5, problems)
    print(f"  PLEASE CHECK BY EYE: did the {SOURCE} front-panel OUTPUT turn on for ~{DC_ON_S} s, then off?")
    print(f"  Note: I/O is left DISABLED; cells 3-4 will FAIL until I/O is enabled again.")

# %% 6. 關閉連線
vna.close()

# %%
