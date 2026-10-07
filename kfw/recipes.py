"""Recipes: declarative "site x action" programs that Claude writes once and Kav runs fast.

A recipe is JSON data, never code. Engines (form_submit, search_compare, detail_extract) execute it
with kfw's generic parts; Kev only answers fuzzy questions (which option means "Taipei"?).
A recipe can only be saved after a dry run of that exact recipe passed its own completion check.
"""

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import draft as draftmod, form, record, safety
from .compare import CDP, HOME, KEV, compare_price, ensure_chrome
from .cdp import Browser
from .judge import Judge, normalize
from .page import ObservedTab
from .sites import classify
from .verify import read_product

BUILTIN = Path(__file__).resolve().parent.parent / "recipes"
USER = HOME / "recipes"
DRYRUNS = HOME / "dryruns"
TYPES = ("form_submit", "search_compare", "detail_extract", "steps")

# Every field the engine reads. Anything else is refused: a running MCP server keeps its old code, and a
# check it does not know (e.g. expect_text added later) would otherwise be skipped while still reporting done
# (TRAPS old-engine-silently-ignores-new-recipe-checks).
_COMMON = {"name", "type", "description", "domains", "intents", "params", "status", "verified_runs", "recorded_from"}
_ROWS = {"pattern", "min_rows", "max_rows", "columns"}
_SCHEMA = {
    "form_submit": {"url": None, "pre": {"click", "optional"}, "fields": {"label", "kind", "value"},
                    "submit": {"click"}, "result": {"rows": _ROWS, "expect_text": None}},
    "search_compare": {"search": None, "per_site": None, "verify_top": None},
    "detail_extract": {"url": None, "rows": _ROWS, "expect_text": None},
    # steps: each step and its `then` / `wait` are checked recursively by _check_steps
    "steps": {"url": None, "steps": None, "result": {"rows": _ROWS, "expect_text": None}},
}
_PARAM_KEYS = {"description", "example", "pattern", "required"}


class RecipeError(ValueError):
    pass


# ---------- storage ----------

