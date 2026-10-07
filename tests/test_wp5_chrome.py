"""WP5 Chrome integration: steps' `pick` on tests/fixtures/site/pick_list.html -> pick_detail.html (isolated :9444
Chrome, KFW_CHROME_TESTS=1). Kev is a fake judge injected in place of recipes.Judge; the fixture pages count every
input-ish event (gate_counter.js), so "nothing was clicked" is measured, not assumed. One optional test talks to the
real Kev (KFW_KEV_TESTS=1, http://127.0.0.1:8009) and records what it says, thresholds untouched."""

import json
import os

import pytest

from kfw import recipes, steps
from kfw.judge import Judge

pytestmark = pytest.mark.chrome


class FakeJudge:
    """Stands in for Judge: records every choice_dist call; `answer(options)` returns the distribution."""
    def __init__(self, answer=None):
        self.answer, self.calls = answer, []

    def row_match(self, want, options, state=None):
        return self.choice_dist(want, options, state)

    def choice_dist(self, question, options, state=None):
        self.calls.append({"question": question, "options": dict(options), "state": state})
        if self.answer is None:
            raise AssertionError("Kev must not be asked here")
        return self.answer(options)

    def usage(self):
        return {"calls": len(self.calls)}


def use(monkeypatch, answer=None):
    fake = FakeJudge(answer)
    monkeypatch.setattr(recipes, "Judge", lambda *a, **k: fake)
    return fake


def dist(**named):
    """answer(): p for the option whose text contains the given word; the rest share what is left; none last."""
    def answer(options):
        p = {cid: 0.0 for cid in options} | {"none": 0.0}
        left = 1.0
        for word, val in named.items():
            hit = [cid for cid, text in options.items() if word in text]
            if word == "none":
                p["none"] = val
            elif hit:
                p[hit[0]] = val
            left -= val
        rest = [cid for cid in p if p[cid] == 0.0]
        for cid in rest:
            p[cid] = max(left, 0) / len(rest)
        return p
    return answer


def flow(chrome, query, want, click="查看", rows=None, expect=None):
    return {"name": "wp5-fixture", "type": "steps", "description": "fixture", "url": chrome.url("pick_list.html?" + query),
            "steps": [{"pick": {"rows": rows or {"pattern": r"NT\$"}, "want": want, "click": click}}],
            "result": {"expect_text": expect if expect is not None else ["詳情:" + want]}}


def run(r, **kw):
    return recipes.execute(r, {}, **kw)


def counts(load):
    return json.loads(load("gate_query.html").evaluate("localStorage.getItem('kfw_ev') || '{}'"))


def clear_counts(load):
    load("gate_query.html").evaluate("localStorage.removeItem('kfw_ev')")


def pick_log(out):
    return next(s for s in out["steps"] if "pick" in s)


# ---------- text matching: no Kev ----------

def test_exact_unique_hit_clicks_the_right_detail(chrome, monkeypatch):
    fake = use(monkeypatch)
    out = run(flow(chrome, "set=basic", "進階 Python 課程"))
    assert out["status"] == "done", out
    ev = pick_log(out)
    assert ev["how"] == "exact" and ev["chosen"]["id"] == "c2" and "進階 Python 課程" in ev["chosen"]["text"]
    assert [c["id"] for c in ev["attempts"][0]["candidates"]] == ["c1", "c2", "c3", "c4"] and "probabilities" not in ev
    assert ev["effect"] == "document" and ev["ready"] and fake.calls == []


def test_exact_beats_a_wider_contains(chrome, monkeypatch):
    fake = use(monkeypatch)  # "Python" is a whole cell of row 1 and only a part of row 2: exact wins, Kev not asked
    out = run(flow(chrome, "set=exactwins", "Python"))
    assert out["status"] == "done" and pick_log(out)["how"] == "exact" and pick_log(out)["chosen"]["id"] == "c1", out
    assert fake.calls == []


def test_contains_unique_hit(chrome, monkeypatch):
    fake = use(monkeypatch)
    out = run(flow(chrome, "set=basic", "資料庫", expect=["詳情:資料庫入門"]))
    assert out["status"] == "done" and pick_log(out)["how"] == "contains" and pick_log(out)["chosen"]["id"] == "c3", out
    assert fake.calls == []


# ---------- Kev decides: full distribution, threshold, stable ids ----------

