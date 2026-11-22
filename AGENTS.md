# Csillagszemu Juh�sz development handoff

## Released baseline

The public Windows x64 preview is [v0.1.1](https://github.com/Albertstein99/csillagszemu-juhasz/releases/tag/v0.1.1). Its [Windows verification run](https://github.com/Albertstein99/csillagszemu-juhasz/actions/runs/44966405243) installed the packaged application on a hosted Windows runner, ran 14 tests and exercised the installed vision models on a real portrait. The desktop integration test used simulated gaze features to complete calibration on two simulated monitors with two camera streams.

Physical gaze accuracy, performance with glasses, hardware disconnect recovery, and the real-world precision gain from adding a camera still need measurements. A portrait confirms that inference executes. Measuring screen error requires a person looking at known targets.

## Where to work

Read README.md for installation, calibration, report definitions and release commands. The csillagszem package separates camera capture and watchdogs (cameras.py), neural inference (vision.py), personal fitting and fusion (model.py), calibration UI (wizard.py), validation and drift correction (session.py), Windows display coordinates (desktop.py), and profile persistence (storage.py). The desktop entry point is run.py. The installer and its build script live in setup/.

## Next development milestone

1. Build a deterministic timestamped replay test that goes through the camera supervisor and the live tracking entry point. Cover a stalled worker, an unplugged camera returning at a different index, stale packets, two views temporarily disagreeing, and display removal during calibration. Check time to unavailable and recovery of the surviving view.
2. Compare the combined estimate against each camera on matched validation samples. Extend the accuracy report with paired sample counts and per-target differences so differences in coverage can be identified. Preserve compatibility with reports and profiles from v0.1.1. Add regression tests and document the new fields.
3. Arrange an attended hardware benchmark. Test one and two independent webcams, each monitor, neutral and shifted seating, and a restart with unchanged geometry. Record median and P90 pixel error, coverage, correct-monitor fraction, jitter and measured recovery time. Keep calibration targets separate from evaluation targets. Obtain permission before collecting or publishing participant data.

Use Windows CI for native dependencies and installer checks. Keep camera frames local. Preserve explicit camera start, separate personal profiles, unavailable output on loss, and detection-only behavior. Develop on a branch and open a pull request with the measurements or tests performed. Leave the released preview available while evaluating changes.