def recipe_hash(recipe):
    body = {k: v for k, v in recipe.items() if k not in ("status", "verified_runs")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def load_all():
    out = {}
    for d in (BUILTIN, USER):  # user recipes override built-ins of the same name
        if d.exists():
            for p in sorted(d.glob("*.json")):
                r = json.loads(p.read_text(encoding="utf-8"))
                out[r["name"]] = {**r, "_path": str(p)}
    return out


def get(name):
    r = load_all().get(name)
    if not r:
        raise RecipeError(f"no recipe named {name!r}")
    return r


def find(text):
    """Cheap lookup for the caller: match domains and intents against free text (a URL or a request)."""
    t = normalize(text)
    hits = []
    for r in load_all().values():
        score = sum(3 for d in r.get("domains", []) if normalize(d) in t) + sum(1 for i in r.get("intents", []) if normalize(i) in t)
        if score:
            hits.append((score, {"name": r["name"], "type": r["type"], "description": r.get("description", ""),
                                 "status": r.get("status", "draft"),
                                 "params": {k: v.get("description", "") + (f" 例:{v['example']}" if v.get("example") else "")
                                            for k, v in r.get("params", {}).items()}}))
    return [h for _, h in sorted(hits, key=lambda x: -x[0])]


def summary():
    """What the user has, in words they can act on: one entry per recipe, with an example request."""
    out = {}
    for name, r in load_all().items():
        runs = r.get("verified_runs") or []
        ex = {k: v.get("example") for k, v in r.get("params", {}).items() if v.get("example")}
        out[name] = {"description": r.get("description", ""), "status": r.get("status", "draft"),
                     "source": "user" if Path(r["_path"]).parent == USER else "builtin",
                     "example_params": ex, "last_verified": runs[-1]["at"] if runs else None}
    return out


def delete(name):
    """Move a user recipe to ~/.kav-fastweb/trash (recoverable). Built-ins cannot be deleted."""
    path = USER / f"{name}.json"
    if not path.exists():
        if (BUILTIN / f"{name}.json").exists():
            raise RecipeError(f"{name!r} is built in and cannot be deleted")
        raise RecipeError(f"no recipe named {name!r}")
    trash = HOME / "trash"
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{name}-{datetime.now().strftime('%y%m%d-%H%M%S')}.json"
    path.rename(dest)
    return {"deleted": name, "moved_to": str(dest), "builtin_remains": (BUILTIN / f"{name}.json").exists()}


def validate(recipe):
    for k in ("name", "type", "description"):
        if not recipe.get(k):
            raise RecipeError(f"recipe needs {k!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,60}", recipe["name"]):
        raise RecipeError("name: lowercase letters, digits and '-' only")
    if recipe["type"] not in TYPES:
        raise RecipeError(f"type must be one of {TYPES}")
    if recipe["type"] == "form_submit":
        for where, steps_ in (("pre", recipe.get("pre") or []), ("submit", [recipe.get("submit")])):
            if any(isinstance(x, dict) and "stateful" in x for x in steps_):
                raise RecipeError(f"{where}: form_submit does not support 'stateful' steps (a state-changing action "
                                  "cannot be re-run safely); such flows need the steps type, and every run also needs allow_stateful")
    _check_keys(recipe)
    if "recorded_from" in recipe:
        _check_recorded_from(recipe)
    if recipe["type"] == "steps":
        _check_steps(recipe)
    if recipe["type"] == "form_submit":
        for k in ("url", "fields", "submit", "result"):
            if k not in recipe:
                raise RecipeError(f"form_submit recipe needs {k!r}")
        if "rows" not in recipe["result"] and "expect_text" not in recipe["result"]:
            raise RecipeError("result needs rows and/or expect_text: completion must be checkable by code")
    rows = (recipe.get("result") or {}).get("rows") or recipe.get("rows") or {}
    cols = rows.get("columns") if isinstance(rows, dict) else None
    if cols is not None and not (isinstance(cols, list) and all(c is None or (isinstance(c, str) and c) for c in cols)
                                 and any(cols)):
        raise RecipeError("rows.columns: a list with one name per cell (null drops that cell), at least one name")
    if cols:
        names = [c for c in cols if c]
        dup = sorted({c for c in names if names.count(c) > 1})
        if dup:
            raise RecipeError(f"rows.columns: duplicate column name(s) {dup}; each named column must be unique "
                              "(a repeated name would overwrite the earlier cell)")
    if recipe["type"] == "search_compare" and "search" not in recipe:
        raise RecipeError("search_compare recipe needs 'search' (site -> URL template with {query})")
    if recipe["type"] == "detail_extract" and "url" not in recipe:
        raise RecipeError("detail_extract recipe needs 'url'")


def _check_recorded_from(recipe):
    """recorded_from: the 12-hex id of the demonstration this recipe was built from (design 7.4). Format and the shape of the
    result contract only; whether the recording exists and matches is dry_run's and save's business, never run_recipe's."""
    rid = recipe["recorded_from"]
    if not isinstance(rid, str) or not record.ID_RE.fullmatch(rid):
        raise RecipeError("recorded_from: the 12-hex id of a recording (from stop_recording)")
    res = recipe.get("result") if recipe["type"] in ("form_submit", "steps") else recipe
    res = res if isinstance(res, dict) else {}
    rows = res.get("rows")
    if rows is not None:
        if not isinstance(rows, dict) or not isinstance(rows.get("pattern"), str) or not rows["pattern"]:
            raise RecipeError("a recorded recipe's rows need a non-empty pattern (the draft's pattern is only a candidate: "
                              "write or confirm one that selects only the result table)")
    else:
        et = res.get("expect_text")
        if not (isinstance(et, list) and et and all(isinstance(x, str) and x.strip() for x in et)):
            raise RecipeError("a recorded recipe without rows needs a non-empty expect_text (text the result must contain)")


def _unknown(where, got, allowed):
    bad = sorted(k for k in got if k not in allowed and not k.startswith("_"))
    if bad:
        raise RecipeError(f"{where}: unsupported field(s) {bad} for this Kav engine. A typo, or a newer feature: "
                          "restart Claude Code so the latest kfw is loaded. Not running, so its checks are not skipped.")


def _check_keys(recipe):
    unknown = _unknown
    schema = _SCHEMA[recipe["type"]]
    unknown("recipe", recipe, _COMMON | set(schema))
    for name, p in recipe.get("params", {}).items():
        unknown(f"params.{name}", p, _PARAM_KEYS)
    for key, sub in schema.items():
        val = recipe.get(key)
        if sub is None or val is None:
            continue
        for i, item in enumerate(val if isinstance(val, list) else [val]):
            if not isinstance(item, dict):
                continue
            nested = sub if isinstance(sub, set) else set(sub)
            unknown(f"{key}[{i}]" if isinstance(val, list) else key, item, nested)
            if isinstance(sub, dict):
                for k2, sub2 in sub.items():
                    if isinstance(sub2, set) and isinstance(item.get(k2), dict):
                        unknown(f"{key}.{k2}", item[k2], sub2)


_STEP_OPS = ("click", "fill", "select", "check", "wait", "next_page", "pick")
_STEP_EXTRA = {"click": {"optional", "then", "stateful"}, "fill": {"value"}, "select": {"value"}, "check": {"value"},
               "wait": set(), "next_page": set(), "pick": set()}
_THEN_KINDS = ("text", "gone", "url_contains", "field", "rows")


def _check_next_page(w, st, is_last, res):
    """{"next_page": {"click", "max_pages", "end"}} (design 6.2): last step only, all three keys, no stateful."""
    if not is_last:
        raise RecipeError(f"{w}: next_page must be the last step (it collects every page and ends the flow)")
    np = st["next_page"]
    if not isinstance(np, dict):
        raise RecipeError(f"{w}.next_page: an object " + '{"click": "下一頁", "max_pages": 3, "end": "disabled"}')
    if "stateful" in np:
        raise RecipeError(f"{w}.next_page: a pager must not be stateful (a next-page button that changes state is refused, not authorized)")
    _unknown(f"{w}.next_page", np, {"click", "max_pages", "end"})
    if not isinstance(np.get("click"), str) or not np["click"].strip():
        raise RecipeError(f"{w}.next_page.click: the text of the next-page button, a non-empty string")
    mp = np.get("max_pages")
    if not isinstance(mp, int) or isinstance(mp, bool) or not 1 <= mp <= 10:
        raise RecipeError(f"{w}.next_page.max_pages: an integer 1-10 (total pages including the first), not {mp!r}")
    if np.get("end") not in ("disabled", "absent"):
        raise RecipeError(f"{w}.next_page.end: required, \"disabled\" or \"absent\" (what the last page shows in place of "
                          f"the button: observe it in the trial run and write it down), not {np.get('end')!r}")
    if not (res.get("rows") or {}).get("pattern"):
        raise RecipeError(f"{w}.next_page needs result.rows.pattern to say which table is the page's content")


def _check_pick(w, st):
    """{"pick": {"rows": {"pattern", "min_rows"?}, "want": "{title}", "click": "查看"}} (design 6.4): the one bounded
    exception to "one step, one target"; never stateful (a stateful-worded target is refused, not authorized)."""
    pk = st["pick"]
    if not isinstance(pk, dict):
        raise RecipeError(f"{w}.pick: an object " + '{"rows": {"pattern": "..."}, "want": "{title}", "click": "查看"}')
    if "stateful" in pk or "stateful" in st:
        raise RecipeError(f"{w}.pick: a pick must not be stateful (a state-changing target is refused, not authorized)")
    _unknown(f"{w}.pick", pk, {"rows", "want", "click"})
    rows = pk.get("rows")
    if not isinstance(rows, dict) or not isinstance(rows.get("pattern"), str) or not rows["pattern"]:
        raise RecipeError(f"{w}.pick.rows: an object with a non-empty 'pattern' (which list the candidates are)")
    _unknown(f"{w}.pick.rows", rows, {"pattern", "min_rows"})
    mr = rows.get("min_rows")
    if "min_rows" in rows and (not isinstance(mr, int) or isinstance(mr, bool) or mr < 1):
        raise RecipeError(f"{w}.pick.rows.min_rows: an integer >= 1, not {mr!r}")
    for k in ("want", "click"):
        if not isinstance(pk.get(k), str) or not pk[k].strip():
            raise RecipeError(f"{w}.pick.{k}: a non-empty string" + (" (may be a {param})" if k == "want" else ""))


def _check_steps(recipe):
    """Recursive schema for the `steps` type (design 6.1): exactly one operation per step, only the extra keys that
    operation allows, `then` with exactly one condition, and no unknown key at any depth."""
    if not isinstance(recipe.get("url"), str) or not recipe["url"]:
        raise RecipeError("steps recipe needs 'url' (the page the first step runs on)")
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        raise RecipeError("steps recipe needs a non-empty 'steps' list")
    res = recipe.get("result")
    if not isinstance(res, dict) or not (res.get("rows") or res.get("expect_text")):
        raise RecipeError("result needs rows and/or a non-empty expect_text: completion must be checkable by code "
                          "(the last page having something on it is not proof)")
    if "rows" in res and not (isinstance(res["rows"], dict) and isinstance(res["rows"].get("pattern"), str) and res["rows"]["pattern"]):
        raise RecipeError("result.rows must be an object with a non-empty 'pattern'")
    for i, st in enumerate(steps):
        w = f"steps[{i}]"
        if not isinstance(st, dict):
            raise RecipeError(f"{w}: a step is an object such as " + '{"click": "查詢", "then": {...}}')
        ops = [k for k in st if k in _STEP_OPS]
        if len(ops) != 1:
            raise RecipeError(f"{w}: exactly one operation key of {_STEP_OPS} per step (found {ops or 'none'}); "
                              "put a second action in its own step")
        op = ops[0]
        _unknown(w, st, {op} | _STEP_EXTRA[op])
        if op == "next_page":
            _check_next_page(w, st, i == len(steps) - 1, res)
            continue
        if op == "pick":
            _check_pick(w, st)
            continue
        if op == "wait":
            wait = st["wait"]
            if not isinstance(wait, dict) or set(wait) != {"text"} or not (isinstance(wait["text"], str) and wait["text"].strip()):
                raise RecipeError(f"{w}: wait is " + '{"wait": {"text": "non-empty text"}}')
            continue
        if not isinstance(st[op], str) or not st[op].strip():
            raise RecipeError(f"{w}.{op}: the label of the control must be a non-empty string")
        if op == "check":
            if not isinstance(st.get("value"), bool):
                raise RecipeError(f"{w}.value: check needs a JSON boolean (true/false), not {st.get('value')!r}; "
                                  "a string such as \"{flag}\" is never coerced")
        elif op in ("fill", "select"):
            if not isinstance(st.get("value"), str):
                raise RecipeError(f"{w}.value: {op} needs a string value")
        else:
            for k in ("optional", "stateful"):
                if k in st and not isinstance(st[k], bool):
                    raise RecipeError(f"{w}.{k}: must be true or false")
            then = st.get("then")
            if not isinstance(then, dict) or len(then) != 1:
                raise RecipeError(f"{w}: every click needs a 'then' with exactly one condition of {_THEN_KINDS}: "
                                  "the click's effect must be provable, not assumed")
            _unknown(f"{w}.then", then, set(_THEN_KINDS))
            kind, val = next(iter(then.items()))
            if kind == "rows":
                if val is not True:
                    raise RecipeError(f"{w}.then.rows must be true (a table matching result.rows.pattern changed)")
                if not (res.get("rows") or {}).get("pattern"):
                    raise RecipeError(f"{w}.then.rows needs result.rows.pattern to say which table")
            elif not isinstance(val, str) or not val.strip():
                raise RecipeError(f"{w}.then.{kind}: needs a non-empty string (an empty text is true on every page)")


def check_params(recipe, params):
    spec = recipe.get("params", {})
    missing = [k for k, v in spec.items() if v.get("required", True) and k not in params]
    if missing:
        raise RecipeError(f"missing params: {missing}")
    for k, v in spec.items():
        if k in params and v.get("pattern") and not re.fullmatch(v["pattern"], str(params[k])):
            raise RecipeError(f"param {k}={params[k]!r} does not match {v['pattern']} (example: {v.get('example')})")


def render(value, params):
    if isinstance(value, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(params.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [render(v, params) for v in value]
    if isinstance(value, dict):
        return {k: render(v, params) for k, v in value.items()}
    return value


def today():
    """Taiwan's date, as sites here print it. Recipes use {today} to prove a page is today's, not the model's say-so."""
    return datetime.now(ZoneInfo("Asia/Taipei")).strftime("%Y/%m/%d")


def render_recipe(recipe, params) -> dict:
    out = render(recipe, {"today": today(), **params})
    assert isinstance(out, dict)
    return out


def save(recipe, dry_run_id):
    validate(recipe)
    rec_path = DRYRUNS / f"{dry_run_id}.json"
    if not rec_path.exists():
        raise RecipeError("unknown dry_run_id; run dry_run first")
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    if rec["recipe_hash"] != recipe_hash(recipe):
        raise RecipeError("this recipe differs from the one that was dry-run; dry-run it again")
    if not rec["passed"]:
        raise RecipeError(f"dry run {dry_run_id} did not pass: {rec['result'].get('status')}")
    if recipe.get("recorded_from"):
        _check_recorded_evidence(recipe, rec)
    USER.mkdir(parents=True, exist_ok=True)
    path = USER / f"{recipe['name']}.json"
    prior = recipe.get("verified_runs")
    if prior is None and path.exists():  # callers usually pass the recipe without its history; keep it
        prior = json.loads(path.read_text(encoding="utf-8")).get("verified_runs", [])
    runs = (prior or []) + [{"at": rec["at"], "params": rec["params"], "evidence": rec["result"].get("evidence")}]
    out = {**{k: v for k, v in recipe.items() if not k.startswith("_")}, "status": "verified", "verified_runs": runs[-5:]}
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def _check_recorded_evidence(recipe, this_run):
    """save_recipe for a recipe built from a demonstration (design 7.4 (a)-(e), I9). Refuses, with the missing piece named:
      (d) the recording exists, is completed, not expired, and its files still hash to the digest;
      (a) a demo-value dry run of this exact recipe matched the demonstration (same recipe_hash and recording_digest);
      (b) with params: a passing run of this exact recipe whose rendered actions differ from (a)'s (the parameters really
          changed what was done); without params (b) does not apply;
      (c) the result rows' columns are filled;
      (e) the runs used as evidence ran in an isolated browser context (server-signed record, not editable after the fact).
    A recording belongs to one saved recipe: a second recipe borrowing it is refused."""
    rid = recipe["recorded_from"]
    rec = record.read_recording(rid)
    if not rec["ok"]:
        raise RecipeError(f"(d) {rec['why']}")
    for name, other in load_all().items():
        if other.get("recorded_from") == rid and name != recipe["name"]:
            raise RecipeError(f"錄製 {rid} 已經是流程 {name!r} 的示範證據;一份示範只能對應一份流程(要重用請重新錄一次)")
    h = recipe_hash(recipe)
    runs = []
    for p in sorted(DRYRUNS.glob("*.json")):
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(r, dict) and r.get("recipe_hash") == h and r.get("recorded_from") == rid:
            runs.append(r)
    if not _signed_ok(this_run):
        raise RecipeError("(e) 這筆試跑紀錄沒有 server 的簽章,或被改過;請重新 dry_run(隔離證據不能手寫)")
    good = [r for r in runs if _signed_ok(r) and r.get("passed") and r.get("recording_digest") == rec["digest"]]
    demo_all = [r for r in good if r.get("demo_run") and r.get("match") is True and r.get("comparator") == rec["draft"]["demo"]["comparator"]]
    if not demo_all:
        raise RecipeError("(a) 缺少「用示範值試跑、結果和示範一致(match: true)」的紀錄;請用草稿裡的示範值 dry_run 一次(recipe 不能改)")
    demo_runs = [r for r in demo_all if r.get("isolated") is True]
    if not demo_runs:
        raise RecipeError("(e) 示範值那次試跑沒有隔離瀏覽器環境的證據(isolated);請重新 dry_run")
    if recipe.get("params"):
        base = {r["rendered_actions_hash"] for r in demo_runs}
        changed = [r for r in good if r.get("rendered_actions_hash") not in base]
        if not changed:
            raise RecipeError("(b) 有 params 的流程還需要一次「換一組參數」的試跑通過,而且實際動作要和示範值那次不同"
                              "(參數真的改變了動作,不是塞一個沒用到的參數)")
        if not any(r.get("isolated") is True for r in changed):
            raise RecipeError("(e) 換參數那次試跑沒有隔離瀏覽器環境的證據(isolated);請重新 dry_run")
    rows = (recipe.get("result") or {}).get("rows") if recipe["type"] in ("form_submit", "steps") else recipe.get("rows")
    if rows and not (isinstance(rows, dict) and rows.get("columns")):
        raise RecipeError("(c) rows.columns 還沒填:草稿沒有自動填時,Claude 要依畫面填好每一格的欄名(不要的格填 null)")


# ---------- engines ----------

def _evidence_dir():
    d = HOME / "runs" / (datetime.now().strftime("%y%m%d-%H%M%S-") + uuid.uuid4().hex[:4])
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_control(ctrls, label, kinds):
    """Exact label first, then contains; ambiguity is reported, not guessed.
    Returns (control, None) or (None, {"why": "not_found" | "ambiguous", "candidates": n})."""
    cands = [c for c in ctrls if c["kind"] in kinds]
    n = normalize(label)
    exact = [c for c in cands if normalize(c["label"]) == n]
    if len(exact) == 1:
        return exact[0], None
    part = [c for c in cands if n in normalize(c["label"])]
    if len(part) == 1:
        return part[0], None
    found = exact or part
    return None, {"why": "ambiguous" if found else "not_found", "candidates": len(found)}


def _why(problem):
    return (problem or {}).get("why")


def _problem_text(label, problem):
    """The problem from _find_control in words Claude can act on."""
    if _why(problem) == "ambiguous":
        return f"ambiguous control labelled {label!r} ({(problem or {}).get('candidates')} candidates): more than one control matches, so none is guessed"
    return f"no control labelled {label!r} (0 candidates)"


def _resolve_option(judge, options, wanted, field_label):
    n = normalize(wanted)
    for o in options:
        if normalize(o) == n:
            return o, "exact"
    part = [o for o in options if n in normalize(o) or normalize(o) in n]
    if len(part) == 1:
        return part[0], "contains"
    ans = judge.choice(f"欄位「{field_label}」要選哪個選項才代表「{wanted}」?", options,
                       state={"欄位": field_label, "要的值": wanted})
    return ans["choice"], f"kev p={ans['p']:.2f}"


def _public(step):
    return {k: v for k, v in step.items() if not k.startswith("_")}


def _gate(tab, action, c, allow_stateful, steps):
    """The shared safety entry for one real action, called after the node is resolved and before any input is
    dispatched. The node is re-read now (form.describe), not taken from the earlier snapshot. Returns a needs_help
    result when refused, else None. form_submit steps are never stateful (design 4, B2)."""
    try:
        target = form.describe(tab, c["id"])
        url = tab.evaluate("location.href")
    except Exception:
        target, url = None, ""
    denied = safety.gate(action, target, url, stateful_step=False, allow_stateful=allow_stateful)
    if not denied:
        return None
    return {"status": "needs_help", "reason": denied["reason"], "hint": denied["hint"], "action": action,
            "target": c.get("label"), "steps": steps}


def _preflight(tab, r, allow_stateful, steps):
    """Gate every action that can already be resolved on the loaded page before anything is dispatched, so a
    refused recipe touches the page with zero input events. Controls that only appear after a pre-step are
    gated when they are reached (each action is gated again at dispatch time either way)."""
    ctrls = form.controls(tab)
    plan = [("click", ("button", "link"), p["click"]) for p in r.get("pre", [])]
    plan += [("select" if f["kind"] == "select" else "fill", ("select",) if f["kind"] == "select" else ("text",), f["label"])
             for f in r["fields"]]
    plan.append(("click", ("button", "link"), r["submit"]["click"]))
    for action, kinds, label in plan:
        c, _ = _find_control(ctrls, label, kinds)
        if c:
            denied = _gate(tab, action, c, allow_stateful, steps)
            if denied:
                return denied
    return None


def _fill_and_submit(tab, r, judge, steps, allow_stateful=False):
    """One pass: load the page, run pre-steps, fill fields, click submit, look for the click's effect.
    Returns a needs_help result, or None once submit was clicked (steps[-1] is the submit step)."""
    tab.navigate(r["url"])
    time.sleep(0.3)
    ready = tab.wait_ready(cap_ms=8000, net_quiet_ms=300, dom_quiet_ms=300)
    steps.append({"ready": ready.reason, "ms": ready.ms, "inflight": ready.inflight})
    denied = _preflight(tab, r, allow_stateful, steps)
    if denied:
        return denied
    for pre in r.get("pre", []):
        c, problem = _find_control(form.controls(tab), pre["click"], ("button", "link"))
        if c:
            denied = _gate(tab, "click", c, allow_stateful, steps)
            if denied:
                return denied
            steps.append({"pre": pre["click"], **_public(form.click(tab, c["id"]))})
            time.sleep(0.5)
        elif pre.get("optional") and _why(problem) == "not_found":  # optional skips absence only, never ambiguity
            steps.append({"pre": pre["click"], "skipped": _problem_text(pre["click"], problem)})
        else:
            return {"status": "needs_help", "reason": "pre_step_failed", "hint": _problem_text(pre["click"], problem),
                    "why": _why(problem), "steps": steps}
    ctrls, settled = form.settle_controls(tab)
    steps.append({"controls_settled": settled["ok"], "ms": settled["ms"]})
    for f in r["fields"]:
        kinds = ("select",) if f["kind"] == "select" else ("text",)
        c, problem = _find_control(ctrls, f["label"], kinds)
        if not c:
            return {"status": "needs_help", "reason": "field_not_found", "hint": _problem_text(f["label"], problem),
                    "why": _why(problem), "field": f["label"], "steps": steps,
                    "controls_seen": [x["label"] for x in ctrls if x["kind"] in kinds][:20]}
        denied = _gate(tab, "select" if f["kind"] == "select" else "fill", c, allow_stateful, steps)
        if denied:
            return denied
        if f["kind"] == "select":
            if normalize(c["value"]) == normalize(f["value"]):
                steps.append({"field": f["label"], "ok": True, "already": c["value"]})
                ctrls = form.controls(tab)
                continue
            opt, how = _resolve_option(judge, c["options"], f["value"], f["label"])
            res = form.select_option(tab, c["id"], opt)
            steps.append({"field": f["label"], "want": f["value"], "chose": opt, "how": how, **res})
        else:
            res = form.fill(tab, c["id"], f["value"])
            steps.append({"field": f["label"], "want": f["value"], **res})
        if not steps[-1].get("ok"):
            return {"status": "needs_help", "reason": "field_not_set", "hint": f"讀回的值不符:{steps[-1]}", "steps": steps}
        ctrls = form.controls(tab)
    c, problem = _find_control(form.controls(tab), r["submit"]["click"], ("button", "link"))
    if not c:
        return {"status": "needs_help", "reason": "submit_not_found", "hint": _problem_text(r["submit"]["click"], problem),
                "why": _why(problem), "steps": steps}
    denied = _gate(tab, "click", c, allow_stateful, steps)
    if denied:
        return denied
    clicked = form.click(tab, c["id"])
    step = {"submit": r["submit"]["click"], **_public(clicked)}
    if clicked.get("ok"):
        step["effect"], step["effect_ms"] = form.wait_submit_effect(tab, clicked)
    steps.append(step)
    return None


def label_rows(got, columns):
    """Name each cell so the answering model cannot misread a column (TRAPS unlabeled-row-columns-misread-by-
    answering-model). A row whose cell count differs is not labelled by guess: it is reported as unmatched."""
    if not columns:
        return got, 0
    out, bad = [], 0
    for row in got:
        if len(row) != len(columns):
            bad += 1
            continue
        out.append({c: v for c, v in zip(columns, row) if c})
    return out, bad


def _ambiguity(detail):
    """A result that more than one table satisfies is not guessed at (design 5.2): needs_help result_ambiguous."""
    n = detail.get("other_qualifying_groups", 0)
    if not n:
        return None
    return {"reason": "result_ambiguous",
            "hint": f"頁面上有 {n + 1} 張表同時符合 rows.pattern 與 min_rows,程式不猜是哪一張:"
                    "看截圖後把 pattern 改得更精確,讓只有想要的那張表符合"}


def skipped_note(n):
    """What Claude must see when the chosen list has rows its pattern did not match: a too-narrow pattern drops rows
    without any error (591: integer-only 坪 and `\\dF/\\dF` floors missed 4 of 30 cards, one of them the answer)."""
    if not n:
        return None
    return f"同一個列表裡有 {n} 列不符 rows.pattern、沒有列入結果:pattern 可能寫得太窄(格式細節和實際資料不同),看截圖後只鎖每列一定有的錨"


def _result_rows(tab, spec, wait=True):
    """The result rows for a `rows` spec, whether the page is ambiguous about them, the wait, and how many rows of the
    chosen list the pattern skipped. wait=True first waits until the count is stable (form_submit); the final read is rows_detail."""
    pattern, min_rows = spec["pattern"], spec.get("min_rows", 1)
    wait_ms = 0
    if wait:
        got, wait_ms = form.wait_rows(tab, pattern, min_rows)
        if not got:
            return [], None, wait_ms, 0
    detail = form.rows_detail(tab, pattern, min_rows)
    return detail["rows"], _ambiguity(detail), wait_ms, detail.get("rows_skipped", 0)


def _open_tab(browser, browser_context_id):
    return ObservedTab.open(browser, browser_context_id=browser_context_id) if browser_context_id else ObservedTab.open(browser)


def _demo_compare(tab, rows_spec, demo):
    """The demonstration-consistency comparison (design 7.4) on the replayed page, run before the tab closes.
    demo = {comparator, group, text} from the recording. -> {comparator, match, diff}."""
    name = demo["comparator"]
    try:
        if name == "rows-exact-v1":
            if not rows_spec or not rows_spec.get("pattern"):
                match, diff = False, {"comparator": name, "why": "配方沒有 rows.pattern,無法取得要比對的表"}
            else:
                got = form.pick_groups(tab, rows_spec["pattern"], rows_spec.get("min_rows", 1))["groups"]
                if len(got) != 1:
                    match, diff = False, {"comparator": name, "why": f"重播後符合 pattern 的表有 {len(got)} 張,不是恰好 1 張"}
                else:
                    g = got[0]
                    match, diff = draftmod.compare_rows_exact(
                        demo["group"], {"rows": [x["cells"] for x in g["rows"]], "total": g["total"], "truncated": g["total"] > len(g["rows"])})
        else:
            match, diff = draftmod.compare_text_contains(demo["text"], tab.evaluate("document.body?.innerText || ''") or "")
    except Exception as e:  # noqa: BLE001 - a comparison that cannot run is a mismatch, never a pass
        match, diff = False, {"comparator": name, "why": f"比對時出錯:{type(e).__name__}: {str(e)[:100]}"}
    return {"comparator": name, "match": match, "diff": diff}


def run_form_submit(recipe, params, browser, judge, shots, allow_stateful=False, browser_context_id=None, demo=None):
    r = render_recipe(recipe, params)
    steps = []
    tab = _open_tab(browser, browser_context_id)
    try:
        for attempt in (1, 2):
            if attempt == 2:
                steps.append({"retry": "按下送出後沒有任何反應(沒換頁、沒送請求、畫面沒變),重新載入頁面再跑一次"})
            failed = _fill_and_submit(tab, r, judge, steps, allow_stateful)
            if failed:
                return failed
            if steps[-1].get("effect") or not steps[-1].get("ok"):
                break
        res_spec, got, wait_ms, ambiguous, skipped = r["result"], [], 0, None, 0
        if "rows" in res_spec:
            got, ambiguous, wait_ms, skipped = _result_rows(tab, res_spec["rows"])
        else:
            tab.wait_ready(cap_ms=10000)
        got, unmatched = label_rows(got, res_spec.get("rows", {}).get("columns"))
        body = tab.evaluate("document.body?.innerText || ''") or ""
        missing = [t for t in res_spec.get("expect_text", []) if t not in body]
        shot = shots / "result.jpg"
        tab.screenshot(shot)
        ok = (not res_spec.get("rows") or len(got) >= res_spec["rows"].get("min_rows", 1)) and not missing and not unmatched
        ok = ok and not ambiguous
        status, reason, hint = ("done", None, None) if ok else classify(tab.evaluate("location.href"), body, 0)
        if ambiguous:
            status, reason, hint = "extraction_failed", ambiguous["reason"], ambiguous["hint"]
        elif not ok and status == "extraction_failed":
            status, reason, hint = "needs_help", "result_not_proven", f"結果沒有被程式證明:rows={len(got)} 缺少文字={missing}"
            if unmatched:
                hint += f"({unmatched} 列的格數和 columns 對不上:欄位可能變了,看截圖後修 columns)"
            if skipped:
                hint += f"({skipped_note(skipped)})"
            if steps[-1].get("ok") and not steps[-1].get("effect"):
                hint += "(重新載入後按下送出仍然沒有反應:看截圖確認按鈕是否可用,或網站改版)"
        out = {"status": status if ok else "needs_help", "reason": reason, "hint": hint,
               "rows": got[: res_spec.get("rows", {}).get("max_rows", 50)], "rows_total": len(got), "rows_skipped": skipped,
               "expect_text_missing": missing, "steps": steps, "result_wait_ms": wait_ms,
               "page_url": tab.evaluate("location.href"), "evidence": {"screenshot": str(shot)}}
        if skipped and ok:
            out["note"] = skipped_note(skipped)
        if demo:
            out["demo_compare"] = _demo_compare(tab, res_spec.get("rows"), demo)
        return out
    finally:
        try:
            tab.close()
        except Exception:
            pass


def run_detail_extract(recipe, params, browser, shots, browser_context_id=None, demo=None):
    r = render_recipe(recipe, params)
    tab = _open_tab(browser, browser_context_id)
    recorded = bool(r.get("recorded_from"))
    try:
        if recorded:  # a demonstrated page is judged by its result contract, not by product data (waiting for a price would only burn 8 s)
            ready = tab.goto(r["url"], cap_ms=10000)
            data, ms = None, ready.ms
            got, ambiguous, _, skipped = _result_rows(tab, r["rows"], wait=True) if "rows" in r else ([], None, 0, 0)
        else:
            tab.navigate(r["url"])
            data, ms = read_product(tab)
            got, ambiguous, _, skipped = _result_rows(tab, r["rows"], wait=False) if "rows" in r else ([], None, 0, 0)
        got, unmatched = label_rows(got, r.get("rows", {}).get("columns"))
        body = tab.evaluate("document.body?.innerText || ''") or ""
        missing = [t for t in r.get("expect_text", []) if t not in body]
        shot = shots / "detail.jpg"
        tab.screenshot(shot)
        # text-contains-v1 (I5): a recorded recipe with no rows is found when its own expect_text is on the page
        text_only = recorded and "rows" not in r and bool(r.get("expect_text"))
        found = bool(data) or bool(got) or text_only
        ok = found and not missing and not unmatched and not ambiguous
        reason = (None if ok else ambiguous["reason"] if ambiguous
                  else "result_not_proven" if found or unmatched else "no_structured_data")
        hint = (ambiguous["hint"] if ambiguous else f"頁面上缺少必須出現的文字={missing}(例如日期不是今天:資料可能還沒更新)" if found and missing
                else f"{unmatched} 列的格數和 columns 對不上:欄位可能變了,看截圖後修 columns" if unmatched else None)
        out = {"status": "done" if ok else "needs_help", "reason": reason, "hint": hint, "expect_text_missing": missing,
               "product": data, "rows": got[:50], "rows_skipped": skipped, "evidence": {"screenshot": str(shot)}, "read_ms": ms}
        if skipped:
            out["note"] = skipped_note(skipped)
        if demo:
            out["demo_compare"] = _demo_compare(tab, r.get("rows"), demo)
        return out
    finally:
        try:
            tab.close()
        except Exception:
            pass


def execute(recipe, params, allow_stateful=False, isolated=False, demo=None):
    """Run a recipe. allow_stateful: True only when the user explicitly asked for this state-changing action in
    this call; it belongs to this call alone (never stored in the recipe, never inherited by the next run).
    isolated: run in a brand-new browser context (no cookies / storage of the Kav profile; disposed afterwards). If that
    cannot be made the run fails: it never falls back to the default profile (I8). The result's `isolated` says what
    actually happened. demo: the demonstration comparison to make on the result (dry_run of a recorded recipe)."""
    validate(recipe)
    check_params(recipe, params)
    t0 = time.perf_counter()
    if recipe["type"] == "search_compare":
        p = render_recipe(recipe, params)
        out = compare_price(params["query"], params.get("spec", params["query"]), params["must"], params.get("must_not", []),
                            sites=list(p["search"]), per_site=p.get("per_site", 10), verify_top=p.get("verify_top", 3),
                            search_urls=p["search"])
        out["evidence"] = {"dir": out.get("evidence_dir")}
        out.setdefault("recipe", recipe["name"])
        return out
    judge = Judge(KEV)
    ensure_chrome()
    browser = Browser(CDP)
    shots = _evidence_dir()
    ctx = None
    try:
        if isolated:
            if recipe["type"] not in ("form_submit", "detail_extract", "steps"):
                raise RecipeError(f"isolated runs support form_submit, detail_extract and steps, not {recipe['type']}")
            try:
                ctx = browser.send("Target.createBrowserContext")["browserContextId"]
            except Exception as e:  # noqa: BLE001 - no fallback to the default profile, ever
                return {"status": "error", "reason": "isolation_unavailable", "isolated": False, "recipe": recipe["name"],
                        "hint": f"沒能建立隔離的瀏覽器環境({e});示範一致檢查必須在乾淨環境跑,不會改用預設 profile。"}
        if recipe["type"] == "steps":
            from .steps import run_steps  # steps imports this module, so import it here
            out = run_steps(recipe, params, browser, judge, shots, allow_stateful=allow_stateful, browser_context_id=ctx, demo=demo)
        elif recipe["type"] == "form_submit":
            out = run_form_submit(recipe, params, browser, judge, shots, allow_stateful, browser_context_id=ctx, demo=demo)
        else:
            out = run_detail_extract(recipe, params, browser, shots, browser_context_id=ctx, demo=demo)
        out["isolated"] = ctx is not None      # written by the server from what really ran, never from the caller
    finally:
        if ctx is not None:
            try:
                browser.send("Target.disposeBrowserContext", browserContextId=ctx)
            except Exception:  # noqa: BLE001
                pass
        browser.close()
    out.update(recipe=recipe["name"], kev=judge.usage(), total_ms=round((time.perf_counter() - t0) * 1000))
    return out


def _key():
    """The server's own secret for signing dry-run evidence of recorded recipes (a record on disk cannot claim `isolated`
    or `match` by being edited or hand-written)."""
    path = DRYRUNS.parent / "dryrun.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
    return path.read_bytes()


_SIGNED = ("run_id", "recipe_hash", "recorded_from", "recording_digest", "rendered_actions_hash", "demo_run", "comparator", "match",
           "isolated", "passed")


def _sign(rec):
    body = json.dumps({k: rec.get(k) for k in _SIGNED}, sort_keys=True, ensure_ascii=False).encode()
    return hmac.new(_key(), body, hashlib.sha256).hexdigest()


def _signed_ok(rec):
    return isinstance(rec.get("sig"), str) and hmac.compare_digest(rec["sig"], _sign(rec))


def _unsupported_after_failed_demo(d_demo, comparison):
    """Why a demonstration run that did not reproduce the demo is (probably) out of scope, or None when the engine itself failed
    (its own reason/hint says what to fix). Isolation removes the demo's browser state, not the server's transactions: this
    is not a stateful sandbox, and dropping recorded_from is not a way around it."""
    if comparison.get("match") is not False:  # the run never reached a mismatching comparison: the engine failed first
        return None
    via = draftmod.via_widget_labels(d_demo.get("actions"))
    if via:
        return {"reason": "widget_value_not_replayable",
                "hint": f"欄位 {via} 的值是示範時透過頁面元件(如日期選擇器、自動完成)設定的;改成直接填值後,在乾淨環境重播的結果和示範不一致。"
                        "這種欄位錄製 v1 無法重播:請改用手寫流程(照一般流程試跑驗證)。"}
    return {"reason": "needs_profile_state",
            "hint": "在乾淨的隔離瀏覽器環境用示範值重播,結果和示範不一致。可能這個任務需要示範當下的 profile 狀態(登入、網站記住的選項、"
                    "先前操作留下的 cookie/storage),或草稿漏掉了某個操作,或結果本身會變動。錄製 v1 不支援需要 profile 狀態的任務,"
                    "也不會自動改用你的 profile 重跑;可改用手寫流程並照一般流程驗證。隔離的是瀏覽器狀態,不是網站伺服器端的交易,"
                    "也不能靠刪掉 recorded_from 來避開這個檢查。"}


def dry_run(recipe, params, allow_stateful=False):
    """Run an unsaved recipe; record whether it passed so save() can require it. A dry run is a real run, so
    allow_stateful means the same as in execute().

    A recipe with `recorded_from` always runs in a fresh isolated browser context (design 7.4, I8) and is compared with the
    demonstration when its rendered actions equal the demonstrated ones (a demo-value run)."""
    validate(recipe)
    rid = recipe.get("recorded_from")
    if not rid:
        result = execute(recipe, params, allow_stateful)
        if recipe["type"] == "steps":  # the result's own proof (rows and/or expect_text) already ran; no partial
            passed = result.get("status") == "done"
        else:
            passed = result.get("status") in ("done", "partial") and bool(result.get("rows") or result.get("offers") or result.get("product"))
        return _write_dry_run(recipe, params, result, passed)
    if recipe["type"] not in ("form_submit", "detail_extract", "steps"):
        raise RecipeError(f"recorded_from is supported for form_submit, detail_extract and steps recipes, not {recipe['type']}")
    rec = record.read_recording(rid)
    if not rec["ok"]:
        raise RecipeError(rec["why"])
    d = rec["draft"]
    if not d.get("draft") or not d.get("demo"):
        raise RecipeError(f"錄製 {rid} 沒有可用的草稿({(d.get('unsupported') or {}).get('reason') or d.get('state')}),不能當示範證據;請重錄")
    check_params(recipe, params)
    actions = draftmod.rendered_actions(render_recipe(recipe, params))
    d_demo = d["demo"]
    is_demo = draftmod.is_demo_run(actions, d_demo["actions"])
    demo = {"comparator": d_demo["comparator"], "group": (rec["mark"] or {}).get("group"), "text": (rec["mark"] or {}).get("text", "")} if is_demo else None
    result = execute(recipe, params, allow_stateful, isolated=True, demo=demo)
    cmp_ = result.get("demo_compare") or {}
    text_mode = d_demo["comparator"] == "text-contains-v1"
    engine_ok = result.get("status") == "done" and (text_mode or bool(result.get("rows")))
    isolated = result.get("isolated") is True
    passed = engine_ok and isolated and (not is_demo or cmp_.get("match") is True)
    extra = {"recorded_from": rid, "recording_digest": rec["digest"], "rendered_actions_hash": draftmod.actions_hash(actions),
             "demo_run": is_demo, "comparator": d_demo["comparator"] if is_demo else None,
             "match": cmp_.get("match") if is_demo else None, "diff": cmp_.get("diff") if is_demo else None, "isolated": isolated}
    out = _write_dry_run(recipe, params, result, passed, extra)
    out["demo"] = {"demo_run": is_demo, "comparator": extra["comparator"], "match": extra["match"], "diff": extra["diff"], "isolated": isolated}
    if is_demo and not passed and isolated:
        unsup = _unsupported_after_failed_demo(d_demo, cmp_)
        if unsup:
            out["unsupported"] = unsup
    if not is_demo:
        out["demo"]["note"] = "這次的動作值和示範不同,只驗證引擎能完成;示範一致要另跑一次「用示範值」的試跑。"
    return out


def _write_dry_run(recipe, params, result, passed, extra=None):
    run_id = uuid.uuid4().hex[:12]
    DRYRUNS.mkdir(parents=True, exist_ok=True)
    rec = {"run_id": run_id, "at": datetime.now().isoformat(timespec="seconds"), "recipe_hash": recipe_hash(recipe),
           "params": params, "passed": passed, "result": {k: result.get(k) for k in ("status", "reason", "evidence", "rows_total")}}
    if extra:
        rec.update(extra)
        rec["sig"] = _sign(rec)
    (DRYRUNS / f"{run_id}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"dry_run_id": run_id, "passed": passed, "result": result}
