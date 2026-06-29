# 007 — multi-provider tool-calling agent

A single-file, cross-platform Python agent that works with **many model providers**
(several with free tiers) and helps with your work through tool-calling: read and write
files, run shell commands, **browse the web with a real browser (Playwright)**, and use
native web search on Anthropic. One file — `007.py` — meant to be read and modified.
Optimised to run from **PowerShell on Windows**; also works on macOS/Linux.

Built for the reality that different machines allow different providers: set whatever key
that machine has, run `--benchmark`, and it tells you what works and lets you save a default.

## 1. Install

```powershell
pip install --user openai anthropic    # openai covers most providers; anthropic for Claude
```

For the web-browsing tools (optional), also install Playwright and its browser:

```powershell
pip install --user playwright
python -m playwright install chromium
```

## 2. Providers & keys

Set the environment variable for whichever provider that machine allows. Most are
**OpenAI-API-compatible**, so one code path covers them all.

| Provider | Free tier | Env var | Get a key |
|----------|-----------|---------|-----------|
| `groq` | ✅ | `GROQ_API_KEY` | <https://console.groq.com> |
| `cerebras` | ✅ | `CEREBRAS_API_KEY` | <https://cloud.cerebras.ai> |
| `gemini` | ✅ | `GEMINI_API_KEY` | <https://aistudio.google.com/apikey> |
| `openrouter` | ✅ (`:free` models) | `OPENROUTER_API_KEY` | <https://openrouter.ai/keys> |
| `ollama` | ✅ local | *(none)* | run `ollama serve` locally |
| `ollama-cloud` | ✅ (free tier) | `OLLAMA_API_KEY` | <https://ollama.com/settings/keys> |
| `openai` | ❌ | `OPENAI_API_KEY` | <https://platform.openai.com/api-keys> |
| `anthropic` | ❌ | `ANTHROPIC_API_KEY` | <https://console.anthropic.com> |
| `mistral` | ❌ | `MISTRAL_API_KEY` | <https://console.mistral.ai> |
| `deepseek` | ❌ | `DEEPSEEK_API_KEY` | <https://platform.deepseek.com> |

### Easiest: the `keys.env` file (recommended for throwaway keys)

Instead of fiddling with environment variables, just edit **`keys.env`** (next to `007.py`)
and paste your keys — `007.py` reads it automatically on startup:

```ini
# keys.env  — remove the "#" and paste your key
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
# OPENAI_API_KEY=sk-...
```

