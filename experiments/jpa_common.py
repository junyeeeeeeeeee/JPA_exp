"""Shared helpers for the experiment scripts.

Linux server -> (LAN SCPI) -> Keysight E5080B VNA -> External DC Source "DC205" (SRS DC205)   [VNA DC control]
             -> (USB serial /dev/dc205) -> SRS DC205                                          [direct DC control]
             -> (LAN SCPI) -> Keysight/Agilent PSG E8257D (pump)

Every setting is read back and compared with the commanded value; a mismatch raises.
With VNA DC control the DC205 cannot be read back, so its checks are VNA-side only
(Activate / I/O state, command configuration, VNA error queue). With direct DC control
(class DC205) the DC205's own output state, voltage, range, overload and error registers are read back.
"""
import datetime
import json
import socket
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "experiment_results"
PARAMS_DIR = ROOT / "JPA_params"


# ---------------------------------------------------------------- SCPI over raw socket
class SCPI:
    def __init__(self, ip, port=5025, timeout=10.0, name="", verbose=True):
        self.name = name or ip
        self.timeout = timeout
        self.verbose = verbose
        self.sock = socket.create_connection((ip, port), timeout=5.0)
        self.sock.settimeout(timeout)
        self.buf = b""

    def close(self):
        self.sock.close()

    def write(self, cmd):
        self.sock.sendall((cmd + "\n").encode("ascii"))
        if self.verbose:
            print(f"  [{self.name}] >> {cmd}")

    def query(self, cmd, timeout=None, quiet=False):
        self.sock.settimeout(timeout or self.timeout)
        try:
            self.sock.sendall((cmd + "\n").encode("ascii"))
            while b"\n" not in self.buf:
                chunk = self.sock.recv(1 << 16)
                if not chunk:
                    raise ConnectionError(f"{self.name} closed the connection")
                self.buf += chunk
        finally:
            self.sock.settimeout(self.timeout)
        line, self.buf = self.buf.split(b"\n", 1)
        reply = line.decode("ascii", "replace").strip()
        if self.verbose and not quiet:
            short = reply if len(reply) < 80 else reply[:77] + "..."
            print(f"  [{self.name}] >> {cmd}\n  [{self.name}] << {short}")
        return reply

    def errors(self):
        """Drain SYST:ERR? and return the non-zero entries as raw strings."""
        errs = []
        for _ in range(50):
            r = self.query("SYST:ERR?", quiet=True)
            if r.lstrip("+").split(",")[0] == "0":
                break
            errs.append(r)
        return errs

    def checked(self, cmd):
        """Write a setting; raise with the raw error text if the error queue is non-empty."""
        self.write(cmd)
        errs = self.errors()
        if errs:
            raise RuntimeError(f"{self.name} reported error(s) after '{cmd}': {errs}")


def is_on(reply):
    return reply.strip().strip('"').upper() in ("1", "ON")


