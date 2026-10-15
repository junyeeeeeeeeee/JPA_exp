"""Minimal test: Linux server -> (LAN SCPI) -> Rohde & Schwarz ZNB20 VNA (4 ports, 100 kHz - 20 GHz).

Run cell by cell (VS Code "Run Cell") to locate a problem step by step, or run the whole file.
Control cells only act when APPLY = True. Never sends *RST. Settings are not restored afterwards.
Every setting is read back and compared with the commanded value; each cell prints RESULT OK / FAIL.
R&S syntax (differs from the E5080B in test_vna.py): trace names in single quotes, IF bandwidth = SENS:BAND,
single sweep = INIT:CONT OFF + INIT:IMM, data = CALC:DATA:TRAC? '<trace>', SDAT, frequencies = CALC:DATA:STIM?.
"""
# %% 參數
VNA_IP = "192.168.1.123"
VNA_PORT = 5025
CH = 1                    # VNA channel
SPARAM = "S21"            # S-parameter of the test trace (4-port: S<out><in>, e.g. "S21" = port 1 -> port 2)
POWER_DBM = -20.0         # source power [dBm]
FREQ_MIN_HZ = 4.0e9
FREQ_MAX_HZ = 8.0e9
IF_BW_HZ = 1.0e3
POINTS = 201
TIMEOUT = 10.0            # per-query timeout [s]
SWEEP_TIMEOUT = 120.0     # single-sweep *OPC? timeout [s]
APPLY = True              # False: read-only. True: apply the settings above and run one single sweep

# %% 工具函式
import socket
import time

import numpy as np


class VNA:
    def __init__(self, ip, port, timeout):
        self.timeout = timeout
        self.sock = socket.create_connection((ip, port), timeout=5.0)
        self.sock.settimeout(timeout)
        self.buf = b""

    def close(self):
        self.sock.close()

    def write(self, cmd):
        self.sock.sendall((cmd + "\n").encode("ascii"))
        print(f"  >> {cmd}")

    def query(self, cmd, timeout=None, show=True):
        self.sock.settimeout(timeout or self.timeout)
        t0 = time.monotonic()
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
            while b"\n" not in self.buf:
                chunk = self.sock.recv(1 << 16)
                if not chunk:
                    raise ConnectionError("VNA closed the connection")
                self.buf += chunk
        finally:
            self.sock.settimeout(self.timeout)
        line, self.buf = self.buf.split(b"\n", 1)
        reply = line.decode("ascii", "replace").strip()
        if show:
            print(f"  >> {cmd}\n  << {reply if len(reply) < 80 else reply[:77] + '...'}    ({time.monotonic() - t0:.3f} s)")
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


def device_clear(ip):
    """VXI-11 Device Clear: aborts a command the ZNB is stuck on (e.g. *OPC? waiting for a trigger that never
    comes). While it is stuck, the ZNB answers no SCPI client at all (socket, VXI-11, HiSLIP)."""
    import pyvisa
    rm = pyvisa.ResourceManager("@py")
    try:
        dev = rm.open_resource(f"TCPIP0::{ip}::inst0::INSTR", timeout=10_000)
        dev.clear()
        print(f"  device clear sent -> {dev.query('*IDN?').strip()}")
        dev.close()
    finally:
        rm.close()


def is_on(reply):
    return reply.strip().strip('"').upper() in ("1", "ON")


def rs_list(reply):
    """'a,b,c' (R&S single-quoted list) -> ['a', 'b', 'c']"""
    return [s.strip() for s in reply.strip().strip("'\"").split(",") if s.strip()]


def expect(label, reply, want, tol=0.0):
    """Compare a readback with the commanded value; return '' if OK, else a description."""
    ok = abs(float(reply) - want) <= tol if isinstance(want, (int, float)) and not isinstance(want, bool) \
        else is_on(reply) == want
    print(f"    {label:<20} read {reply:<22} expected {want!s:<12} -> {'OK' if ok else 'MISMATCH'}")
    return "" if ok else f"{label}: read {reply}, expected {want}"


def result(cell, problems):
    problems = [p for p in problems if p]
    print(f"\n  RESULT {cell}: {'OK' if not problems else 'FAIL'}")
    for p in problems:
        print(f"    - {p}")


trace = None   # name of the test trace, set in cell 3

