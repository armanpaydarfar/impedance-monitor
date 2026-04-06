# impedance-monitor

Standalone ANT Neuro electrode impedance monitor. Displays per-electrode impedance
in real time using a PySide6 GUI with a colour-coded head topomap.

## Requirements

- Linux
- Python 3.12
- PySide6 >= 6.7
- `libeego-SDK.so` from ANT Neuro (not managed by pip/conda — see Installation)
- udev rule `90-eego.rules` installed for unprivileged USB access

## Installation

Create and activate a Python 3.12 environment with the required dependencies. Using
conda:

```bash
conda env create -f environment.yml
conda activate impedance-monitor
```

Then run the installer from the project root:

```bash
cd /path/to/impedance-monitor
./install.sh
```

`install.sh` will:
1. Locate `libeego-SDK.so` (fails clearly if not found)
2. Install the udev rule (requires `sudo`)
3. Run `pip install -e .`
4. Verify the setup with `impedance-monitor --check`

## Usage

```bash
# Launch the GUI (hardware required for live mode)
impedance-monitor --mode live --cap ca209

# Mock mode — no hardware required, for UI testing
impedance-monitor --mode mock --cap ca209

# Pre-populate subject and data directory (editable in the GUI before starting)
impedance-monitor --mode live --cap ca209 --subject PILOT007 --data-dir /data/eeg

# Custom SDK location
impedance-monitor --mode live --sdk-path /opt/antneuro/libeego-SDK.so

# Verify setup (no hardware connection opened)
impedance-monitor --check
```

Once the window opens, configure the log directory and subject ID if needed, then
click **▶ Start** to connect to the amplifier and begin acquisition.

## GUI overview

```
┌──────────────────────────────────────────────────────────────────┐
│ Mode: LIVE  Cap: CA-209  Poll: 500 ms  Subject: [____] Log: [__] │  ← config panel
│                                                          [▶ Start]│
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│              [colour-coded electrode topomap]                     │  ← head widget
│              [label in circle, kΩ value below]                    │
│                                                                   │
├──────────────────────────────────────────────────────────────────┤
│ Status: Connected  Battery: 85%  Poll: 500ms  Updated: 10:23:45  │  ← status bar
│                                        [Save Snapshot]  [Quit]   │
└──────────────────────────────────────────────────────────────────┘
```

**Electrode circles** show the channel label centred inside and the impedance value
(e.g. `4.5K`, `30K`) just below the circle. OPEN-circuit channels show white with
no value — the colour alone signals the state. REF and GND are drawn outside the
head outline at fixed positions.

**Updated timestamp** in the status bar refreshes on every successful poll, so you
can immediately see if the display is stale.

## Cap layouts

| Name    | Electrodes       | Description        |
|---------|------------------|--------------------|
| `ca209` | 32 EEG + GND + REF | Default cap      |
| `ca001` | 32 EEG + GND + REF | Alternate 32-ch  |
| `ca200` | 64 EEG + GND + REF | High-density cap |

## Impedance thresholds

| Status   | Range          | Colour |
|----------|----------------|--------|
| Good     | 100 Ω – 10 kΩ  | Green  |
| Marginal | 10 – 20 kΩ     | Orange |
| Bad      | > 20 kΩ        | Red    |
| Open     | < 100 Ω        | White  |

Values below 100 Ω indicate open-circuit (SDK issue 3165) and are never classified
as good impedance. The white colour signals "no contact" unambiguously.

## Logging

One `.log` file is created per session in the configured log directory:

```
{log_dir}/impedance_monitor_{timestamp}.log
```

The log file mirrors everything printed to the terminal — timestamps, level tags,
and message text. Impedance readings are logged at most once per second regardless
of the polling rate, so the file gives a readable time-stamped record of how
electrode impedances evolved during cap setup. Example log lines:

```
2026-04-06 10:23:45,123 [INFO] Session started. Log: /home/.../impedance_logs/...
2026-04-06 10:23:45,456 [INFO] Acquisition started. Mode=LIVE Cap=CA-209 Poll=500ms
2026-04-06 10:23:46,001 [INFO] Readings: FP1=4.2K FPz=3.1K ... GND=open REF=2.1K  [28G 2M 0B 2O]
2026-04-06 10:24:46,003 [INFO] Readings: FP1=3.8K FPz=2.9K ... GND=open REF=1.9K  [30G 0M 0B 2O]
```

The `[28G 2M 0B 2O]` suffix is a count of Good / Marginal / Bad / Open channels.

## SDK constraints

- Only one eego stream can be active at a time. Close eegoSports before running
  live mode.
- The first `getData()` result is discarded after stream open (SDK issue 3162).
- The tool calls `eemagine_sdk_exit()` on shutdown. Use the Quit button or close
  the window — do not kill the process.
