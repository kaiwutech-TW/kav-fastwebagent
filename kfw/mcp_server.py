"""Kav-FastwebAgent MCP server (stdio). Claude plans and writes recipes; Kav runs them fast and locally.

Run: uv run python -m kfw.mcp_server   (registered for Claude Code in .mcp.json)
Needs Kev on KFW_KEV (default :8009). Chrome is launched on KFW_CDP (default :9333) if absent.
Kept short on purpose: these instructions sit in every conversation. The how-to lives in the
kav-fastweb skill, loaded only when used.
"""

import anyio
import httpx
from mcp.server.mcpserver import MCPServer

from . import recipes, record
from .cdp import Browser
from .compare import CDP, KEV, ensure_chrome
from .inspect import inspect_page as _inspect

INSTRUCTIONS = ("Kav-FastwebAgent runs website tasks on this Mac from saved recipes (fast, local, code-verified). "
                "Always find_recipe first and run_recipe if one fits. Writing a new recipe: follow the kav-fastweb skill "
                "(inspect_page -> write -> dry_run -> save_recipe). It never logs in, solves captchas or buys; "
                "act on every needs_help reason it returns.")

server = MCPServer(name="kav-fastweb", instructions=INSTRUCTIONS)


def _thread(fn):
    return anyio.to_thread.run_sync(fn)


@server.tool()
async def find_recipe(request: str) -> dict:
    """Find saved recipes for a request or URL (e.g. "高鐵 台北到左營 時刻", "https://www.thsrc.com.tw/").
    Returns {"recipes": [...]} with name, type, description, status and the params each needs; empty = none yet."""
    return {"recipes": recipes.find(request)}


@server.tool()
async def run_recipe(name: str, params: dict, allow_stateful: bool = False) -> dict:
    """Run a saved recipe with params (see find_recipe for what each needs, formats are enforced).
    Returns status done | partial | needs_help, the results, and evidence (screenshot paths).
    allow_stateful: pass true ONLY when the user explicitly asked for this state-changing action (add to cart,
    subscribe, delete...). It applies to this call only, is never saved into the recipe and is not remembered for
    the next call. Payment, checkout, login and password/card fields are refused whatever this says."""
    try:
        return await _thread(lambda: recipes.execute(recipes.get(name), params, allow_stateful=allow_stateful))
    except recipes.RecipeError as e:
        return {"status": "error", "reason": "bad_request", "hint": str(e)}


@server.tool()
async def inspect_page(url: str) -> dict:
    """Compact structure of a page for writing a recipe: labelled fields with options, clickable labels,
    product list, repeated rows (time/price/date patterns), product structured data, blocked reason."""
    def work():
        ensure_chrome()
        b = Browser(CDP)
        try:
            return _inspect(b, url)
        finally:
            b.close()
    return await _thread(work)


@server.tool()
async def dry_run(recipe: dict, params: dict, allow_stateful: bool = False) -> dict:
    """Run an unsaved recipe once with example params. Returns dry_run_id, passed, and the full result.
    passed means the recipe's own completion check was met by code; inspect the evidence before saving.
    A dry run is a real run. allow_stateful: pass true ONLY when the user explicitly asked for this state-changing
    action; this call only, never saved into the recipe.
    A recipe with recorded_from always runs in a fresh isolated browser context (no cookies/storage from the Kav profile) and the
    result says `demo`: when the rendered actions equal the demonstration's, the replay is compared with what the user marked
    (match, diff). It never falls back to your profile. `unsupported` explains a demonstration that cannot be replayed."""
    try:
        return await _thread(lambda: recipes.dry_run(recipe, params, allow_stateful=allow_stateful))
    except recipes.RecipeError as e:
        return {"passed": False, "error": str(e)}


@server.tool()
async def save_recipe(recipe: dict, dry_run_id: str) -> dict:
    """Save a recipe. Refused unless dry_run_id is a passing dry run of this exact recipe. A recipe with recorded_from also needs a
    demo-value dry run that matched the demonstration and, with params, a passing isolated run with different actions."""
    try:
        return {"saved": await _thread(lambda: recipes.save(recipe, dry_run_id))}
    except recipes.RecipeError as e:
        return {"saved": None, "error": str(e)}


@server.tool()
async def list_recipes() -> dict:
    """The user's saved flows: {"recipes": {name: description, source user|builtin, example_params, last_verified}}."""
    return {"recipes": recipes.summary()}


@server.tool()
async def delete_recipe(name: str) -> dict:
    """Delete a user-saved recipe (moved to ~/.kav-fastweb/trash, recoverable). Built-ins cannot be deleted.
    Only when the user asked to delete that flow."""
    try:
        return recipes.delete(name)
    except recipes.RecipeError as e:
        return {"deleted": None, "error": str(e)}


@server.tool()
async def start_recording(url: str) -> dict:
    """Open url in the Kav Chrome (foreground tab) and record what the user does there, so a flow can be built from a
    demonstration. Returns {recording_id, state, tell_user}: say tell_user to the user. Only one recording at a time.
    Use only when the user said they will demonstrate, or agreed to when you offered. Never record logins or payments;
    password/card fields stop and delete the recording."""
    return await _thread(lambda: record.manager().start(url))


@server.tool()
async def stop_recording(recording_id: str, discard: bool = False, compare_to: str | None = None) -> dict:
    """Finish (or discard) a recording. Safe to call again: a finished recording returns the same result.
    Returns {state: completed|incomplete|discarded, reason?, draft, param_candidates, warnings, demo, live_checks, unsupported?,
    demo_summary, marked_summary, screenshot?, diff?}. draft is a form_submit / detail_extract / steps recipe skeleton built from what
    the user did (a candidate: fill name/description/params, columns and a specific rows.pattern; it carries recorded_from) or null
    with `unsupported: {reason, hint}` when this shape cannot be turned into a recipe yet (never silently reduced). live_checks
    says whether the candidate row pattern singled out the marked table on the page. compare_to=<recipe name> adds `diff`: what the
    demonstration does differently from that recipe. incomplete means Kav could not record everything (new tab, iframe, custom
    widget...): tell the user the reason. The summaries are what the user did and marked; they are not scrubbed of personal data."""
    return await _thread(lambda: record.manager().stop(recording_id, discard=discard, compare_to=compare_to))


@server.tool()
async def status() -> dict:
    """Are Kev and the Kav Chrome up; which recipes exist."""
    def check(url):
        try:
            return httpx.get(url, timeout=2).status_code == 200
        except httpx.HTTPError:
            return False
    return {"kev": {"url": KEV, "up": await _thread(lambda: check(KEV + "/v1/models"))},
            "chrome": {"url": CDP, "up": await _thread(lambda: check(CDP + "/json/version"))},
            "recipes": {n: {"type": r["type"], "status": r.get("status", "draft")} for n, r in recipes.load_all().items()}}


def main():
    server.run("stdio")


if __name__ == "__main__":
    main()