# %% 1. VNA 連線
print(f"\n=== 1. VNA connection {VNA_IP}:{VNA_PORT} ===")
# The ZNB serves one SCPI socket client at a time: a second connection is accepted but never answered.
# Re-running this cell in the same kernel therefore closes the previous connection first.
if globals().get("vna") is not None:
    globals()["vna"].close()
    print("  closed the previous connection of this kernel")
vna = VNA(VNA_IP, VNA_PORT, TIMEOUT)
try:
    idn = vna.query("*IDN?")
except TimeoutError:
    vna.close()
    print("  no answer to *IDN?: the ZNB is probably stuck on an earlier command (e.g. *OPC? waiting for a "
          "trigger); sending device clear")
    device_clear(VNA_IP)
    vna = VNA(VNA_IP, VNA_PORT, TIMEOUT)
    idn = vna.query("*IDN?")
vna.query("*OPT?")
errs = vna.errors()
print(f"  error queue: {errs or 'empty'}  (raw; may be left over from earlier use)")
if "ZNB" not in idn:
    print(f"  WARNING: {VNA_IP} does not identify as a ZNB: {idn!r}")

# %% 2. VNA 狀態（只讀）
print(f"\n=== 2. VNA channel {CH} status (read-only) ===")
f_lo = float(vna.query("SYST:FREQ? MIN"))
f_hi = float(vna.query("SYST:FREQ? MAX"))
vna.query("CONF:CHAN:CAT?")
vna.query(f"CALC{CH}:PAR:CAT?")
vna.query("DISP:WIND1:TRAC:CAT?")
vna.query(f"INIT{CH}:CONT?")
trig = vna.query(f"TRIG{CH}:SOUR?").upper()
vna.query(f"SENS{CH}:SWE:TYPE?")
vna.query(f"SENS{CH}:FREQ:STAR?")
vna.query(f"SENS{CH}:FREQ:STOP?")
vna.query(f"SENS{CH}:SWE:POIN?")
vna.query(f"SENS{CH}:BAND?")
vna.query(f"SOUR{CH}:POW?")
vna.query(f"SENS{CH}:SWE:COUN?")
vna.query(f"SENS{CH}:SWE:TIME?")
vna.query(f"SENS{CH}:AVER:STAT?")
vna.query(f"SENS{CH}:CORR:STAT?")
vna.query(f"SENS{CH}:ROSC?")
rf_on = is_on(vna.query("OUTP?"))
errs = vna.errors()
problems = [f"VNA error queue: {errs}" if errs else ""]
if not f_lo <= FREQ_MIN_HZ < FREQ_MAX_HZ <= f_hi:
    problems.append(f"requested {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz is outside the instrument range "
                    f"{f_lo/1e9:g}-{f_hi/1e9:g} GHz")
if not trig.startswith("IMM"):
    problems.append(f"trigger source is {trig}: INIT:IMM would wait for a trigger (cell 3 sets TRIG:SOUR IMM)")
if not rf_on:
    problems.append("RF output is OFF (OUTP? = 0): a sweep would measure noise only")
result(2, problems)
if not APPLY:
    print("\n  APPLY = False: read-only, nothing will be changed. Set APPLY = True to run cells 3-4.")

