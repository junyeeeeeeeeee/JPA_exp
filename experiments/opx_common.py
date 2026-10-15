"""Shared helpers for the OPX+ / Octave scripts.

Linux server -> (LAN) -> QM router -> OPX+ "con1" + Octave "oct1"
  ro   : Octave RF out 1 (fed by OPX AO1/AO2) -> JPA signal line
         Octave RF in 1  (down-converted to OPX AI1/AI2) <- JPA output chain
  pump : Octave RF out 2 (fed by OPX AO3/AO4) -> pump port (RF side of the bias tee)
  flux : OPX AO5, DC offset only                -> DC side of the bias tee

All QUA config details live here. The scripts change only a few numbers in SETUP
(frequencies, amplitudes, gains, flux voltage), the same way they set VNA parameters.

Safety defaults:
  - Both Octave RF outputs are "always_off" when the QM opens; a script switches an output ON
    explicitly (rf_on) and OFF again (rf_off) when it is done.
  - The flux offset starts at SETUP["flux_V"] (default 0 V) and returns to 0 V when the QM closes
    (keep_dc_offsets_when_closing=False).
  - set_flux reads the offset back and raises on a mismatch, like jpa_common.
"""
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_DB_DIR = ROOT / "opx_calibration"      # Octave mixer calibration database (local only)

# ---------------------------------------------------------------- setup (edit here)
SETUP = {
    # network: QOP >= 2.2 uses host + cluster_name (see the QM admin panel)
    "host": "192.168.1.55",    # OPX+ on the lab LAN (same subnet as this server)
    "port": None,              # None = gateway port 80, which redirects to the QOP and lists the cluster's Octaves
    "cluster_name": "OPXplus_3",
    "con": "con1",
    "octave": "oct1",          # Octave name as shown in the QM admin panel
    "octave_ip": None,         # None: Octave found automatically through the gateway (192.168.1.54:80); or set by hand
    "octave_port": None,
    # wiring
    "ro_rf_out": 1,            # Octave RF out used for the readout drive (AO1/AO2)
    "ro_rf_in": 1,             # Octave RF in used for the readout signal (AI1/AI2)
    "pump_rf_out": 2,          # Octave RF out used for the pump (AO3/AO4)
    "flux_ao": 5,              # OPX analog output used as DC flux source
    # readout: RF = LO + IF, |IF| <= ~350 MHz
    "ro_lo_Hz": 5.60e9,
    "ro_if_Hz": 50e6,
    "ro_gain_dB": 0.0,         # Octave RF out gain, -20 .. +20 dB in 0.5 dB steps
    "ro_amp_V": 0.05,          # OPX amplitude of the readout tone (|I|, peak) [V]
    "ro_len_ns": 10_000,       # readout pulse / integration length [ns], multiple of 4
    # pump: RF = LO + IF
    "pump_lo_Hz": 11.15e9,
    "pump_if_Hz": 50e6,
    "pump_gain_dB": 0.0,
    "pump_amp_V": 0.10,
    # CW building block: one constant pulse, repeated back to back in infinite_loop_
    "cw_len_ns": 1_000,
    # flux (DC offset of flux_ao): |V| <= 0.5 into 50 ohm
    "flux_V": 0.0,
    # acquisition: fill in from instrument_test/test_opx_loopback.py
    "time_of_flight_ns": 24,   # >= 24, multiple of 4
    "ai_offsets_V": (0.0, 0.0),
    "ai_gain_dB": 0,           # OPX analog input gain, -12 .. +20 dB
}

FLUX_LIMIT_V = 0.5
_AMP_LIMIT_V = 0.5 - 2**-16


