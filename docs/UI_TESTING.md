# Gaussian Elimination Trainer UI regression testing

This package uses Python Playwright and an installed Chromium-compatible browser to test the single-file Gaussian Elimination Trainer without starting a web server.

## Run it

Install the test dependency first:

```bash
python -m pip install playwright
python -m playwright install chromium
```

```bash
python tests/ui_tests.py --html index.html --output ui_test_report
```

The script defaults to `index.html` and `ui_test_report`, so the same suite can also be run as:

```bash
python tests/ui_tests.py
```

The suite uses `CHROMIUM_PATH` if it is set, then `/usr/bin/chromium` if it exists, and otherwise the Chromium installed by `python -m playwright install chromium`.

The default suite covers:

- Android-like portrait viewports at 360×800 and 412×915
- a 915×412 touch landscape viewport
- a 1440×900 desktop viewport
- generated-matrix behavior before Start
- mode-selector focus/touch styling
- opening operation prompts without page jumps
- Guided-mode factor entry
- Practice-mode full-row entry after computation history already exists
- completing a numeric row operation
- mode switching after a computation has started
- long computation histories
- desktop Practice-mode and export-control smoke tests

The output directory contains:

- `report.html`: human-readable results
- `report.json`: machine-readable measurements
- `screenshots/`: automatic screenshots for failures and selected checkpoints

The process exits with status 1 when failures are detected. Add `--no-fail-exit` while developing if a report is desired even when the current page is known to be broken.

## What the harness measures

The checks include:

- `window.scrollY` before and after actions
- `historyScroll.scrollTop`, `scrollHeight`, and `clientHeight`
- element bounding rectangles
- visible intersection ratios within the prompt pane, history pane, and viewport
- overlap between Back/Cancel controls, text inputs, row-entry controls, and keypad
- whether a control is covered at its center point
- whether relevant current-matrix rows remain visible above a fixed mobile sheet
- console errors and uncaught page errors

A blocked normal click is recorded as a failure, after which the test uses a DOM click so that later stages can still be exercised.

## Interpreting failures

The suite is intended to catch regressions in the supported mobile and desktop workflows. A failure usually indicates that a control is covered, a relevant matrix is no longer visible, the page jumped unexpectedly, or a browser console/page error occurred. Open `report.html` in the output directory first; screenshots and detailed geometry measurements are available alongside it.

## Limits of headless testing

Chromium emulation covers touch events, viewport geometry, the in-page keypad, scrolling, overlap, and responsive CSS. It does not perfectly reproduce:

- Android Chrome's collapsing address bar
- the operating-system soft keyboard
- Samsung-specific browser chrome
- actual haptic feedback
- GPU timing of the fireworks animation

After the automated suite passes, a short real-device smoke test should remain: generated matrix, Guided factor entry, Practice full-row entry, operation completion, long history, and mode switching.
