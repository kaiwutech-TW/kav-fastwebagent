"""WP1 Chrome integration: the recorder in a real (isolated, :9444) Chrome. Run with KFW_CHROME_TESTS=1.
Fixture sites: tests/fixtures/site/rec_*.html on a.test / b.test (host-resolver-rules). The 'user' is a second CDP
connection (rec_helpers.Sim) sending Input.* events; nothing here touches :9333 or ~/.kav-fastweb."""

import json
import time

import pytest

from chrome_harness import CDP_URL
from rec_helpers import ALT, CTRL, Sim, groups_of, settle

from kfw import form, record
from kfw.cdp import Browser, wait_until

pytestmark = pytest.mark.chrome


@pytest.fixture
def mgr(chrome, tmp_path):
    chrome.check_identity()
    b = Browser(CDP_URL)
    before = {t["targetId"] for t in b.send("Target.getTargets")["targetInfos"] if t["type"] == "page"}
    m = record.Manager(home=tmp_path, browser_factory=lambda: Browser(CDP_URL))
    yield m
    a = m.active()
    if a is not None:
        a.finish(discard=True)
    for t in b.send("Target.getTargets")["targetInfos"]:
        if t["type"] == "page" and t["targetId"] not in before:
            try:
                b.send("Target.closeTarget", targetId=t["targetId"])
            except Exception:
                pass
    b.close()


class Session:
    """A started recording plus the user simulator."""

    def __init__(self, mgr, chrome, page, host="a.test"):
        self.mgr, self.chrome = mgr, chrome
        self.url = chrome.url(page, host)
        self.started = mgr.start(self.url)
        assert self.started["state"] == "recording", self.started
        self.id = self.started["recording_id"]
        self.rec = mgr.active()
        assert self.rec is not None
        self.sim = Sim(self.rec.target_id)
        self.dir = mgr.root / self.id

    def wait_groups(self, n, closed=True, timeout=5):
        ok = wait_until(lambda: len([g for g in groups_of(self.rec) if g["closed"] or not closed]) >= n, timeout)
        assert ok, groups_of(self.rec)
        return groups_of(self.rec)

    def stop(self, **kw):
        res = self.mgr.stop(self.id, **kw)
        self.sim.close()
        return res

    def log(self):
        return record.read_log(self.dir)


@pytest.fixture
def start(mgr, chrome):
    made = []

    def _start(page, host="a.test"):
        s = Session(mgr, chrome, page, host)
        made.append(s)
        return s
    yield _start
    for s in made:
        try:
            s.sim.close()
        except Exception:
            pass


def kinds(rec):
    return [g["kind"] for g in groups_of(rec)]


def test_start_arms_and_the_bar_is_visible_and_clickable(start):
    s = start("rec_form.html")
    assert "tell_user" in s.started
    info = s.sim.info()
    assert info["visible"] and info["connected"] and info["hit"] is True
    d = s.rec.debug()
    assert d["state"] == "recording" and d["armed"] and d["epoch"] == 1
    assert "http" in s.rec.url


# ---------- action groups: one user action = one group ----------

def changes(s, g):
    snaps = record.read_snapshots(s.dir)
    return record.snap_diff(snaps.get(g["prev"]), snaps.get(g["snap"]))


