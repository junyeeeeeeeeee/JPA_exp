"""Minimal test: Linux server -> (LAN SCPI) -> Keysight E5080B VNA only (no DC205).

Run cell by cell (VS Code "Run Cell") to locate a problem step by step, or run the whole file.
Control cells only act when APPLY = True. Never sends *RST. Settings are not restored afterwards.
Every setting is read back and compared with the commanded value; each cell prints RESULT OK / FAIL.
So that the sweep does not drive the DC205, cell 3 turns the channel's DC sources off (SOUR:DC:ENAB OFF);
the experiment scripts turn them on again when they need the bias.
"""
# %% 參數
VNA_IP = "192.168.1.23"
VNA_PORT = 5025
CH = 1                    # VNA channel
POWER_DBM = -20.0         # port-1 output power [dBm]
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


def is_on(reply):
    return reply.strip().strip('"').upper() in ("1", "ON")


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


mnum = None   # S21 measurement number, set in cell 3

# %% 1. VNA 連線
print(f"\n=== 1. VNA connection {VNA_IP}:{VNA_PORT} ===")
vna = VNA(VNA_IP, VNA_PORT, TIMEOUT)
vna.query("*IDN?")
errs = vna.errors()
print(f"  error queue: {errs or 'empty'}  (raw; may be left over from earlier use)")

# %% 2. VNA 狀態（只讀）
print(f"\n=== 2. VNA channel {CH} status (read-only) ===")
vna.query("SYST:CHAN:CAT?")
vna.query(f"CALC{CH}:PAR:CAT:EXT?")
vna.query(f"SENS{CH}:SWE:MODE?")
vna.query(f"SENS{CH}:SWE:TYPE?")
vna.query(f"SENS{CH}:FREQ:STAR?")
vna.query(f"SENS{CH}:FREQ:STOP?")
vna.query(f"SENS{CH}:SWE:POIN?")
vna.query(f"SENS{CH}:BWID?")
vna.query(f"SOUR{CH}:POW1?")
vna.query(f"SENS{CH}:AVER?")
vna.query(f"SENS{CH}:CORR?")
dc_on = is_on(vna.query(f"SOUR{CH}:DC:ENAB?"))
errs = vna.errors()
print(f"\n  RESULT 2: {'OK' if not errs else 'WARNING'}  error queue: {errs or 'empty'}")
if dc_on:
    print(f"  note: DC sources are enabled in channel {CH}; a sweep would also drive the DC205 "
          f"(cell 3 turns them off).")
if not APPLY:
    print("\n  APPLY = False: read-only, nothing will be changed. Set APPLY = True to run cells 3-4.")

