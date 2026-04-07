"""Live persona browser agent — navigates a website as a specific persona.

Two modes:
1. Autonomous (requires API key): agent makes its own Claude Vision calls
2. MCP-driven (free): Playwright captures state, Claude Code evaluates via MCP tools

The MCP-driven mode uses these tools in a loop:
  start_persona_session → capture_page_state → execute_persona_action → ... → end_persona_session
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Optional

from debuggai.engines.persona.discover import Persona
from debuggai.engines.persona.experience import (
    ExperienceReport,
    ExperienceStep,
    StepEvaluation,
)

logger = logging.getLogger("debuggai")

MAX_STEPS = 15

# ── Global session state for MCP-driven mode ──────────────────

_active_session: Optional[dict] = None


async def _get_playwright():
    try:
        from playwright.async_api import async_playwright
        return async_playwright
    except ImportError:
        raise RuntimeError(
            "Live persona testing requires Playwright. "
            "Install with: pip install 'debuggai[live]' && playwright install chromium"
        )


# ── MCP-driven mode (free — Claude Code is the brain) ─────────


def start_session(url: str, persona_name: str, persona_description: str,
                  persona_tech_level: str, persona_goal: str,
                  viewport_width: int = 1280, viewport_height: int = 720) -> dict:
    """Start a live persona testing session. Returns initial page state.

    This opens a real browser and navigates to the URL.
    Call capture_page_state() to get screenshots for evaluation,
    then execute_persona_action() to interact.
    """
    global _active_session

    # Close any existing session first
    if _active_session:
        try:
            end_session()
        except Exception:
            _active_session = None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _start():
        pw_class = await _get_playwright()
        pw = await pw_class().start()
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height},
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            # Clean up on navigation failure
            await browser.close()
            await pw.stop()
            return {"error": f"Failed to load {url}: {e}"}

        return {"pw": pw, "browser": browser, "context": context, "page": page}

    try:
        result = loop.run_until_complete(_start())
    except Exception as e:
        loop.close()
        return {"error": f"Browser launch failed: {e}"}

    if "error" in result:
        loop.close()
        return {"error": result["error"]}

    _active_session = {
        "loop": loop,
        "pw": result["pw"],
        "browser": result["browser"],
        "context": result.get("context"),
        "page": result["page"],
        "persona": {
            "name": persona_name,
            "description": persona_description,
            "tech_level": persona_tech_level,
            "goal": persona_goal,
        },
        "url": url,
        "step_count": 0,
        "steps": [],
        "start_time": time.time(),
    }

    if "error" in result:
        return {"status": "error", "error": result["error"]}

    # Capture initial state
    return capture_page_state()


def capture_page_state() -> dict:
    """Capture current page state — screenshot (base64) + metadata.

    Returns the screenshot for Claude Code to evaluate as the persona.
    Claude Code then calls execute_persona_action() with the next action.
    """
    global _active_session
    if not _active_session:
        return {"error": "No active session. Call start_session first."}

    loop = _active_session["loop"]
    page = _active_session["page"]

    async def _capture():
        screenshot_bytes = await page.screenshot(type="png")
        title = await page.title()
        url = page.url

        # Get visible text for context
        try:
            visible_text = await page.evaluate("""
                () => {
                    const walker = document.createTreeWalker(
                        document.body, NodeFilter.SHOW_TEXT, null
                    );
                    const texts = [];
                    let node;
                    while (node = walker.nextNode()) {
                        const t = node.textContent.trim();
                        if (t.length > 2) texts.push(t);
                    }
                    return texts.slice(0, 50).join(' | ');
                }
            """)
        except Exception:
            visible_text = ""

        # Get interactive elements
        try:
            elements = await page.evaluate("""
                () => {
                    const els = [];
                    document.querySelectorAll('a, button, input, select, textarea, [role="button"], [onclick]').forEach(el => {
                        const text = (el.textContent || el.placeholder || el.ariaLabel || el.name || '').trim().slice(0, 50);
                        const tag = el.tagName.toLowerCase();
                        const type = el.type || '';
                        if (text || type) els.push(`${tag}${type ? '['+type+']' : ''}: "${text}"`);
                    });
                    return els.slice(0, 30);
                }
            """)
        except Exception:
            elements = []

        return {
            "screenshot_base64": base64.standard_b64encode(screenshot_bytes).decode(),
            "title": title,
            "url": url,
            "visible_text": visible_text[:1000],
            "interactive_elements": elements,
        }

    result = loop.run_until_complete(_capture())
    result["step"] = _active_session["step_count"] + 1
    result["persona"] = _active_session["persona"]
    result["status"] = "ok"

    return result


def execute_persona_action(
    action: str,
    target: str = "",
    feeling: str = "smooth",
    observation: str = "",
    friction: str | None = None,
    reasoning: str = "",
) -> dict:
    """Execute an action on the page and capture the result.

    Args:
        action: click | type | scroll | back | done | give_up
        target: What to click/type (element text, placeholder, or CSS selector)
        feeling: How the persona feels: smooth | confused | frustrated | lost
        observation: What the persona observed on the page
        friction: Description of any friction (or empty)
        reasoning: Why the persona chose this action
    """
    global _active_session
    if not _active_session:
        return {"error": "No active session."}

    loop = _active_session["loop"]
    page = _active_session["page"]

    # Record the step
    _active_session["step_count"] += 1
    step = ExperienceStep(
        step_num=_active_session["step_count"],
        url=page.url,
        page_title="",
        evaluation=StepEvaluation(
            observation=observation,
            feeling=feeling,
            friction=friction if friction else None,
            action=action,
            target=target,
            reasoning=reasoning,
        ),
    )

    async def _get_title():
        return await page.title()

    step.page_title = loop.run_until_complete(_get_title()) or "Untitled"
    _active_session["steps"].append(step)

    # Check terminal actions
    if action in ("done", "give_up"):
        return {"status": action, "step": step.step_num}

    # Execute the action
    async def _execute():
        if action == "click":
            strategies = [
                lambda: page.get_by_text(target, exact=False).first.click(timeout=5000),
                lambda: page.get_by_role("button", name=target).first.click(timeout=5000),
                lambda: page.get_by_role("link", name=target).first.click(timeout=5000),
                lambda: page.locator(f'[aria-label*="{target}" i]').first.click(timeout=5000),
                lambda: page.locator(f'[placeholder*="{target}" i]').first.click(timeout=5000),
            ]
            for strategy in strategies:
                try:
                    await strategy()
                    return True
                except Exception:
                    continue
            try:
                await page.locator(f'*:has-text("{target}")').first.click(timeout=3000)
                return True
            except Exception:
                return False

        elif action == "type":
            parts = target.split(" in ", 1)
            text = parts[0].strip().strip("\"'")
            field = parts[1].strip().strip("\"'") if len(parts) > 1 else ""
            if field:
                try:
                    await page.get_by_placeholder(field).first.fill(text, timeout=5000)
                    return True
                except Exception:
                    try:
                        await page.get_by_label(field).first.fill(text, timeout=5000)
                        return True
                    except Exception:
                        return False
            return False

        elif action == "scroll":
            await page.mouse.wheel(0, 400)
            await asyncio.sleep(0.5)
            return True

        elif action == "back":
            await page.go_back()
            return True

        return False

    success = loop.run_until_complete(_execute())

    # Wait for page to settle
    try:
        loop.run_until_complete(page.wait_for_load_state("networkidle", timeout=5000))
    except Exception:
        pass

    # Capture new state
    new_state = capture_page_state()
    new_state["action_success"] = success
    return new_state


def end_session() -> ExperienceReport:
    """End the persona testing session and return the experience report."""
    global _active_session
    if not _active_session:
        return ExperienceReport(
            persona_name="Unknown", persona_description="", goal="", url="",
        )

    loop = _active_session["loop"]
    persona = _active_session["persona"]

    # Close browser
    async def _close():
        try:
            await _active_session["browser"].close()
            await _active_session["pw"].stop()
        except Exception:
            pass

    loop.run_until_complete(_close())
    loop.close()  # Prevent event loop leak

    report = ExperienceReport(
        persona_name=persona["name"],
        persona_description=persona["description"],
        goal=persona["goal"],
        url=_active_session["url"],
        steps=_active_session["steps"],
        task_completed=any(s.evaluation.action == "done" for s in _active_session["steps"]),
        gave_up=any(s.evaluation.action == "give_up" for s in _active_session["steps"]),
        total_duration_ms=int((time.time() - _active_session["start_time"]) * 1000),
    )

    _active_session = None
    return report


# ── Autonomous mode (requires API key) ────────────────────────


async def run_persona_agent(
    url: str,
    persona: Persona,
    api_key: str,
    max_steps: int = MAX_STEPS,
    headless: bool = True,
) -> ExperienceReport:
    """Run the live persona agent autonomously (requires API key).

    For the free MCP-driven mode, use start_session/capture_page_state/
    execute_persona_action/end_session instead.
    """
    import anthropic

    pw_class = await _get_playwright()
    client = anthropic.Anthropic(api_key=api_key)

    report = ExperienceReport(
        persona_name=persona.name,
        persona_description=persona.description,
        goal=persona.goals[0] if persona.goals else "Explore the application",
        url=url,
    )

    start_time = time.time()

    async with pw_class() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            report.gave_up = True
            report.steps.append(ExperienceStep(
                step_num=1, url=url, page_title="Failed to load",
                evaluation=StepEvaluation(
                    observation=f"Page failed to load: {e}", feeling="lost",
                    friction=f"Site unreachable: {e}", action="give_up",
                ),
            ))
            await browser.close()
            return report

        previous_actions = []

        for step_num in range(1, max_steps + 1):
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode()
            title = await page.title()

            evaluation = _evaluate_step_autonomous(
                client, screenshot_b64, persona, step_num, title, page.url, previous_actions,
            )

            step = ExperienceStep(
                step_num=step_num, url=page.url, page_title=title or "Untitled",
                evaluation=evaluation,
            )
            report.steps.append(step)
            previous_actions.append(f"Step {step_num}: {evaluation.action} '{evaluation.target}' — {evaluation.feeling}")

            if evaluation.action == "give_up":
                report.gave_up = True
                break
            if evaluation.action == "done":
                report.task_completed = True
                break

            try:
                await _execute_action_autonomous(page, evaluation)
            except Exception as e:
                step.evaluation.friction = f"Action failed: {e}"
                step.evaluation.feeling = "frustrated"

            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        await browser.close()

    report.total_duration_ms = int((time.time() - start_time) * 1000)
    return report


def _evaluate_step_autonomous(client, screenshot_b64, persona, step_num, title, url, previous_actions):
    """Evaluate a step using Claude Vision (autonomous mode)."""
    history = "\n".join(previous_actions[-5:]) if previous_actions else "First step."

    try:
        response = client.messages.create(
            model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=512,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                {"type": "text", "text": f"""You are {persona.name} ({persona.tech_level}). Goal: {persona.goals[0] if persona.goals else "explore"}.
