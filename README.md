# 2.1-inch TFT ESL BLE investigation

This project isolates the Windows/Python environment used to identify, inspect,
and update the verified target ESL. Read-only investigation tools and the
explicitly bounded display writer are kept separate.

## Safety boundary

- `scan_ble.py` receives advertisements only.
- `inspect_gatt.py` requires one explicit address and never writes, pairs, or
  enables notifications.
- Optional GATT reads are limited to an allow-list of standard GAP, Battery,
  and Device Information characteristics.
- Gicisky is installed for source/model inspection, but its upload API is not
  called by these scripts.
- <code>send_image.py</code> is the beginner-facing wrapper. It still requires
  the verified local profile, a fresh single-candidate scan, live GATT
  preflight, strict acknowledgements, and an interactive <code>SEND</code>
  confirmation.
- Display-image transfer is available only through the confirmation-gated
  sender. Firmware, DFU, OTA, NVM, factory reset, and unknown writes are not
  supported.
- Non-candidate BLE names and addresses are counted but not retained.

## Environment

- Windows 11 x64
- Python 3.14.4
- Project-local `.venv`
- Dependencies are pinned in `requirements.txt`

Rebuild from this directory:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
```

No Administrator session is required.

## Validation

```powershell
.\.venv\Scripts\python.exe scripts\check_environment.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Git distribution boundary