# %% 3. VNA 設定：S21 量測、頻率、點數、IFBW、功率（讀回比對）
if APPLY:
    print(f"\n=== 3. Set S21 sweep: {FREQ_MIN_HZ/1e9:g}-{FREQ_MAX_HZ/1e9:g} GHz, {POINTS} pts, "
          f"IFBW {IF_BW_HZ:g} Hz, {POWER_DBM:g} dBm ===")
    problems = []
    try:
        vna.checked(f"SENS{CH}:SWE:MODE HOLD")
        cat = vna.query(f"CALC{CH}:PAR:CAT:EXT?").strip('"').split(",")
        name = next((n for n, p in zip(cat[::2], cat[1::2]) if p.upper() == "S21"), None)
        if name is None:
            name = "JPA_S21"
            vna.checked(f'CALC{CH}:PAR:DEF:EXT "{name}","S21"')
            traces = [int(t) for t in vna.query("DISP:WIND1:CAT?").strip('"').split(",") if t.strip()]
            vna.checked(f'DISP:WIND1:TRAC{max(traces, default=0) + 1}:FEED "{name}"')
        vna.checked(f'CALC{CH}:PAR:SEL "{name}"')
        mnum = int(vna.query(f"CALC{CH}:PAR:MNUM?"))
        print(f"  using S21 measurement \"{name}\" (number {mnum})")
        vna.checked(f"SOUR{CH}:DC:ENAB OFF")          # keep the DC205 out of this test
        vna.checked(f"SENS{CH}:SWE:TYPE LIN")
        vna.checked(f"SENS{CH}:FREQ:STAR {FREQ_MIN_HZ}")
        vna.checked(f"SENS{CH}:FREQ:STOP {FREQ_MAX_HZ}")
        vna.checked(f"SENS{CH}:SWE:POIN {POINTS}")
        vna.checked(f"SENS{CH}:BWID {IF_BW_HZ}")
        vna.checked(f"SOUR{CH}:POW1 {POWER_DBM}")
        vna.checked("FORM:DATA ASC,0")
        print("  readback:")
        par = vna.query(f"CALC{CH}:MEAS{mnum}:PAR?").strip('"')
        print(f"    {'measurement':<20} read {par:<22} expected {'S21':<12} -> {'OK' if par == 'S21' else 'MISMATCH'}")
        problems += [
            "" if par == "S21" else f"measurement {mnum} is {par}, expected S21",
            expect("DC sources", vna.query(f"SOUR{CH}:DC:ENAB?"), False),
            expect("freq min [Hz]", vna.query(f"SENS{CH}:FREQ:STAR?"), FREQ_MIN_HZ, 1),
            expect("freq max [Hz]", vna.query(f"SENS{CH}:FREQ:STOP?"), FREQ_MAX_HZ, 1),
            expect("points", vna.query(f"SENS{CH}:SWE:POIN?"), POINTS),
            expect("IF bandwidth [Hz]", vna.query(f"SENS{CH}:BWID?"), IF_BW_HZ, 1e-6 * IF_BW_HZ),
            expect("power [dBm]", vna.query(f"SOUR{CH}:POW1?"), POWER_DBM, 0.01),
        ]
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(3, problems)

# %% 4. VNA 掃描：single sweep，讀回 S21 資料並畫圖
if APPLY:
    print(f"\n=== 4. Single sweep (timeout {SWEEP_TIMEOUT:.0f} s) ===")
    problems = []
    try:
        if mnum is None:
            raise RuntimeError("no S21 measurement selected: run cell 3 first")
        vna.write(f"SENS{CH}:SWE:MODE SING")
        t0 = time.monotonic()
        vna.query("*OPC?", timeout=SWEEP_TIMEOUT)
        print(f"  sweep finished in {time.monotonic() - t0:.3f} s")
        errs = vna.errors()
        if errs:
            problems.append(f"VNA error queue after sweep: {errs}")
        raw = np.array(vna.query(f"CALC{CH}:MEAS{mnum}:DATA:SDATA?", show=False).split(","), float)
        freq = np.array(vna.query(f"CALC{CH}:MEAS{mnum}:DATA:X?", show=False).split(","), float)
        s21 = raw[0::2] + 1j * raw[1::2]
        amp_db = 20 * np.log10(np.abs(s21))
        print(f"  data: {len(s21)} points, freq {freq[0]/1e9:g}-{freq[-1]/1e9:g} GHz, "
              f"|S21| {amp_db.min():.2f} .. {amp_db.max():.2f} dB")
        if len(s21) != POINTS or len(freq) != POINTS:
            problems.append(f"got {len(s21)} data / {len(freq)} freq points, expected {POINTS}")
        if not np.all(np.isfinite(s21)) or np.all(s21 == 0):
            problems.append("S21 data contains non-finite values or is all zero")

        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.plot(freq / 1e9, amp_db)
        ax.set(xlabel="Frequency [GHz]", ylabel="|S21| [dB]", title=f"VNA test sweep, {POWER_DBM:g} dBm")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        plt.show()
    except Exception as e:
        problems.append(f"{type(e).__name__}: {e}")
    result(4, problems)

# %% 5. 關閉連線
vna.close()

# %%