Page: {title} ({url}). Step {step_num}. Previous: {history}

As this persona, evaluate this page. Return JSON:
{{"observation":"what you see","feeling":"smooth|confused|frustrated|lost","friction":"issue or null","action":"click|type|scroll|back|done|give_up","target":"element","reasoning":"why"}}"""},
            ]}],
        )
        text = response.content[0].text
        if "```" in text:
            text = text.split("```json")[-1].split("```")[0] if "```json" in text else text.split("```")[1].split("```")[0]
        data = json.loads(text.strip())
        return StepEvaluation(**{k: data.get(k) for k in StepEvaluation.__dataclass_fields__})
    except Exception as e:
        return StepEvaluation(observation="Evaluation failed", feeling="confused", action="scroll", reasoning=str(e))


async def _execute_action_autonomous(page, evaluation):
    """Execute action in autonomous mode."""
    if evaluation.action == "click":
        for strategy in [
            lambda: page.get_by_text(evaluation.target, exact=False).first.click(timeout=5000),
            lambda: page.get_by_role("button", name=evaluation.target).first.click(timeout=5000),
            lambda: page.get_by_role("link", name=evaluation.target).first.click(timeout=5000),
        ]:
            try:
                await strategy()
                return
            except Exception:
                continue
    elif evaluation.action == "scroll":
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(0.5)
    elif evaluation.action == "back":
        await page.go_back()


def run_persona_agent_sync(url, persona, api_key, max_steps=MAX_STEPS, headless=True):
    """Synchronous wrapper for autonomous mode."""
    return asyncio.run(run_persona_agent(url, persona, api_key, max_steps, headless))