def expect_num(label, reply, want, tol, verbose=True):
    """Raise if a numeric readback differs from the commanded value by more than tol."""
    got = float(reply)
    ok = abs(got - want) <= tol
    if verbose or not ok:
        print(f"    {label:<24} set {want:<14.9g} read {got:<14.9g} -> {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise RuntimeError(f"{label}: commanded {want}, instrument reports {got}")
    return got


# ---------------------------------------------------------------- PSG (pump)
def check_psg_off(ip, port=5025):
    """Measurements without pump (01 S21, 02 flux offset): read the PSG and raise if its RF output is ON."""
    psg = SCPI(ip, port, name="PSG")
    try:
        idn = psg.query("*IDN?")
        st = {
            "idn": idn,
            "output_on": is_on(psg.query("OUTP?")),
            "freq_Hz": float(psg.query("FREQ?")),
            "power_dBm": float(psg.query("POW?")),
        }
    finally:
        psg.close()
    if st["output_on"]:
        raise RuntimeError("PSG RF output is ON. This experiment is done without pump: "
                           "turn the PSG output OFF first (OUTP OFF), then rerun.")
    print("    PSG RF output is OFF -> OK")
    return st


# ---------------------------------------------------------------- DC205 via VNA External DC Source
def check_dc205(vna, source, ch):
    """Raise unless the VNA is configured to drive the DC205 the way these scripts expect."""
    q = lambda c: vna.query(c)
    if not is_on(q(f'SYST:CONF:EDEV:EXIS? "{source}"')):
        raise RuntimeError(f'No External Device "{source}" in the VNA.')
    if not is_on(q(f'SYST:CONF:EDEV:STAT? "{source}"')):
        raise RuntimeError(f"{source} is NOT ACTIVATED in the VNA (SYST:CONF:EDEV:STAT = 0): "
                           f"check 'Activate' in the External Device dialog.")
    init = q(f'SYST:CONF:EDEV:DC:COMM:INIT? "{source}"').strip('"').upper()
    exit_ = q(f'SYST:CONF:EDEV:DC:COMM:EXIT? "{source}"').strip('"').upper()
    setp = q(f'SYST:CONF:EDEV:DC:COMM:POIN:SET? "{source}"').strip('"').upper()
    if init not in ("SOUT ON", "SOUT 1") or exit_ not in ("SOUT OFF", "SOUT 0"):
        raise RuntimeError(f'{source} Enable/Disable I/O commands are "{init}"/"{exit_}", '
                           f'expected "SOUT ON"/"SOUT OFF" (output control depends on them).')
    if not setp.startswith("VOLT"):
        raise RuntimeError(f'{source} Set Point command is "{setp}", expected "VOLT {{%f}}".')
    names = [s.strip().strip('"') for s in q(f"SOUR{ch}:DC:CAT?").strip('"').split(",")]
    if source not in names:
        raise RuntimeError(f"{source} is not in channel {ch}'s DC source list ({names}).")
    print(f"    {source} configuration -> OK")


def set_dc(vna, ch, source, volt):
    """Store Start = Stop = volt in the VNA (sent to the DC205 during the next sweep) and read back."""
    vna.checked(f'SOUR{ch}:DC:STAR "{source}",{volt}')
    vna.checked(f'SOUR{ch}:DC:STOP "{source}",{volt}')
    vna.checked(f"SOUR{ch}:DC:ENAB ON")
    vna.checked(f'SOUR{ch}:DC:STAT "{source}",ON')
    expect_num("DC start [V]", vna.query(f'SOUR{ch}:DC:STAR? "{source}"'), volt, 1e-9, vna.verbose)
    expect_num("DC stop [V]", vna.query(f'SOUR{ch}:DC:STOP? "{source}"'), volt, 1e-9, vna.verbose)
    if not (is_on(vna.query(f"SOUR{ch}:DC:ENAB?")) and is_on(vna.query(f'SOUR{ch}:DC:STAT? "{source}"'))):
        raise RuntimeError(f"{source} is not enabled in channel {ch} after setting it.")


def dc_output_on(vna, source):
    """Enable I/O -> the VNA sends "SOUT ON" to the DC205."""
    if is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{source}"')):
        print(f"    {source} I/O already enabled (output ON)")
        return
    vna.checked(f'SYST:CONF:EDEV:IOEN "{source}",ON')
    if not is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{source}"')):
        raise RuntimeError(f"Enable I/O to {source} did not take effect (IOEN still 0).")
    print(f"    {source} I/O enabled -> SOUT ON sent")


def dc_output_off(vna, source):
    """Disable I/O -> the VNA sends "SOUT OFF" to the DC205. Returns True if the readback confirms it."""
    vna.write(f'SYST:CONF:EDEV:IOEN "{source}",OFF')
    off = not is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{source}"'))
    errs = vna.errors()
    print(f"    {source} I/O disabled (SOUT OFF sent) -> {'OK' if off and not errs else 'FAIL'}"
          + (f"  VNA errors: {errs}" if errs else ""))
    print(f"    PLEASE CHECK BY EYE: {source} front-panel OUTPUT is OFF.")
    return off and not errs


def require_dc_io(vna, source):
    if not is_on(vna.query(f'SYST:CONF:EDEV:IOEN? "{source}"', quiet=True)):
        raise RuntimeError(f"VNA I/O to {source} is DISABLED: the bias would NOT be applied.")


def vna_dc_off(vna, ch):
    """Direct DC control: make sure the VNA does not drive any External DC Source during its sweeps."""
    vna.checked(f"SOUR{ch}:DC:ENAB OFF")
    if is_on(vna.query(f"SOUR{ch}:DC:ENAB?")):
        raise RuntimeError(f"VNA channel {ch} DC sources are still enabled after SOUR:DC:ENAB OFF.")
    print(f"    VNA channel {ch} DC sources disabled -> OK")


# ---------------------------------------------------------------- DC205 direct (USB serial)
class DC205:
    """SRS DC205 connected to the server (USB virtual COM port, 115200 baud, no flow control).
    Every change is read back from the DC205 itself; a mismatch, overload or DC205 error raises."""
    RANGE_V = {"RANGE1": 1.01, "RANGE10": 10.1}           # RANGE100 needs the interlock: not allowed here
    CODES = {"0": "RANGE1", "1": "RANGE10", "2": "RANGE100"}  # RNGE? answers with the numeric code

    def __init__(self, port="/dev/dc205", baud=115200, timeout_ms=3000, verbose=True):
        import pyvisa
        self.verbose = verbose
        self.rm = pyvisa.ResourceManager("@py")
        self.dev = self.rm.open_resource(f"ASRL{port}::INSTR", baud_rate=baud, data_bits=8, timeout=timeout_ms,
                                         write_termination="\n", read_termination="\n")
        self.idn = self.query("*IDN?")
        if "DC205" not in self.idn:
            raise RuntimeError(f"{port} does not answer like a DC205: {self.idn!r}")
        self.errors()                                      # clear errors left over from earlier use

    def close(self):
        self.dev.close()
        self.rm.close()

    def query(self, cmd):
        reply = self.dev.query(cmd).strip()
        if self.verbose:
            print(f"  [DC205] >> {cmd}\n  [DC205] << {reply}")
        return reply

    def write(self, cmd):
        self.dev.write(cmd)
        if self.verbose:
            print(f"  [DC205] >> {cmd}")

    def errors(self):
        """LEXE? / LCME? (0 = none); reading clears them."""
        lexe, lcme = int(self.dev.query("LEXE?")), int(self.dev.query("LCME?"))
        return [] if lexe == 0 and lcme == 0 else [f"LEXE={lexe} (execution error)", f"LCME={lcme} (command error)"]

    def state(self):
        r = self.dev.query("RNGE?").strip()
        return {"output_on": is_on(self.dev.query("SOUT?")), "volt_V": float(self.dev.query("VOLT?")),
                "range": self.CODES.get(r, r), "overload": self.dev.query("OVLD?").strip()}

    def check(self, expect_on, volt, rng, tag=""):
        """Read the DC205 and raise unless it matches what was commanded. Returns the state dict."""
        st = self.state()
        bad = []
        if st["output_on"] != expect_on:
            bad.append(f"SOUT={'ON' if st['output_on'] else 'OFF'} (expected {'ON' if expect_on else 'OFF'})")
        if abs(st["volt_V"] - volt) > 2e-6 * self.RANGE_V[rng] + 1e-9:
            bad.append(f"VOLT={st['volt_V']:.6g} (expected {volt:.6g})")
        if st["range"] != rng:
            bad.append(f"RNGE={st['range']} (expected {rng})")
        if st["overload"].upper() not in ("0", "OFF"):
            bad.append(f"OVLD={st['overload']} (overload)")
        bad += self.errors()
        if self.verbose or bad:
            print(f"    DC205 {tag:<10} SOUT={'ON ' if st['output_on'] else 'OFF'} VOLT={st['volt_V']:+.6f} V "
                  f"{st['range']} OVLD={st['overload']} -> {'OK' if not bad else 'FAIL: ' + '; '.join(bad)}")
        if bad:
            raise RuntimeError(f"DC205 state does not match the command ({tag}): {'; '.join(bad)}")
        return st

    def set_range(self, rng):
        if rng not in self.RANGE_V:
            raise ValueError(f"range must be one of {list(self.RANGE_V)}")
        st = self.state()
        if st["range"] != rng:
            if st["output_on"]:
                raise RuntimeError(f"DC205 output is ON: switch it OFF before changing the range to {rng}")
            self.write(f"RNGE {list(self.CODES)[list(self.CODES.values()).index(rng)]}")
        self.check(st["output_on"], self.state()["volt_V"], rng, "range")

    def set_volt(self, volt, rng):
        if abs(volt) > self.RANGE_V[rng]:
            raise ValueError(f"{volt} V is outside {rng} (±{self.RANGE_V[rng]} V)")
        on = self.state()["output_on"]
        self.write(f"VOLT {volt}")
        return self.check(on, volt, rng, "set volt")

    def output(self, on, volt, rng):
        self.write(f"SOUT {'ON' if on else 'OFF'}")
        return self.check(on, volt, rng, "output " + ("ON" if on else "OFF"))


# ---------------------------------------------------------------- VNA S21
def setup_s21(vna, ch, power_dbm, f_min, f_max, ifbw, points):
    """Use (or create) an S21 measurement in channel ch, apply the sweep settings and read them back.
    Returns (measurement number, dict of VNA settings as read back)."""
    vna.checked(f"SENS{ch}:SWE:MODE HOLD")
    cat = vna.query(f"CALC{ch}:PAR:CAT:EXT?").strip('"').split(",")
    pairs = dict(zip(cat[::2], cat[1::2]))
    name = next((n for n, p in pairs.items() if p.upper() == "S21"), None)
    if name is None:
        name = "JPA_S21"
        vna.checked(f'CALC{ch}:PAR:DEF:EXT "{name}","S21"')
        traces = [int(t) for t in vna.query("DISP:WIND1:CAT?").strip('"').split(",") if t.strip()]
        vna.checked(f'DISP:WIND1:TRAC{max(traces, default=0) + 1}:FEED "{name}"')
    vna.checked(f'CALC{ch}:PAR:SEL "{name}"')
    mnum = int(vna.query(f"CALC{ch}:PAR:MNUM?"))

    vna.checked(f"SENS{ch}:SWE:TYPE LIN")
    vna.checked(f"SENS{ch}:FREQ:STAR {f_min}")
    vna.checked(f"SENS{ch}:FREQ:STOP {f_max}")
    vna.checked(f"SENS{ch}:SWE:POIN {points}")
    vna.checked(f"SENS{ch}:BWID {ifbw}")
    vna.checked(f"SOUR{ch}:POW1 {power_dbm}")
    vna.checked("FORM:DATA ASC,0")
    print("  VNA readback:")
    rb = {
        "measurement": name,
        "mnum": mnum,
        "freq_min_Hz": expect_num("freq min [Hz]", vna.query(f"SENS{ch}:FREQ:STAR?"), f_min, 1),
        "freq_max_Hz": expect_num("freq max [Hz]", vna.query(f"SENS{ch}:FREQ:STOP?"), f_max, 1),
        "points": int(expect_num("points", vna.query(f"SENS{ch}:SWE:POIN?"), points, 0)),
        "if_bandwidth_Hz": expect_num("IF bandwidth [Hz]", vna.query(f"SENS{ch}:BWID?"), ifbw, 1e-6 * ifbw),
        "power_dBm": expect_num("power [dBm]", vna.query(f"SOUR{ch}:POW1?"), power_dbm, 0.01),
        "averaging": is_on(vna.query(f"SENS{ch}:AVER?")),
        "error_correction": is_on(vna.query(f"SENS{ch}:CORR?")),
        "vna_electrical_delay_s": float(vna.query(f"CALC{ch}:MEAS{mnum}:CORR:EDEL?")),
        "sweep_time_s": float(vna.query(f"SENS{ch}:SWE:TIME?")),
    }
    return mnum, rb


def sweep_s21(vna, ch, mnum, source=None, timeout=300.0):
    """One single sweep; return complex S21. With source (VNA DC control) the VNA sends VOLT to the
    DC205 during the sweep and its I/O state is checked before and after; source=None skips that."""
    if source:
        require_dc_io(vna, source)
    vna.write(f"SENS{ch}:SWE:MODE SING")
    vna.query("*OPC?", timeout=timeout, quiet=True)
    errs = vna.errors()
    if errs:
        raise RuntimeError(f"VNA error(s) during sweep: {errs}")
    if source:
        require_dc_io(vna, source)   # I/O dropped during the sweep -> bias may not have been applied
    raw = np.array(vna.query(f"CALC{ch}:MEAS{mnum}:DATA:SDATA?", timeout=timeout, quiet=True).split(","), float)
    return raw[0::2] + 1j * raw[1::2]


def read_freq(vna, ch, mnum):
    return np.array(vna.query(f"CALC{ch}:MEAS{mnum}:DATA:X?", quiet=True).split(","), float)


# ---------------------------------------------------------------- analysis
def remove_delay(freq, s21, delay_s=None):
    """Remove the cable electrical delay: S21 * exp(+i 2 pi f tau).
    delay_s=None fits tau from the median point-to-point slope of the unwrapped phase (robust against the
    resonance's phase step; for 2D data the median over all traces is used so every trace gets the
    same tau). Returns (s21_corrected, tau)."""
    if delay_s is None:
        dphase = np.diff(np.unwrap(np.angle(np.atleast_2d(s21)), axis=-1), axis=-1)
        delay_s = float(-np.median(dphase[np.isfinite(dphase)]) / np.median(np.diff(freq)) / (2 * np.pi))
    return s21 * np.exp(2j * np.pi * freq * delay_s), delay_s


def unwrap_2d(s21):
    """Unwrapped phase of 1D or 2D S21 (rows = bias values). Each row is unwrapped along frequency; in 2D the
    rows are then shifted by multiples of 2 pi so that they are continuous along the bias axis at the
    frequency column with the strongest signal (a per-row unwrap from f_min jumps by 2 pi between rows
    whenever the phase at f_min sits near +-pi)."""
    ph = np.unwrap(np.angle(s21), axis=-1)
    if ph.ndim == 2 and len(ph) > 1:
        col = ph[:, np.argmax(np.abs(s21).min(axis=0))]
        ph = ph + (np.unwrap(col) - col)[:, None]
    return ph


def background_trace(s21, ref="median", values=None):
    """Complex background trace for normalization S21 / background (removes cable delay, standing waves and
    the frequency dependence of the lines, circulators and amplifiers, which a linear delay cannot).
    s21: 2D (rows = bias values). ref="median": median of the real and imaginary parts over the rows (the
    resonance moves with bias, so at each frequency most rows are off resonance); ref=<number>: the row whose
    bias in `values` is nearest (choose a bias where the resonance is outside the band)."""
    s21 = np.atleast_2d(s21)
    if isinstance(ref, str):
        if ref != "median":
            raise ValueError(f"background ref must be 'median' or a bias value, not {ref!r}")
        return np.median(s21.real, axis=0) + 1j * np.median(s21.imag, axis=0)
    return s21[np.argmin(np.abs(np.asarray(values) - ref))]


def load_background(path, freq):
    """Background trace from the data.npz of an earlier run on the same frequency grid (a 2D run gives its
    complex median over the rows)."""
    d = np.load(path)
    if d["freq_Hz"].shape != freq.shape or not np.allclose(d["freq_Hz"], freq):
        raise ValueError(f"{path}: frequency grid differs from this run's")
    s = d["s21"]
    return background_trace(s) if s.ndim == 2 else s


# ---------------------------------------------------------------- files
def load_jpa_params(sample):
    path = PARAMS_DIR / f"{sample}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: create the sample's parameter file first.")
    return json.loads(path.read_text(encoding="utf-8"))


def new_run_dir(sample, experiment, tag=""):
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + (f"_{tag}" if tag else "")
    run = RESULTS_DIR / sample / experiment / stamp
    run.mkdir(parents=True, exist_ok=False)
    return run


def _jsonable(o):
    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serializable: {type(o)}")


def save_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=_jsonable) + "\n", encoding="utf-8")


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def elapsed(t0):
    return time.monotonic() - t0
