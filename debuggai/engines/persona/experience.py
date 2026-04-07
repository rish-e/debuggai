"""Experience report models and formatting for live persona testing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StepEvaluation:
    """Claude Vision's evaluation of a single step."""
    observation: str = ""
    feeling: str = "smooth"  # smooth | confused | frustrated | lost
    friction: Optional[str] = None
    action: str = "click"  # click | type | scroll | back | give_up
    target: str = ""
    reasoning: str = ""


@dataclass
class ExperienceStep:
    """A single step in the persona's journey."""
    step_num: int
    url: str
    page_title: str = ""
    evaluation: StepEvaluation = field(default_factory=StepEvaluation)
    screenshot_path: Optional[str] = None
    duration_ms: int = 0


@dataclass
class ExperienceReport:
    """Complete experience report from a persona's journey."""
    persona_name: str
    persona_description: str
    goal: str
    url: str
    steps: list[ExperienceStep] = field(default_factory=list)
    task_completed: bool = False
    gave_up: bool = False
    total_duration_ms: int = 0

    @property
    def experience_score(self) -> int:
        """0-100 score based on friction vs smooth steps."""
        if not self.steps:
            return 0
        feeling_scores = {"smooth": 100, "confused": 50, "frustrated": 20, "lost": 0}
        total = sum(feeling_scores.get(s.evaluation.feeling, 50) for s in self.steps)
        score = total // len(self.steps)
        if self.gave_up:
            score = min(score, 30)
        if not self.task_completed:
            score = int(score * 0.7)
        return score

    @property
    def friction_count(self) -> int:
        return sum(1 for s in self.steps if s.evaluation.friction)

    @property
    def smooth_count(self) -> int:
        return sum(1 for s in self.steps if s.evaluation.feeling == "smooth")

    def format_terminal(self) -> str:
        """Format for Rich terminal output."""
        lines = []
        score = self.experience_score
        score_color = "green" if score >= 70 else "yellow" if score >= 40 else "red"

        lines.append("")
        lines.append("[bold]DebuggAI Experience Report[/bold]")
        lines.append(f"[dim]Persona:[/dim] {self.persona_name} — {self.persona_description}")
        lines.append(f"[dim]Goal:[/dim] {self.goal}")
        lines.append(f"[dim]URL:[/dim] {self.url}")
        lines.append(f"[dim]Steps:[/dim] {len(self.steps)} | "
                      f"Task: {'completed' if self.task_completed else 'incomplete'} | "
                      f"Gave up: {'yes' if self.gave_up else 'no'}")
        lines.append(f"[bold]Experience Score:[/bold] [{score_color}]{score}/100[/{score_color}]")
        lines.append("")

        # Journey
        lines.append("[bold]Journey[/bold]")
        for step in self.steps:
            e = step.evaluation
            feeling_icon = {
                "smooth": "[green]smooth[/green]",
                "confused": "[yellow]confused[/yellow]",
                "frustrated": "[red]frustrated[/red]",
                "lost": "[bold red]lost[/bold red]",
            }.get(e.feeling, e.feeling)

            dots = "." * max(1, 50 - len(f"Step {step.step_num}: {step.page_title}"))
            lines.append(f"  Step {step.step_num}: {step.page_title} {dots} {feeling_icon}")
            lines.append(f"    [dim]{e.observation}[/dim]")
            if e.friction:
                lines.append(f"    [yellow]FRICTION:[/yellow] {e.friction}")
            lines.append("")

        # Summary
        lines.append("[bold]Summary[/bold]")
        lines.append(f"  Smooth: {self.smooth_count}/{len(self.steps)} steps")
        lines.append(f"  Friction points: {self.friction_count}")
        lines.append("")

        # Top improvements
        frictions = [s.evaluation.friction for s in self.steps if s.evaluation.friction]
        if frictions:
            lines.append("[bold]Top Improvements[/bold]")
            for i, f in enumerate(frictions[:5], 1):
                lines.append(f"  {i}. {f}")
            lines.append("")

        return "\n".join(lines)

    def format_markdown(self) -> str:
        """Format as Markdown."""
        lines = []
        score = self.experience_score

        lines.append(f"# DebuggAI Experience Report")
        lines.append(f"**Persona:** {self.persona_name} — {self.persona_description}")
        lines.append(f"**Goal:** {self.goal}")
        lines.append(f"**URL:** {self.url}")
        lines.append(f"**Steps:** {len(self.steps)} | "
                      f"Task: {'completed' if self.task_completed else 'incomplete'} | "
                      f"Gave up: {'yes' if self.gave_up else 'no'}")
        lines.append(f"**Experience Score:** {score}/100")
        lines.append("")

        lines.append("## Journey")
        for step in self.steps:
            e = step.evaluation
            icon = {"smooth": "+", "confused": "~", "frustrated": "!", "lost": "x"}.get(e.feeling, "?")
            lines.append(f"### Step {step.step_num}: {step.page_title} [{icon}] {e.feeling}")
            lines.append(f"> {e.observation}")
            if e.friction:
                lines.append(f"> **FRICTION:** {e.friction}")
            lines.append("")

        frictions = [s.evaluation.friction for s in self.steps if s.evaluation.friction]
        if frictions:
            lines.append("## Top Improvements")
            for i, f in enumerate(frictions[:5], 1):
                lines.append(f"{i}. {f}")

        return "\n".join(lines)
