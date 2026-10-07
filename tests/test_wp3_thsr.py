"""WP3 real site: the thsr-timetable form_submit recipe rewritten as an equivalent `steps` recipe, run side by side.
Needs the network and a headed isolated Chrome:  KFW_CHROME_TESTS=1 KFW_CHROME_HEADED=1 KFW_REAL_SITE=1 pytest -m chrome tests/test_wp3_thsr.py -s
The steps recipe lives only here (not in recipes/)."""

import copy
import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kfw import recipes

pytestmark = [pytest.mark.chrome, pytest.mark.skipif(os.environ.get("KFW_REAL_SITE") != "1", reason="set KFW_REAL_SITE=1 (real network)")]


def steps_version():
    fs = json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8"))
    r = {k: copy.deepcopy(fs[k]) for k in ("description", "domains", "intents", "params", "url", "result")}
    r.update(name="thsr-steps-test", type="steps", steps=[
        {"click": "不同意", "optional": True, "then": {"gone": "不同意"}},
        {"select": "出發站", "value": "{from}"},
        {"select": "到達站", "value": "{to}"},
        {"fill": "出發日期", "value": "{date}"},
        {"fill": "出發時間", "value": "{time}"},
        {"click": "查詢", "then": {"rows": True}},
    ])
    return r


def test_thsr_steps_matches_form_submit(chrome):
    date = (datetime.now(ZoneInfo("Asia/Taipei")) + timedelta(days=7)).strftime("%Y/%m/%d")
    params = {"from": "台中", "to": "台北", "date": date, "time": "15:00"}
    recipe = steps_version()
    recipes.validate(recipe)
    t0 = time.perf_counter()
    a = recipes.execute(recipe, params)
    t_steps = time.perf_counter() - t0
    t0 = time.perf_counter()
    b = recipes.execute(json.load(open(recipes.BUILTIN / "thsr-timetable.json", encoding="utf-8")), params)
    t_form = time.perf_counter() - t0
    print(f"\n[thsr] params={params}\n[thsr] steps: {a['status']} rows={a.get('rows_total')} {t_steps:.1f}s kev={a['kev']}"
          f"\n[thsr] form_submit: {b['status']} rows={b.get('rows_total')} {t_form:.1f}s kev={b['kev']}")
    print("[thsr] steps log:", json.dumps(a["steps"], ensure_ascii=False))
    assert a["status"] == "done", a
    assert b["status"] == "done", b
    assert a["rows"] == b["rows"] and a["rows_total"] == b["rows_total"] > 0
