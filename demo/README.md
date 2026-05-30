# Demo assets — Beta Fund × EverMind hackathon

- **`autopilot-slides.pptx`** — 4-slide submission deck (title · problem/team · product · proof).
- **`autopilot-demo.mp4`** — 32s terminal screencast of the real flow (index → verify → eval → submit).
- **`run_demo.sh`** — runnable live demo (`bash demo/run_demo.sh`, ~90s).
- **`make_slides.py` / `make_video.py`** — regenerate the deck/video (need python-pptx / Pillow + ffmpeg).

## Submit (what's done vs the one on-site step)
- ✅ Code pushed: github.com/OCWC22/context-autopilot (private).
- ✅ EverMind/EverOS: **live** (key in `.env`; `autopilot submit` writes memory for real).
- ⏳ Butterbase: set `BUTTERBASE_APP_ID` + `BUTTERBASE_API_KEY` (promo `BUILD0530`), then
  `autopilot submit` writes project/eval/artifacts; submit via **Butterbase MCP** with code **`build0530`**.
- Real Claude Code OAuth benchmark: `claude /login` then `bash benchmarks/claude_oauth_bench.sh .`

## Numbers (measured by `autopilot eval`)
−98.7% tokens · −98.0% time · −93.9% cost · retrieval F1 +0.32 · 1 frontier call avoided · task success preserved.
