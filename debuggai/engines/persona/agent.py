"""Live persona browser agent — navigates a website as a specific persona.

Uses Playwright to control a real browser and Claude Vision to evaluate
each step from the persona's perspective.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Optional

import anthropic

from debuggai.engines.persona.discover import Persona
from debuggai.engines.persona.experience import (
    ExperienceReport,
    ExperienceStep,
    StepEvaluation,
)

logger = logging.getLogger("debuggai")

MAX_STEPS = 15


async def run_persona_agent(
    url: str,
    persona: Persona,
    api_key: str,
    max_steps: int = MAX_STEPS,
    headless: bool = True,
) -> ExperienceReport:
    """Run the live persona agent on a URL.

    Opens a browser, navigates as the persona, evaluates each step
    with Claude Vision, and returns an experience report.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError(
            "Live persona testing requires Playwright. "
            "Install with: pip install 'debuggai[live]' && playwright install chromium"
        )

    client = anthropic.Anthropic(api_key=api_key)
    report = ExperienceReport(
        persona_name=persona.name,
        persona_description=persona.description,
        goal=persona.goals[0] if persona.goals else "Explore the application",
        url=url,
    )

    start_time = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) DebuggAI-PersonaAgent/1.0",
        )
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            logger.warning("DebuggAI: Failed to load %s: %s", url, e)
            report.gave_up = True
            report.steps.append(ExperienceStep(
                step_num=1, url=url, page_title="Failed to load",
                evaluation=StepEvaluation(
                    observation=f"Page failed to load: {e}",
                    feeling="lost",
                    friction=f"Site unreachable or timed out: {e}",
                    action="give_up",
                ),
            ))
            await browser.close()
            return report

        previous_actions = []

        for step_num in range(1, max_steps + 1):
            step_start = time.time()

            # Capture screenshot
            screenshot_bytes = await page.screenshot(type="png")
            screenshot_b64 = base64.standard_b64encode(screenshot_bytes).decode()

            # Get page info
            title = await page.title()
            current_url = page.url

            # Evaluate with Claude Vision
            evaluation = _evaluate_step(
                client=client,
                screenshot_b64=screenshot_b64,
                persona=persona,
                step_num=step_num,
                page_title=title,
                current_url=current_url,
                previous_actions=previous_actions,
            )

            step = ExperienceStep(
                step_num=step_num,
                url=current_url,
                page_title=title or "Untitled",
                evaluation=evaluation,
                duration_ms=int((time.time() - step_start) * 1000),
            )
            report.steps.append(step)
            previous_actions.append(f"Step {step_num}: {evaluation.action} '{evaluation.target}' — {evaluation.feeling}")

            # Check if persona gives up
            if evaluation.action == "give_up":
                report.gave_up = True
                break

            # Check if task is complete
            if evaluation.action == "done":
                report.task_completed = True
                break

            # Execute the action
            try:
                await _execute_action(page, evaluation)
            except Exception as e:
                logger.warning("DebuggAI: Action failed at step %d: %s", step_num, e)
                step.evaluation.friction = f"Action failed: {e}"
                step.evaluation.feeling = "frustrated"

            # Wait for page to settle
            try:
                await page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass  # Page might not have network activity

        await browser.close()

    report.total_duration_ms = int((time.time() - start_time) * 1000)

    # If we exhausted all steps without completing, mark as incomplete
    if not report.task_completed and not report.gave_up:
        report.task_completed = False

    return report


