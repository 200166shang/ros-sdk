"""Terminal interaction for the Conan CI access provisioning flow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt


class ConsoleUi:
    """Collect values and show decisions without owning provisioning state."""

    def __init__(self, environment_file: Path, stage_count: int = 7) -> None:
        self.environment_file = environment_file
        self.stage_count = stage_count
        self._stage_number = 0
        self.console = Console()

    def banner(self) -> None:
        self.console.print(
            Panel(
                "You drive the browser; this wizard tells you exactly what to do and\n"
                "captures the values you copy back. Stop any time with Ctrl-C and re-run\n"
                "later, since it remembers values already saved.",
                title="Restricted Conan CI access",
            )
        )
        self.pause("Ready to start?")

    def stage(self, title: str) -> None:
        self._stage_number += 1
        self.console.rule(f"Stage {self._stage_number}/{self.stage_count} · {title}")

    def say(self, message: str) -> None:
        self.console.print(f"  {message}", markup=False)

    def step(self, message: str) -> None:
        self.console.print(f"  • {message}", markup=False)

    def note(self, message: str) -> None:
        self.console.print(f"  {message}", markup=False)

    def warn(self, message: str) -> None:
        self.console.print(f"  ⚠ {message}", style="yellow", markup=False)

    def pause(self, message: str = "Press Enter to continue") -> None:
        Prompt.ask(f"  {message}", default="", show_default=False)

    def confirm(self, question: str) -> bool:
        return Confirm.ask(f"  {question}", default=False)

    def ask(self, key: str, prompt: str) -> str:
        current = self._existing(key)
        suffix = " [Enter keeps current]" if current else ""
        return Prompt.ask(f"  {prompt}{suffix}", default=current, show_default=False)

    def ask_default(self, prompt: str, default: str) -> str:
        return Prompt.ask(f"  {prompt}", default=default)

    def show_file(self, path: Path) -> None:
        for line in path.read_text(encoding="utf-8").splitlines():
            self.console.print(f"  {line}", markup=False)

    def finish(self, artifacts: Any, environment_file: Path) -> None:
        self.console.print("\n[green]✓ Setup complete[/green]")
        if artifacts.written_secrets:
            self.note(
                f"set {len(artifacts.written_secrets)} GitHub secret(s): "
                f"{' '.join(artifacts.written_secrets)}"
            )
        self.note(
            f"Temporary files will be deleted; no credentials were written to {environment_file}."
        )

    def _existing(self, key: str) -> str:
        if not self.environment_file.exists():
            return ""
        prefix = f"{key}="
        values = [
            line[len(prefix):]
            for line in self.environment_file.read_text(encoding="utf-8").splitlines()
            if line.startswith(prefix)
        ]
        return values[-1] if values else ""