def _check(p):
    for k in ("ro_len_ns", "cw_len_ns", "time_of_flight_ns"):
        if p[k] % 4:
            raise ValueError(f"{k} = {p[k]} must be a multiple of 4 ns")
    if p["time_of_flight_ns"] < 24:
        raise ValueError("time_of_flight_ns must be >= 24")
    for k in ("ro_if_Hz", "pump_if_Hz"):
        if abs(p[k]) > 350e6:
            raise ValueError(f"{k} = {p[k]:g} is outside the +-350 MHz IF band")
    for k in ("ro_amp_V", "pump_amp_V"):
        if not 0 <= p[k] <= _AMP_LIMIT_V:
            raise ValueError(f"{k} = {p[k]} V is outside 0 .. 0.5 V")
    for k in ("ro_gain_dB", "pump_gain_dB"):
        if not -20 <= p[k] <= 20 or (2 * p[k]) % 1:
            raise ValueError(f"{k} = {p[k]} must be in -20 .. +20 dB, 0.5 dB steps")
    if abs(p["flux_V"]) > FLUX_LIMIT_V:
        raise ValueError(f"flux_V = {p['flux_V']} V is outside +-{FLUX_LIMIT_V} V")


def params(**overrides):
    """SETUP with overrides applied and checked."""
    unknown = set(overrides) - set(SETUP)
    if unknown:
        raise KeyError(f"unknown setup keys: {sorted(unknown)}")
    p = {**SETUP, **overrides}
    _check(p)
    return p


# ---------------------------------------------------------------- QUA config
def build_config(p):
    """QUA config for the three elements "ro", "pump" and "flux" (QOP >= 2.2, Octave in the config)."""
    con, octv, n_ro = p["con"], p["octave"], p["ro_len_ns"]
    return {
        "controllers": {
            con: {
                "analog_outputs": {
                    1: {"offset": 0.0}, 2: {"offset": 0.0},          # ro I/Q   -> Octave RF1
                    3: {"offset": 0.0}, 4: {"offset": 0.0},          # pump I/Q -> Octave RF2
                    p["flux_ao"]: {"offset": p["flux_V"]},           # flux DC
                },
                "digital_outputs": {1: {}},
                "analog_inputs": {
                    1: {"offset": p["ai_offsets_V"][0], "gain_db": p["ai_gain_dB"]},
                    2: {"offset": p["ai_offsets_V"][1], "gain_db": p["ai_gain_dB"]},
                },
            },
        },
        "octaves": {
            octv: {
                "RF_outputs": {
                    p["ro_rf_out"]: {"LO_frequency": p["ro_lo_Hz"], "LO_source": "internal",
                                     "output_mode": "always_off", "gain": p["ro_gain_dB"]},
                    p["pump_rf_out"]: {"LO_frequency": p["pump_lo_Hz"], "LO_source": "internal",
                                       "output_mode": "always_off", "gain": p["pump_gain_dB"]},
                },
                "RF_inputs": {
                    p["ro_rf_in"]: {"LO_frequency": p["ro_lo_Hz"], "LO_source": "internal"},
                },
                "connectivity": con,
            },
        },
        "elements": {
            "ro": {
                "RF_inputs": {"port": (octv, p["ro_rf_out"])},
                "RF_outputs": {"port": (octv, p["ro_rf_in"])},
                "intermediate_frequency": p["ro_if_Hz"],
                "operations": {"cw": "ro_cw_pulse", "readout": "readout_pulse"},
                "time_of_flight": p["time_of_flight_ns"],
                "smearing": 0,
            },
            "pump": {
                "RF_inputs": {"port": (octv, p["pump_rf_out"])},
                "intermediate_frequency": p["pump_if_Hz"],
                "operations": {"cw": "pump_cw_pulse"},
            },
            "flux": {
                "singleInput": {"port": (con, p["flux_ao"])},
                "operations": {"zero": "flux_zero_pulse"},
            },
        },
        "pulses": {
            "ro_cw_pulse": {"operation": "control", "length": p["cw_len_ns"],
                            "waveforms": {"I": "ro_wf", "Q": "zero_wf"}},
            "pump_cw_pulse": {"operation": "control", "length": p["cw_len_ns"],
                              "waveforms": {"I": "pump_wf", "Q": "zero_wf"}},
            "readout_pulse": {"operation": "measurement", "length": n_ro,
                              "waveforms": {"I": "ro_wf", "Q": "zero_wf"},
                              "integration_weights": {"cos": "cos_w", "sin": "sin_w", "minus_sin": "minus_sin_w"},
                              "digital_marker": "ON"},
            "flux_zero_pulse": {"operation": "control", "length": 16,
                                "waveforms": {"single": "zero_wf"}},
        },
        "waveforms": {
            "ro_wf": {"type": "constant", "sample": p["ro_amp_V"]},
            "pump_wf": {"type": "constant", "sample": p["pump_amp_V"]},
            "zero_wf": {"type": "constant", "sample": 0.0},
        },
        "digital_waveforms": {"ON": {"samples": [(1, 0)]}},
        "integration_weights": {
            "cos_w": {"cosine": [(1.0, n_ro)], "sine": [(0.0, n_ro)]},
            "sin_w": {"cosine": [(0.0, n_ro)], "sine": [(1.0, n_ro)]},
            "minus_sin_w": {"cosine": [(0.0, n_ro)], "sine": [(-1.0, n_ro)]},
        },
    }