def test_semantic_pick_with_confident_judge(chrome, monkeypatch):
    fake = use(monkeypatch, dist(退費=0.91, none=0.03))
    out = run(flow(chrome, "set=semantic", "想把錢退回來", expect=["詳情:退費申請表"]))
    assert out["status"] == "done", out
    ev = pick_log(out)
    assert ev["how"] == "kev" and ev["chosen"]["id"] == "c2" and ev["probabilities"]["c2"] == 0.91 and "kev_ms" in ev
    assert set(ev["probabilities"]) == {"c1", "c2", "c3", "c4", "none"}
    assert list(fake.calls[0]["options"]) == ["c1", "c2", "c3", "c4"] and "退費申請表" in fake.calls[0]["options"]["c2"]
    assert out["kev"] == {"calls": 1}


def test_none_highest_is_pick_uncertain_and_nothing_clicked(chrome, load, monkeypatch):
    use(monkeypatch, dist(none=0.9))
    clear_counts(load)
    out = run(flow(chrome, "set=nomatch", "想吃牛肉麵"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_uncertain" and out["why"] == "none_highest", out
    assert [c["id"] for c in out["candidates"]] == ["c1", "c2", "c3"] and out["probabilities"]["none"] == 0.9
    assert all(len(c["text"]) <= 80 for c in out["candidates"])
    assert counts(load) == {}


def test_same_text_rows_are_not_merged_and_are_uncertain(chrome, load, monkeypatch):
    fake = use(monkeypatch, lambda o: {"c1": 0.45, "c2": 0.45, "c3": 0.02, "none": 0.08})
    clear_counts(load)
    out = run(flow(chrome, "set=dupe", "熱門課程"))  # two exact hits: text cannot decide, Kev is asked
    assert out["status"] == "needs_help" and out["reason"] == "pick_uncertain", out
    assert list(fake.calls[0]["options"]) == ["c1", "c2", "c3"]
    assert fake.calls[0]["options"]["c1"] == fake.calls[0]["options"]["c2"]  # identical texts, two ids
    assert [c["id"] for c in out["candidates"]] == ["c1", "c2", "c3"]
    assert counts(load) == {}


def test_low_confidence_is_pick_uncertain(chrome, load, monkeypatch):
    use(monkeypatch, dist(退費=0.79, none=0.05))
    clear_counts(load)
    out = run(flow(chrome, "set=semantic", "想把錢退回來"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_uncertain" and out["why"] == "low_confidence", out
    assert counts(load) == {}


def test_small_gap_is_pick_uncertain(chrome, monkeypatch):
    use(monkeypatch, lambda o: {"c1": 0.0, "c2": 0.81, "c3": 0.52, "c4": 0.0, "none": 0.0})
    out = run(flow(chrome, "set=semantic", "想把錢退回來"))
    assert out["reason"] == "pick_uncertain" and out["why"] == "small_gap", out


def test_kev_failure_stops_never_guesses(chrome, load, monkeypatch):
    def boom(options):
        raise ValueError("Kev is down")
    use(monkeypatch, boom)
    clear_counts(load)
    out = run(flow(chrome, "set=semantic", "想把錢退回來"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_uncertain" and out["why"] == "kev_error", out
    assert "Kev is down" in pick_log(out)["attempts"][0]["kev_error"] and counts(load) == {}


def test_no_rows_is_pick_no_candidate(chrome, monkeypatch):
    use(monkeypatch)
    monkeypatch.setattr(steps, "THEN_CAP_S", 1.5)
    out = run(flow(chrome, "set=empty", "任何"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_no_candidate", out


def test_two_matching_lists_is_result_ambiguous(chrome, monkeypatch):
    use(monkeypatch)
    out = run(flow(chrome, "set=basic&two=1", "進階 Python 課程"))
    assert out["status"] == "needs_help" and out["reason"] == "result_ambiguous", out


# ---------- the control inside the chosen row ----------

def test_no_control_in_the_chosen_row_clicks_nothing(chrome, load, monkeypatch):
    use(monkeypatch)
    clear_counts(load)
    out = run(flow(chrome, "set=basic&mode=nocontrol", "進階 Python 課程"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_no_control" and out["why"] == "not_found", out
    assert out["chosen"]["id"] == "c2" and counts(load) == {}


def test_two_matching_controls_in_the_row_click_nothing(chrome, load, monkeypatch):
    use(monkeypatch)
    clear_counts(load)
    out = run(flow(chrome, "set=basic&mode=twobtn", "進階 Python 課程"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_control_ambiguous" and out["why"] == "ambiguous", out
    assert counts(load) == {}


def test_state_changing_button_is_refused_with_zero_events(chrome, load, monkeypatch):
    use(monkeypatch)
    clear_counts(load)
    out = run(flow(chrome, "set=basic&mode=cart", "進階 Python 課程", click="加入購物車"), allow_stateful=True)
    assert out["status"] == "needs_help" and out["reason"] == "stateful_not_authorized" and out["action"] == "pick", out
    assert counts(load) == {}  # even with allow_stateful: a pick can never be authorized


def test_click_that_does_nothing_is_pick_no_effect(chrome, monkeypatch):
    use(monkeypatch)
    monkeypatch.setattr(steps, "THEN_CAP_S", 2.0)
    out = run(flow(chrome, "set=basic&mode=noeffect", "進階 Python 課程"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_no_effect", out
    assert out["chosen"]["id"] == "c2"


# ---------- the list changes under the engine ----------

@pytest.mark.parametrize("mode", ["rerender", "text"])
def test_reordered_list_is_reobserved_and_the_right_row_is_clicked(chrome, monkeypatch, mode):
    use(monkeypatch)
    out = run(flow(chrome, f"set=basic&mode={mode}", "進階 Python 課程"))
    assert out["status"] == "done", out  # expect_text 詳情:進階 Python 課程 proves the detail page
    ev = pick_log(out)
    assert len(ev["attempts"]) == 2 and ev["attempts"][0]["stale"] in ("control_gone", "row_gone", "row_text_changed"), ev


def test_moved_row_nodes_keep_their_identity(chrome, monkeypatch):
    use(monkeypatch)  # two row nodes swapped places: the chosen node is the same node, its own link is clicked
    out = run(flow(chrome, "set=basic&mode=move", "進階 Python 課程"))
    assert out["status"] == "done", out
    assert len(pick_log(out)["attempts"]) == 1


def test_a_list_that_keeps_changing_is_pick_stale_and_clicks_nothing(chrome, load, monkeypatch):
    use(monkeypatch)
    clear_counts(load)
    out = run(flow(chrome, "set=basic&mode=always", "進階 Python 課程"))
    assert out["status"] == "needs_help" and out["reason"] == "pick_stale", out
    assert [a["stale"] for a in pick_log(out)["attempts"]] == ["control_gone", "control_gone"] and counts(load) == {}


def test_verify_pick_sees_each_kind_of_change(load):
    from kfw import form
    tab = load("pick_list.html?set=basic")

    def observe():
        obs = form.pick_groups(tab, r"NT\$", 1)
        g = obs["groups"][0]
        row = g["rows"][1]
        return obs["generation"], g["group_id"], row, row["controls"][0]["id"]

    def verify(o):
        gen, gid, row, cid = o
        return form.verify_pick(tab, row["row_id"], gid, row["text"], gen, cid)

    o = observe()
    form.pick_groups(tab, r"NT\$", 1)  # a newer observation clears the old marks (and bumps the generation)
    assert verify(o) == {"ok": False, "why": "row_gone"}
    o = observe()
    assert verify(o) == {"ok": True}
    tab.evaluate("document.querySelectorAll('.row')[1].firstElementChild.textContent += '!'")
    assert verify(o) == {"ok": False, "why": "row_text_changed"}
    o = observe()
    tab.evaluate("document.querySelectorAll('.row')[1].appendChild(document.querySelectorAll('.row')[2].querySelector('a'))")
    assert verify(o) == {"ok": False, "why": "row_text_changed"} or verify(o) == {"ok": False, "why": "control_moved"}
    o = observe()
    tab.evaluate("document.querySelectorAll('.row')[1].remove()")
    assert verify(o) == {"ok": False, "why": "row_gone"}


# ---------- optional: the real Kev ----------

@pytest.mark.skipif(os.environ.get("KFW_KEV_TESTS") != "1", reason="set KFW_KEV_TESTS=1 (Kev on http://127.0.0.1:8009)")
@pytest.mark.parametrize("want,expected", [
    ("想把錢退回來", "退費申請表"),
    ("我要請一天假", "請假單"),
    ("需要一張報稅用的收據", "發票補開"),
    ("想訂去東京的飛機", "機票訂位"),
    ("想吃牛肉麵", None),  # nothing fits: the right answer is to stop
])
def test_real_kev_semantic_pick(chrome, want, expected):
    if not Judge("http://127.0.0.1:8009").healthy():
        pytest.skip("Kev is not running on :8009")
    out = run(flow(chrome, "set=semantic", want, expect=["詳情:" + (expected or "")]))
    ev = pick_log(out)
    att = ev["attempts"][-1]
    chosen = att.get("chosen", {}).get("text", "")
    print(f"\n[real-kev] want={want!r} status={out['status']} reason={out.get('reason')} chosen={chosen[:12]!r} "
          f"p={att.get('probabilities')} kev_ms={att.get('kev_ms')} kev={out.get('kev')}")
    if expected:
        assert out["status"] == "done" or out["reason"] == "pick_uncertain", out  # wrong pick is the only failure
        assert expected in chosen or out["status"] != "done", out
    else:
        assert out["status"] == "needs_help", out
