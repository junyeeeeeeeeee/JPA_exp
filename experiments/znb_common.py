"""Shared helpers for the Rohde & Schwarz ZNB VNA (ZNB20, 4 ports, 100 kHz - 20 GHz).

Linux server -> (LAN SCPI, raw socket port 5025) -> R&S ZNB20

R&S SCPI differs from the Keysight E5080B in jpa_common:
  - traces have names in single quotes: CALC<ch>:PAR:SDEF 'name','S21', CALC<ch>:PAR:CAT? -> 'Trc1,S21'
  - IF bandwidth is SENS<ch>:BAND, the port power is SOUR<ch>:POW
  - single sweep: INIT<ch>:CONT OFF (hold), SENS<ch>:SWE:COUN 1, then INIT<ch>:IMM + *OPC?
  - data: CALC<ch>:DATA:TRAC? 'name', SDAT (re,im pairs); frequencies: CALC<ch>:DATA:STIM?
Every setting is read back and compared with the commanded value; a mismatch raises (jc.expect_num).
Never sends *RST.
"""
import numpy as np

import jpa_common as jc

TRACE = "JPA_S21"              # trace created when the channel has no trace with the wanted S-parameter


def _list(reply):
    """'a,b,c' (R&S single-quoted list) -> ['a', 'b', 'c']"""
    return [s.strip() for s in reply.strip().strip("'\"").split(",") if s.strip()]


def device_clear(ip):
    """VXI-11 Device Clear: aborts a command the ZNB is stuck on (e.g. *OPC? waiting for a trigger that never
    comes). While it is stuck, the ZNB answers no SCPI client at all (socket, VXI-11, HiSLIP)."""
    import pyvisa
    rm = pyvisa.ResourceManager("@py")
    try:
        dev = rm.open_resource(f"TCPIP0::{ip}::inst0::INSTR", timeout=10_000)
        dev.clear()
        print(f"    ZNB {ip}: device clear sent -> {dev.query('*IDN?').strip()}")
        dev.close()
    finally:
        rm.close()


def setup_s21(vna, ch, power_dbm, f_min, f_max, ifbw, points, sparam="S21"):
    """Use (or create) a trace measuring sparam in channel ch, apply the sweep settings and read them back.
    The channel is put on hold (INIT<ch>:CONT OFF); sweep_s21 then runs one sweep at a time.
    Returns (trace name, dict of VNA settings as read back)."""
    sparam = sparam.upper()
    vna.checked(f"INIT{ch}:CONT OFF")
    cat = _list(vna.query(f"CALC{ch}:PAR:CAT?"))
    name = next((n for n, p in zip(cat[::2], cat[1::2]) if p.upper() == sparam), None)
    if name is None:
        name = TRACE
        vna.checked(f"CALC{ch}:PAR:SDEF '{name}','{sparam}'")
        nums = [int(n) for n in _list(vna.query("DISP:WIND1:TRAC:CAT?"))[::2]]
        vna.checked(f"DISP:WIND1:TRAC{max(nums, default=0) + 1}:FEED '{name}'")
    vna.checked(f"CALC{ch}:PAR:SEL '{name}'")

    vna.checked(f"SENS{ch}:SWE:TYPE LIN")
    vna.checked(f"SENS{ch}:FREQ:STAR {f_min}")
    vna.checked(f"SENS{ch}:FREQ:STOP {f_max}")
    vna.checked(f"SENS{ch}:SWE:POIN {points}")
    vna.checked(f"SENS{ch}:BAND {ifbw}")
    vna.checked(f"SOUR{ch}:POW {power_dbm}")
    vna.checked(f"SENS{ch}:SWE:COUN 1")
    vna.checked(f"TRIG{ch}:SOUR IMM")              # MAN / EXT would leave INIT:IMM waiting and block *OPC?
    vna.checked("FORM:DATA ASC")
    print("  ZNB readback:")
    par = vna.query(f"CALC{ch}:PAR:MEAS? '{name}'").strip("'\"").upper()
    if par != sparam:
        raise RuntimeError(f"trace '{name}' measures {par}, expected {sparam}")
    rb = {
        "trace": name,
        "sparam": par,
        "freq_min_Hz": jc.expect_num("freq min [Hz]", vna.query(f"SENS{ch}:FREQ:STAR?"), f_min, 1),
        "freq_max_Hz": jc.expect_num("freq max [Hz]", vna.query(f"SENS{ch}:FREQ:STOP?"), f_max, 1),
        "points": int(jc.expect_num("points", vna.query(f"SENS{ch}:SWE:POIN?"), points, 0)),
        "if_bandwidth_Hz": jc.expect_num("IF bandwidth [Hz]", vna.query(f"SENS{ch}:BAND?"), ifbw, 1e-6 * ifbw),
        "power_dBm": jc.expect_num("power [dBm]", vna.query(f"SOUR{ch}:POW?"), power_dbm, 0.01),
        "sweep_count": int(jc.expect_num("sweep count", vna.query(f"SENS{ch}:SWE:COUN?"), 1, 0)),
        "continuous": jc.is_on(vna.query(f"INIT{ch}:CONT?")),
        "trigger_source": vna.query(f"TRIG{ch}:SOUR?").upper(),
        "averaging": jc.is_on(vna.query(f"SENS{ch}:AVER:STAT?")),
        "error_correction": jc.is_on(vna.query(f"SENS{ch}:CORR:STAT?")),
        "ref_oscillator": vna.query(f"SENS{ch}:ROSC?"),
        "rf_output_on": jc.is_on(vna.query("OUTP?")),
        "sweep_time_s": float(vna.query(f"SENS{ch}:SWE:TIME?")),
    }
    if rb["continuous"]:
        raise RuntimeError(f"channel {ch} is still in continuous sweep after INIT{ch}:CONT OFF")
    if not rb["trigger_source"].startswith("IMM"):
        raise RuntimeError(f"channel {ch} trigger source is {rb['trigger_source']} after TRIG{ch}:SOUR IMM")
    if not rb["rf_output_on"]:
        raise RuntimeError("ZNB RF output is OFF (OUTP? = 0): switch it on (OUTP ON) first")
    return name, rb


def sweep_s21(vna, ch, name, timeout=300.0):
    """One single sweep of channel ch; return the complex data of trace name."""
    vna.write(f"INIT{ch}:IMM")
    try:
        vna.query("*OPC?", timeout=timeout, quiet=True)
    except TimeoutError:
        device_clear(vna.sock.getpeername()[0])    # otherwise the ZNB stays blocked for every client
        raise TimeoutError(f"ZNB sweep did not finish in {timeout} s (device clear sent; check TRIG{ch}:SOUR? "
                           f"and the sweep time)") from None
    errs = vna.errors()
    if errs:
        raise RuntimeError(f"ZNB error(s) during sweep: {errs}")
    raw = np.array(vna.query(f"CALC{ch}:DATA:TRAC? '{name}', SDAT", timeout=timeout, quiet=True).split(","), float)
    return raw[0::2] + 1j * raw[1::2]


def read_freq(vna, ch):
    return np.array(vna.query(f"CALC{ch}:DATA:STIM?", quiet=True).split(","), float)