# %% 3. VNA 設定：S21 trace、頻率、點數、IFBW、功率（讀回比對）
if APPLY:
    print(f"\n=== 3. Set {SPARAM} sweep: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
          f"IFBW {IF_BW_HZ:g} Hz, {POWER_DBM:g} dBm ===")
    problems = []
    try:
        vna.checked(f"INIT{CH}:CONT OFF")             # hold: sweep only on INIT:IMM (cell 4)
        cat = rs_list(vna.query(f"CALC{CH}:PAR:CAT?"))
        trace = next((n for n, p in zip(cat[::2], cat[1::2]) if p.upper() == SPARAM.upper()), None)
        if trace is None:
            trace = "JPA_S21"
            vna.checked(f"CALC{CH}:PAR:SDEF '{trace}','{SPARAM}'")
            nums = [int(n) for n in rs_list(vna.query("DISP:WIND1:TRAC:CAT?"))[::2]]
            vna.checked(f"DISP:WIND1:TRAC{max(nums, default=0) + 1}:FEED '{trace}'")
        vna.checked(f"CALC{CH}:PAR:SEL '{trace}'")
        print(f"  using trace '{trace}'")
        vna.checked(f"SENS{CH}:SWE:TYPE LIN")
        vna.checked(f"SENS{CH}:FREQ:STAR {FREQ_MIN_HZ}")
        vna.checked(f"SENS{CH}:FREQ:STOP {FREQ_MAX_HZ}")
        vna.checked(f"SENS{CH}:SWE:POIN {POINTS}")
        vna.checked(f"SENS{CH}:BAND {IF_BW_HZ}")
        vna.checked(f"SOUR{CH}:POW {POWER_DBM}")
        vna.checked(f"SENS{CH}:SWE:COUN 1")
        vna.checked(f"TRIG{CH}:SOUR IMM")              # MAN / EXT: INIT:IMM would wait and block *OPC?
        vna.checked("FORM:DATA ASC")
        print("  readback:")
        par = vna.query(f"CALC{CH}:PAR:MEAS? '{trace}'").strip("'\"").upper()
        print(f"    {'trace parameter':<20} read {par:<22} expected {SPARAM.upper():<12} -> "
              f"{'OK' if par == SPARAM.upper() else 'MISMATCH'}")
        problems += [
            "" if par == SPARAM.upper() else f"trace '{trace}' measures {par}, expected {SPARAM}",
            expect("continuous sweep", vna.query(f"INIT{CH}:CONT?"), False),
            expect("freq min [Hz]", vna.query(f"SENS{CH}:FREQ:STAR?"), FREQ_MIN_HZ, 1),
            expect("freq max [Hz]", vna.query(f"SENS{CH}:FREQ:STOP?"), FREQ_MAX_HZ, 1),
            expect("points", vna.query(f"SENS{CH}:SWE:POIN?"), POINTS),
            expect("IF bandwidth [Hz]", vna.query(f"SENS{CH}:BAND?"), IF_BW_HZ, 1e-6 * IF_BW_HZ),
            expect("power [dBm]", vna.query(f"SOUR{CH}:POW?"), POWER_DBM, 0.01),
            expect("sweep count", vna.query(f"SENS{CH}:SWE:COUN?"), 1),
            "" if vna.query(f"TRIG{CH}:SOUR?").upper().startswith("IMM") else "trigger source is not IMMediate",
        ]
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(3, problems)

# %% 4. VNA 掃描：single sweep，讀回 S21 資料並畫圖
if APPLY:
    print(f"\n=== 4. Single sweep (timeout {SWEEP_TIMEOUT:.0f} s) ===")
    problems = []
    try:
        if trace is None:
            raise RuntimeError("no trace selected: run cell 3 first")
        print(f"  VNA sweep time estimate {float(vna.query(f'SENS{CH}:SWE:TIME?')):.3f} s")
        vna.write(f"INIT{CH}:IMM")
        t0 = time.monotonic()
        try:
            vna.query("*OPC?", timeout=SWEEP_TIMEOUT)
        except TimeoutError:
            device_clear(VNA_IP)                      # otherwise the ZNB stays blocked for every client
            raise TimeoutError(f"sweep did not finish in {SWEEP_TIMEOUT} s (device clear sent; "
                               f"check TRIG{CH}:SOUR? and the sweep time)") from None
        print(f"  sweep finished in {time.monotonic() - t0:.3f} s")
        errs = vna.errors()
        if errs:
            problems.append(f"VNA error queue after sweep: {errs}")
        raw = np.array(vna.query(f"CALC{CH}:DATA:TRAC? '{trace}', SDAT", show=False).split(","), float)
        freq = np.array(vna.query(f"CALC{CH}:DATA:STIM?", show=False).split(","), float)
        s21 = raw[0::2] + 1j * raw[1::2]
        amp_db = 20 * np.log10(np.abs(s21))
        print(f"  data: {len(s21)} points, freq {freq[0]/1e9:g}-{freq[-1]/1e9:g} GHz, "
              f"|{SPARAM}| {amp_db.min():.2f} .. {amp_db.max():.2f} dB")
        if len(s21) != POINTS or len(freq) != POINTS:
            problems.append(f"got {len(s21)} data / {len(freq)} freq points, expected {POINTS}")
        if not np.all(np.isfinite(s21)) or np.all(s21 == 0):
            problems.append("S21 data contains non-finite values or is all zero")

        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.plot(freq / 1e9, amp_db)
        ax.set(xlabel="Frequency [GHz]", ylabel=f"|{SPARAM}| [dB]", title=f"ZNB test sweep, {POWER_DBM:g} dBm")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        plt.show()
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(4, problems)

# %% 5. 關閉連線
vna.close()

# %%
