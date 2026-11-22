# Csillagszemű Juhász

Csillagszemű Juhász estimates where one person is looking on an extended Windows desktop using ordinary webcams. It can display a click-through gaze dot over other apps. Each person can keep their own calibration. Capture and inference run locally.

## Install on Windows

**[Download the Windows package](https://github.com/Albertstein99/csillagszemu-juhasz/raw/refs/heads/main/downloads/Csillagszemu-Juhasz-Windows.zip)** · [GitHub releases](https://github.com/Albertstein99/csillagszemu-juhasz/releases)

1. Extract **Csillagszemu-Juhasz-Windows.zip**. Open **Csillagszemu-Juhasz-Setup.exe** and choose **Install**. Use Windows 10 version 1803 or later, or Windows 11, on x64 hardware. Setup downloads its private Python environment, libraries and models. Allow about 1.5 GB of free space. Tracking works offline afterward.
2. Open **Csillagszemű Juhász** from Start. In Windows camera privacy settings, allow desktop apps to use cameras. Close another app if it has exclusive use of a camera.
3. Choose **Start cameras**. Select a device and tick **Show selected camera** to check framing. Each camera used for tracking should see both eyes. Double-click a row or use Space to disable an unwanted or virtual camera.
4. When at least one camera reports **Eyes visible**, choose **Calibrate**. Use **New profile** for a different person. Follow the center of each target and blink normally. On the second pass, shift your head a few centimeters or change distance slightly. Space or a click starts each block. Esc cancels and S skips an unusable training target.
5. Review **Accuracy report**. Turn on **Desktop gaze dot** for a live overlay. **Check accuracy** runs another set of fixations without retraining. The tracker never moves your pointer or clicks.

The webcam request defaults to 1920 × 1080. A driver can negotiate a different size. If multiple USB cameras stall or the computer cannot keep up, choose 720p or 480p. Calibration is keyed to the actual received resolution. Profiles reload when the app opens. Start cameras resumes tracking after a reboot.

## What the measurements mean

Each monitor gets 13 training targets, a second pass over 9 positions, and 9 held-out check positions. Training waits for a stable fixation. Validation measures fixed time windows and counts missing predictions. The targets advance automatically after the start of each block.

| Report field | Definition |
| --- | --- |
| Median px / P90 px | Median or 90th percentile across per-target median Euclidean errors, in current Windows desktop pixels. An estimate on the wrong screen incurs its full desktop distance. A target needs predictions in at least half its samples to receive an error score. |
| Coverage | Fraction of sampled times at which the tracker returned a point, including time spent blinking or looking away. |
| Screen hit | Fraction of available predictions routed to the target monitor. |
| Jitter px | Median within-fixation distance from the fixation’s median point, summarized across targets on the correct screen. |
| Combined | The live fusion and smoothing path. Individual camera rows use the same target windows. Exported JSON includes counts and errors for each target. |

Prefer a new **Check accuracy** run when comparing setups. Try testing from your usual seat and again after shifting position. Compare **Combined** with the individual cameras on the same display, paying attention to coverage as well as error. A second view can help with independent noise and dropouts. Similar viewpoints, reflections, or a consistently misaligned camera can give correlated errors. A dot that barely moves can still be far away from the true gaze point.

During calibration, a camera fit is accepted only if every display it learned has at least 6 scored validation targets, 60% sample coverage, 80% correct-monitor routing, and median error at most 15% of that screen's diagonal. These are broad rejection thresholds. Use the reported pixel errors to judge suitability for a particular task. A failed fit preserves the prior accepted model. The calibration report describes the candidate that was just tested. A subsequent accuracy check measures the active saved model.

## Cameras, screens and head motion

Csillagszemű Juhász uses MediaPipe Face Landmarker for both irises and eyelids, Intel's Open Model Zoo head-pose network, and a trained binocular appearance model for gaze direction. The personalized mapping considers learned gaze angles, normalized iris position, eye asymmetry, head rotation, translation and apparent face size. Regularized fits are compared using grouped cross-validation. All observations for a repeated target stay in the same fold. Final validation positions are excluded from training and model selection.

Each camera runs in a separate process, with one latest image waiting for inference. Blinks, multiple faces, stale frames, pronounced extrapolation and conflicting camera predictions can produce an unavailable state. Fusion uses per-display cross-validation error, live eye visibility and timestamps. Observations more than 90 ms behind the newest view are excluded from fusion. A watchdog recovers a blocked camera process independently.

Displays and cameras are identified using their Windows device paths where available. Calibration coordinates are saved in the original desktop layout and mapped back to each connected display. This supports negative origins, mixed DPI, a new primary display, and same-aspect resolution changes. A disconnected display drops out of the output. When a known camera or display returns, its matching calibration can be reused. A newly added camera or display needs a calibration that covers it. Recalibrating a subset preserves saved models for other device combinations.

Use **Extend** for distinct monitor targets. Mirrored displays present one Windows desktop surface. Devices without persistent hardware identifiers may be identified by a logical display or unique camera name. A driver reinstall or changing the USB port of a serial-less device can require a new calibration. Moving a physical camera, changing digital zoom, rotating a display, or moving it relative to the camera also changes the setup. Automatic framing and movement of laptop lids can affect results. Ordinary glasses may work best with lighting that leaves the eyes visible from each view.

**Learn from clicks** is optional. A stable pre-click fixation close to the pointer supplies a possible reference. The app requires seven mutually consistent clicks spread over three screen regions before applying a small correction. Corrections are bounded, local to that screen and session, and reset when the option is switched off. Windows clicks can be unrelated to gaze, so this feature starts off. Initial calibration requires labeled targets.

## Development and cloud builds

The included **Csillagszemu-Juhasz-source.zip** contains the entire source tree, installer builder, unit tests and Windows CI workflow. Extract it to a project directory for editing. Publish that directory to a Git repository, including the hidden `.github` directory, to use the workflow. It runs on pushes and pull requests or on manual dispatch. The Windows runner installs the inference stack, downloads checksum-verified model assets, tests a public reference portrait, and builds a downloadable installer.

For background development, connect the repository to a published Codex Cloud environment and start a cloud task against it. The project can be private. A cloud worker can change the software and run replay tests while the laptop is powered off. Live validation of webcam aim, head movement, glasses and multi-camera timing needs an attended physical setup.

From a Windows x64 checkout with Python 3.12 and Tk available, run these PowerShell commands.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python setup/assets.py
.\.venv\Scripts\python run.py --verify
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python run.py
```

Run `python setup/build.py` to create the Windows download under `dist`. The builder uses the .NET Framework compiler included on supported x64 Windows installations. The graphical installer verifies the pinned runtime and models, initializes both inference and Tk, then creates a Start menu shortcut. The installer is unsigned. First installation needs HTTPS access to GitHub, PyPI, Google Cloud Storage and Intel's Open Model Zoo. The Microsoft Visual C++ 2015–2022 x64 runtime may be needed on a clean Windows image if a dependency reports a missing DLL.

The reusable `csillagszem.model.track` interface takes fresh, per-camera feature frames, saved calibrations, live screen geometry and a monotonic time. It returns an `Estimate` with physical desktop coordinates, screen identity, contributing cameras and timestamp, or `None` when unavailable. The `error` field is a weighting scale derived from calibration residuals. Future dwell or accessibility controls can consume this interface. No clinical or accessibility performance claim is made for this release.

Profiles and the latest accuracy report live under `%LOCALAPPDATA%\Csillagszemű Juhász`. Preview frames stay in memory. Export saves anonymized hardware keys, device labels, target locations and error statistics. Model weights are downloaded from their publishers during setup. See **THIRD-PARTY.md** for provenance.

To uninstall, close Csillagszemű Juhász, remove its Start menu shortcut, and delete `%LOCALAPPDATA%\Programs\Csillagszemu-Juhasz`. The separate `%LOCALAPPDATA%\Csillagszemű Juhász` directory contains personal calibrations and can be kept for a future installation.