Use this `esl-control` directory as the repository root. The tracked
`config\protocol_model_a0.json` contains only the common Model 0xA0 protocol
profile. Every receiving PC must create its own verified device profile under
`evidence\`; never copy a developer's device profile to another PC.

`examples\device_profile.example.json` is a public, non-runnable schema
example. Its identifier is a placeholder and every safety gate is disabled.
Do not copy it into `evidence\` or fill it in by hand. Run the device
identification workflow on the receiving PC so the real profile is created
locally from observed scan, power-cycle, GATT, and protocol evidence.

The following paths are intentionally excluded by `.gitignore`: `.venv`,
`logs`, `evidence`, generated `images`, real-device photos, and the private
experiment report. Before committing or pushing, run:

```powershell
.\.venv\Scripts\python.exe scripts\check_public_release.py
```

Do not use `git add -f` to override these exclusions. Review the staged file
list before every commit. Publishing or pushing remains a separate operator
decision.

## Beginner: send one 250 x 132 image

Prepare one 250 x 132 image (PNG recommended). Color or grayscale input is
converted locally to exact black and white. A different image size is rejected
instead of being silently stretched.

The simplest Windows operation is to drag the image onto
<code>SEND_IMAGE.cmd</code> in Explorer. The launcher opens the guided sender;
it does not write anything until the exact word <code>SEND</code> is entered.

First check the image and local device configuration without BLE communication:

~~~powershell
.\.venv\Scripts\python.exe scripts\send_image.py images\clear_sample_adjusted_v3.png --check-only
~~~

Then start the guided send:

~~~powershell
.\.venv\Scripts\python.exe scripts\send_image.py images\clear_sample_adjusted_v3.png
~~~

The tool performs a fresh scan and stops before the first device write. Type
the exact word <code>SEND</code> only after checking the displayed summary.
Press Enter without typing <code>SEND</code> to cancel. There is no automatic
retry.

## BLE advertisement scan

Use the physical-label-derived suffix only when it has been independently
checked. The scan saves full identifiers only for devices matching the target
name, service UUID, manufacturer ID, model ID, or supplied suffix.

```powershell
.\.venv\Scripts\python.exe scripts\scan_ble.py --duration 20
.\.venv\Scripts\python.exe scripts\scan_ble.py --duration 20 --expected-suffix <HEX_SUFFIX>
```

Run at least twice. A later supervised sequence should compare device powered
on, powered off, and powered on again before uniqueness is claimed.

For the supervised power-cycle check, wait for the operator to disconnect the
battery, scan and save an OFF result, reconnect the battery, and save a new ON
result. Then run:

```powershell
.\.venv\Scripts\python.exe scripts\verify_power_cycle.py --profile evidence\device_profile_<LATEST>.json --off-scan logs\ble_scan_<OFF>.json --on-scan logs\ble_scan_<ON>.json
```

Create a cautious profile from saved scan files:

```powershell
.\.venv\Scripts\python.exe scripts\identify_device.py logs\ble_scan_<A>.json logs\ble_scan_<B>.json
```

After a successful read-only GATT capture, create a new profile with that
evidence attached:

```powershell
.\.venv\Scripts\python.exe scripts\identify_device.py logs\ble_scan_<A>.json logs\ble_scan_<B>.json --gatt logs\gatt_<CAPTURE>.json
```

## GATT enumeration

Copy the exact address from the saved target profile. The default mode performs
connection and service discovery only.

```powershell
.\.venv\Scripts\python.exe scripts\inspect_gatt.py --address <EXACT_ADDRESS>
```

To additionally read only allow-listed standard characteristics:

```powershell
.\.venv\Scripts\python.exe scripts\inspect_gatt.py --address <EXACT_ADDRESS> --read-standard
```

There is no automatic retry. On failure, save the log and diagnose before
trying again.

## Local TEST image and payload dry run

These commands create files only. They do not import Bleak or communicate with
the device.

```powershell
.\.venv\Scripts\python.exe scripts\render_test_image.py
.\.venv\Scripts\python.exe scripts\prepare_payload.py --image images\test_pattern.png --profile evidence\device_profile_<LATEST>.json --protocol config\protocol_model_a0.json
```

For a legibility-oriented sample that accounts for the TFT's effective
resolution, use the large-text preset:

```powershell
.\.venv\Scripts\python.exe scripts\render_clear_sample.py
.\.venv\Scripts\python.exe scripts\prepare_payload.py --image images\clear_sample_adjusted.png --profile evidence\device_profile_<LATEST>.json --protocol config\protocol_model_a0.json
```

For a local-only text / picture / QR demonstration, generate both a vertical
three-panel sample and a larger QR-only sample:

```powershell
.\.venv\Scripts\python.exe scripts\render_layout_samples.py
```

The command writes `images\three_panel_text_picture_qr.png` and
`images\qr_full_sample.png`, records hashes under `evidence\layout_samples_*.json`,
and refuses to overwrite existing files. QR generation is local and uses the
pinned `qrcode==8.2` dependency; no BLE operation occurs.

The payload preparation refuses to proceed unless every non-approval hard gate
is true. It records the exact target, image hash, payload hash, UUIDs, packet
count, forbidden OTA UUIDs, and zero automatic retries. It still sets
`write_allowed` to false; a separate user approval and bounded writer are
required for any device change.

The bounded writer requires both a fresh single-candidate scan and an explicit
`--approve` switch. It writes only the prepared payload through FEF1/FEF2,
stops on any unexpected response, performs no automatic retry, and disconnects
once the device reports completion:

```powershell
.\.venv\Scripts\python.exe scripts\write_test_image.py `
  --plan evidence\write_plan_<LATEST>.json `
  --profile evidence\device_profile_<LATEST>.json `
  --scan logs\ble_scan_<FRESH>.json `
  --approve --approval-note "ユーザー承認: 進めてください"
```

Do not run the writer for a different image or profile. The current display
cannot be read back by this project, so restoration requires a separately
approved image write.

## Logs and privacy

- Session logs and JSON results are under `logs/`.
- Machine-local evidence is under `evidence/`.
- BLE identifiers and all machine-local evidence are ignored by Git.
- Do not publish scan logs, `device_profile*.json`, write histories, or
  real-device photographs.
- The tracked `config\protocol_model_a0.json` is model-common and contains no
  device address or user data.

## Recovery and removal

The setup does not change the global Python installation, registry, Windows
Bluetooth settings, or drivers. To roll it back, close any process using this
project and remove only this `esl-control` directory after confirming its
absolute path and preserving any desired local logs. Removing the PC-side
project does not restore the ESL screen; the last successfully written image
remains until another approved image is sent.

## Current stop gate

Even if scan confidence reaches 0.80, device writing remains blocked until all
hard gates are satisfied: power-cycle identification, model and GATT match,
verified non-DFU protocol, exact dimensions/color depth, fixed target address,
bounded failure behavior, and explicit user approval for the exact test write.