def _evaluate_step(
    client: anthropic.Anthropic,
    screenshot_b64: str,
    persona: Persona,
    step_num: int,
    page_title: str,
    current_url: str,
    previous_actions: list[str],
) -> StepEvaluation:
    """Send screenshot to Claude Vision for persona-based evaluation."""
    history = "\n".join(previous_actions[-5:]) if previous_actions else "This is the first step."

    prompt = f"""You are role-playing as this persona using a website:

Name: {persona.name}
Tech level: {persona.tech_level}
Goal: {persona.goals[0] if persona.goals else "Explore the application"}
Description: {persona.description}
Pain points: {', '.join(persona.pain_points[:3]) if persona.pain_points else 'None specified'}

Current page: {page_title} ({current_url})
Step: {step_num}

Previous actions:
{history}

Look at this screenshot. As this persona:

1. What do you see on this page? Describe briefly.
2. How does this feel? (smooth = clear and easy, confused = not sure what to do, frustrated = something is wrong or annoying, lost = completely stuck)
3. Is there any friction? (something confusing, missing, unclear, slow, or annoying — from THIS persona's perspective)
4. What would you do next? Pick ONE action:
   - click: click on a specific element (describe it)
   - type: type text into a field (specify field and text)
   - scroll: scroll down to see more
   - back: go back (confused, trying something else)
   - done: task is complete, you accomplished your goal
   - give_up: you're too frustrated/lost to continue

Return ONLY a JSON object:
{{
  "observation": "what you see",
  "feeling": "smooth|confused|frustrated|lost",
  "friction": "description of friction or null",
  "action": "click|type|scroll|back|done|give_up",
  "target": "what to click/type in (CSS-like description or visible text)",
  "reasoning": "why you chose this action as this persona"
}}"""

    try:
        response = client.messages.create(
            model=os.environ.get("DEBUGGAI_MODEL", "claude-sonnet-4-20250514"),
            max_tokens=512,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": screenshot_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )

        text = response.content[0].text
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        data = json.loads(text.strip())
        return StepEvaluation(
            observation=data.get("observation", ""),
            feeling=data.get("feeling", "confused"),
            friction=data.get("friction"),
            action=data.get("action", "scroll"),
            target=data.get("target", ""),
            reasoning=data.get("reasoning", ""),
        )

    except (anthropic.APIError, json.JSONDecodeError) as e:
        logger.warning("DebuggAI: Vision evaluation failed: %s", e)
        return StepEvaluation(
            observation="Could not evaluate this step",
            feeling="confused",
            action="scroll",
            reasoning=f"Evaluation failed: {e}",
        )


async def _execute_action(page, evaluation: StepEvaluation) -> None:
    """Execute the persona's chosen action on the page."""
    action = evaluation.action
    target = evaluation.target

    if action == "click":
        # Try multiple strategies to find the element
        clicked = False
        strategies = [
            lambda: page.get_by_text(target, exact=False).first.click(timeout=5000),
            lambda: page.get_by_role("button", name=target).first.click(timeout=5000),
            lambda: page.get_by_role("link", name=target).first.click(timeout=5000),
            lambda: page.locator(f'text="{target}"').first.click(timeout=5000),
            lambda: page.locator(f'[aria-label*="{target}" i]').first.click(timeout=5000),
            lambda: page.locator(f'[placeholder*="{target}" i]').first.click(timeout=5000),
        ]
        for strategy in strategies:
            try:
                await strategy()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            # Fallback: try clicking by partial text match
            try:
                await page.locator(f'*:has-text("{target}")').first.click(timeout=3000)
            except Exception:
                logger.debug("DebuggAI: Could not click '%s'", target)

    elif action == "type":
        # Parse "text" in "field" pattern
        parts = target.split(" in ", 1)
        text_to_type = parts[0].strip().strip('"\'')
        field = parts[1].strip().strip('"\'') if len(parts) > 1 else ""

        if field:
            try:
                await page.get_by_placeholder(field).first.fill(text_to_type, timeout=5000)
            except Exception:
                try:
                    await page.get_by_label(field).first.fill(text_to_type, timeout=5000)
                except Exception:
                    logger.debug("DebuggAI: Could not type in '%s'", field)
        else:
            try:
                focused = page.locator(":focus")
                await focused.fill(text_to_type, timeout=3000)
            except Exception:
                pass

    elif action == "scroll":
        await page.mouse.wheel(0, 400)
        await asyncio.sleep(0.5)

    elif action == "back":
        await page.go_back()


def run_persona_agent_sync(
    url: str,
    persona: Persona,
    api_key: str,
    max_steps: int = MAX_STEPS,
    headless: bool = True,
) -> ExperienceReport:
    """Synchronous wrapper for the async agent."""
    return asyncio.run(run_persona_agent(url, persona, api_key, max_steps, headless))
