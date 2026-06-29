#!/usr/bin/env python3
"""mini agent - single-file, cross-platform tool-calling harness (Anthropic or OpenAI).

Optimised to run from PowerShell on Windows; also works on macOS/Linux.

Quick start (PowerShell):
    pip install --user anthropic         # or: pip install --user openai
    $env:ANTHROPIC_API_KEY = "sk-ant-..."    # or: $env:OPENAI_API_KEY = "sk-..."
    python 007.py                         # auto-picks the provider whose key is set
    python 007.py --provider openai       # or force one

Tools: read_file, write_file, run_shell, browser_* (Playwright web browsing),
and native web search on Anthropic. write_file, run_shell, browser_click and
browser_type ask for [y/N] confirmation first.
Quit with Ctrl-Z then Enter (Windows) or Ctrl-D (macOS/Linux).
"""

import argparse
import atexit
import json
import os
import platform
import shutil
import subprocess
import sys

# Force UTF-8 on the console so non-ASCII output (e.g. Spanish accents) never
# raises UnicodeEncodeError under Windows PowerShell / cmd.
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

IS_WINDOWS = platform.system() == "Windows"
SHELL_NAME = "PowerShell" if IS_WINDOWS else "bash"
WORKDIR = os.getcwd()

BROWSER_HEADLESS = True    # set False to watch the Playwright browser window
PAGE_TEXT_LIMIT = 6000     # max chars of page text returned to the model

ANTHROPIC_MODEL = "claude-opus-4-8"    # or claude-sonnet-4-6 / claude-haiku-4-5
OPENAI_MODEL = "gpt-4o"                # or gpt-4.1 / o4-mini - whatever your key has

SYSTEM = (
    "You are a helpful work assistant running on the user's laptop. "
    "Use the tools to read/write files, run {} commands, and browse the web with "
    "a real browser (browser_navigate / browser_read / browser_click / browser_type). "
    "Be concise. Prefer doing the work over describing it."
).format(SHELL_NAME)


# --------------------------------------------------------------------------- #
# Tools (provider-neutral specs + local execution)
# --------------------------------------------------------------------------- #

TOOL_SPECS = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file and return its contents.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a UTF-8 text file with the given content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run a {} command in the working directory; returns stdout+stderr.".format(SHELL_NAME),
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "browser_navigate",
        "description": "Open a URL in a real browser; returns the page URL, title and visible text.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL, e.g. https://example.com"}},
            "required": ["url"],
        },
    },
    {
        "name": "browser_read",
        "description": "Re-read the current browser page (URL, title and visible text) after an action.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_click",
        "description": "Click an element on the current page by visible text or CSS selector; returns the resulting page.",
        "parameters": {
            "type": "object",
            "properties": {"target": {"type": "string", "description": "Visible link/button text, or a CSS selector"}},
            "required": ["target"],
        },
    },
    {
        "name": "browser_type",
        "description": "Type text into an input (by CSS selector) on the current page, optionally pressing Enter to submit.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "CSS selector of the input, e.g. input[name='q']"},
                "text": {"type": "string"},
                "enter": {"type": "boolean", "description": "Press Enter after typing (submit the form)"},
            },
            "required": ["selector", "text"],
        },
    },
]


def confirm(action):
    return input("\n[confirm] {} ? [y/N] ".format(action)).strip().lower() == "y"


def _run_shell(command):
    if IS_WINDOWS:
        exe = shutil.which("pwsh") or shutil.which("powershell")
        if not exe:
            return "Error: no PowerShell (pwsh/powershell) found on PATH."
        argv = [exe, "-NoProfile", "-NonInteractive", "-Command", command]
        out = subprocess.run(
            argv, cwd=WORKDIR, capture_output=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    else:
        out = subprocess.run(
            command, shell=True, cwd=WORKDIR, capture_output=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
    return (out.stdout + out.stderr) or "(no output)"


# --- Browser automation (Playwright) --------------------------------------- #
# Lazily started on first use; one persistent browser + page per session.
_BROWSER = {"pw": None, "browser": None, "page": None}


def _get_page():
    if _BROWSER["page"] is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install --user playwright "
                "&& python -m playwright install chromium"
            )
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=BROWSER_HEADLESS)
        _BROWSER.update(pw=pw, browser=browser, page=browser.new_page())
    return _BROWSER["page"]


def _page_summary(page):
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        text = page.inner_text("body").strip()
    except Exception:
        text = ""
    if len(text) > PAGE_TEXT_LIMIT:
        text = text[:PAGE_TEXT_LIMIT] + "\n... [truncated]"
    return "URL: {}\nTitle: {}\n\n{}".format(page.url, title, text)


def _close_browser():
    for key in ("browser", "pw"):
        obj = _BROWSER[key]
        if obj is None:
            continue
        try:
            obj.close() if key == "browser" else obj.stop()
        except Exception:
            pass
    _BROWSER.update(pw=None, browser=None, page=None)


atexit.register(_close_browser)


