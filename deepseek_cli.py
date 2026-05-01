##########
import re#
import os#
import sys##
import json####
import difflib##
import requests###
import subprocess######
from rich import print ##
from pathlib import Path###
from rich.text import Text###
from rich.panel import Panel##
from typing import List, Dict####
from rich.console import Console########
from rich.prompt import Prompt, Confirm##
from dataclasses import dataclass, field#
#########################################

API_BASE = "https://api.deepseek.com/v1"
#EDITABLE MODEL
MODEL = "deepseek-chat"

#Talking
@dataclass
class Conversation:
    messages: List[Dict[str, str]] = field(default_factory=list)

    def add(self, role, content):
        self.messages.append({"role": role, "content": content})

    def context(self):
        return self.messages[-75:]

#CLI

class AgentCLI:
    def __init__(self):
        self.console = Console()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.allowed_dir = Path.cwd().resolve()
        self.convo = Conversation()

        if not self.api_key:
            self.console.print("[red]Missing API key[/red]")
            sys.exit(1)

#Security stuff

    def safe_path(self, path: Path):
        return str(path.resolve()).startswith(str(self.allowed_dir))

#File tool stuff

    def read_file(self, path):
        p = (self.allowed_dir / path).resolve()

        if not self.safe_path(p):
            return "Access denied"
        if not p.exists():
            return "File not found"

        return p.read_text()

    def write_file(self, path, content):
        p = (self.allowed_dir / path).resolve()

        if not self.safe_path(p):
            return "Access denied"

        old = p.read_text() if p.exists() else ""

        self.show_diff(old, content)

        if not Confirm.ask(f"Apply changes to {p}?"):
            return "Cancelled"

        p.write_text(content)
        return "File updated"

    def show_diff(self, old, new):
        diff = difflib.ndiff(old.splitlines(), new.splitlines())
        text = Text()

        for line in diff:
            if line.startswith("+ "):
                text.append(line + "\n", style="green")
            elif line.startswith("- "):
                text.append(line + "\n", style="red")
            else:
                text.append(line + "\n", style="dim")

        self.console.print(Panel(text, title="Diff"))

# Terminal stuff

    def run_cmd(self, cmd):
        if not Confirm.ask(f"Run: {cmd}?"):
            return "Cancelled"

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.allowed_dir,
                capture_output=True,
                text=True,
                timeout=30
            )

            out = ""
            if result.stdout:
                out += f"[STDOUT]\n{result.stdout}\n"
            if result.stderr:
                out += f"[STDERR]\n{result.stderr}\n"

            return out or "[No output]"

        except Exception as e:
            return str(e)

#JSON

    def extract_json(self, text: str):
        match = re.search(r"\{.*\}", text, re.DOTALL)
        return match.group(0) if match else text

    def safe_json(self, raw: str):
        try:
            return json.loads(raw)
        except:
            try:
                return json.loads(self.extract_json(raw))
            except:
                return None

#Output formatting

    def force_bullets(self, text: str) -> str:
        """
        Ensures explanation responses are readable bullet points
        """
        if not text:
            return text

        # already formatted
        if "-" in text[:40] or "•" in text:
            return text

        sentences = re.split(r"\.\s+", text.strip())
        bullets = [f"- {s.strip()}" for s in sentences if s.strip()]

        return "\n".join(bullets)

#Agent settings

    def call_ai(self):
        system = {
            "role": "system",
            "content": """
You are a CLI AI agent.

RULES:
- Output ONLY valid JSON
- NEVER add explanations outside JSON
- "action" must always be an object

IMPORTANT OUTPUT STYLE RULE:
If action.type = "respond" AND the user is explaining code/file:

You MUST format the response content as bullet points:
- Short lines
- No long paragraphs
- Group ideas

FORMAT:

{
  "plan": ["step1", "step2"],
  "action": {
    "type": "read_file | edit_file | run | respond",
    "path": "...",
    "command": "...",
    "content": "..."
  }
}
"""
        }

        try:
            res = requests.post(
                f"{API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": MODEL,
                    "messages": [system] + self.convo.context(),
                },
                timeout=60
            )

            if res.status_code != 200:
                return None

            return res.json()["choices"][0]["message"]["content"]

        except Exception as e:
            self.console.print(f"[red]{e}[/red]")
            return None

#Agent loop

    def run_agent(self, user_input):
        self.convo.add("user", user_input)

        for step in range(5):
            raw = self.call_ai()
            if not raw:
                return

            data = self.safe_json(raw)

            if not data:
                self.console.print("[yellow]Invalid JSON, retrying...[/yellow]")
                self.convo.add("assistant", "Fix JSON format")
                continue

            action = data.get("action", {})
            if isinstance(action, str):
                action = {"type": action}

            t = action.get("type")

            # show plan
            self.console.print("\n[cyan]Plan:[/cyan]")
            for p in data.get("plan", []):
                self.console.print(f"- {p}")

#Actions

            if t == "respond":
                content = action.get("content", "")

                formatted = self.force_bullets(content)

                self.console.print(
                    Panel(formatted, title="Response", border_style="cyan")
                )
                return

            elif t == "read_file":
                result = self.read_file(action.get("path", ""))

            elif t == "edit_file":
                result = self.write_file(
                    action.get("path", ""),
                    action.get("content", "")
                )

            elif t == "run":
                result = self.run_cmd(action.get("command", ""))

            else:
                result = "Unknown action"

            self.console.print(Panel(str(result)[:2000], title=f"Step {step+1}"))

            self.convo.add("assistant", raw)
            self.convo.add("user", f"Result:\n{result}")

  #Run the CLI

    def run(self):
        self.console.print(f"[green]Current directory: {self.allowed_dir}[/green]")

        while True:
            try:
                print("[cyan] Welcome to a self made DeepSeek CLI! [/cyan]")
                user_input = Prompt.ask("[cyan]Your input[/cyan]")
                self.run_agent(user_input)
            except KeyboardInterrupt:
                break


#Startup and actually run it
if __name__ == "__main__":
    AgentCLI().run()