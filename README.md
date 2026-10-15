# AS_JPA

JPA measurements, controlled from a Linux server over LAN. Two setups:

- **OPX+ / ZNB (current)**: a Rohde & Schwarz ZNB20 VNA measures S21; the QM OPX+ / Octave supplies the flux (OPX DC offset) and the pump (Octave RF out).
- **DC205 / E5080B (earlier)**: a Keysight E5080B VNA (which drives an SRS DC205 as its External DC Source) and a Keysight/Agilent PSG E8257D pump, over SCPI.

## Folder layout

| Folder | Contents |
| --- | --- |
| `instrument_test/` | Small test scripts, one instrument link per script |
| `experiments/` | Measurement scripts |
| `experiment_results/` | Raw data. **Local only, listed in `.gitignore`.** |
| `analysis/` | Analysis scripts and notebooks |
| `JPA_params/` | One JSON file per JPA sample (flux offset, operating point, circuit parameters, history). Edit by hand. |

Scripts are split into `# %%` cells. Run them cell by cell in VS Code ("Run Cell") or all at once with `python <file>`. Instrument addresses and other parameters are at the top of each file.

## Environment setup

Requires Python 3.12. The environment uses [uv](https://docs.astral.sh/uv/), so pip, sudo and `python3-venv` are not needed.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # once per machine
uv venv --python 3.12 --prompt AS_JPA_env AS_JPA_env
source AS_JPA_env/bin/activate
uv pip install -r requirements.txt
```

Packages: `pyvisa` and `pyvisa-py` (a pure-Python VISA backend, so no NI or Keysight VISA install is needed), `pyserial` (serial instruments such as the DC205), plus `numpy`, `scipy`, `matplotlib` and `ipykernel`.

## Instrument test

| Instrument | Address | Script |
| --- | --- | --- |
| R&S ZNB20 VNA (4 ports, 100 kHz–20 GHz) | `TCPIP0::192.168.1.123::5025::SOCKET` | `instrument_test/test_vna_znb.py` |
| E5080B VNA only | `TCPIP0::192.168.1.23::5025::SOCKET` | `instrument_test/test_vna.py` |
| E5080B VNA + DC205 | (VNA address) | `instrument_test/test_vna_dc205.py` |
| DC205 direct | USB (FT232R) to the server as `/dev/dc205`, 115200 baud, no flow control. Access comes from the udev rule `/etc/udev/rules.d/99-dc205.rules` (group `users`, serial A1082CIQ). | `instrument_test/test_dc205_direct.py` |
| DC205 | Connected by USB to the VNA (`ASRL4::INSTR` on the VNA). It is controlled only through the VNA's External DC Source `"DC205"`. | (same as above) |
| PSG E8257D | `TCPIP0::<PSG_IP>::5025::SOCKET` | `instrument_test/test_psg_e8257d.py` |
| OPX+ / Octave: connection + simulation | `SETUP` in `experiments/opx_common.py` (host, cluster_name) | `instrument_test/test_opx_connect.py` |
| OPX+ / Octave: loopback (time of flight, input offsets) | (same) | `instrument_test/test_opx_loopback.py` |
| OPX+ / Octave: CW pump / readout tones, DC flux | (same) | `instrument_test/test_opx_cw.py` |

```bash
python instrument_test/test_vna_znb.py       # ZNB: APPLY = True sets an S21 trace and runs one sweep
python instrument_test/test_vna_dc205.py     # read-only unless APPLY = True in the file
python instrument_test/test_psg_e8257d.py    # read-only; set PSG_IP first
python instrument_test/test_opx_connect.py   # no output: versions + server simulation
python instrument_test/test_opx_loopback.py  # APPLY = True; RF out -> attenuator -> RF in, not the fridge
python instrument_test/test_opx_cw.py        # APPLY = True; spectrum analyzer / meter on the outputs
```

Notes:
- ZNB (R&S) SCPI differs from the E5080B: trace names are in single quotes (`CALC1:PAR:SDEF 'JPA_S21','S21'`), the IF bandwidth is `SENS1:BAND`, a single sweep is `INIT1:CONT OFF` then `INIT1:IMM; *OPC?`, and data is read with `CALC1:DATA:TRAC? '<trace>', SDAT` (frequencies: `CALC1:DATA:STIM?`). ZNB helpers are in `experiments/znb_common.py`.
- In the E5080B DC-source write commands, the source name comes first: `SOUR1:DC:STAR "DC205",0`.
- The test scripts never send `*RST`.
- OPX+ / Octave: all QUA config is built in `experiments/opx_common.py` from the `SETUP` dict. Octave RF outputs open in the OFF state and are switched ON only while a script uses them; the flux offset returns to 0 V when the QM closes. Octave mixer calibrations are stored in `opx_calibration/` (local only).

## Experiments

Folders are numbered by experiment. Inside an experiment there is one version per instrument setup.

| Script | What it does |
| --- | --- |
| **01 S21** (`experiments/01_S21/`) | |
| `01_S21_E5080B.py` | One E5080B S21 sweep. The VNA's DC sources are disabled, so the DC205 is not driven. |
| `01_S21_ZNB.py` | One ZNB S21 sweep. The OPX+ is not used; by default the script stops if a QM is open (the pump or flux state would be unknown). |
| `01_S21_OPX_wideband.py` | Wide-band S21 with OPX+/Octave: the band is split into LO segments (IF swept inside each), stitched, joint mismatch saved; optional Octave calibration per LO |
| **02 flux offset** (`experiments/02_flux_offset/`) | |
| `DC205_E5080B/02_1_flux_offset_S21.py` | One DC205 voltage, one E5080B S21 sweep (no pump) |
| `DC205_E5080B/02_2_flux_offset_S21_2d.py` | DC205 voltage scan × S21 sweep, 2D map |
| `DC205_E5080B/02_1_flux_offset_S21_direct.py` | Same as 02_1, DC205 controlled directly by the server (`/dev/dc205`) |
| `DC205_E5080B/02_2_flux_offset_S21_2d_direct.py` | Same as 02_2, DC205 controlled directly by the server |
| `OPX_ZNB/02_1_flux_offset_S21.py` | One OPX flux offset, one ZNB S21 sweep (pump OFF) |
| `OPX_ZNB/02_2_flux_offset_S21_2d.py` | OPX flux scan × ZNB S21 sweep, 2D map |

In `DC205_E5080B/`, the plain scripts drive the DC205 through the VNA (External DC Source). The `_direct` scripts talk to the DC205 over USB. They read its output state, voltage, range, overload flag and error registers before and after every sweep, and save the readbacks. Their results go to `<YYYYmmdd_HHMMSS>_direct/`.

In `OPX_ZNB/`, opening the QM closes any other QM on the cluster. Both Octave RF outputs (pump included) stay OFF. Every flux step is read back from the OPX. The flux returns to 0 V when the QM closes at the end. Results go to `<YYYYmmdd_HHMMSS>_opx_znb/`.

Shared code: `experiments/jpa_common.py` (SCPI, E5080B, DC205, PSG, files), `experiments/znb_common.py` (ZNB) and `experiments/opx_common.py` (OPX+/Octave). Each script has three cells: 1 parameters, 2 measurement, 3 analysis and plots.

- Before measuring, the E5080B scripts check that the PSG RF output is OFF and that every VNA setting reads back as commanded. The DC205-through-VNA scripts also check that the DC205 is Activated in the VNA with Enable/Disable I/O set to `SOUT ON`/`SOUT OFF`. The ZNB scripts read back every ZNB setting and check that the ZNB RF output is ON.
- The DC205 output is switched ON for the measurement and OFF afterwards. Through the VNA this is done with Enable/Disable I/O; in the `_direct` scripts with `SOUT`. The voltage setting is left at the last value.
- Phase plots have the electrical delay removed. By default it is fitted from the phase slope.

Results go to `experiment_results/<sample>/<experiment>/<YYYYmmdd_HHMMSS>[_tag]/`, with tag `e5080b`, `znb`, `opx`, `direct` or `opx_znb` (no tag for the DC205-through-VNA scripts), so different setups of the same experiment are kept side by side:
- `params.json`: parameters, VNA readback, instrument IDs and a snapshot of the sample's `JPA_params`
- `data.npz`: raw complex S21
- `data.csv`: 1D only
- `S21_amp.png` and `S21_phase.png`