def execute_tool(name, tool_input):
    """Run a client-side tool and return a string result (never raises)."""
    try:
        if name == "read_file":
            with open(tool_input["path"], "r", encoding="utf-8") as f:
                return f.read()
        if name == "write_file":
            if not confirm("write file " + tool_input["path"]):
                return "User declined the write."
            with open(tool_input["path"], "w", encoding="utf-8") as f:
                f.write(tool_input["content"])
            return "Wrote {} bytes to {}".format(
                len(tool_input["content"]), tool_input["path"]
            )
        if name == "run_shell":
            cmd = tool_input["command"]
            if not confirm("run: " + cmd):
                return "User declined the command."
            return _run_shell(cmd)
        if name == "browser_navigate":
            page = _get_page()
            page.goto(tool_input["url"], wait_until="domcontentloaded", timeout=30000)
            return _page_summary(page)
        if name == "browser_read":
            if _BROWSER["page"] is None:
                return "No page open yet - use browser_navigate first."
            return _page_summary(_BROWSER["page"])
        if name == "browser_click":
            target = tool_input["target"]
            if not confirm("click '{}'".format(target)):
                return "User declined the click."
            page = _get_page()
            try:
                page.get_by_text(target, exact=False).first.click(timeout=8000)
            except Exception:
                page.click(target, timeout=8000)          # fall back to CSS selector
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            return _page_summary(page)
        if name == "browser_type":
            sel, txt = tool_input["selector"], tool_input["text"]
            submit = bool(tool_input.get("enter"))
            if not confirm("type into {}{}".format(sel, " and submit" if submit else "")):
                return "User declined the input."
            page = _get_page()
            page.fill(sel, txt, timeout=8000)
            if submit:
                page.press(sel, "Enter")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            return _page_summary(page)
        return "Unknown tool: " + name
    except Exception as e:                      # return errors to the model, don't crash
        return "Error: {}".format(e)


# --------------------------------------------------------------------------- #
# Anthropic provider
# --------------------------------------------------------------------------- #

ANTHROPIC_TOOLS = [
    {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
    for s in TOOL_SPECS
]
# Server-side web search - executed by Anthropic, no local handler needed.
ANTHROPIC_TOOLS.append({"type": "web_search_20260209", "name": "web_search"})


def run_anthropic(client, messages, model):
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            thinking={"type": "adaptive"},
            tools=ANTHROPIC_TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        for block in response.content:
            if block.type == "text":
                print("\nClaude:", block.text)

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type == "tool_use":          # custom client tools only
                    print("[tool] {} {}".format(block.name, json.dumps(block.input)))
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": execute_tool(block.name, block.input),
                    })
            messages.append({"role": "user", "content": results})
            continue
        if response.stop_reason == "pause_turn":      # web search paused; resume
            continue
        if response.stop_reason == "refusal":
            print("\n[refused]")
        if response.stop_reason == "max_tokens":
            print("\n[truncated: hit max_tokens]")
        return


# --------------------------------------------------------------------------- #
# OpenAI provider (Chat Completions + function calling)
# --------------------------------------------------------------------------- #

OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": s["name"],
            "description": s["description"],
            "parameters": s["parameters"],
        },
    }
    for s in TOOL_SPECS
]


def run_openai(client, messages, model):
    while True:
        # No max_tokens: o-series / newer models reject it in favour of
        # max_completion_tokens. Letting it default keeps this model-agnostic.
        response = client.chat.completions.create(
            model=model, messages=messages, tools=OPENAI_TOOLS,
        )
        choice = response.choices[0]
        msg = choice.message

        if msg.content:
            print("\nAssistant:", msg.content)

        if msg.tool_calls:
            messages.append({
                "role": "assistant",
                "content": msg.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                print("[tool] {} {}".format(tc.function.name, tc.function.arguments))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": execute_tool(tc.function.name, args),
                })
            continue

        messages.append({"role": "assistant", "content": msg.content})
        if choice.finish_reason == "length":
            print("\n[truncated: hit token limit]")
        return


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def pick_provider(explicit):
    if explicit:
        return explicit
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"            # default; fails with a clear auth error if no key


def main():
    parser = argparse.ArgumentParser(
        description="single-file Claude/OpenAI tool-calling agent"
    )
    parser.add_argument(
        "--provider", choices=["anthropic", "openai"], default=None,
        help="force a provider (default: auto-detect from whichever key is set)",
    )
    args = parser.parse_args()
    provider = pick_provider(args.provider)

    if provider == "anthropic":
        import anthropic                       # lazy: only the chosen SDK is required
        client = anthropic.Anthropic()         # reads ANTHROPIC_API_KEY / auth token
        model, runner, messages = ANTHROPIC_MODEL, run_anthropic, []
        speaker = "Anthropic"
    else:
        from openai import OpenAI              # lazy: only the chosen SDK is required
        client = OpenAI()                      # reads OPENAI_API_KEY
        model, runner = OPENAI_MODEL, run_openai
        messages = [{"role": "system", "content": SYSTEM}]
        speaker = "OpenAI"

    quit_hint = "Ctrl-Z then Enter" if IS_WINDOWS else "Ctrl-D"
    print("Mini agent ready ({} {}). Type a request; {} to quit.".format(
        speaker, model, quit_hint))
    while True:
        try:
            user = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        runner(client, messages, model)


if __name__ == "__main__":
    main()
