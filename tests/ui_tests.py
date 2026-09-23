#!/usr/bin/env python3
"""Automated UI regression tests for the Gaussian Elimination Trainer.

The suite renders the supplied single-file HTML directly in Chromium using
Playwright, exercises representative Guided/Practice/Free workflows, and
checks scroll stability, clickability, visibility, and overlap geometry.

Usage:
    python tests/ui_tests.py --html index.html --output ui_test_report

The script writes report.html, report.json, and checkpoint screenshots.
It exits nonzero when failures are found unless --no-fail-exit is supplied.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import math
import os
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from playwright.sync_api import Browser, BrowserContext, Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = REPO_ROOT / "index.html"
DEFAULT_OUTPUT = REPO_ROOT / "ui_test_report"
# Use CHROMIUM_PATH if set, then a system Chromium, and otherwise the browser
# installed by `python -m playwright install chromium`.
CHROMIUM = os.environ.get("CHROMIUM_PATH") or ("/usr/bin/chromium" if Path("/usr/bin/chromium").exists() else None)


@dataclass(frozen=True)
class Viewport:
    name: str
    width: int
    height: int
    mobile: bool
    touch: bool


VIEWPORTS = {
    "android-compact": Viewport("android-compact", 360, 800, True, True),
    "android-standard": Viewport("android-standard", 412, 915, True, True),
    "mobile-landscape": Viewport("mobile-landscape", 915, 412, True, True),
    "tablet": Viewport("tablet", 1024, 768, False, True),
    "desktop": Viewport("desktop", 1440, 900, False, False),
}


@dataclass
class Check:
    test: str
    viewport: str
    step: str
    status: str
    message: str
    screenshot: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestSummary:
    test: str
    viewport: str
    status: str
    duration_ms: int
    checks: int
    failures: int
    errors: int


class Suite:
    def __init__(self, html_path: Path, output: Path, browser: Browser):
        self.html_path = html_path
        self.html_source = html_path.read_text(encoding="utf-8")
        self.output = output
        self.screens = output / "screenshots"
        self.screens.mkdir(parents=True, exist_ok=True)
        self.browser = browser
        self.checks: list[Check] = []
        self.summaries: list[TestSummary] = []
        self.console_messages: list[dict[str, str]] = []
        self._shot_counter = 0

    def new_page(self, viewport: Viewport) -> tuple[BrowserContext, Page]:
        context = self.browser.new_context(
            viewport={"width": viewport.width, "height": viewport.height},
            screen={"width": viewport.width, "height": viewport.height},
            is_mobile=viewport.mobile,
            has_touch=viewport.touch,
            device_scale_factor=1,
            reduced_motion="no-preference",
        )
        page = context.new_page()
        page.set_default_timeout(2500)
        page.on(
            "console",
            lambda msg: self.console_messages.append(
                {"viewport": viewport.name, "type": msg.type, "text": msg.text}
            ),
        )
        page.on(
            "pageerror",
            lambda exc: self.console_messages.append(
                {"viewport": viewport.name, "type": "pageerror", "text": str(exc)}
            ),
        )
        # Keep the first-visit welcome tour from covering the controls under test.
        page.add_init_script("window.__disableWelcomeTour = true;")
        # Browser navigation is intentionally avoided. This also makes the suite
        # independent of a local web server.
        page.set_content(self.html_source, wait_until="load")
        page.wait_for_timeout(80)
        return context, page

    def screenshot(self, page: Page, test: str, viewport: Viewport, step: str) -> str:
        self._shot_counter += 1
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", step).strip("-")[:70]
        name = f"{self._shot_counter:03d}_{viewport.name}_{test}_{safe}.png"
        page.screenshot(path=str(self.screens / name), full_page=False)
        return f"screenshots/{name}"

    def record(
        self,
        test: str,
        viewport: Viewport,
        step: str,
        status: str,
        message: str,
        *,
        page: Page | None = None,
        screenshot: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        shot = self.screenshot(page, test, viewport, step) if screenshot and page else None
        self.checks.append(
            Check(
                test=test,
                viewport=viewport.name,
                step=step,
                status=status,
                message=message,
                screenshot=shot,
                details=details or {},
            )
        )

    def expect(
        self,
        condition: bool,
        test: str,
        viewport: Viewport,
        step: str,
        message: str,
        *,
        page: Page,
        details: dict[str, Any] | None = None,
        screenshot_on_pass: bool = False,
    ) -> bool:
        self.record(
            test,
            viewport,
            step,
            "pass" if condition else "fail",
            message,
            page=page,
            screenshot=screenshot_on_pass or not condition,
            details=details,
        )
        return condition

    @staticmethod
    def eval_rect(page: Page, selector: str) -> dict[str, Any] | None:
        return page.evaluate(
            """selector => {
                const el = document.querySelector(selector);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return {
                    selector,
                    top:r.top, right:r.right, bottom:r.bottom, left:r.left,
                    width:r.width, height:r.height,
                    display:s.display, visibility:s.visibility, opacity:Number(s.opacity),
                    clientWidth:el.clientWidth, clientHeight:el.clientHeight,
                    scrollWidth:el.scrollWidth, scrollHeight:el.scrollHeight,
                    scrollTop:el.scrollTop, scrollLeft:el.scrollLeft
                };
            }""",
            selector,
        )

    @staticmethod
    def page_state(page: Page) -> dict[str, Any]:
        return page.evaluate(
            """() => ({
                scrollX: window.scrollX,
                scrollY: window.scrollY,
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                visualHeight: window.visualViewport?.height ?? null,
                bodyClass: document.body.className,
                prompt: document.querySelector('#promptLine')?.innerText ?? '',
                historyScrollTop: document.querySelector('#historyScroll')?.scrollTop ?? null,
                historyScrollHeight: document.querySelector('#historyScroll')?.scrollHeight ?? null,
                historyClientHeight: document.querySelector('#historyScroll')?.clientHeight ?? null,
                mode: document.querySelector('.mode-pill.active')?.textContent?.trim() ?? '',
                activeElement: document.activeElement?.id || document.activeElement?.className || document.activeElement?.tagName
            })"""
        )

    @staticmethod
    def intersection(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float, float]:
        width = max(0.0, min(a["right"], b["right"]) - max(a["left"], b["left"]))
        height = max(0.0, min(a["bottom"], b["bottom"]) - max(a["top"], b["top"]))
        return width, height, width * height

    def assert_no_overlap(
        self,
        page: Page,
        test: str,
        viewport: Viewport,
        step: str,
        selector_a: str,
        selector_b: str,
        label: str,
        tolerance: float = 1.0,
    ) -> bool:
        a = self.eval_rect(page, selector_a)
        b = self.eval_rect(page, selector_b)
        if not a or not b:
            return self.expect(
                False,
                test,
                viewport,
                step,
                f"Could not measure {label} because one element was missing.",
                page=page,
                details={"a": a, "b": b},
            )
        width, height, area = self.intersection(a, b)
        ok = width <= tolerance or height <= tolerance
        return self.expect(
            ok,
            test,
            viewport,
            step,
            f"{label} {'do not overlap' if ok else 'overlap'}.",
            page=page,
            details={"a": a, "b": b, "intersection": {"width": width, "height": height, "area": area}},
        )

    def assert_visible_in_clip(
        self,
        page: Page,
        test: str,
        viewport: Viewport,
        step: str,
        selector: str,
        clip_selector: str | None,
        label: str,
        minimum_ratio: float = 0.90,
    ) -> bool:
        element = self.eval_rect(page, selector)
        if not element:
            return self.expect(False, test, viewport, step, f"{label} is missing.", page=page)
        viewport_rect = {
            "left": 0,
            "top": 0,
            "right": page.viewport_size["width"],
            "bottom": page.viewport_size["height"],
        }
        clip = self.eval_rect(page, clip_selector) if clip_selector else viewport_rect
        if not clip:
            clip = viewport_rect
        composite = {
            "left": max(viewport_rect["left"], clip["left"]),
            "top": max(viewport_rect["top"], clip["top"]),
            "right": min(viewport_rect["right"], clip["right"]),
            "bottom": min(viewport_rect["bottom"], clip["bottom"]),
        }
        width, height, visible_area = self.intersection(element, composite)
        area = max(1.0, element["width"] * element["height"])
        ratio = visible_area / area
        style_visible = (
            element["display"] != "none"
            and element["visibility"] != "hidden"
            and element["opacity"] > 0
        )
        ok = style_visible and ratio >= minimum_ratio
        return self.expect(
            ok,
            test,
            viewport,
            step,
            f"{label} is {ratio:.0%} visible in its usable area.",
            page=page,
            details={"element": element, "clip": composite, "visibleRatio": ratio},
        )

    def assert_relevant_rows_visible(
        self,
        page: Page,
        test: str,
        viewport: Viewport,
        step: str,
        rows: Iterable[int],
        minimum_ratio: float = 0.78,
    ) -> bool:
        measurements = page.evaluate(
            """rows => {
                const table = document.querySelector('.step-line:last-child .matrix-table');
                const history = document.querySelector('#historyScroll');
                const panel = document.querySelector('#interactionPanel');
                if (!table || !history || !panel) return null;
                const hr = history.getBoundingClientRect();
                const pr = panel.getBoundingClientRect();
                const panelIsFixed = getComputedStyle(panel).position === 'fixed';
                const clip = {
                    left: Math.max(0, hr.left),
                    right: Math.min(innerWidth, hr.right),
                    top: Math.max(0, hr.top),
                    bottom: Math.min(innerHeight, hr.bottom, panelIsFixed ? pr.top : innerHeight)
                };
                return rows.map(index => {
                    const row = table.rows[index];
                    if (!row) return {index, missing:true};
                    const r = row.getBoundingClientRect();
                    const w = Math.max(0, Math.min(r.right, clip.right) - Math.max(r.left, clip.left));
                    const h = Math.max(0, Math.min(r.bottom, clip.bottom) - Math.max(r.top, clip.top));
                    const ratio = (w*h) / Math.max(1, r.width*r.height);
                    return {index, ratio, rect:{top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height}, clip};
                });
            }""",
            list(rows),
        )
        if measurements is None:
            return self.expect(False, test, viewport, step, "Could not locate the current matrix rows.", page=page)
        ok = all(not m.get("missing") and m.get("ratio", 0) >= minimum_ratio for m in measurements)
        return self.expect(
            ok,
            test,
            viewport,
            step,
            f"Relevant current-matrix rows are {'visible' if ok else 'obscured'} above the mobile sheet.",
            page=page,
            details={"rows": measurements, "minimumRatio": minimum_ratio},
        )

    def assert_clickable(
        self,
        page: Page,
        test: str,
        viewport: Viewport,
        step: str,
        selector: str,
        label: str,
    ) -> bool:
        info = page.evaluate(
            """selector => {
                const el = document.querySelector(selector);
                if (!el) return {missing:true};
                const r = el.getBoundingClientRect();
                const x = Math.max(0, Math.min(innerWidth - 1, r.left + r.width/2));
                const y = Math.max(0, Math.min(innerHeight - 1, r.top + r.height/2));
                const top = document.elementFromPoint(x, y);
                return {
                    rect:{top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height},
                    point:{x,y},
                    topTag:top?.tagName ?? null,
                    topId:top?.id ?? null,
                    topClass:top?.className ?? null,
                    targetContainsTop:!!top && (el === top || el.contains(top)),
                    topContainsTarget:!!top && top.contains(el)
                };
            }""",
            selector,
        )
        ok = bool(info and not info.get("missing") and (info.get("targetContainsTop") or info.get("topContainsTarget")))
        return self.expect(
            ok,
            test,
            viewport,
            step,
            f"{label} is {'clickable' if ok else 'covered at its center point'}.",
            page=page,
            details=info,
        )

    def user_click(
        self,
        page: Page,
        test: str,
        viewport: Viewport,
        step: str,
        selector: str,
        *,
        nth: int | None = None,
        record_blocked: bool = True,
    ) -> None:
        locator = page.locator(selector)
        if nth is not None:
            locator = locator.nth(nth)
        try:
            locator.click(timeout=1200)
        except PlaywrightError as exc:
            if record_blocked:
                self.record(
                    test,
                    viewport,
                    step,
                    "fail",
                    f"A normal user click was blocked; the test continued with a DOM click. {type(exc).__name__}",
                    page=page,
                    screenshot=True,
                    details={"selector": selector, "nth": nth, "error": str(exc)[:900]},
                )
            locator.evaluate("el => el.click()")
        page.wait_for_timeout(40)

    def set_matrix(self, page: Page, rows: list[list[str]]) -> None:
        row_count = len(rows)
        col_count = len(rows[0])
        page.select_option("#rowCount", str(row_count))
        page.select_option("#colCount", str(col_count))
        page.wait_for_timeout(30)
        # Changing size focuses the first matrix cell and opens the custom keypad.
        page.locator('button[data-action="hide"]').evaluate("el => el.click()")
        flat = [value for row in rows for value in row]
        inputs = page.locator(".matrix-entry")
        if inputs.count() != len(flat):
            raise RuntimeError(f"Expected {len(flat)} entry inputs, found {inputs.count()}")
        for index, value in enumerate(flat):
            inputs.nth(index).evaluate(
                "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
                value,
            )

    def choose_mode(self, page: Page, mode: str, *, normal_click: bool = True) -> None:
        selector = {"free": "#freeModeBtn", "guided": "#guidedModeBtn", "practice": "#practiceModeBtn"}[mode]
        if normal_click:
            page.locator(selector).click()
        else:
            page.locator(selector).evaluate("el => el.click()")
        page.wait_for_timeout(60)

    def start(self, page: Page) -> None:
        page.locator("#startBtn").click()
        page.wait_for_timeout(100)

    @staticmethod
    def dom_click(page: Page, selector: str, nth: int | None = None) -> None:
        locator = page.locator(selector)
        if nth is not None:
            locator = locator.nth(nth)
        locator.evaluate("el => el.click()")
        page.wait_for_timeout(50)

    @staticmethod
    def fill_factor(page: Page, value: str, press_enter: bool = False) -> None:
        input_el = page.locator("#factorInput")
        input_el.evaluate(
            "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', {bubbles:true})); }",
            value,
        )
        if press_enter:
            input_el.press("Enter")
            page.wait_for_timeout(100)

    def run_test(self, name: str, viewport: Viewport, function: Callable[[Page, str, Viewport], None]) -> None:
        context, page = self.new_page(viewport)
        start_time = time.perf_counter()
        before = len(self.checks)
        try:
            function(page, name, viewport)
        except Exception as exc:
            self.record(
                name,
                viewport,
                "uncaught-exception",
                "error",
                f"Uncaught test error: {exc}",
                page=page,
                screenshot=True,
                details={"traceback": traceback.format_exc()},
            )
        finally:
            duration = int((time.perf_counter() - start_time) * 1000)
            recent = self.checks[before:]
            failures = sum(c.status == "fail" for c in recent)
            errors = sum(c.status == "error" for c in recent)
            status = "error" if errors else "fail" if failures else "pass"
            self.summaries.append(
                TestSummary(
                    test=name,
                    viewport=viewport.name,
                    status=status,
                    duration_ms=duration,
                    checks=len(recent),
                    failures=failures,
                    errors=errors,
                )
            )
            context.close()

    # --------------------------- Test cases ---------------------------

    def test_generate_stays_in_setup(self, page: Page, test: str, viewport: Viewport) -> None:
        before = self.page_state(page)
        self.user_click(page, test, viewport, "generate", "#randomBtn")
        after = self.page_state(page)
        delta = after["scrollY"] - before["scrollY"]
        self.expect(
            abs(delta) <= 8,
            test,
            viewport,
            "generate-scroll",
            "Generating a problem does not move the page before the matrix is accepted.",
            page=page,
            details={"before": before, "after": after, "delta": delta},
        )
        self.assert_visible_in_clip(page, test, viewport, "generated-entry-grid", "#entryMatrix", None, "Generated matrix-entry grid", 0.55)
        self.assert_visible_in_clip(page, test, viewport, "generated-start-button", "#startBtn", None, "Start button", 0.90)
        self.record(test, viewport, "generated-matrix", "pass", "Generated matrix checkpoint.", page=page, screenshot=True)

    def test_mode_selector_focus(self, page: Page, test: str, viewport: Viewport) -> None:
        self.user_click(page, test, viewport, "tap-guided", "#guidedModeBtn")
        page.wait_for_timeout(280)
        colors = page.evaluate(
            """() => {
                const b = document.querySelector('#guidedModeBtn');
                const s = getComputedStyle(b);
                return {background:s.backgroundColor, color:s.color, className:b.className, active:document.activeElement===b};
            }"""
        )
        page.locator("#guidedModeBtn").evaluate("el => el.blur()")
        page.wait_for_timeout(80)
        settled = page.evaluate(
            """() => {
                const b = document.querySelector('#guidedModeBtn');
                const s = getComputedStyle(b);
                return {background:s.backgroundColor, color:s.color, className:b.className};
            }"""
        )
        ok = colors["background"] == settled["background"] and colors["color"] == settled["color"]
        self.expect(
            ok,
            test,
            viewport,
            "active-style",
            "The active mode style is stable immediately after a touch/focus interaction.",
            page=page,
            details={"immediate": colors, "settled": settled},
        )

    def test_mobile_header_workspace_state(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "0"], ["2", "1"]])
        self.choose_mode(page, "practice")
        self.start(page)
        page.wait_for_timeout(120)

        header = self.eval_rect(page, "header")
        mode_switch = self.eval_rect(page, ".mode-switch")
        work_panel = self.eval_rect(page, ".work-panel")
        edit_button = self.eval_rect(page, "#editMatrixBtn")
        header_hidden = bool(header and (header["display"] == "none" or header["height"] == 0))
        modes_hidden = bool(mode_switch and (mode_switch["display"] == "none" or mode_switch["width"] == 0 or mode_switch["height"] == 0))
        hidden = header_hidden and modes_hidden
        self.expect(
            hidden,
            test,
            viewport,
            "header-hidden-during-work",
            "The mobile title and mode selector are hidden after the computation starts.",
            page=page,
            details={"header": header, "modeSwitch": mode_switch},
        )
        self.assert_visible_in_clip(page, test, viewport, "workspace-near-top", ".work-panel", None, "Computation workspace", 0.45)
        self.assert_visible_in_clip(page, test, viewport, "change-matrix-visible", "#editMatrixBtn", None, "Change matrix button", 0.85)
        self.expect(
            bool(work_panel and work_panel["top"] <= 12),
            test,
            viewport,
            "workspace-uses-header-space",
            "The computation workspace moves into the space released by the hidden header.",
            page=page,
            details={"workPanel": work_panel, "editButton": edit_button},
        )

        self.user_click(page, test, viewport, "return-to-setup", "#editMatrixBtn")
        page.wait_for_timeout(120)
        restored_header = self.eval_rect(page, "header")
        restored_modes = self.eval_rect(page, ".mode-switch")
        setup = self.eval_rect(page, ".setup-panel")
        restored = bool(restored_header and restored_header["display"] != "none" and restored_header["height"] > 0)
        restored = restored and bool(restored_modes and restored_modes["display"] != "none" and restored_modes["height"] > 0)
        restored = restored and bool(setup and setup["display"] != "none" and setup["height"] > 0)
        self.expect(
            restored,
            test,
            viewport,
            "header-restored-in-setup",
            "Returning to matrix setup restores the title, mode selector, and setup panel.",
            page=page,
            details={"header": restored_header, "modeSwitch": restored_modes, "setup": setup},
        )
        self.record(test, viewport, "mobile-header-checkpoint", "pass", "Mobile workspace header checkpoint.", page=page, screenshot=True)

    def test_operation_buttons_no_page_jump(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "0"], ["2", "1"]])
        self.choose_mode(page, "practice")
        self.start(page)
        # Put the operation toolbar at a reproducible useful position.
        page.locator(".work-panel").evaluate("el => el.scrollIntoView({block:'start', behavior:'instant'})")
        page.wait_for_timeout(50)
        before = self.page_state(page)
        self.assert_visible_in_clip(page, test, viewport, "controls-before", ".operation-toolbar", None, "Operation toolbar", 0.80)
        self.user_click(page, test, viewport, "click-interchange", "#swapBtn")
        after = self.page_state(page)
        delta = after["scrollY"] - before["scrollY"]
        self.expect(
            abs(delta) <= 8,
            test,
            viewport,
            "operation-scroll",
            "Opening an operation prompt does not move the document page.",
            page=page,
            details={"before": before, "after": after, "delta": delta},
        )
        self.assert_visible_in_clip(page, test, viewport, "controls-after", ".operation-toolbar", None, "Operation toolbar after clicking Interchange rows", 0.65)
        self.record(test, viewport, "interchange-prompt", "pass", "Interchange prompt checkpoint.", page=page, screenshot=True)

    def test_guided_factor_entry(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "1", "-2", "1"], ["1", "1", "-1", "1"], ["0", "1", "-2", "2"]])
        self.choose_mode(page, "guided")
        self.start(page)
        # Pick R1 as pivot, then choose replacement R1 -> R2.
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, "#replaceBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        page.wait_for_timeout(150)
        self.assert_visible_in_clip(page, test, viewport, "guided-factor-input", "#factorInput", "#promptLine", "Guided factor input", 0.92)
        self.assert_visible_in_clip(page, test, viewport, "guided-prompt", "#promptLine .prompt-text", "#promptLine", "Guided prompt text", 0.70)
        if page.locator(".mobile-back-control").count():
            self.assert_no_overlap(page, test, viewport, "guided-back-input", "#factorInput", ".mobile-back-control", "Guided Back button and factor input")
        if page.locator("#numericKeypad.open").count():
            self.assert_no_overlap(page, test, viewport, "guided-keypad-input", "#factorInput", "#numericKeypad", "Guided factor input and keypad")
        self.assert_relevant_rows_visible(page, test, viewport, "guided-matrix-rows", [0, 1])
        self.assert_clickable(page, test, viewport, "guided-factor-clickable", "#factorInput", "Guided factor input")
        self.record(test, viewport, "guided-factor-checkpoint", "pass", "Guided factor-entry checkpoint.", page=page, screenshot=True)

    def test_practice_row_entry(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "1", "-2", "1"], ["1", "1", "-1", "1"], ["0", "1", "-2", "2"]])
        self.choose_mode(page, "practice")
        self.start(page)
        # Add history first; row-entry layout must still reveal the current matrix.
        self.dom_click(page, "#swapBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        self.dom_click(page, "#swapBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(3) td:nth-child(1)")
        self.dom_click(page, "#replaceBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        page.wait_for_timeout(100)
        before_factor = self.page_state(page)
        self.fill_factor(page, "-1", press_enter=True)
        after_row_entry = self.page_state(page)
        delta = after_row_entry["scrollY"] - before_factor["scrollY"]
        self.expect(
            abs(delta) <= 12,
            test,
            viewport,
            "practice-page-scroll",
            "Moving from factor entry to full-row entry does not jump the document page.",
            page=page,
            details={"before": before_factor, "after": after_row_entry, "delta": delta},
        )
        self.expect(
            page.locator(".row-result-input").count() == 4,
            test,
            viewport,
            "practice-row-fields",
            "Practice mode displays one resulting-row field per matrix column.",
            page=page,
            details={"count": page.locator(".row-result-input").count()},
        )
        self.assert_visible_in_clip(page, test, viewport, "practice-first-row-input", ".row-result-input", "#promptLine", "First Practice-mode row-entry field", 0.90)
        if page.locator(".mobile-back-control").count():
            self.assert_no_overlap(page, test, viewport, "practice-back-inputs", ".practice-row-input-scroller", ".mobile-back-control", "Practice row-entry inputs and Back button")
            self.assert_no_overlap(page, test, viewport, "practice-back-check", ".practice-row-entry-wrap > button", ".mobile-back-control", "Practice Check row and Back buttons")
        if page.locator("#numericKeypad.open").count():
            self.assert_no_overlap(page, test, viewport, "practice-keypad-row", ".practice-row-entry-wrap", "#numericKeypad", "Practice row-entry area and keypad")
        self.assert_relevant_rows_visible(page, test, viewport, "practice-matrix-rows", [0, 1])
        self.record(test, viewport, "practice-row-entry-checkpoint", "pass", "Practice full-row-entry checkpoint.", page=page, screenshot=True)

    def test_numeric_operation_completion(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "1", "-2", "1"], ["1", "1", "-1", "1"], ["0", "1", "-2", "2"]])
        self.choose_mode(page, "free")
        self.start(page)
        page.locator(".work-panel").evaluate("el => el.scrollIntoView({block:'start', behavior:'instant'})")
        page.wait_for_timeout(50)
        self.dom_click(page, "#replaceBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        page.wait_for_timeout(80)
        before = self.page_state(page)
        self.fill_factor(page, "-1", press_enter=True)
        after = self.page_state(page)
        delta = after["scrollY"] - before["scrollY"]
        self.expect(
            abs(delta) <= 12,
            test,
            viewport,
            "completion-page-scroll",
            "Completing a numeric row operation does not jump to the setup area or top of the page.",
            page=page,
            details={"before": before, "after": after, "delta": delta},
        )
        self.assert_relevant_rows_visible(page, test, viewport, "completion-current-matrix", [0, 1], minimum_ratio=0.65)
        self.assert_visible_in_clip(page, test, viewport, "completion-workspace", ".work-panel", None, "Computation workspace after applying the operation", 0.30)
        self.record(test, viewport, "completion-checkpoint", "pass", "Numeric-operation completion checkpoint.", page=page, screenshot=True)

    def test_mode_switch_after_start(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "0"], ["2", "1"]])
        self.choose_mode(page, "free")
        self.start(page)
        page.locator(".work-panel").evaluate("el => el.scrollIntoView({block:'start', behavior:'instant'})")
        page.wait_for_timeout(50)
        before = self.page_state(page)
        # DOM click avoids Playwright's own scroll-into-view so this measures only app behavior.
        self.choose_mode(page, "guided", normal_click=False)
        after = self.page_state(page)
        delta = after["scrollY"] - before["scrollY"]
        self.expect(
            abs(delta) <= 8,
            test,
            viewport,
            "mode-switch-scroll",
            "Switching modes after starting does not move the document page.",
            page=page,
            details={"before": before, "after": after, "delta": delta},
        )
        self.assert_relevant_rows_visible(page, test, viewport, "mode-switch-current-matrix", [0, 1], minimum_ratio=0.65)

    def test_long_history_latest_visible(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "2", "3", "4"], ["0", "1", "2", "3"], ["0", "0", "1", "2"]])
        self.choose_mode(page, "free")
        self.start(page)
        initial_page_y = self.page_state(page)["scrollY"]
        for index in range(7):
            self.dom_click(page, "#scaleBtn")
            self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
            self.fill_factor(page, "-1", press_enter=True)
            page.wait_for_timeout(60)
            self.assert_relevant_rows_visible(page, test, viewport, f"latest-visible-{index+1}", [0], minimum_ratio=0.65)
        state = self.page_state(page)
        overflowed = state["historyScrollHeight"] > state["historyClientHeight"] + 2
        history_ok = (not overflowed) or state["historyScrollTop"] > 0
        self.expect(
            history_ok,
            test,
            viewport,
            "history-overflowed",
            "When the history overflows, it scrolls to reveal the latest computation.",
            page=page,
            details={**state, "overflowed": overflowed},
        )
        if viewport.mobile:
            self.expect(
                abs(state["scrollY"] - initial_page_y) <= 12,
                test,
                viewport,
                "long-history-page-stable",
                "Appending several operations keeps the document page anchored.",
                page=page,
                details={"initialScrollY": initial_page_y, "final": state},
            )
        self.record(test, viewport, "long-history-checkpoint", "pass", "Long-history checkpoint.", page=page, screenshot=True)

    def test_desktop_practice_smoke(self, page: Page, test: str, viewport: Viewport) -> None:
        self.set_matrix(page, [["1", "1", "-2", "1"], ["1", "1", "-1", "1"], ["0", "1", "-2", "2"]])
        self.choose_mode(page, "practice")
        self.start(page)
        self.dom_click(page, "#replaceBtn")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(1) td:nth-child(1)")
        self.dom_click(page, ".matrix-table.interactive tr:nth-child(2) td:nth-child(1)")
        self.fill_factor(page, "-1", press_enter=True)
        self.assert_visible_in_clip(page, test, viewport, "desktop-row-entry", ".practice-row-entry-wrap", None, "Desktop Practice row-entry controls", 0.95)
        self.expect(
            page.locator("#numericKeypad.open").count() == 0,
            test,
            viewport,
            "desktop-no-custom-keypad",
            "The custom touch keypad does not open on a desktop pointer layout.",
            page=page,
        )
        self.assert_visible_in_clip(page, test, viewport, "desktop-exports", ".export-toolbar", None, "Desktop export controls", 0.90)
        self.record(test, viewport, "desktop-practice-checkpoint", "pass", "Desktop Practice-mode checkpoint.", page=page, screenshot=True)

    def write_report(self) -> None:
        data = {
            "html": str(self.html_path),
            "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summaries": [asdict(item) for item in self.summaries],
            "checks": [asdict(item) for item in self.checks],
            "console": self.console_messages,
        }
        (self.output / "report.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

        pass_count = sum(item.status == "pass" for item in self.summaries)
        fail_count = sum(item.status == "fail" for item in self.summaries)
        error_count = sum(item.status == "error" for item in self.summaries)
        check_failures = [c for c in self.checks if c.status in {"fail", "error"}]

        def esc(value: Any) -> str:
            return html_module.escape(str(value))

        rows = []
        for summary in self.summaries:
            rows.append(
                "<tr>"
                f"<td>{esc(summary.viewport)}</td><td>{esc(summary.test)}</td>"
                f"<td><span class='status {summary.status}'>{esc(summary.status.upper())}</span></td>"
                f"<td>{summary.checks}</td><td>{summary.failures}</td><td>{summary.duration_ms} ms</td>"
                "</tr>"
            )

        failure_cards = []
        for check in check_failures:
            shot = f"<a href='{esc(check.screenshot)}'><img src='{esc(check.screenshot)}' alt='Failure screenshot'></a>" if check.screenshot else ""
            details = esc(json.dumps(check.details, indent=2, sort_keys=True))
            failure_cards.append(
                "<article class='failure'>"
                f"<h3>{esc(check.viewport)} · {esc(check.test)} · {esc(check.step)}</h3>"
                f"<p><span class='status {esc(check.status)}'>{esc(check.status.upper())}</span> {esc(check.message)}</p>"
                f"{shot}<details><summary>Measurements</summary><pre>{details}</pre></details>"
                "</article>"
            )

        all_checks = []
        for check in self.checks:
            link = f"<a href='{esc(check.screenshot)}'>screenshot</a>" if check.screenshot else ""
            all_checks.append(
                "<tr>"
                f"<td>{esc(check.viewport)}</td><td>{esc(check.test)}</td><td>{esc(check.step)}</td>"
                f"<td><span class='status {esc(check.status)}'>{esc(check.status.upper())}</span></td>"
                f"<td>{esc(check.message)}</td><td>{link}</td>"
                "</tr>"
            )

        report = f"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
<title>Gaussian Elimination Trainer UI Test Report</title>
<style>
:root {{ color-scheme: light dark; font-family: system-ui, sans-serif; }}
body {{ max-width: 1200px; margin: 32px auto; padding: 0 18px; line-height: 1.45; }}
h1,h2,h3 {{ line-height: 1.2; }}
.summary {{ display:flex; gap:12px; flex-wrap:wrap; margin:18px 0; }}
.metric {{ border:1px solid #aaa6; border-radius:10px; padding:12px 16px; min-width:110px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th,td {{ border-bottom:1px solid #aaa5; text-align:left; padding:8px; vertical-align:top; }}
.status {{ font-weight:750; font-size:12px; padding:3px 7px; border-radius:999px; }}
.status.pass {{ background:#dcfce7; color:#166534; }}
.status.fail {{ background:#fee2e2; color:#991b1b; }}
.status.error {{ background:#ffedd5; color:#9a3412; }}
.failure {{ border:1px solid #ef444477; border-left:5px solid #ef4444; border-radius:10px; padding:14px; margin:14px 0; }}
.failure img {{ max-width:360px; width:100%; border:1px solid #aaa7; }}
pre {{ white-space:pre-wrap; word-break:break-word; font-size:12px; }}
.small {{ color:#666; }}
</style>
</head>
<body>
<h1>Gaussian Elimination Trainer UI Test Report</h1>
<p class='small'>Tested file: <code>{esc(self.html_path)}</code></p>
<div class='summary'>
<div class='metric'><strong>{pass_count}</strong><br>passing tests</div>
<div class='metric'><strong>{fail_count}</strong><br>failing tests</div>
<div class='metric'><strong>{error_count}</strong><br>test errors</div>
<div class='metric'><strong>{len(self.checks)}</strong><br>geometry checks</div>
</div>
<h2>Test runs</h2>
<table><thead><tr><th>Viewport</th><th>Test</th><th>Status</th><th>Checks</th><th>Failures</th><th>Time</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<h2>Failures and errors</h2>
{''.join(failure_cards) if failure_cards else '<p>No failures.</p>'}
<h2>All checks</h2>
<table><thead><tr><th>Viewport</th><th>Test</th><th>Step</th><th>Status</th><th>Message</th><th>Artifact</th></tr></thead>
<tbody>{''.join(all_checks)}</tbody></table>
</body></html>"""
        (self.output / "report.html").write_text(report, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", default=str(DEFAULT_HTML), help="Single-file trainer HTML to test")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Directory for reports and screenshots")
    parser.add_argument(
        "--viewports",
        default="android-compact,android-standard,mobile-landscape,desktop",
        help=f"Comma-separated viewport names: {', '.join(VIEWPORTS)}",
    )
    parser.add_argument("--headed", action="store_true", help="Show Chromium while tests run")
    parser.add_argument("--no-fail-exit", action="store_true", help="Exit 0 even when tests fail")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    html_path = Path(args.html).resolve()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected = []
    for name in [item.strip() for item in args.viewports.split(",") if item.strip()]:
        if name not in VIEWPORTS:
            raise SystemExit(f"Unknown viewport {name!r}. Available: {', '.join(VIEWPORTS)}")
        selected.append(VIEWPORTS[name])

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.headed,
            executable_path=CHROMIUM,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        suite = Suite(html_path, output, browser)

        mobile_tests: list[tuple[str, Callable[[Page, str, Viewport], None]]] = [
            ("generate-stays-in-setup", suite.test_generate_stays_in_setup),
            ("mode-selector-focus", suite.test_mode_selector_focus),
            ("mobile-header-workspace-state", suite.test_mobile_header_workspace_state),
            ("operation-buttons-no-page-jump", suite.test_operation_buttons_no_page_jump),
            ("guided-factor-entry", suite.test_guided_factor_entry),
            ("practice-row-entry", suite.test_practice_row_entry),
            ("numeric-operation-completion", suite.test_numeric_operation_completion),
            ("long-history-latest-visible", suite.test_long_history_latest_visible),
        ]
        desktop_tests: list[tuple[str, Callable[[Page, str, Viewport], None]]] = [
            ("generate-stays-in-setup", suite.test_generate_stays_in_setup),
            ("mode-selector-focus", suite.test_mode_selector_focus),
            ("desktop-practice-smoke", suite.test_desktop_practice_smoke),
            ("numeric-operation-completion", suite.test_numeric_operation_completion),
            ("mode-switch-after-start", suite.test_mode_switch_after_start),
            ("long-history-latest-visible", suite.test_long_history_latest_visible),
        ]

        for viewport in selected:
            tests = mobile_tests if viewport.mobile else desktop_tests
            for name, function in tests:
                print(f"[{viewport.name}] {name} ...", flush=True)
                suite.run_test(name, viewport, function)

        browser.close()
        suite.write_report()

    failing = sum(summary.status != "pass" for summary in suite.summaries)
    print(f"\nReport: {output / 'report.html'}")
    print(f"JSON:   {output / 'report.json'}")
    print(f"Runs: {len(suite.summaries)}, failing/error: {failing}")
    return 0 if args.no_fail_exit or failing == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