# ---------------------------------------------------------------- connection
def connect(p, log_level="WARNING"):
    """QuantumMachinesManager for the cluster; prints the server versions.
    From QOP 2.4 the gateway reports the cluster's Octaves, so normally no Octave address is needed."""
    from qm import QuantumMachinesManager
    CALIBRATION_DB_DIR.mkdir(exist_ok=True)
    octave_config = None
    if p["octave_ip"] is not None:
        from qm.octave import QmOctaveConfig
        octave_config = QmOctaveConfig()
        octave_config.add_device_info(p["octave"], p["octave_ip"], p["octave_port"])
    qmm = QuantumMachinesManager(host=p["host"], port=p["port"], cluster_name=p["cluster_name"], log_level=log_level,
                                 octave=octave_config, octave_calibration_db_path=str(CALIBRATION_DB_DIR))
    sd = qmm._server_details
    octaves = {n: f"{d.host}:{d.port}" for n, d in sd.octaves.items()}
    print(f"    connected to {sd.connection_details.host}:{sd.connection_details.port} ({p['cluster_name']}), "
          f"Octaves {octaves or 'given by hand'}")
    print(f"    versions: {qmm.version()}")
    if p["octave_ip"] is None and p["octave"] not in sd.octaves:
        raise RuntimeError(f"cluster has no Octave named '{p['octave']}' (it lists: {sorted(sd.octaves)})")
    return qmm


def open_qm(qmm, config):
    """Open a QM (closes the other QMs). Octave RF outputs start OFF; flux returns to 0 V on close."""
    return qmm.open_qm(config, close_other_machines=True, keep_dc_offsets_when_closing=False)


def check_no_open_qm(qmm):
    """For measurements that leave the OPX alone (e.g. a ZNB S21 without flux): raise if a QM is open,
    because it may be playing the pump or holding a flux offset."""
    ids = qmm.list_open_qms()
    if ids:
        raise RuntimeError(f"QM(s) open on the cluster: {ids}. The pump / flux state is unknown: close them "
                           f"(qmm.close_all_qms()) or measure with an OPX-controlled flux (02_flux_offset/OPX_ZNB).")
    print("    no QM open on the OPX (pump not playing) -> OK")


# ---------------------------------------------------------------- outputs
def rf_on(qm, element):
    from qm.octave import RFOutputMode
    qm.octave.set_rf_output_mode(element, RFOutputMode.on)
    print(f"    Octave RF output of '{element}' -> ON")


def rf_off(qm, element):
    from qm.octave import RFOutputMode
    qm.octave.set_rf_output_mode(element, RFOutputMode.off)
    print(f"    Octave RF output of '{element}' -> OFF")


def set_rf_gain(qm, element, gain_dB):
    if not -20 <= gain_dB <= 20 or (2 * gain_dB) % 1:
        raise ValueError(f"gain {gain_dB} dB must be in -20 .. +20 dB, 0.5 dB steps")
    qm.octave.set_rf_output_gain(element, gain_dB)
    print(f"    Octave gain of '{element}' -> {gain_dB:g} dB")


