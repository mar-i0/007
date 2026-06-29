#!/usr/bin/env python3
"""007 - single-file, cross-platform tool-calling agent for many model providers.

Optimised to run from PowerShell on Windows; also works on macOS/Linux.

Providers (auto-detected from whichever API key / local server is present):
    anthropic, openai, openrouter, groq, gemini, cerebras, mistral, deepseek, ollama
Most non-Anthropic providers share the OpenAI-compatible API, so one loop covers them all.

Quick start (PowerShell):
    pip install --user openai anthropic         # install what you need
    $env:GROQ_API_KEY = "..."                    # or any provider's key (see --list)
    python 007.py --benchmark                    # test available models, pick & save a default
    python 007.py                                # use the saved / auto-detected default
    python 007.py --provider groq --model llama-3.3-70b-versatile   # force one

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
import time

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
CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".007.json")

BROWSER_HEADLESS = True    # set False to watch the Playwright browser window
PAGE_TEXT_LIMIT = 6000     # max chars of page text returned to the model

SYSTEM = (
    "You are a helpful work assistant running on the user's laptop. "
    "Use the tools to read/write files, run {} commands, and browse the web with "
    "a real browser (browser_navigate / browser_read / browser_click / browser_type). "
    "Be concise. Prefer doing the work over describing it."
).format(SHELL_NAME)


# --------------------------------------------------------------------------- #
# Provider registry
# --------------------------------------------------------------------------- #
# kind: "anthropic" or "openai" (OpenAI-compatible). To add any other
# OpenAI-compatible endpoint (e.g. Together, Fireworks, a company gateway),
# just append an entry here.

PROVIDERS = {
    "groq": {
        "kind": "openai", "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1", "free": True,
        "default_model": "llama-3.3-70b-versatile",
        "models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "moonshotai/kimi-k2-instruct",
            "qwen/qwen3-32b",
            "deepseek-r1-distill-llama-70b",
            "gemma2-9b-it",
        ],
    },
    "cerebras": {
        "kind": "openai", "key_env": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1", "free": True,
        "default_model": "llama-3.3-70b",
        "models": [
            "llama-3.3-70b",
            "llama3.1-8b",
            "llama-4-scout-17b-16e-instruct",
            "qwen-3-32b",
        ],
    },
    "gemini": {
        "kind": "openai", "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "free": True,
        "default_model": "gemini-2.0-flash",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-1.5-flash",
        ],
    },
    "openrouter": {
        "kind": "openai", "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1", "free": True,
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "models": [
            "meta-llama/llama-3.3-70b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "deepseek/deepseek-chat-v3-0324:free",
            "mistralai/mistral-small-3.1-24b-instruct:free",
            "meta-llama/llama-3.2-3b-instruct:free",
        ],
    },
    "ollama": {
        "kind": "openai", "key_env": None, "local": True,
        "base_url": "http://localhost:11434/v1", "free": True,
        "default_model": "llama3.2",
        "models": ["llama3.2", "llama3.1", "qwen2.5", "mistral"],
    },
    "openai": {
        "kind": "openai", "key_env": "OPENAI_API_KEY", "base_url": None, "free": False,
        "default_model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "o4-mini"],
    },
    "anthropic": {
        "kind": "anthropic", "key_env": "ANTHROPIC_API_KEY", "free": False,
        "default_model": "claude-opus-4-8",
        "models": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5"],
    },
    "mistral": {
        "kind": "openai", "key_env": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1", "free": False,
        "default_model": "mistral-large-latest",
        "models": [
            "mistral-large-latest",
            "mistral-small-latest",
            "open-mistral-nemo",
            "ministral-8b-latest",
        ],
    },
    "deepseek": {
        "kind": "openai", "key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com", "free": False,
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
}


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
# Anthropic loop
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
# OpenAI-compatible loop (OpenAI, OpenRouter, Groq, Gemini, Ollama, ...)
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
# Provider plumbing: availability, clients, config, benchmark
# --------------------------------------------------------------------------- #

def _key_for(prov):
    if prov.get("key_env"):
        return os.environ.get(prov["key_env"], "")
    return "local"            # local servers ignore the key but the SDK needs one


def _local_reachable(base_url):
    import socket
    try:
        from urllib.parse import urlparse
        u = urlparse(base_url)
        host = u.hostname or "localhost"
        port = u.port or (443 if u.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=0.6):
            return True
    except Exception:
        return False


def is_available(name):
    prov = PROVIDERS[name]
    if prov.get("local"):
        return _local_reachable(prov["base_url"])
    return bool(os.environ.get(prov.get("key_env") or "", ""))


def make_client(name, timeout=None):
    prov = PROVIDERS[name]
    # When timeout is set we're benchmarking: also drop retries so a dead
    # endpoint fails fast instead of retrying 2-3 times.
    extra = {"timeout": timeout, "max_retries": 0} if timeout else {}
    if prov["kind"] == "anthropic":
        import anthropic
        return anthropic.Anthropic(**extra)
    from openai import OpenAI
    kwargs = {"api_key": _key_for(prov) or "none"}
    if prov.get("base_url"):
        kwargs["base_url"] = prov["base_url"]
    kwargs.update(extra)
    return OpenAI(**kwargs)


def _keys_file_paths():
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "keys.env"),
        os.path.join(WORKDIR, "keys.env"),
        os.path.join(os.path.expanduser("~"), ".007.keys"),
    ]
    seen, out = set(), []
    for p in candidates:                       # de-duplicate (here may == WORKDIR)
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def load_keys_file():
    """Read API keys from a simple KEY=value file and put them in the env.

    Real environment variables take precedence (we only fill in missing ones),
    so a key already exported in the shell is never overridden.
    """
    for path in _keys_file_paths():
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("export "):
                        line = line[7:].strip()
                    if "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip().strip('"').strip("'")
                    if key and val:
                        os.environ.setdefault(key, val)
        except Exception as e:
            print("[warn] could not read {}: {}".format(path, e))
        return path                            # stop at the first file that exists
    return None


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(provider, model):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"provider": provider, "model": model}, f, indent=2)
        return True
    except Exception as e:
        print("[warn] could not save config: {}".format(e))
        return False


def ping(name, model):
    """Send a tiny request; return (ok, latency_ms, note)."""
    prov = PROVIDERS[name]
    t0 = time.time()
    try:
        client = make_client(name, timeout=20)
        if prov["kind"] == "anthropic":
            client.messages.create(
                model=model, max_tokens=16,
                messages=[{"role": "user", "content": "Reply with OK"}],
            )
        else:
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with OK"}],
            )
        return True, int((time.time() - t0) * 1000), ""
    except Exception as e:
        return False, int((time.time() - t0) * 1000), str(e).splitlines()[0][:90]


def _models_of(prov):
    return prov.get("models") or [prov["default_model"]]


def list_providers():
    print("Providers (set the matching env var, or use keys.env):\n")
    for name, prov in PROVIDERS.items():
        tag = "free " if prov.get("free") else "paid "
        key = prov.get("key_env") or "(local, no key)"
        mark = "available" if is_available(name) else "not set"
        print("  {:<11} {} {:<22} {:>2} models  [{}]".format(
            name, tag, key, len(_models_of(prov)), mark))
    print("\nKeys file: keys.env (next to the script).  Config: {}".format(CONFIG_PATH))


def run_benchmark():
    """Ping every model of every available provider; print a ranked table.

    Returns (working_rows, suggestion) where each row is
    (name, model, ok, ms, note, free).
    """
    print("Checking available providers (one quick call per model)...\n")
    rows = []
    for name, prov in PROVIDERS.items():
        free = bool(prov.get("free"))
        if not is_available(name):
            reason = "local server not reachable" if prov.get("local") \
                else "no {}".format(prov.get("key_env"))
            print("  {:<11} -- skipped ({})".format(name, reason))
            continue
        for model in _models_of(prov):
            ok, ms, note = ping(name, model)
            status = "OK  {:>5} ms".format(ms) if ok else "FAIL ({})".format(note)
            print("  {:<11} {:<46} {} {}".format(
                name, model, status, "[free]" if free else "[paid]"))
            rows.append((name, model, ok, ms, note, free))

    working = [r for r in rows if r[2]]
    free_working = sorted([r for r in working if r[5]], key=lambda r: r[3])
    any_working = sorted(working, key=lambda r: r[3])
    suggestion = free_working[0] if free_working else (any_working[0] if any_working else None)
    return working, suggestion


def choose_via_benchmark():
    working, suggestion = run_benchmark()
    if not working:
        print("\nNo provider is available. Set an API key (see --list) and retry.")
        sys.exit(1)

    print("\nWorking models:")
    for i, r in enumerate(working, 1):
        star = "  <- suggested" if r is suggestion else ""
        print("  [{}] {} / {}   {} ms   ({}){}".format(
            i, r[0], r[1], r[3], "free" if r[5] else "paid", star))

    raw = input("\nChoose a number (Enter = suggested): ").strip()
    choice = suggestion
    if raw:
        try:
            choice = working[int(raw) - 1]
        except Exception:
            print("Invalid choice; using the suggestion.")
    provider, model = choice[0], choice[1]

    ans = input("\n¿Usarlo como predeterminado? [y/N] ").strip().lower()
    if ans == "y":
        if save_config(provider, model):
            print("Saved as default in {}".format(CONFIG_PATH))
    return provider, model


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def resolve(args):
    """Decide (provider, model) from flags, then config, then auto-detect."""
    if args.benchmark:
        return choose_via_benchmark()
    if args.provider:
        return args.provider, (args.model or PROVIDERS[args.provider]["default_model"])

    cfg = load_config()
    if cfg.get("provider") in PROVIDERS:
        return cfg["provider"], (args.model or cfg.get("model")
                                 or PROVIDERS[cfg["provider"]]["default_model"])

    avail = [n for n in PROVIDERS if is_available(n)]
    if avail:
        free_avail = [n for n in avail if PROVIDERS[n].get("free")]
        name = (free_avail or avail)[0]
        return name, (args.model or PROVIDERS[name]["default_model"])

    return "anthropic", (args.model or PROVIDERS["anthropic"]["default_model"])


def main():
    parser = argparse.ArgumentParser(description="single-file multi-provider tool-calling agent")
    parser.add_argument("--provider", choices=list(PROVIDERS), default=None,
                        help="force a provider (default: saved config, else auto-detect)")
    parser.add_argument("--model", default=None, help="override the model id")
    parser.add_argument("--benchmark", action="store_true",
                        help="test available providers, suggest one, and offer to save it")
    parser.add_argument("--list", action="store_true",
                        help="list providers and which are available, then exit")
    args = parser.parse_args()

    loaded = load_keys_file()                  # fill env from keys.env if present
    if loaded:
        print("Loaded keys from {}".format(loaded))

    if args.list:
        list_providers()
        return

    provider, model = resolve(args)

    try:
        client = make_client(provider)
    except ImportError as e:
        sdk = "anthropic" if PROVIDERS[provider]["kind"] == "anthropic" else "openai"
        print("Missing SDK for '{}': {}. Run: pip install --user {}".format(provider, e, sdk))
        return

    if PROVIDERS[provider]["kind"] == "anthropic":
        runner, messages = run_anthropic, []
    else:
        runner, messages = run_openai, [{"role": "system", "content": SYSTEM}]

    quit_hint = "Ctrl-Z then Enter" if IS_WINDOWS else "Ctrl-D"
    print("007 ready ({} / {}). Type a request; {} to quit.".format(
        provider, model, quit_hint))
    while True:
        try:
            user = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        messages.append({"role": "user", "content": user})
        try:
            runner(client, messages, model)
        except Exception as e:               # never crash the REPL on a provider hiccup
            print("\n[error] {}".format(e))


if __name__ == "__main__":
    main()
