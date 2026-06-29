# mini agent

A single-file, cross-platform Python harness that lets **Claude (Anthropic)** or
**OpenAI** help with your work through tool-calling: read and write files, run shell
commands, **browse the web with a real browser (Playwright)**, and (Anthropic) use
native web search. One file — `007.py` — meant to be read and modified. Optimised to
run from **PowerShell on Windows**; also works on macOS/Linux.

## 1. Install

```powershell
pip install --user anthropic     # or: pip install --user openai  (install only what you use)
```

For the web-browsing tools (optional), also install Playwright and its browser:

```powershell
pip install --user playwright
python -m playwright install chromium
```

Verify:

```powershell
python -c "import sys; print(sys.version)"
```

## 2. Set your API key

Each provider reads its key from the environment. In **PowerShell**:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # Anthropic
$env:OPENAI_API_KEY    = "sk-..."         # OpenAI
```

That sets it for the current session. To persist it across sessions:

```powershell
setx ANTHROPIC_API_KEY "sk-ant-..."        # then open a NEW PowerShell window
```

(macOS/Linux: `export ANTHROPIC_API_KEY="sk-ant-..."`)

### Anthropic note

A Claude.ai / Claude Code subscription is a *separate* product and doesn't grant API
access on its own — you need an API key from <https://console.anthropic.com> (billed
pay-as-you-go). Alternatively, the official `ant` CLI (`ant auth login`) lets the SDK
ride your subscription via OAuth; that needs one extra binary installed and is more
fragile. OpenAI keys come from <https://platform.openai.com/api-keys>.

## 3. Run

```powershell
python 007.py                    # auto-picks the provider whose key is set
python 007.py --provider openai  # or force one
```

Type a request; quit with **Ctrl-Z then Enter** (Windows) or **Ctrl-D** (macOS/Linux).
Examples:

- `What's in requirements.txt?` → reads the file
- `List the files here.` → runs a shell command (asks to confirm first)
- `Create hello.txt saying hi.` → writes a file (asks to confirm first)
- `Open example.com and summarise it.` → real browser via Playwright
- `Search the web for today's date.` → native web search (**Anthropic only**, see Notes)

The conversation has memory within a session, so follow-ups work.

## PowerShell specifics

- **UTF-8 is forced** on input/output so accented text (e.g. Spanish) doesn't crash the
  console. If output still looks garbled in old *Windows PowerShell 5.1*, run `chcp 65001`
  once, or use **PowerShell 7 / Windows Terminal**.
- **`run_shell` runs PowerShell** on Windows (`pwsh` if present, else `powershell`) and
  bash/sh on macOS/Linux — so the model writes commands for the shell you're actually on.
- Provider auto-detect uses whichever of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` is set;
  `--provider` overrides.

## Web browsing (Playwright)

Four tools drive a real Chromium browser, with one persistent browser per session:

- `browser_navigate(url)` — open a page; returns its URL, title and visible text.
- `browser_read()` — re-read the current page after an action.
- `browser_click(target)` — click by visible text or CSS selector (asks to confirm).
- `browser_type(selector, text, enter?)` — fill an input, optionally submit (asks to confirm).

Runs headless by default; set `BROWSER_HEADLESS = False` near the top of `007.py` to watch
the window. The browser starts lazily on first use, so you only need Playwright installed
if you actually browse. This also gives **OpenAI** real web access (it has no native search).

## Safety gate

`write_file`, `run_shell`, `browser_click` and `browser_type` ask `[y/N]` before acting
(these are the state-changing / outward-facing actions). Answer `n` to decline — the model
is told and adapts. `read_file`, `browser_navigate`, `browser_read` and Anthropic's
`web_search` run without prompting.

## Add your own tool

1. Append a spec to `TOOL_SPECS` (`name`, `description`, `parameters`) — both providers
   pick it up automatically.
2. Add a matching `if name == "your_tool":` branch in `execute_tool` that returns a string.

## Notes

- **Models** are constants near the top of `007.py`: `ANTHROPIC_MODEL`
  (`claude-opus-4-8` → `claude-sonnet-4-6`/`claude-haiku-4-5` for less cost) and
  `OPENAI_MODEL` (`gpt-4o` → `gpt-4.1`, `o4-mini`, whatever your key has).
- **Web access**: both providers can browse via the Playwright `browser_*` tools.
  Anthropic additionally has a native server-side `web_search` tool (faster for quick
  lookups); OpenAI has no native search here, so it relies on browsing.
- **OpenAI `max_tokens`** is omitted on purpose so the loop works across model families
  (o-series / newer models reject it in favour of `max_completion_tokens`).
- Both loops are non-streaming for simplicity. Streaming, directory sandboxing for the
  file tools, and a `run_shell` allowlist are natural next steps.