def set_lo(qm, element, lo_Hz):
    """Change the Octave LO of an element (Python side; not inside a running QUA loop)."""
    qm.octave.set_lo_frequency(element, lo_Hz)
    print(f"    Octave LO of '{element}' -> {lo_Hz / 1e9:.6f} GHz")


def set_if(qm, element, if_Hz):
    """Change the IF of an element; also works while a program (e.g. a CW loop) is running."""
    if abs(if_Hz) > 350e6:
        raise ValueError(f"IF {if_Hz:g} Hz is outside the +-350 MHz band")
    qm.set_intermediate_frequency(element, if_Hz)
    print(f"    IF of '{element}' -> {if_Hz / 1e6:.3f} MHz")


def set_flux(qm, volt, tol=1e-6):
    """Set the DC offset of the flux output and read it back; a mismatch raises."""
    if abs(volt) > FLUX_LIMIT_V:
        raise ValueError(f"flux {volt} V is outside +-{FLUX_LIMIT_V} V")
    qm.set_output_dc_offset_by_element("flux", "single", volt)
    got = qm.get_output_dc_offset_by_element("flux", "single")
    ok = abs(got - volt) <= tol
    print(f"    flux offset [V]          set {volt:<14.9g} read {got:<14.9g} -> {'OK' if ok else 'MISMATCH'}")
    if not ok:
        raise RuntimeError(f"flux offset: commanded {volt} V, OPX reports {got} V")
    return got


def calibrate(qm, element):
    """Octave automatic mixer calibration (LO leakage + image) at the element's current LO/IF."""
    print(f"    calibrating '{element}' (LO leakage + image) ...")
    return qm.calibrate_element(element)


# ---------------------------------------------------------------- QUA programs
def cw_program(elements):
    """Play the "cw" pulse of each element back to back forever (stop with job.halt())."""
    from qm.qua import program, infinite_loop_, play
    with program() as prog:
        with infinite_loop_():
            for el in elements:
                play("cw", el)
    return prog


