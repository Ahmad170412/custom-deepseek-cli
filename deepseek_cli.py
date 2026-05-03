#########
import re#
import os#
import sys##
import json###
import difflib##
import requests###
import subprocess#####
from rich import print###
from pathlib import Path##
from rich.text import Text###
from rich.panel import Panel#####
from rich.console import Console########
from rich.prompt import Prompt, Confirm#
########################################
API_BASE = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


class AgentCLI:
    def __init__(self):
        self.console = Console()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.allowed_dir = Path.cwd().resolve()

        if not self.api_key:
            self.console.print("[red]Missing API key[/red]")
            sys.exit(1)

    # Security
    def safe_path(self, path: Path):
        return str(path.resolve()).startswith(str(self.allowed_dir))

    # File tools
    def read_file(self, path):
        p = (self.allowed_dir / path).resolve()

        if not self.safe_path(p):
            return "Access denied"
        if not p.exists():
            return "File not found"

        try:
            return p.read_text()
        except Exception as e:
            return f"Error reading file: {e}"

    def write_file(self, path, content):
        p = (self.allowed_dir / path).resolve()

        if not self.safe_path(p):
            return "Access denied"

        try:
            old = p.read_text() if p.exists() else ""
            self.show_diff(old, content)

            if not Confirm.ask(f"Apply changes to {p}?"):
                return "Cancelled"

            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return "File updated"

        except Exception as e:
            return f"Error: {e}"

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

    # Terminal
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
                timeout=60
            )

            out = ""
            if result.stdout:
                out += f"[STDOUT]\n{result.stdout}\n"
            if result.stderr:
                out += f"[STDERR]\n{result.stderr}\n"

            return out or "[No output]"

        except subprocess.TimeoutExpired:
            return "Command timed out after 60 seconds"
        except Exception as e:
            return f"Error: {e}"

    # JSON parsing
    def safe_json(self, raw: str):
        try:
            return json.loads(raw)
        except:
            pass

        try:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(raw.lstrip())
            return obj
        except:
            pass

        try:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except:
            pass

        try:
            start = raw.find('{')
            if start != -1:
                depth = 0
                for i, char in enumerate(raw[start:], start):
                    if char == '{':
                        depth += 1
                    elif char == '}':
                        depth -= 1
                        if depth == 0:
                            return json.loads(raw[start:i+1])
        except:
            pass

        self.console.print(f"[yellow]Could not parse JSON[/yellow]")
        return None

    # AI call (NO MEMORY)
    def call_ai(self, user_input):
        system = {
            "role": "system",
            "content": """
You are James, a CLI AI agent.
You are optimistic and occasionally sarcastic.

RULES:
- Output ONLY valid JSON
- "action" must always be an object

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
                    "messages": [system, {"role": "user", "content": user_input}],
                },
                timeout=60
            )

            if res.status_code != 200:
                self.console.print(f"[red]API Error {res.status_code}[/red]")
                return None

            return res.json()["choices"][0]["message"]["content"]

        except Exception as e:
            self.console.print(f"[red]API call failed: {e}[/red]")
            return None

    # Agent loop
    def run_agent(self, user_input):
        max_steps = 6

        for step in range(max_steps):
            raw = self.call_ai(user_input)
            if not raw:
                return

            data = self.safe_json(raw)
            if not data:
                return

            action = data.get("action", {})
            t = action.get("type")

            if t == "respond":
                content = action.get("content", "")
                self.console.print(Panel(content, title="Response", border_style="cyan"))
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
                result = f"Unknown action: {t}"

            self.console.print(Panel(str(result), title=f"Step {step+1}", border_style="green"))

            # feed result into next iteration
            user_input = f"Result:\n{result}"

    # Slash commands (simplified)
    def handle_slash_command(self, cmd: str):
        global MODEL

        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            self.console.print("[cyan]/help, /model, /status, /exit[/cyan]")

        elif command == "/model":
            if args:
                MODEL = args.strip()
                self.console.print(f"[green]Switched to {MODEL}[/green]")
            else:
                self.console.print(f"[yellow]{MODEL}[/yellow]")

        elif command == "/status":
            self.console.print(f"Model: {MODEL}\nDir: {self.allowed_dir}")

        elif command in ("/exit", "/quit"):
            sys.exit(0)

        else:
            self.console.print("[red]Unknown command[/red]")

    def run(self):
        self.console.print("[cyan]=[/cyan]" * 30)
        self.console.print("[cyan]        DeepSeek CLI [/cyan]")
        self.console.print("[cyan]=[/cyan]" * 30)
        while True:
            try:
                user_input = Prompt.ask("\n[cyan]›[/cyan]")

                if not user_input.strip():
                    continue

                if user_input.startswith("/"):
                    self.handle_slash_command(user_input)
                    continue

                self.run_agent(user_input)

            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    AgentCLI().run()
