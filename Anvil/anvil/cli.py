"""Anvil CLI - command line interface."""

import os
import json
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .agent import DesignAgent
from .project.manager import ProjectManager

console = Console()

DEFAULT_PROJECT_DIR = os.path.expanduser("~/develop/elderly-care-robot/DesignTool/Anvil/projects")


@click.group()
@click.version_option(version="0.1.0")
def main():
    """Anvil - AI Mechanical Design Tool"""
    pass


@main.command()
@click.argument("name")
@click.option("--dir", "-d", default=None)
def new(name, dir=None):
    """Create a new design project."""
    project_dir = dir or os.path.join(DEFAULT_PROJECT_DIR, name)
    if os.path.exists(project_dir):
        console.print("[yellow]Project already exists[/yellow]")
        if not click.confirm("Continue?"):
            return
    ProjectManager.create(project_dir, name)
    console.print(Panel("[green]Created![/green] " + project_dir, title="Anvil", border_style="green"))


@main.command()
@click.option("--dir", "-d", default=None)
def chat(dir=None):
    """Start interactive design chat."""
    project_dir = dir or _find_project()
    if not project_dir:
        console.print("[red]No project found. Run: anvil new <name>[/red]")
        return
    agent = DesignAgent(project_dir)
    config = agent.project.get_config()
    console.print(Panel("Project: " + config["name"] + "\n/help for commands", title="Anvil", border_style="blue"))
    while True:
        try:
            user_input = Prompt.ask("\n[bold blue]Design[/bold blue]")
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input.strip():
            continue
        cmd = user_input.strip()
        if cmd in ("/quit", "/exit", "/q"):
            break
        elif cmd == "/help":
            console.print(Markdown("## Commands\n- /help\n- /quit\n- /status\n- /docs"))
            continue
        elif cmd == "/status":
            console.print(Panel(agent.get_status(), title="Status"))
            continue
        with console.status("[green]Thinking...[/green]"):
            result = agent.chat(user_input)
        try:
            data = json.loads(result)
            response = data.get("text", result)
            files = data.get("files", [])
            if files:
                response += "\n\n---\n**生成的文件:**\n"
                for f in files:
                    response += "- " + f.split("/")[-1] + "\n"
        except json.JSONDecodeError:
            response = result
        console.print(Markdown(response))


@main.command()
@click.option("--dir", "-d", default=None)
def status(dir=None):
    """Show project status."""
    project_dir = dir or _find_project()
    if not project_dir:
        console.print("[red]No project found.[/red]")
        return
    agent = DesignAgent(project_dir)
    console.print(Panel(agent.get_status(), title="Status"))


def _find_project():
    current = os.getcwd()
    while current != "/":
        if os.path.exists(os.path.join(current, ".anvil.json")):
            return current
        current = os.path.dirname(current)
    return None


if __name__ == "__main__":
    main()
