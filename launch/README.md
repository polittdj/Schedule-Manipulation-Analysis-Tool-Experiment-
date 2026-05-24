# One-click launchers

Each launcher, on click, does everything needed: on first run it creates the
virtual environment and installs dependencies, then it starts the local server
(`127.0.0.1`) and opens your browser to the tool. Closing the window stops it.
**All processing stays on your machine** (LAW 1). Prerequisite: **Python 3.11+**
installed (https://www.python.org/downloads/ — on Windows tick *"Add Python to
PATH"*).

Pick your OS:

## macOS — `Schedule-Forensics.command`
1. In Finder, double-click `launch/Schedule-Forensics.command`. The first time,
   macOS may block it: **right-click → Open → Open** (only needed once).
2. To get a Desktop icon: right-click the file → **Make Alias**, then drag the
   alias to your Desktop. (Use an *alias*, not a copy — the alias points back here
   so it can find the project.)
3. *(Optional icon image)* select the alias → **Get Info**, drag `icon.svg`
   (or a PNG of it) onto the icon well at the top-left.

## Windows 11 — `Schedule-Forensics.bat`
**Easiest (one-time):** double-click `launch\Install-Desktop-Shortcut.bat`. It puts
a **Schedule Forensics** icon (using `icon.ico`) on your Desktop. After that, just
double-click that Desktop icon to launch.

*Manual alternative:* right-click `launch\Schedule-Forensics.bat` → **Send to →
Desktop (create shortcut)** (then optionally **Properties → Change Icon…** →
`launch\icon.ico`).

## Linux — `Schedule-Forensics.desktop`
```sh
# from the repo root: fill in the absolute path and install the desktop entry
REPO="$(pwd)"
sed "s#__REPO__#$REPO#g" launch/Schedule-Forensics.desktop > ~/.local/share/applications/schedule-forensics.desktop
chmod +x launch/schedule-forensics.sh
cp ~/.local/share/applications/schedule-forensics.desktop ~/Desktop/   # optional; then "Allow Launching"
```
Then launch it from your apps menu or the Desktop icon.

## AI-polished executive summaries (optional, automatic)
- **Easiest — Ollama:** install [Ollama](https://ollama.com) and run
  `ollama pull llama3.2` once. The macOS/Linux/Windows launchers then **auto-detect
  Ollama, start it, and use it** to polish the executive summary (override the model
  with `SF_OLLAMA_MODEL`). Nothing is auto-downloaded; with no Ollama — or no pulled
  model — the tool uses its deterministic summary. See `docs/OLLAMA.md`.
- **Start/stop with the tool:** when you exit, the launcher unloads the model (frees
  memory). On **Windows** it shuts Ollama down (it restarts next time you launch the
  tool); on **macOS/Linux** it stops the Ollama server only if the launcher started
  it, leaving a system-managed Ollama running. The shutdown runs on a clean stop
  (Ctrl+C / quitting the tool); if you force-close the window it may be skipped, but
  Ollama unloads an idle model on its own after a few minutes.
- **Or any local OpenAI-compatible server** (llama.cpp `llama-server`, LM Studio,
  vLLM): set `SF_LLM_BASE_URL` (e.g. `http://127.0.0.1:8080/v1`) + `SF_LLM_MODEL`
  in the launcher header.
- **Loopback only** — a non-local URL/host is refused (LAW 1), and the model only
  *rephrases* the summary (it never changes a number). If it's unreachable, the tool
  falls back to the deterministic summary automatically.

## Options (all launchers have an editable header)
- **Port:** set `SF_PORT` (default `5000`; handy if 5000 is busy, e.g. macOS AirPlay).

`icon.svg` is the shared artwork (a schedule chart under a magnifier). It's vector;
convert to `.ico` (Windows) / `.png` (Linux/macOS) with any converter if you want
a custom shortcut icon — purely cosmetic.
