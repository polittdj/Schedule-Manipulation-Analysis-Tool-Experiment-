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

## Options (all launchers have an editable header)
- **Port:** set `SF_PORT` (default `5000`; handy if 5000 is busy, e.g. macOS AirPlay).
- **Local Qwen model (optional):** to get AI-polished executive summaries, run a
  local OpenAI-compatible server (llama.cpp `llama-server`, LM Studio, or vLLM)
  hosting your Qwen 32B Q4_K_M, then uncomment/set `SF_LLM_BASE_URL`
  (e.g. `http://127.0.0.1:8080/v1`) and `SF_LLM_MODEL` in the launcher. **Loopback
  only** — a non-local URL is refused (LAW 1). If the model server isn't running,
  the tool falls back to the deterministic summary automatically.

`icon.svg` is the shared artwork (a schedule chart under a magnifier). It's vector;
convert to `.ico` (Windows) / `.png` (Linux/macOS) with any converter if you want
a custom shortcut icon — purely cosmetic.
