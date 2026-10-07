# Kav-FastwebAgent

[繁體中文](README.md) | **English** | [简体中文](README.zh-CN.md)

**Describe a web task you do all the time once, and it becomes a "flow". After that, one sentence runs it locally in about 6 seconds, and code checks the result.**

Ask an AI agent to look up a train timetable and it takes a screenshot, clicks, takes another screenshot... and works the page out from scratch every single time: two minutes and close to a million tokens.
But every week you're checking the same site and the same table. Only the date and the stations change.

Kav works differently. The first time, Claude reads the page, writes it up as a "flow", and runs it once so you can confirm the result. After that, the same task runs directly on your Mac in a dedicated Chrome.
Code checks that the answer is really there; when a judgment call is needed (which row of a list), simple ones can go to a small local model, [Kev](https://github.com/jaredpalmer/kev) (optional), and the rest go back to Claude. If the site changes and the flow breaks, just say "that's wrong". Claude fixes it and tells you what changed.


<sub>Same request: "find Taiwan High Speed Rail trains from Taichung to Taipei after 3 pm on 10/12". Top: a Kav flow. Bottom: Claude in Chrome operating the browser step by step. Measured 2026-09-29; both answers matched the official site.</sub>

## What it helps with

### If you don't write code

All you need to do is ask, then decide whether the result is right.

- **Repeated lookups in one sentence**: train timetables, today's exchange rates, price comparison across stores, parcel tracking, any "fill in a form → search → read the result" page.
- **Every result comes with evidence**: there's always a screenshot. If nothing is found, a login is needed or the site blocks it, it tells you why instead of pretending it finished.
- **No engineer needed when it breaks**: say "that's wrong, it should be...". Claude fixes the flow, reruns it and tells you what changed.

### If you already use Claude Code / Codex

| What hurts today | With Kav |
|---|---|
| Agents drive web pages slowly, reading screenshots and retrying every time | Fixed web actions become flows that run locally. Train timetable lookup: about **22 s vs 116 s** (about 5x) |
| One web task burns hundreds of thousands to a million tokens | Same task: **176k–266k vs 770k–1.28M** input tokens (about 4x). Fetching never goes through a model; judgment calls only get the extracted text |
| The agent says "done" while the page hadn't finished loading, or it read the wrong column | Code decides "done": load detection, read-back after submitting, a label on every cell, a check that the date is today, and the lowest price re-checked on the product page |
| Scrapers need an engineer and break whenever the site changes | A flow is data (JSON), not code. When it breaks, Claude repairs it with a fixed method |
| Worry that the agent will log in, pay, or get around a CAPTCHA | Those rules live in local code, not in the model's judgment |

### Good fit / not a fit

| Good fit | Not a fit |
|---|---|
| **Multi-step web actions you repeat**: form lookups (timetables, parcels, query systems), searching and comparing across several sites | One-off tasks, or just opening a page to look (Claude in Chrome is just as fast: the exchange-rate page took about 20 s both ways) |
| Reading a known URL where the data must be current (today's rates, notices) | Logging in, paying, ordering, solving CAPTCHAs (by design) |
| Sites you've logged into yourself in Kav's dedicated Chrome | Sites that block automation (e.g. Shopee), games, desktop apps that aren't web pages |

## Real examples

All three are Taiwanese sites, because that's where we tested. You can talk to Claude in any language.

**Train timetable (form lookup)**: "Taiwan High Speed Rail, Taichung to Taipei after 3 pm on 10/12" → about 6 s, 0 Kev calls.

![Taiwan High Speed Rail timetable result](docs/images/thsr-result.jpg)

**Today's Bank of Taiwan exchange rates (read a fixed page, check it's today's)**: a user said "make me a flow: check Bank of Taiwan's USD and JPY rates for today".
Claude wrote the flow from scratch and it passed on the first try run (about 36 s). The user then added "check that it's today's". Now, if the posted date on the page isn't today, the flow reports "not posted yet" instead of passing off old data.

![Bank of Taiwan board rates](docs/images/bot-fx-rates.jpg)

**Price comparison across four stores (search + judgment)**: PChome, momo, Yahoo Shopping and Coupang are searched at once. Kev, running locally, tells "the console" apart from "console + game bundle", accessories and refurbished units.
One Switch 2 run takes 5.6–7.8 s, with 18–31 Kev calls and roughly 6k–11k tokens, all local. The lowest price is also opened and re-checked on its product page.

![Coupang search results](docs/images/compare-coupang.jpg)

<details>
<summary>How the numbers were measured, and what's still missing</summary>

- Comparison: the same request was given to "a Kav flow" and to "Claude in Chrome step by step", each in a fresh Claude Code session. Train lookup: Kav 3 runs, baseline 4 runs; exchange rates: 1 run each. **The sample is small**: the 5x comes from a single site.
- Building a flow is a one-time cost (about 36 s and 3 tool calls for the exchange-rate flow). Repairing a broken flow cost about 12k–26k output tokens. Repair has so far been blind-tested on one site with two kinds of breakage.
- The train and exchange-rate flows **don't use Kev at all**: their speed comes from "flow + local code". Kev currently only contributes to flows that need judgment calls, like price comparison.
- **Kev is optional, not the selling point.** On 2026-10-07 we measured "which row" picking on a 591 rental list (30 cards, 18 colloquial requests): Kev never picked a wrong row and stopped correctly whenever it should, but it also stopped on every two-condition or "cheapest" request, answering only 4 of 11 unique-answer questions; Claude reading the same text got all of them. Fetching the rows took the engine 31 ms, while Claude driving a browser took 21–162 s and 450k–910k tokens per question. So the time and token savings come from the engine's fetching; for judgment calls the cheapest reliable option is Claude, and Kev only helps on single-attribute requests or offline. Record: `.flightwake/records/261007-pick-judgment-experiment.md`.
- Full records are in `.flightwake/records/` (`260929-control-experiment-and-demo`, `260929-kev-usage-accounting`, in Chinese).

</details>

## How it works

![The first time, build a flow by describing it; after that, one sentence runs it locally](docs/images/how-it-works.svg)

<sub>Diagram text is in Chinese. Top row, first time: you describe the task → Claude writes the flow → Kav runs a trial and checks it with code, plus a screenshot → you confirm and it's saved. Bottom row, every time after: you ask in one sentence → Claude finds the flow and only fills in parameters → Kav runs it on your Mac → answer plus screenshot, or the reason it couldn't.</sub>

- **Claude**: understands what you want, writes the flow, and repairs it when it breaks.
- **Kav (local code)**: runs the flow in a dedicated Chrome and checks whether the page has loaded, whether each field really got filled in, and whether the result really appeared. When it can't, it returns `needs_help` with the reason and a screenshot.
- **Kev (small local model)**: answers only fuzzy judgment questions, such as "is this listing the console itself or a bundle?".

## What computer you need

Kav itself (Chrome + local code) is light. The heavy part is the local model Kev, so first check whether your flows need it:

| Flows you want to run | Need Kev? | Recommended |
|---|---|---|
| Form lookups, reading fixed pages (timetables, exchange rates) | No | Any Mac that runs Chrome and Claude Code |
| Price comparison, deciding "is this the same product?" | Yes | Apple Silicon Mac (M1 or later) with **32 GB of memory** for Kev-4B |

### Which Kev

| Model | Hardware (per Kev) | Accuracy (Kev's evaluation, question types it wasn't trained on) | Advice |
|---|---|---|---|
| Kev-0.8B | Any Apple Silicon Mac | 0.648 | Worth trying on a 16 GB Mac; not yet tested with Kav |
| **Kev-4B** | 32 GB Mac | 0.817 | **Default**; all of Kav's measurements use it |
| Kev-9B | 32 GB Mac | 0.822 | Slightly more accurate than 4B at twice the size; usually not needed |
| Kev-27B | 80 GB data-centre GPU | 0.848 | No Mac version |

To switch models, change `--run` in the start command, e.g. `--run jaredpalmer/kev-0.8b`. Kav needs no configuration change.

**Our test machine**: Apple M5 Max, 36 GB of memory. Kev-4B runs on MLX (bf16) automatically and uses about 4.5 GB of memory while running. One price-comparison run searches 4 sites in parallel and makes 18–31 Kev calls.

**On the Claude side**: all our measurements used Claude Opus 5.5. Running a saved flow is cheap (it only fills in parameters). Writing and repairing flows depends more on model capability, and other models haven't been tested.

### Notes for Mac

- **Run Kev only on Apple Silicon (M1 or later)**: Kev uses MLX acceleration on Apple Silicon automatically. Intel Macs have no MLX and fall back to the CPU, which is very slow. Flows that don't use Kev are unaffected.
- Chrome must be in the default location (`/Applications/Google Chrome.app`). If it's somewhere else, point `KFW_CHROME` at it.
- Kav opens a separate Chrome window (dedicated profile, debugging port 9333) and never touches your everyday Chrome.

### Notes for Windows (not yet tested)

Kav has only been tested on a Mac. The code isn't tied to macOS, but you must handle these:

- **Chrome location**: the default path is the Mac one, so set `KFW_CHROME`, for example by adding
  `-e KFW_CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"` when registering the MCP server.
- **Folders**: screenshots, flows and the Chrome profile go in `%USERPROFILE%\.kav-fastweb\`.
- **Kev needs an NVIDIA GPU (CUDA)**: there's no MLX on Windows, and without a GPU it runs on the CPU, which is too slow in practice. Kev only lists data-centre GPUs (L4 / L40S / H100), and we haven't tested whether a consumer gaming GPU can run 4B.
  Without a suitable GPU, run only the flows that don't need Kev, or run Kev on another Mac (`--host 0.0.0.0`) and set `KFW_KEV` to `http://<that Mac's IP>:8009`. That setup is untested too, and only suits a home or office network: Kav doesn't support Kev API keys yet.
- The install commands below are written for macOS / Linux. On Windows, adapt them in PowerShell, or just give Claude Code the "paste this" block below.

## Install

You need Google Chrome, [uv](https://docs.astral.sh/uv/) and Claude Code. Kev-4B downloads about 9 GB the first time.

### Easiest: paste this into your Claude Code

````text
Please install Kav-FastwebAgent for me, and report the result after each step:
1. Clone https://github.com/kaiwutech-TW/Kav-FastwebAgent into ~/Kav-FastwebAgent and run uv sync inside it.
2. Ask me whether to install Kev (small local model, about 9 GB, only needed for price comparison). If yes:
   git clone https://github.com/jaredpalmer/kev ~/Kav-FastwebAgent/vendor/kev
   then run uv sync --extra serve inside vendor/kev
3. Make it usable from any folder:
   - Register the MCP server with claude mcp add --scope user kav-fastweb -- uv run --project <absolute path of ~/Kav-FastwebAgent> python -m kfw.mcp_server
   - Copy the whole ~/Kav-FastwebAgent/.claude/skills/kav-fastweb folder into ~/.claude/skills/
   - If this machine runs Windows: add -e KFW_CHROME="<full path to chrome.exe>" when registering the MCP server
4. Tell me how to start Kev in the future, and remind me to restart Claude Code.
````

After restarting Claude Code, ask for "kav status" and it will tell you whether Chrome and Kev are running.

> Step 3 (usable from any folder) hasn't been tested yet. The tested setup is opening Claude Code inside the Kav folder, where the project's `.mcp.json` and skill load automatically.

### Manual install

```bash
git clone https://github.com/kaiwutech-TW/Kav-FastwebAgent ~/Kav-FastwebAgent && cd ~/Kav-FastwebAgent && uv sync
# Optional: Kev (only for price comparison; about 9 GB on first download)
git clone https://github.com/jaredpalmer/kev vendor/kev
cd vendor/kev && uv sync --extra serve && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009
```

Open Claude Code in `~/Kav-FastwebAgent` and approve `kav-fastweb` from `.mcp.json`.
If Chrome isn't running, Kav starts one with its own profile (`~/.kav-fastweb/chrome-profile`, not your everyday Chrome). Screenshots are saved in `~/.kav-fastweb/runs/`.

<details>
<summary>Codex users (not yet tested)</summary>

Kav is a standard MCP server, so Codex should be able to use it. Add this to `~/.codex/config.toml`:

```toml
[mcp_servers.kav-fastweb]
command = "uv"
args = ["run", "--project", "/your/path/Kav-FastwebAgent", "python", "-m", "kfw.mcp_server"]
```

Then copy `.claude/skills/kav-fastweb` into a skills folder Codex reads (for example `.agents/skills/` in your project).

</details>

## Set up a web task you do regularly

### 1. Tell Claude using this template

````text
Make me a flow:
- Site: <URL>
- What changes each time: <e.g. departure station, arrival station, date>
- The result I want to see: <e.g. train number, departure and arrival times>
- What counts as correct: <optional, e.g. the date must be today>
````

It's fine to leave things out. Claude asks for anything missing, all at once.

### 2. Claude runs a trial and shows you the result

Claude opens the page to see its fields, writes the flow, runs it once, then shows you the key results and a screenshot and asks "is this what you want?".
You only need to judge whether the result is right:

- Right → say "yes". It saves the flow and tells you how to call it next time.
- Wrong → say what's wrong ("the fare is missing", "I want the cash selling rate"). It fixes it and shows you again.

### 3. From then on, one sentence

| You want to... | Just say |
|---|---|
| Use a flow | Ask directly, e.g. "trains from Hsinchu to Tainan after 9 am on 10/20" |
| Fix a wrong result or a changed site | "That's wrong, it should be..." → Claude fixes it, reruns it and tells you what changed |
| See your flows | "What flows do I have?" |
| Delete a flow | "Delete the <name> flow" (moved to `~/.kav-fastweb/trash/`, recoverable) |
| Use a site that needs a login | Log in once yourself in Kav's dedicated Chrome window (a secondary account is recommended). Kav never logs in for you |

**Tip**: the more specific "what counts as correct" is, the more reliable the flow. Adding "the date is today" to the exchange-rate flow, for instance, means old data is never taken as the answer.

### Hard to explain? Show it once (new, being validated)

Some sites take several pages, a pick from a list, or unusual menus, and are hard to describe. Say "**let me show you**":

1. Claude opens the page in Kav's Chrome, and you do the task once the usual way **with a real example** (don't type passwords, card numbers or other personal data).
2. When the result appears, press "**Mark result**" in the bar at the top of the page, click the part you want, then press "**Done**".
3. Claude turns what you did into a flow and replays it once in a **clean browser environment**: the result must match what you marked exactly before it's shown to you for confirmation and saved.

Limits: stay in the same tab. Opening new tabs, filling forms inside embedded frames (iframes), pages that ask for a password, and tasks whose results keep changing (prices, remaining seats) are reported as not recordable.
When a flow breaks and Claude can't fix it in two tries, it will also ask whether you'd like to show it once.

### What it won't do

Log in for you, solve CAPTCHAs, pay or place orders, or scrape at high volume. Some sites block automation (e.g. Shopee). When that happens it stops and tells you why, and doesn't try to get around it.
With Cloudflare WARP or a VPN on, some sites (e.g. Coupang) refuse access.

## For developers

Following the `kav-fastweb` skill (`.claude/skills/kav-fastweb/`), Claude writes a **recipe** (what users see as a "flow") for each "site × action", and saves it only after a trial run passes with evidence.
MCP tools: `find_recipe`, `run_recipe`, `inspect_page`, `dry_run`, `save_recipe`, `list_recipes`, `delete_recipe`, `start_recording`, `stop_recording`, `status`.

Built-in recipes live in `recipes/`. Users' own recipes are in `~/.kav-fastweb/recipes/` and override a built-in of the same name.

| Recipe | Type | What it does |
|---|---|---|
| `tw-shop-compare` | search_compare | Compares PChome / momo / Yahoo Shopping / Coupang at once and returns the lowest price verified on its product page |
| `thsr-timetable` | form_submit | Taiwan High Speed Rail timetable (stations, date, time → list of trains) |

Every run returns `kev` (Kev call count, tokens and summed time).

### Price rule

`price` = the one-off price anyone can pay. First-purchase prices, card cashback and points go only in `conditional_offers` / `notes` and don't affect ranking.
Items priced far from the median (< 0.5× or > 2×) move to `suspicious`, are left out of ranking, and need Claude to review them.

### Development

```bash
uv run pytest -q          # unit tests (the price rule uses 83 real product cards)
uvx pyright               # type check
uv run python tests/mcp_e2e.py "PS5 Pro" "Sony PlayStation 5 Pro 主機(全新)" "ps5pro,playstation5pro;主機"   # run the price-comparison recipe through MCP
uv run python tests/mcp_recipe_flow.py <recipe.json> '<params json>' [--save]   # the skill's flow: dry_run → save → find
```

Evaluation numbers are in `evals/price/README.md`; working records are in `.flightwake/` (in Chinese).
