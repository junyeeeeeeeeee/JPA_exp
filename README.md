# AS_JPA

JPA measurements: a Keysight E5080B VNA (which drives an SRS DC205 as its External DC Source) and a Keysight/Agilent PSG E8257D, all controlled from a Linux server over LAN using SCPI.

## Folder layout

| Folder | Contents |
| --- | --- |
| `instrument_test/` | Small test scripts, one instrument link per script |
| `experiments/` | Measurement scripts |
| `experiment_results/` | Raw data. **Local only, listed in `.gitignore`.** |
| `analysis/` | Analysis scripts and notebooks |

Scripts are split into `# %%` cells. Run them cell by cell in VS Code ("Run Cell") or all at once with `python <file>`. Instrument addresses and other parameters are at the top of each file.

## Environment setup

Requires Python 3.12. The environment uses [uv](https://docs.astral.sh/uv/), so pip, sudo and `python3-venv` are not needed.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # once per machine
uv venv --python 3.12 .venv
uv pip install -r requirements.txt
source .venv/bin/activate
```

Packages: `pyvisa` and `pyvisa-py` (a pure-Python VISA backend, so no NI or Keysight VISA install is needed), plus `numpy`, `scipy`, `matplotlib` and `ipykernel`.

## Instrument test

| Instrument | Address | Script |
| --- | --- | --- |
| E5080B VNA | `TCPIP0::192.168.1.23::5025::SOCKET` | `instrument_test/test_vna_dc205.py` |
| DC205 | Connected by USB to the VNA (`ASRL4::INSTR` on the VNA). It is controlled only through the VNA's External DC Source `"DC205"`. | (same as above) |
| PSG E8257D | `TCPIP0::<PSG_IP>::5025::SOCKET` | `instrument_test/test_psg_e8257d.py` |

```bash
python instrument_test/test_vna_dc205.py     # read-only unless APPLY = True in the file
python instrument_test/test_psg_e8257d.py    # read-only; set PSG_IP first
```

Notes:
- In the E5080B DC-source write commands, the source name comes first: `SOUR1:DC:STAR "DC205",0`.
- The test scripts never send `*RST`.