- Format is `NAME=value`, one per line; `#` lines and blanks are ignored; no quotes needed.
- It's **git-ignored**, so your keys are never pushed. A `keys.env.example` template is in
  the repo (copy it to `keys.env` if it's missing).
- Searched in: the script's folder, the current folder, then `~/.007.keys`.
- Real environment variables (below) take precedence if both are set.

### Or environment variables

In **PowerShell** (current session, or `setx ...` + new window to persist):

```powershell
$env:GROQ_API_KEY = "gsk_..."        # example: a free provider
```

`python 007.py --list` shows every provider and which ones are currently available.

> **Anthropic note:** a Claude.ai / Claude Code subscription is a *separate* product and
> doesn't grant API access — you need an API key, or the `ant` CLI (`ant auth login`) for
> subscription OAuth.
>
> **Adding more providers** is one entry in the `PROVIDERS` dict in `007.py` (`name`,
> `base_url`, `key_env`, `default_model`) — any OpenAI-compatible endpoint works.

## 3. Pick a model with `--benchmark`

```powershell
python 007.py --benchmark
```

It probes **every model of every available provider** (~40 models across the 9 providers).
Each probe does two things in one call: confirms the model answers, and asks it to call a
trivial tool to check it actually supports **tool-calling** (this agent needs it). The
table shows latency, `tools:yes/NO`, free/paid, or why a model was skipped:

```
groq   llama-3.3-70b-versatile   OK   320 ms  tools:yes [free]
groq   gemma2-9b-it              OK   300 ms  tools:NO  [free]
openai gpt-4o                    OK   150 ms  tools:yes [paid]
```

The **suggestion** prefers models that pass the tool test, free first, then fastest. You
pick a number; it asks **¿Usarlo como predeterminado?** and, if yes, saves your choice to
`~/.007.json` so future runs start there automatically.

Notes: the tool test is a heuristic (a capable model could still answer in text), and model
IDs drift, so some rows may show `FAIL` — harmless, just pick a `tools:yes` one. The
candidate list per provider lives in the `PROVIDERS` dict in `007.py`, easy to edit.

## 4. Run

```powershell
python 007.py                          # saved default, else auto-detect (free first)
python 007.py --provider groq          # force a provider (uses its default model)
python 007.py --provider openrouter --model "qwen/qwen-2.5-72b-instruct:free"
```

Type a request; quit with **Ctrl-Z then Enter** (Windows) or **Ctrl-D** (macOS/Linux).
Examples:

- `What's in requirements.txt?` → reads the file
- `List the files here.` → runs a shell command (asks to confirm first)
- `Create hello.txt saying hi.` → writes a file (asks to confirm first)
- `Open example.com and summarise it.` → real browser via Playwright

The conversation has memory within a session, so follow-ups work.

## PowerShell specifics

- **UTF-8 is forced** on input/output so accented text (e.g. Spanish) doesn't crash the
  console. If output still looks garbled in old *Windows PowerShell 5.1*, run `chcp 65001`
  once, or use **PowerShell 7 / Windows Terminal**.
- **`run_shell` runs PowerShell** on Windows (`pwsh` if present, else `powershell`) and
  bash/sh on macOS/Linux — so the model writes commands for the shell you're actually on.

## Web browsing (Playwright)

Four tools drive a real Chromium browser, with one persistent browser per session:

- `browser_navigate(url)` — open a page; returns its URL, title and visible text.
- `browser_read()` — re-read the current page after an action.
- `browser_click(target)` — click by visible text or CSS selector (asks to confirm).
- `browser_type(selector, text, enter?)` — fill an input, optionally submit (asks to confirm).

Runs headless by default; set `BROWSER_HEADLESS = False` near the top of `007.py` to watch
the window. The browser starts lazily, so you only need Playwright installed if you browse.
This gives **every** provider real web access, not just Anthropic.

## Safety gate

`write_file`, `run_shell`, `browser_click` and `browser_type` ask `[y/N]` before acting
(the state-changing / outward-facing actions). Answer `n` to decline — the model is told
and adapts. `read_file`, `browser_navigate`, `browser_read` and Anthropic's `web_search`
run without prompting.

## Add your own tool

1. Append a spec to `TOOL_SPECS` (`name`, `description`, `parameters`) — every provider
   picks it up automatically.
2. Add a matching `if name == "your_tool":` branch in `execute_tool` that returns a string.

## Notes

- **Default models** live in the `PROVIDERS` dict in `007.py`; override per-run with
  `--model`, or save a default via `--benchmark`.
- **Tool-calling quality varies by model.** The agent relies on function calling; big
  instruction-tuned models (Llama 3.3 70B, GPT-4o, Claude, Gemini, DeepSeek) handle it
  well, smaller/local models less so. If a model ignores tools or errors on them, pick a
  stronger one — the REPL won't crash, it prints `[error]` and waits for your next message.
- **Web search**: Anthropic has a native server-side `web_search` tool (fast lookups);
  other providers use the Playwright `browser_*` tools instead.
- **OpenAI `max_tokens`** is omitted on purpose so the loop works across model families
  (o-series / newer models reject it in favour of `max_completion_tokens`).
- Both loops are non-streaming for simplicity. Streaming, directory sandboxing for the
  file tools, and a `run_shell` allowlist are natural next steps.