def test_single_insert_text_is_one_group(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.insert("王小明")
    gs = s.wait_groups(2)
    assert [g["kind"] for g in gs] == ["pointer", "text_input"]
    ch = changes(s, gs[1])
    assert [(c["label"], c["after"]) for c in ch] == [("姓名", "王小明")]
    res = s.stop()
    assert res["state"] == "completed", res


def test_per_key_typing_is_one_group(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.type_keys("abcd")
    gs = s.wait_groups(2)
    assert [g["kind"] for g in gs] == ["pointer", "text_input"]
    assert changes(s, gs[1])[0]["after"] == "abcd"
    assert s.rec.debug()["reasons"] == []


def test_paste_is_one_group(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.insert("貼上的內容")
    s.wait_groups(2)
    s.sim.key("a", code="KeyA", modifiers=4, commands=["selectAll"])
    s.sim.key("c", code="KeyC", modifiers=4, commands=["copy"])
    s.sim.focus_by_click("#memo")
    s.sim.key("v", code="KeyV", modifiers=4, commands=["paste"])
    assert wait_until(lambda: s.sim.ev("document.getElementById('memo').value") == "貼上的內容", 3), "the paste did not reach the page"
    gs = s.wait_groups(5)
    kinds_ = [g["kind"] for g in gs]
    assert kinds_.count("paste") == 1, kinds_            # the paste is exactly one group (not paste + text_input)
    last = [g for g in gs if g["kind"] == "paste"][0]
    assert [(c["label"], c["after"]) for c in changes(s, last)] == [("備註", "貼上的內容")]


def test_ime_composition_is_one_group(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.call("Input.imeSetComposition", text="ㄋ", selectionStart=1, selectionEnd=1)
    s.sim.call("Input.imeSetComposition", text="你", selectionStart=1, selectionEnd=1)
    s.sim.insert("你好")
    gs = s.wait_groups(2)
    assert [g["kind"] for g in gs] == ["pointer", "ime"]
    assert changes(s, gs[1])[0]["after"] == "你好"


def test_click_button_with_many_events_is_one_group(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    gs = s.wait_groups(1)
    assert len(gs) == 1 and gs[0]["kind"] == "pointer"
    assert gs[0]["target"]["is_button_like"] and gs[0]["target"]["label"] == "按我"
    assert s.sim.ev("window.__clicks") == 1
    settle(0.5)
    assert len(groups_of(s.rec)) == 1


def test_select_change_is_one_group(start):
    s = start("rec_form.html")
    s.sim.ev("document.getElementById('city').focus()")
    s.sim.key("k", code="KeyK", text="k")               # type-ahead on the focused select
    gs = s.wait_groups(1)
    assert len(gs) == 1
    ch = changes(s, gs[0])
    assert [(c["label"], c["after"]) for c in ch] == [("城市", "Kaohsiung")]
    settle(0.4)
    assert len(groups_of(s.rec)) == 1


def test_form_submit_click_is_one_group_and_the_result_page_is_a_new_epoch(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.insert("甲")
    s.wait_groups(2)
    s.sim.click("#go")                       # pointerdown, mouseup, click, submit, navigation
    assert wait_until(lambda: s.rec.debug()["epoch"] == 2 and s.rec.debug()["armed"], 8)
    gs = groups_of(s.rec)
    assert [g["kind"] for g in gs] == ["pointer", "text_input", "pointer"]
    submit = gs[2]
    assert submit["target"]["label"] == "查詢" and submit["closed"] and not submit.get("synthetic")   # closed by beforeunload
    assert [c["after"] for c in changes(s, gs[1])] == ["甲"]
    res = s.stop()
    assert res["state"] == "completed", res
    lg = s.log()
    assert any(r["type"] == "group_close" and r.get("unloading") for r in lg)
    assert any(r["type"] == "group_nav" for r in lg)


# ---------- documents: navigation, reload, SPA, BFCache ----------

def hellos(s):
    return [r for r in s.log() if r["type"] == "hello"]


def wait_epoch(s, n, timeout=8):
    assert wait_until(lambda: (lambda d: d["epoch"] == n and d["armed"])(s.rec.debug()), timeout), s.rec.debug()


def test_cross_site_navigation_gets_a_new_epoch_and_recording_continues(start, chrome):
    s = start("rec_a.html")
    s.sim.focus_by_click("#inp")
    s.sim.insert("在 A")
    s.wait_groups(2)
    s.sim.click("#tob")                        # a.test -> b.test: another renderer process, same target and session
    wait_epoch(s, 2)
    s.sim.focus_by_click("#inp")
    s.sim.insert("在 B")
    gs = s.wait_groups(5)
    assert [g["epoch"] for g in gs] == [1, 1, 1, 2, 2]
    assert [h["href"].split("/")[2].split(":")[0] for h in hellos(s)] == ["a.test", "b.test"]
    res = s.stop()
    assert res["state"] == "completed", res
    assert [u["url"].split("/")[2].split(":")[0] for u in res["demo_summary"]["urls"]] == ["a.test", "b.test"]


def test_reload_is_a_new_epoch(start):
    s = start("rec_a.html")
    s.sim.focus_by_click("#inp")
    s.sim.insert("x")
    s.wait_groups(2)
    s.sim.call("Page.reload")
    wait_epoch(s, 2)
    assert [h["nav_type"] for h in hellos(s)] == ["navigate", "reload"]
    s.sim.focus_by_click("#inp")
    s.sim.insert("y")
    gs = s.wait_groups(4)
    assert [g["epoch"] for g in gs] == [1, 1, 2, 2]
    assert s.stop()["state"] == "completed"


def test_spa_navigation_does_not_make_a_new_hello(start):
    s = start("rec_a.html")
    s.sim.click("#push")
    s.wait_groups(1)
    s.sim.click("#push")
    s.wait_groups(2)
    assert s.rec.debug()["epoch"] == 1
    assert len(hellos(s)) == 1
    d = s.rec.debug()
    assert d["reasons"] == []
    navs = [r for r in s.log() if r["type"] == "nav" and r["how"] == "same_document"]
    assert len(navs) == 2
    assert d["last_seq"] > 4            # seq keeps counting through the SPA changes: still the same epoch
    assert s.stop()["state"] == "completed"


def test_bfcache_return_is_a_new_epoch_and_late_data_of_the_old_token_is_dropped(start, chrome):
    s = start("rec_a.html")
    s.sim.focus_by_click("#inp")
    s.sim.insert("A")
    s.wait_groups(2)
    s.sim.click("#tob")
    wait_epoch(s, 2)
    s.sim.back()
    wait_epoch(s, 3)
    # the document really came from BFCache: the page's own pageshow log says persisted
    assert wait_until(lambda: s.sim.ev("window.__pageshows") == [False, True], 3), s.sim.ev("window.__pageshows")
    assert [h["restored"] for h in hellos(s)] == [False, False, True]
    assert s.rec.debug()["reasons"] == []
    # late data carrying an old epoch's token must be dropped, not accepted and not an error
    old_token = sorted(s.rec._retired)[0]
    before = s.rec.debug()
    s.sim.iso("__kfwRec(JSON.stringify({type:'group_open', token: %s, seq: 999, gid:'gX', kind:'pointer', "
              "target:{tag:'A',native:false,in_controls:false,id:null,label:'',text:'',is_button_like:true,custom_element:false,iframe:false}, prev_snap:null}))"
              % json.dumps(old_token))
    assert wait_until(lambda: s.rec.debug()["stale_dropped"] == before["stale_dropped"] + 1, 3)
    d = s.rec.debug()
    assert d["reasons"] == [] and not any(g["gid"] == "gX" for g in d["groups"])
    s.sim.focus_by_click("#inp")               # the restored document records again, with the new token, seq from 1
    s.sim.insert("B")
    s.wait_groups(4)
    assert s.stop()["state"] == "completed"


# ---------- forged payloads ----------

def forge(s, payload_js, expect_reason, expect_detail=None):
    s.sim.iso(f"__kfwRec({payload_js})")
    assert wait_until(lambda: expect_reason in s.rec.debug()["reasons"], 3), s.rec.debug()
    if expect_detail:
        assert wait_until(lambda: any(r.get("detail") == expect_detail for r in s.log() if r["type"] == "incomplete"), 3), s.log()


def test_main_world_cannot_call_the_binding(start):
    s = start("rec_form.html")
    assert s.sim.ev("typeof window.__kfwRec + '|' + typeof window.__kfwArm + '|' + typeof window.__kfwTeardown + '|' + typeof window.__kfwFlush") \
        == "undefined|undefined|undefined|undefined"
    with pytest.raises(RuntimeError):
        s.sim.ev("window.__kfwRec('{}')")
    # a fake binding the page defines itself reaches nobody
    s.sim.ev("window.__kfwRec = function () { window.__fakeCalled = true; }; window.__kfwRec(JSON.stringify({type:'done'}))")
    settle(0.5)
    d = s.rec.debug()
    assert d["state"] == "recording" and d["reasons"] == [] and not s.rec._auto_finish


def test_wrong_token_is_dropped_and_marks_incomplete(start):
    s = start("rec_form.html")
    forge(s, "JSON.stringify({type:'group_open', token:'not-the-token', seq:1, gid:'g9', kind:'pointer', "
             "target:{tag:'A',native:false,in_controls:false,id:null,label:'',text:'',is_button_like:true,custom_element:false,iframe:false}, prev_snap:null})",
          "bad_payload", "bad_token")
    assert not any(g["gid"] == "g9" for g in s.rec.debug()["groups"])
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "bad_payload"


def test_skipped_seq_is_dropped_and_marks_incomplete(start):
    s = start("rec_form.html")
    tok = s.rec.epoch.token
    nxt = s.rec.debug()["last_seq"] + 5
    forge(s, "JSON.stringify({type:'flag', token:%s, seq:%d, reason:'new_tab'})" % (json.dumps(tok), nxt), "seq_gap")
    assert "new_tab" not in s.rec.debug()["reasons"]           # the skipped-ahead message itself was dropped
    assert s.stop()["reason"] == "seq_gap"


def test_oversized_payload_is_dropped_and_marks_incomplete(start):
    s = start("rec_form.html")
    tok = s.rec.epoch.token
    forge(s, "JSON.stringify({type:'flag', token:%s, seq:%d, reason:'new_tab', pad:'x'.repeat(70000)})"
          % (json.dumps(tok), s.rec.debug()["last_seq"] + 1), "bad_payload", "too_large")
    assert "new_tab" not in s.rec.debug()["reasons"]
    assert s.stop()["reason"] == "bad_payload"


def test_non_json_and_wrong_schema_are_dropped(start):
    s = start("rec_form.html")
    forge(s, "'{not json'", "bad_payload", "not_json")
    tok = s.rec.epoch.token
    s.sim.iso("__kfwRec(JSON.stringify({type:'group_open', token:%s, seq:%d, gid:'g1', kind:'teleport'}))"
              % (json.dumps(tok), s.rec.debug()["last_seq"] + 1))
    assert wait_until(lambda: any(r.get("detail", "").startswith("schema:group_open") for r in s.log() if r["type"] == "incomplete"), 3)


def test_binding_from_a_context_that_is_not_the_main_frame_kfw_rec_is_ignored(start):
    """A same-site iframe gets its own kfw_rec world; the recorder there sends no hello, and a forged hello from a
    non-main-frame context is refused because Python only knows main-frame kfw_rec contexts."""
    s = start("rec_iframe.html")
    d = s.rec.debug()
    assert d["epoch"] == 1 and len(d["ctx"]) == 1               # the iframe's world is not in the known contexts
    fid = s.sim.call("Page.getFrameTree")["frameTree"]["childFrames"][0]["frame"]["id"]
    iso = s.sim.call("Page.createIsolatedWorld", frameId=fid, worldName="kfw_rec")["executionContextId"]
    r = s.sim.call("Runtime.evaluate", contextId=iso, returnByValue=True,
                   expression="typeof __kfwRec === 'function' ? (__kfwRec(JSON.stringify({type:'hello', doc_id:'x', href:'http://x/', "
                              "restored:false, persisted:false, nav_type:null, ready_state:'complete'})), 'sent') : 'no-binding'")
    print("\n[iframe world] ", r["result"].get("value"))
    settle(0.4)
    assert s.rec.debug()["epoch"] == 1                            # no epoch was granted to it either way
    if r["result"].get("value") == "sent":
        assert "bad_payload" in s.rec.debug()["reasons"]


# ---------- new tab / iframe / custom elements ----------

def close_extra_tabs(keep):
    b = Browser(CDP_URL)
    try:
        for t in b.send("Target.getTargets")["targetInfos"]:
            if t["type"] == "page" and t["targetId"] != keep and t["url"].startswith("http"):
                try:
                    b.send("Target.closeTarget", targetId=t["targetId"])
                except Exception:
                    pass
    finally:
        b.close()


def test_target_blank_link_is_incomplete_new_tab(start):
    s = start("rec_newtab.html")
    s.sim.click("#blank")
    assert wait_until(lambda: "new_tab" in s.rec.debug()["reasons"], 5), s.rec.debug()
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "new_tab"
    close_extra_tabs(s.rec.target_id)


def test_ctrl_click_link_is_incomplete_new_tab(start):
    s = start("rec_newtab.html")
    s.sim.click("#plain", modifiers=CTRL)
    assert wait_until(lambda: "new_tab" in s.rec.debug()["reasons"], 5), s.rec.debug()
    assert s.stop()["reason"] == "new_tab"
    close_extra_tabs(s.rec.target_id)


def test_window_open_from_the_page_is_incomplete_new_tab(start):
    s = start("rec_newtab.html")
    # no click at all: only the target-level discovery can see this one (openerId == recording tab)
    s.sim.ev("(window.open('rec_b.html'), 1)", gesture=True)
    assert wait_until(lambda: "new_tab" in s.rec.debug()["reasons"], 5), s.rec.debug()
    assert any(r.get("opener") is True for r in s.log() if r["type"] == "incomplete" and r["reason"] == "new_tab")
    assert s.stop()["reason"] == "new_tab"
    close_extra_tabs(s.rec.target_id)


def test_a_tab_that_existed_before_the_recording_is_not_a_new_tab(mgr, chrome):
    b = Browser(CDP_URL)
    tid = b.send("Target.createTarget", url="about:blank")["targetId"]
    try:
        s = Session(mgr, chrome, "rec_form.html")
        settle(0.5)
        assert s.rec.debug()["reasons"] == []
        assert s.stop()["state"] == "completed"
    finally:
        b.send("Target.closeTarget", targetId=tid)
        b.close()


def test_click_inside_an_iframe_is_incomplete(start):
    s = start("rec_iframe.html")
    x, y, w, h = s.sim.rect("#fr")
    s.sim.click_at(x + 50, y + 20)                   # the frame's own input: the parent window blurs, activeElement is the iframe
    assert wait_until(lambda: "iframe_interaction" in s.rec.debug()["reasons"], 5), s.rec.debug()
    s.sim.insert("in the frame")
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "iframe_interaction"


def test_click_on_a_non_focusable_area_of_an_iframe_is_a_known_blind_spot(start):
    """Design 2.3 says this may go undetected. Recorded here as observed, not as a promise."""
    s = start("rec_iframe.html")
    x, y, w, h = s.sim.rect("#fr")
    s.sim.click_at(x + w - 20, y + h - 20)           # empty area inside the frame
    settle(0.6)
    detected = "iframe_interaction" in s.rec.debug()["reasons"]
    print(f"\n[blind spot] click on non-focusable iframe area detected={detected}")
    assert s.stop()["state"] in ("completed", "incomplete")


def test_custom_element_with_closed_shadow_root_is_incomplete(start):
    s = start("rec_custom.html")
    s.sim.click("#w1")                               # <my-widget>: the closed root's button is seen as its host
    assert wait_until(lambda: "custom_element_interaction" in s.rec.debug()["reasons"], 5), s.rec.debug()
    g = groups_of(s.rec)[0]
    assert g["target"]["custom_element"] and g["target"]["tag"] == "MY-WIDGET"
    assert s.stop()["reason"] == "custom_element_interaction"


def test_input_inside_an_open_shadow_root_is_incomplete(start):
    s = start("rec_custom.html")
    s.sim.click("#w2")
    assert wait_until(lambda: "custom_element_interaction" in s.rec.debug()["reasons"], 5), s.rec.debug()


def test_closed_shadow_root_under_a_plain_div_is_a_known_blind_spot(start):
    """A closed root hosted by a non-custom tag looks like an ordinary element from outside (design 2.3): NOT detected."""
    s = start("rec_custom.html")
    s.sim.click("#hostdiv")
    s.wait_groups(1)
    settle(0.5)
    d = s.rec.debug()
    print(f"\n[blind spot] closed root under <div>: reasons={d['reasons']}")
    assert "custom_element_interaction" not in d["reasons"]      # documents the gap; the demo-consistency replay is the backstop


# ---------- sensitive fields: blocked, tombstone only, no screenshot ----------

def assert_tombstone_only(s, origin_host):
    files = sorted(p.name for p in s.dir.iterdir())
    assert files == ["meta.json"], files
    meta = json.loads((s.dir / "meta.json").read_text())
    assert set(meta) == {"state", "reason", "origin"}, meta
    assert meta["state"] == "incomplete" and meta["reason"] == "blocked" and origin_host in meta["origin"]
    assert "?" not in meta["origin"] and meta["origin"].count("/") == 2      # origin only, no path or query


def test_password_field_focus_is_blocked_and_leaves_only_a_tombstone(start):
    s = start("rec_sensitive.html")
    s.sim.focus_by_click("#u")
    s.sim.insert("someone")
    s.wait_groups(2)
    s.sim.focus_by_click("#pw")                      # focus alone is enough
    assert wait_until(lambda: s.rec.debug()["state"] == "incomplete", 5), s.rec.debug()
    assert wait_until(lambda: s.rec.finished, 5)
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "blocked"
    assert res["demo_summary"] is None and res["marked_summary"] is None and "screenshot" not in res
    assert_tombstone_only(s, "a.test")


def test_typing_into_a_card_number_field_is_blocked(start):
    s = start("rec_sensitive.html")
    s.sim.focus_by_click("#cc")
    assert wait_until(lambda: s.rec.debug()["state"] == "incomplete", 5)
    s.sim.insert("4111111111111111")
    res = s.stop()
    assert res["reason"] == "blocked"
    assert_tombstone_only(s, "a.test")
    assert "4111" not in (s.dir / "meta.json").read_text()


def test_prefilled_password_present_at_baseline_is_blocked(start):
    s = start("rec_sensitive_prefill.html")           # the value is there before the user does anything
    assert wait_until(lambda: s.rec.finished, 5), s.rec.debug()
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "blocked" and "screenshot" not in res
    assert_tombstone_only(s, "a.test")
    assert "hunter2" not in (s.dir / "meta.json").read_text()


def test_stop_after_blocked_never_reproduces_content(start):
    s = start("rec_sensitive.html")
    s.sim.focus_by_click("#pw")
    assert wait_until(lambda: s.rec.finished, 5)
    first = s.stop()
    again = s.mgr.stop(s.id)
    assert first == again and again["demo_summary"] is None and "screenshot" not in again
    assert sorted(p.name for p in s.dir.iterdir()) == ["meta.json"]


# ---------- arm gap and pre-arm input ----------

def test_input_before_arm_is_incomplete_pre_arm_input(start, monkeypatch):
    s = start("rec_a.html")
    real_arm = record.Recording._arm

    def slow_arm(self, ep):
        time.sleep(1.0)                              # the user acts while the new document waits to be armed
        real_arm(self, ep)
    monkeypatch.setattr(record.Recording, "_arm", slow_arm)
    s.sim.call("Page.reload")                        # epoch 2 is granted at once, armed only a second later
    assert wait_until(lambda: s.rec.debug()["epoch"] == 2, 8)
    time.sleep(0.2)
    s.sim.click("#push")                             # a real click in the unarmed document (no navigation)
    assert wait_until(lambda: "pre_arm_input" in s.rec.debug()["reasons"], 8), s.rec.debug()
    rec = [r for r in s.log() if r["type"] == "armed" and r["pre_arm_inputs"] > 0]
    assert rec and rec[0]["pre_kinds"][0] == "pointerdown"
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "pre_arm_input"


def test_leaving_a_document_before_it_was_armed_is_a_gap(start, monkeypatch):
    s = start("rec_a.html")
    real_arm = record.Recording._arm
    monkeypatch.setattr(record.Recording, "_arm", lambda self, ep: (time.sleep(1.0), real_arm(self, ep)))
    s.sim.call("Page.reload")
    assert wait_until(lambda: s.rec.debug()["epoch"] == 2, 8)
    s.sim.click("#tosame")                           # gone within the second: what happened in between is unknown
    assert wait_until(lambda: "gap" in s.rec.debug()["reasons"], 8), s.rec.debug()
    assert s.stop()["reason"] == "gap"


def test_a_document_that_never_arms_is_a_gap(start, monkeypatch):
    monkeypatch.setattr(record, "GAP_S", 1.0)
    s = start("rec_a.html")
    monkeypatch.setattr(record.Recording, "_arm", lambda self, ep: None)     # arm never happens
    s.sim.call("Page.reload")
    assert wait_until(lambda: s.rec.debug()["epoch"] == 2, 8)
    assert wait_until(lambda: "gap" in s.rec.debug()["reasons"], 6), s.rec.debug()
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "gap"


# ---------- the barrier ----------

def test_last_group_before_leaving_is_complete_when_it_is_a_button_navigation(start):
    s = start("rec_form.html")
    s.sim.iso("__kfwTestHook('noUnloadClose', true)")    # beforeunload does not get to close it: Python must resolve it
    s.sim.click("#tolink")
    wait_epoch(s, 2)
    g = groups_of(s.rec)[-1]
    assert g["target"]["label"] == "前往結果" and g.get("synthetic") is True and g["snap"] is None
    res = s.stop()
    assert res["state"] == "completed", res
    lg = s.log()
    assert any(r["type"] == "group_close" and r.get("synthetic") and r.get("doc_navigated_after") for r in lg)


def test_an_unclosed_input_group_before_leaving_is_incomplete(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.wait_groups(1)
    s.sim.iso("__kfwTestHook('noUnloadClose', true)")
    s.sim.insert("寫了一半")
    s.sim.call("Page.navigate", url=s.chrome.url("rec_result.html", "a.test"))   # gone before the group is stable
    wait_epoch(s, 2)
    assert "unclosed_input_group" in s.rec.debug()["reasons"], s.rec.debug()
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "unclosed_input_group"


def test_stop_flushes_a_still_open_group(start):
    s = start("rec_form.html")
    s.sim.focus_by_click("#name")
    s.sim.insert("剛打完")
    assert wait_until(lambda: any(g["kind"] == "text_input" for g in groups_of(s.rec)), 3)   # opened, maybe not yet closed
    res = s.stop()                                    # flush closes it and the barrier waits for the close to arrive
    assert res["state"] == "completed", res
    gs = [r for r in s.log() if r["type"] == "group_close" and r["kind"] == "text_input"]
    assert len(gs) == 1 and gs[0]["snap"]
    assert "screenshot" in res and (s.dir / "screenshot.jpg").stat().st_size > 1000


def test_barrier_checks_every_snapshot_reference_resolves(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    rec = s.rec
    rec._refs.add("deadbeefdeadbeef")                 # a reference nobody sent: the barrier must notice
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "unflushed"


def test_closing_the_page_is_incomplete_page_closed(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    closer = Browser(CDP_URL)                         # kept open until the tab is really gone (headed Chrome is slower)
    try:
        closer.send("Target.closeTarget", targetId=s.rec.target_id)
        assert wait_until(lambda: s.rec.finished, 10), s.rec.debug()
    finally:
        closer.close()
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "page_closed"


# ---------- stop is idempotent; discard; the one-recording lock ----------

def test_repeated_stop_returns_the_same_result(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    first = s.mgr.stop(s.id)
    second = s.mgr.stop(s.id)
    third = s.mgr.stop(s.id)
    assert first == second == third and first["state"] == "completed"
    assert (s.dir / "result.json").exists() and (s.dir / "log.jsonl").exists()
    meta = json.loads((s.dir / "meta.json").read_text())
    assert meta["state"] == "completed" and len(meta["digest"]) == 64


def test_discard_leaves_a_tombstone_and_stays_discarded(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    res = s.mgr.stop(s.id, discard=True)
    assert res == {"recording_id": s.id, "state": "discarded"}
    assert sorted(p.name for p in s.dir.iterdir()) == ["meta.json"]
    assert json.loads((s.dir / "meta.json").read_text()) == {"state": "discarded"}
    assert s.mgr.stop(s.id) == {"recording_id": s.id, "state": "discarded"}


def test_discard_after_completion_turns_it_into_a_tombstone(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    assert s.mgr.stop(s.id)["state"] == "completed"
    assert s.mgr.stop(s.id, discard=True)["state"] == "discarded"
    assert sorted(p.name for p in s.dir.iterdir()) == ["meta.json"]


def test_only_one_recording_at_a_time(start, mgr, chrome):
    s = start("rec_form.html")
    other = mgr.start(chrome.url("rec_b.html"))
    assert other["state"] == "error" and other["reason"] == "recording_in_progress" and other["recording_id"] == s.id
    assert s.stop()["state"] == "completed"
    again = mgr.start(chrome.url("rec_b.html"))          # free again once the first one is finished
    assert again["state"] == "recording"
    mgr.stop(again["recording_id"], discard=True)


def test_done_button_finishes_the_recording_by_itself(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    s.sim.click_bar("done")
    assert wait_until(lambda: s.rec.finished, 8)
    res = s.mgr.stop(s.id)
    assert res["state"] == "completed" and res["demo_summary"]["action_groups"] == 1
    assert s.mgr.active() is None
    groups = [g for g in s.log() if g["type"] == "group_open"]
    assert len(groups) == 1, "pressing the bar's own button must not become a site action group"


def test_idle_timeout_completes_after_the_barrier(start, monkeypatch):
    monkeypatch.setattr(record, "IDLE_S", 1.0)
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    assert wait_until(lambda: s.rec.finished, 8)
    assert s.mgr.stop(s.id)["state"] == "completed"


def test_too_long_is_incomplete(start, monkeypatch):
    monkeypatch.setattr(record, "MAX_S", 1.5)
    s = start("rec_form.html")
    assert wait_until(lambda: s.rec.finished, 8)
    res = s.mgr.stop(s.id)
    assert res["state"] == "incomplete" and res["reason"] == "too_long"


# ---------- teardown leaves nothing behind ----------

def test_teardown_removes_bar_and_listeners(start):
    s = start("rec_form.html")
    with_bar = s.sim.ev("document.body.childElementCount")
    assert s.sim.info()["connected"]
    sim, res_dir = s.sim, s.dir
    s.mgr.stop(s.id)
    # the stopped page: no host, permanently disabled, and nothing is sent any more
    info = sim.info()
    assert info["torn"] is True and info["connected"] is False and info["visible"] is False
    assert sim.ev("document.body.childElementCount") == with_bar - 1
    sends_before = info["sends"]
    sim.click("#plain")
    sim.focus_by_click("#name")
    sim.insert("still typing")
    settle(0.5)
    assert sim.info()["sends"] == sends_before and sim.info()["token"] is None
    assert (res_dir / "meta.json").exists()


def test_bfcache_return_after_stop_does_not_revive_the_recorder(mgr, chrome, monkeypatch):
    monkeypatch.setattr(record, "RECORDER_JS", record.build_recorder_js(unarmed_ms=1500))
    s = Session(mgr, chrome, "rec_a.html")
    body_children = s.sim.ev("document.body.childElementCount") - 1      # minus the bar
    s.sim.click("#tob")
    wait_epoch(s, 2)
    tid = s.rec.target_id
    res = s.stop()                                     # A sits in BFCache with its recorder JS still alive there
    assert res["state"] == "completed"
    sim = Sim(tid)
    try:
        sim.back()
        assert wait_until(lambda: sim.ev("window.__pageshows") == [False, True], 5), sim.ev("window.__pageshows")   # really BFCache
        info = sim.info()
        assert info["token"] is None and info["visible"] is False        # nobody armed it: no bar, no token
        sim.click("#inp")
        sim.insert("typed after stop")
        settle(0.3)
        assert sim.info()["sends"] <= info["sends"] + 1                  # at most its own hello, never data
        assert wait_until(lambda: sim.info()["torn"] is True, 5)         # and it switches itself off for good
        assert sim.ev("document.body.childElementCount") == body_children
    finally:
        sim.close()
    # nothing reached the finished recording
    assert json.loads((s.dir / "meta.json").read_text())["state"] == "completed"
    assert not any(r["type"] == "hello" and r["epoch"] > 2 for r in record.read_log(s.dir))


# ---------- mark mode ----------

SITE_EVENTS = ("pointerdown", "pointerup", "mousedown", "mouseup", "click", "keydown", "keyup", "input", "beforeinput", "wheel",
               "mousemove", "pointermove", "submit")


def site_events(sim):
    ev = sim.ev("window.__ev") or {}
    return {k: v for k, v in ev.items() if k in SITE_EVENTS and v}


def enter_mark(s):
    s.sim.click_bar("mark")
    assert wait_until(lambda: s.sim.info()["marking"], 3), s.sim.info()
    s.sim.ev("window.__evReset()")


def test_mark_mode_swallows_every_site_event_including_enter_in_a_focused_input(start):
    s = start("rec_mark.html")
    s.sim.focus_by_click("#q")
    s.sim.ev("window.__evReset()")
    enter_mark(s)                                     # the bar keeps the page focus where it is; entering mark mode blurs it
    assert s.sim.ev("document.activeElement !== document.getElementById('q')")      # blurred; the overlay (host) holds focus
    x, y, w, h = s.sim.rect("#note")
    s.sim.mouse("mouseMoved", x + 5, y + 5)
    s.sim.key("Enter", code="Enter")                  # would submit the form if the input still had focus
    s.sim.type_keys("zz")
    s.sim.wheel(x + 5, y + 5, 300)
    s.sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
    s.sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)      # this click is the mark itself
    assert wait_until(lambda: s.rec.debug()["marks"] == 1, 3)
    assert site_events(s.sim) == {}, site_events(s.sim)
    assert s.sim.ev("window.__submitted || 0") == 0 and s.sim.ev("document.getElementById('q').value") == ""
    assert s.sim.ev("window.scrollY") == 0
    assert not s.sim.info()["marking"]
    assert s.rec.debug()["reasons"] == []


def test_esc_cancels_mark_mode_and_restores_focus(start):
    s = start("rec_mark.html")
    s.sim.focus_by_click("#q")
    enter_mark(s)
    s.sim.mouse("mouseMoved", 300, 300)
    s.sim.key("Escape", code="Escape")
    assert wait_until(lambda: not s.sim.info()["marking"], 3)
    assert s.sim.ev("document.activeElement === document.getElementById('q')")
    ev = site_events(s.sim)
    assert not {"keydown", "pointerdown", "click", "mousedown"} & set(ev), ev      # (the Esc keyup after the mode ended may pass)
    assert s.rec.debug()["marks"] == 0 and s.rec.debug()["reasons"] == []


def test_real_click_on_bar_buttons_is_not_a_site_action_group(start):
    s = start("rec_mark.html")
    s.sim.click_bar("mark")
    assert wait_until(lambda: s.sim.info()["marking"], 3)
    s.sim.click_bar("mark")                           # the same button now cancels
    assert wait_until(lambda: not s.sim.info()["marking"], 3)
    settle(0.5)
    assert groups_of(s.rec) == [] and not any(r["type"] == "group_open" for r in s.log())
    assert s.rec.debug()["reasons"] == []


def mark_table(s, presses=3):
    x, y, w, h = s.sim.rect("#t td")
    s.sim.mouse("mouseMoved", x + 5, y + 5)
    for _ in range(presses):
        s.sim.key("ArrowUp", code="ArrowUp")         # td -> tr -> tbody -> table
    s.sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
    s.sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)
    assert wait_until(lambda: s.rec.debug()["marks"] == 1, 3), s.sim.info()


def test_mark_records_canonical_cells_total_fingerprint_and_same_signature_groups(start):
    s = start("rec_mark.html")
    enter_mark(s)
    mark_table(s)
    m = s.rec.marks[-1]
    g = m["group"]
    assert m["tag"] == "TABLE" and "蘋果" in m["text"]
    assert g["rows"] == [["蘋果", "30"], ["香蕉", "25"], ["橘子", "18"], ["葡萄", "90"]]
    assert g["total"] == 4 and g["truncated"] is False and g["has_th"] is True and g["rows_sent"] == 4
    assert g["same_signature_groups"] == 2            # #t2 has the same row signature: the pattern alone would be ambiguous
    assert s.sim.ev("document.querySelectorAll('[data-kfw-row],[data-kfw-group]').length") == 0     # the marks are cleaned up
    # the fingerprint is the shared observation code's: the same groups() the replay engine uses gives the same value
    ref = s.sim.ev(f"{form.GROUPS_JS}('#t', null, null, false)")
    assert [x["fingerprint"] for x in ref if x["total"] == 4] == [g["fingerprint"]]
    res = s.stop()
    assert res["state"] == "completed"
    ms = res["marked_summary"]
    assert ms["table"]["total_rows"] == 4 and ms["table"]["rows"][0] == ["蘋果", "30"] and ms["table"]["same_signature_groups"] == 2
    assert [r["type"] for r in s.log() if r["type"] == "mark"] == ["mark"]


def test_mark_a_text_block_has_no_group(start):
    s = start("rec_mark.html")
    enter_mark(s)
    x, y, w, h = s.sim.rect("#note")
    s.sim.mouse("mouseMoved", x + 5, y + 5)
    s.sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
    s.sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)
    assert wait_until(lambda: s.rec.debug()["marks"] == 1, 3)
    m = s.rec.marks[-1]
    assert m["group"] is None and "說明文字" in m["text"] and m["tag"] == "P"
    ms = s.stop()["marked_summary"]
    assert "table" not in ms and "說明文字" in ms["text"]


def test_mark_on_an_element_without_text_marks_nothing_and_stays_in_mark_mode(start):
    s = start("rec_mark.html")
    enter_mark(s)
    x, y, w, h = s.sim.rect("#q")                     # an empty input: no text to mark
    s.sim.mouse("mouseMoved", x + 5, y + 5)
    s.sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
    s.sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)
    settle(0.3)
    info = s.sim.info()
    assert s.rec.debug()["marks"] == 0 and info["marking"] and "沒有文字" in info["status"]
    s.sim.key("Escape", code="Escape")


# ---------- CSP: the bar is visible, clickable and removable under each ----------

@pytest.mark.parametrize("page", ["rec_csp_script.html", "rec_csp_style.html", "rec_csp_tt.html"])
def test_bar_under_csp(start, page):
    s = start(page)
    info = s.sim.info()
    assert info["visible"] and info["connected"] and info["hit"] is True and info["hostRect"][2] > 100 and info["hostRect"][3] > 20
    s.sim.click_bar("mark")                           # a real mouse click on the bar's button works
    assert wait_until(lambda: s.sim.info()["marking"], 3)
    s.sim.key("Escape", code="Escape")
    assert wait_until(lambda: not s.sim.info()["marking"], 3)
    s.sim.focus_by_click("#inp")                      # and the page is still recorded normally
    s.sim.insert("csp ok")
    gs = s.wait_groups(2)
    assert [g["kind"] for g in gs] == ["pointer", "text_input"]
    sim = s.sim
    res = s.mgr.stop(s.id)
    assert res["state"] == "completed", res
    info = sim.info()
    assert info["torn"] and not info["connected"] and not info["visible"]
    sim.close()


# ---------- snapshots: hash dedup, size budget; bar survives the site; the MCP tools ----------

def test_identical_snapshots_are_stored_once_and_referenced_by_id(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    s.sim.click("#plain")
    s.wait_groups(2)
    s.sim.click("#plain")
    s.wait_groups(3)
    snaps = [r for r in s.log() if r["type"] == "snapshot"]
    closes = [r for r in s.log() if r["type"] == "group_close"]
    assert len(closes) == 3 and len({c["snap"] for c in closes}) == 1          # same page state: one snapshot, three references
    assert len(snaps) == 1 and len(list((s.dir / "snapshots").glob("*.json"))) == 1


def test_a_page_with_1500_links_still_fits_the_payload_limit(start):
    s = start("rec_big.html")
    s.sim.focus_by_click("#q")
    s.sim.insert("x")
    s.wait_groups(2)
    assert s.rec.debug()["reasons"] == [], s.log()
    snaps = [r for r in s.log() if r["type"] == "snapshot"]
    assert snaps and any(r["links_dropped"] > 0 for r in snaps)                # links were shed, form fields kept
    controls = record.read_snapshots(s.dir)
    assert all(any(c["label"] == "關鍵字" for c in cs) for cs in controls.values())
    assert s.stop()["state"] == "completed"


def test_bar_comes_back_after_the_site_removes_it_and_teardown_wins_over_remount(start):
    s = start("rec_form.html")
    assert s.sim.info()["connected"]
    s.sim.ev("document.body.replaceChildren(); 1")          # a site that rebuilds its whole body
    assert wait_until(lambda: s.sim.info()["connected"] and s.sim.info()["hit"] is True, 3), s.sim.info()
    s.sim.iso("__kfwTeardown()")                             # teardown flag first: nothing may re-mount afterwards
    s.sim.ev("document.body.replaceChildren(document.createElement('p')); document.body.append(document.createElement('div')); 1")
    settle(0.5)
    info = s.sim.info()
    assert info["torn"] and not info["connected"] and s.sim.ev("document.body.childElementCount") == 2


def test_bar_mounts_late_when_the_body_appears_after_injection(start):
    s = start("rec_form.html")
    s.sim.ev("document.documentElement.removeChild(document.body); 1")     # no body at all
    settle(0.2)
    assert not s.sim.info()["connected"]
    s.sim.ev("document.documentElement.appendChild(document.createElement('body')); 1")
    assert wait_until(lambda: s.sim.info()["connected"], 3)


def test_mcp_tools_end_to_end_return_small_results(chrome, tmp_path):
    import asyncio

    from kfw import mcp_server
    chrome.check_identity()
    b = Browser(CDP_URL)
    before = {t["targetId"] for t in b.send("Target.getTargets")["targetInfos"] if t["type"] == "page"}
    try:
        out = asyncio.run(mcp_server.start_recording(chrome.url("rec_mark.html", "a.test")))
        assert out["state"] == "recording" and len(out["recording_id"]) == 12 and "標記結果" in out["tell_user"]
        rid = out["recording_id"]
        rec = record.manager().active()
        assert rec is not None and rec.id == rid
        sim = Sim(rec.target_id)
        sim.click_bar("mark")
        assert wait_until(lambda: sim.info()["marking"], 3)
        x, y, w, h = sim.rect("#t td")
        sim.mouse("mouseMoved", x + 5, y + 5)
        for _ in range(3):
            sim.key("ArrowUp", code="ArrowUp")
        sim.mouse("mousePressed", x + 5, y + 5, "left", 1)
        sim.mouse("mouseReleased", x + 5, y + 5, "left", 1)
        assert wait_until(lambda: rec.debug()["marks"] == 1, 3)
        again = asyncio.run(mcp_server.start_recording(chrome.url("rec_b.html", "a.test")))
        assert again["reason"] == "recording_in_progress"
        res = asyncio.run(mcp_server.stop_recording(rid, compare_to="some-recipe"))
        assert res["state"] == "completed" and res["draft"]["type"] == "detail_extract" and "screenshot" in res     # WP2: a marked table is a draft
        assert res["diff"]["error"] and any("compare_to" in w for w in res["warnings"])           # unknown recipe: said so, not silently skipped
        assert res["marked_summary"]["table"]["total_rows"] == 4
        assert len(json.dumps(res, ensure_ascii=False)) < 9000
        assert asyncio.run(mcp_server.stop_recording(rid)) == {k: v for k, v in res.items() if k not in ("warnings", "diff")} | {"warnings": [w for w in res["warnings"] if "compare_to" not in w]}
        sim.close()
    finally:
        for t in b.send("Target.getTargets")["targetInfos"]:
            if t["type"] == "page" and t["targetId"] not in before:
                try:
                    b.send("Target.closeTarget", targetId=t["targetId"])
                except Exception:
                    pass
        b.close()


# ---------- connection loss ----------

def test_detach_and_reattach_is_incomplete_reattached_and_recording_continues(start):
    s = start("rec_form.html")
    old = s.rec.session
    s.rec.browser.send("Target.detachFromTarget", sessionId=old)          # the session dies; the tab lives on
    assert wait_until(lambda: "reattached" in s.rec.debug()["reasons"] and s.rec.session != old, 8), s.rec.debug()
    s.sim.click("#tolink")                                                # the fresh session still sees new documents
    wait_epoch(s, 2)
    res = s.stop()
    assert res["state"] == "incomplete" and res["reason"] == "reattached"


def test_browser_connection_lost_is_incomplete_browser_disconnected(start):
    s = start("rec_form.html")
    s.sim.click("#plain")
    s.wait_groups(1)
    s.rec.browser.ws.close()                                              # the websocket dies without a deliberate close()
    assert wait_until(lambda: s.rec.finished, 8), s.rec.debug()
    res = s.mgr.stop(s.id)
    assert res["state"] == "incomplete" and res["reason"] == "browser_disconnected"
    assert s.mgr.active() is None