def raw_adc_program(n_avg, wait_ns=2_000):
    """Averaged raw ADC traces of the "readout" pulse on both inputs (time-of-flight check)."""
    from qm.qua import (program, declare, declare_output_stream, for_, measure, wait,
                        reset_if_phase, stream_processing)
    with program() as prog:
        n = declare(int)
        adc_st = declare_output_stream(adc_trace=True)
        with for_(n, 0, n < n_avg, n + 1):
            reset_if_phase("ro")
            measure("readout", "ro", adc_stream=adc_st)
            wait(wait_ns // 4, "ro")
        with stream_processing():
            adc_st.input1().average().save("adc1")
            adc_st.input2().average().save("adc2")
            adc_st.input1().save("adc1_single")
            adc_st.input2().save("adc2_single")
    return prog


def raw2volts(adc):
    """OPX+ ADC: 12 bit over 1 V full scale."""
    return np.asarray(adc, dtype=float) / 4096


def find_time_of_flight(adc1_V, adc2_V, current_tof_ns):
    """Arrival time of the readout pulse in an averaged trace -> suggested time_of_flight (multiple of 4 ns).
    The trace starts current_tof_ns after the pulse is sent, so the arrival index is added to it."""
    from scipy.signal import savgol_filter
    a1, a2 = adc1_V - np.mean(adc1_V), adc2_V - np.mean(adc2_V)
    env = savgol_filter(np.abs(a1 + 1j * a2), 11, 3)
    th = (np.mean(env[:100]) + np.max(env)) / 2
    above = np.where(env > th)[0]
    if len(above) == 0:
        raise RuntimeError("no pulse found in the ADC trace (check the loopback cable and amplitudes)")
    arrival = int(above[0])
    return arrival, int(4 * round((current_tof_ns + arrival) / 4))


# ---------------------------------------------------------------- segmented S21 (wide band)
OCTAVE_LO_RANGE_HZ = (2.0e9, 18.0e9)


def segment_plan(f_start, f_stop, df, if_max=300e6, if_min=0.0, sides="both", overlap=20e6):
    """Split [f_start, f_stop] into LO segments; every segment measures RF = LO + IF.

    sides = "both" : IF in [-if_max, -if_min] U [if_min, if_max], LO in the middle of the segment
                     (segment width 2*if_max, LO step 2*if_max - overlap; |IF| < if_min is skipped,
                     so if_min > 0 leaves a hole of 2*if_min around every LO)
    sides = "upper": IF in [if_min, if_max], LO below the segment (width if_max - if_min); the first LO is
                     raised to the Octave minimum (2 GHz) if needed, which leaves the lowest if_min uncovered
    All RF points lie on one global grid f_start + k*df, so overlapping segments measure the same
    frequencies and the mismatch at the joints can be checked.
    Returns a list of dicts {lo_Hz, if_Hz (int array), f_Hz (array)}.
    """
    if not 0 <= if_min < if_max <= 350e6:
        raise ValueError("need 0 <= if_min < if_max <= 350 MHz")
    if sides not in ("both", "upper"):
        raise ValueError('sides must be "both" or "upper"')
    width = 2 * if_max if sides == "both" else if_max - if_min
    step = width - overlap
    if step <= 0:
        raise ValueError("overlap must be smaller than the segment width")
    grid = f_start + df * np.arange(int(round((f_stop - f_start) / df)) + 1)
    lo0 = f_start + if_max if sides == "both" else max(f_start - if_min, OCTAVE_LO_RANGE_HZ[0])
    plan, k = [], 0
    while True:
        lo = lo0 + k * step
        ifs = grid - lo
        sel = (np.abs(ifs) <= if_max + 1e-3) & (np.abs(ifs) >= if_min - 1e-3)
        if sides == "upper":
            sel &= ifs > 0
        if sel.any():
            if not OCTAVE_LO_RANGE_HZ[0] <= lo <= OCTAVE_LO_RANGE_HZ[1]:
                raise ValueError(f"LO {lo / 1e9:.4f} GHz is outside the Octave range "
                                 f"{OCTAVE_LO_RANGE_HZ[0] / 1e9:g}-{OCTAVE_LO_RANGE_HZ[1] / 1e9:g} GHz")
            plan.append({"lo_Hz": float(lo), "if_Hz": np.rint(ifs[sel]).astype(int), "f_Hz": grid[sel]})
        if lo + (if_max if sides == "both" else if_min) >= f_stop:
            break
        k += 1
    missing = np.setdiff1d(np.round(grid), np.round(np.concatenate([s["f_Hz"] for s in plan])))
    if len(missing):
        print(f"    note: {len(missing)} grid points are not covered (|IF| < if_min around each LO)")
    return plan


def s21_program(ifs, n_avg, wait_ns=1_000):
    """One LO segment: for every IF, play the readout pulse and demodulate it (I, Q averaged n_avg times)."""
    from qm.qua import (program, declare, fixed, declare_output_stream, for_, for_each_, update_frequency,
                        measure, dual_demod, wait, save, stream_processing)
    ifs = [int(f) for f in ifs]
    with program() as prog:
        n, f = declare(int), declare(int)
        I, Q = declare(fixed), declare(fixed)
        I_st, Q_st, n_st = declare_output_stream(), declare_output_stream(), declare_output_stream()
        with for_(n, 0, n < n_avg, n + 1):
            with for_each_(f, ifs):
                update_frequency("ro", f)
                measure("readout", "ro",
                        dual_demod.full("cos", "sin", I),
                        dual_demod.full("minus_sin", "cos", Q))
                wait(wait_ns // 4, "ro")
                save(I, I_st)
                save(Q, Q_st)
            save(n, n_st)
        with stream_processing():
            I_st.buffer(len(ifs)).average().save("I")
            Q_st.buffer(len(ifs)).average().save("Q")
            n_st.save("iteration")
    return prog


def demod2volts(z, length_ns):
    """Demodulated sum -> amplitude [V] at the ADC (OPX+: 12-bit samples, weights of 1)."""
    return np.asarray(z) * 4096 / length_ns


def tune_ro_lo(qm, lo_Hz):
    """Move the readout LO (Octave up- and down-converter) and apply the stored mixer calibration
    for that LO, if one exists (otherwise qm logs a warning and keeps the current correction)."""
    qm.octave.set_lo_frequency("ro", lo_Hz)
    qm.octave.set_downconversion("ro", lo_frequency=lo_Hz)
    qm.octave.set_element_parameters_from_calibration_db("ro")


def measure_s21_segment(qm, seg, n_avg, length_ns, wait_ns=1_000, timeout_s=600):
    """Run s21_program for one segment (LO already tuned). Returns complex amplitude [V] per point."""
    job = qm.execute(s21_program(seg["if_Hz"], n_avg, wait_ns))
    res = job.result_handles
    if not res.wait_for_all_values(timeout=timeout_s):
        job.halt()
        raise TimeoutError(f"segment LO {seg['lo_Hz'] / 1e9:.4f} GHz did not finish in {timeout_s} s")
    z = res.get("I").fetch_all() + 1j * res.get("Q").fetch_all()
    return demod2volts(z, length_ns)


def stitch(plan, data, align="none"):
    """Join the segments on the global grid. Where segments overlap, keep the point with the smallest |IF|.

    The joint mismatch (dB, deg) between neighbours is always measured on the raw data.
    align = "none"      : segments are joined as measured
            "phase"     : every segment is rotated so its overlap with the previous one has the same phase
            "phase+amp" : as "phase", and the amplitude is scaled the same way
    The correction is chained from the first segment, so the first segment sets the absolute level and phase.
    """
    if align not in ("none", "phase", "phase+amp"):
        raise ValueError('align must be "none", "phase" or "phase+amp"')
    joints, factors = [], [1.0 + 0j]
    for k in range(len(plan) - 1):
        fa, fb = np.round(plan[k]["f_Hz"]), np.round(plan[k + 1]["f_Hz"])
        common, ia, ib = np.intersect1d(fa, fb, return_indices=True)
        corr = 1.0 + 0j
        if len(common):
            r = data[k + 1][ib] / data[k][ia]
            ph = np.angle(np.mean(r / np.abs(r)))
            db = float(np.median(20 * np.log10(np.abs(r))))
            joints.append({"lo_a_Hz": plan[k]["lo_Hz"], "lo_b_Hz": plan[k + 1]["lo_Hz"], "n_points": len(common),
                           "f_Hz": float(common.mean()), "dB_mean": db, "deg_mean": float(np.degrees(ph))})
            if align != "none":
                corr = np.exp(-1j * ph) * (10 ** (-db / 20) if align == "phase+amp" else 1.0)
        factors.append(factors[-1] * corr)
    data = [z * c for z, c in zip(data, factors)]
    f_all = np.unique(np.round(np.concatenate([s["f_Hz"] for s in plan])))
    best = {}
    for k, (s, z) in enumerate(zip(plan, data)):
        for f, if_, v in zip(np.round(s["f_Hz"]), s["if_Hz"], z):
            if f not in best or abs(if_) < best[f][0]:
                best[f] = (abs(if_), v, k)
    s21 = np.array([best[f][1] for f in f_all])
    seg_idx = np.array([best[f][2] for f in f_all])
    return f_all, s21, seg_idx, joints


def fit_delay(freq, s21, seg_idx):
    """Electrical delay from the median phase slope, using only steps inside a segment (joints excluded).
    The slope is ambiguous for |delay| near or above 1/(2 df): a warning is printed then."""
    dphi = np.angle(s21[1:] / s21[:-1])
    same = seg_idx[1:] == seg_idx[:-1]
    df = float(np.median(np.diff(freq)))
    tau = float(-np.median(dphi[same]) / (2 * np.pi * df))
    if abs(tau) > 0.35 / df:
        print(f"    WARNING: fitted delay {tau * 1e9:.1f} ns is close to the alias limit 1/(2 df) = {0.5e9 / df:.0f} ns; "
              f"use a smaller frequency step or set the delay by hand")
    return tau
