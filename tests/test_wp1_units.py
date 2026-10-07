"""WP1 unit tests (no Chrome): payload validation, the state machine, limits, tombstones, recovery, retention, and the
Recording's message handling driven with a fake browser."""

import json
import os
import time

import pytest

from kfw import record
from kfw.record import Manager, Recording, Store, BadPayload

TARGET = {"tag": "BUTTON", "native": True, "in_controls": True, "id": "k1", "label": "查詢", "text": "查詢",
          "is_button_like": True, "custom_element": False, "iframe": False}
FIELD_TARGET = {**TARGET, "tag": "INPUT", "is_button_like": False, "label": "姓名", "text": ""}


# ---------- payload validation ----------

def test_parse_payload_rejects_non_strings_oversize_and_junk():
    for bad in (None, 5, {"type": "done"}, ["x"]):
        with pytest.raises(BadPayload, match="not_a_string"):
            record.parse_payload(bad)
    with pytest.raises(BadPayload, match="too_large"):
        record.parse_payload(json.dumps({"type": "done", "pad": "x" * record.MAX_PAYLOAD}))
    with pytest.raises(BadPayload, match="too_large"):    # the limit is bytes, not characters
        record.parse_payload(json.dumps({"type": "done", "pad": "中" * (record.MAX_PAYLOAD // 3)}, ensure_ascii=False))
    for junk in ("{nope", "", "[1]", "null", '"s"'):
        with pytest.raises(BadPayload):
            record.parse_payload(junk)
    with pytest.raises(BadPayload, match="unknown_type"):
        record.parse_payload(json.dumps({"type": "exfiltrate"}))
    with pytest.raises(BadPayload, match="unknown_type"):
        record.parse_payload(json.dumps({"no_type": 1}))
    assert record.parse_payload(json.dumps({"type": "done"}))["type"] == "done"


def test_clean_payload_schema_per_type():
    ok = {"type": "group_open", "gid": "g1", "kind": "pointer", "target": TARGET, "prev_snap": None, "token": "t", "seq": 1, "junk": "dropped"}
    out = record.clean_payload(ok)
    assert "junk" not in out and "token" not in out and out["target"]["label"] == "查詢"
    for field, bad in (("kind", "teleport"), ("gid", 5), ("target", {**TARGET, "native": "yes"}), ("prev_snap", 7)):
        with pytest.raises(BadPayload, match=f"schema:group_open.{field}"):
            record.clean_payload({**ok, field: bad})
    with pytest.raises(BadPayload):
        record.clean_payload({k: v for k, v in ok.items() if k != "target"})
    close = {"type": "group_close", "gid": "g1", "kind": "text_input", "snap": "ab12", "keys": ["Enter"]}
    assert record.clean_payload({**close, "unloading": True})["unloading"] is True
    with pytest.raises(BadPayload):
        record.clean_payload({**close, "keys": ["Backspace"]})       # only Enter/Escape/Tab are ever recorded
    with pytest.raises(BadPayload):
        record.clean_payload({**close, "unloading": "yes"})
    assert record.clean_payload({"type": "flag", "reason": "new_tab"})["reason"] == "new_tab"
    with pytest.raises(BadPayload):
        record.clean_payload({"type": "flag", "reason": "whatever"})
    with pytest.raises(BadPayload):
        record.clean_payload({"type": "snapshot", "id": "a", "controls": ["not a dict"], "links_dropped": 0})
    with pytest.raises(BadPayload):
        record.clean_payload({"type": "snapshot", "id": "a", "controls": [{}] * 3001, "links_dropped": 0})
    mark = {"type": "mark", "tag": "TABLE", "text": "t", "text_truncated": False, "href": "http://a/", "group": None}
    assert record.clean_payload(mark)["group"] is None
    grp = {"rows": [["a", "1"]], "rows_sent": 1, "total": 1, "truncated": False, "fingerprint": "ff", "has_th": True, "same_signature_groups": 1}
    assert record.clean_payload({**mark, "group": grp})["group"]["total"] == 1
    with pytest.raises(BadPayload):
        record.clean_payload({**mark, "group": {**grp, "rows": [["a", 1]]}})       # cells are strings
    with pytest.raises(BadPayload):
        record.clean_payload({**mark, "text": "x" * 2001})


def test_sensitive_present_and_snap_diff_and_origin():
    assert record.sensitive_present([{"sensitive": True, "has_value": True}])
    assert record.sensitive_present([{"sensitive": True, "has_value": False, "value": "x"}])   # a value must never appear at all
    assert not record.sensitive_present([{"sensitive": True, "has_value": False, "value": ""}, {"sensitive": False, "has_value": True}])
    prev = [{"id": "k1", "kind": "text", "label": "姓名", "value": ""}, {"id": "k2", "kind": "select", "label": "城市", "value": "台北"},
            {"id": "k3", "kind": "checkbox", "label": "同意", "checked": False}, {"id": "k4", "kind": "button", "label": "查詢"},
            {"id": "k5", "kind": "text", "label": "卡", "value": "", "sensitive": True}]
    cur = [{"id": "k1", "kind": "text", "label": "姓名", "value": "王"}, {"id": "k2", "kind": "select", "label": "城市", "value": "台北"},
           {"id": "k3", "kind": "checkbox", "label": "同意", "checked": True}, {"id": "k4", "kind": "button", "label": "查詢"},
           {"id": "k5", "kind": "text", "label": "卡", "value": "", "sensitive": True}, {"id": "k9", "kind": "text", "label": "新", "value": "z"}]
    assert [(c["label"], c["before"], c["after"]) for c in record.snap_diff(prev, cur)] == [("姓名", "", "王"), ("同意", False, True)]
    assert record.snap_diff(None, cur) == [] and record.snap_diff(prev, None) == []
    assert record.origin_of("http://a.test:8080/x/y?q=1#z") == "http://a.test:8080"
    assert record.origin_of("about:blank") == "" and record.origin_of("::::") == ""


# ---------- state machine ----------

def test_transition_table_is_the_designed_one():
    assert set(record.TRANSITIONS) == {"starting", "recording", "stopping", "completed", "incomplete", "discarded"}
    assert "blocked" not in record.TRANSITIONS                    # blocked is a reason of incomplete, never a state
    assert record.TRANSITIONS["starting"] == {"recording", "incomplete"}
    assert record.TRANSITIONS["recording"] == {"stopping", "incomplete", "discarded"}
    assert record.TRANSITIONS["stopping"] == {"completed", "incomplete", "discarded"}
    assert record.TRANSITIONS["discarded"] == set()
    assert record.TERMINAL == ("completed", "incomplete", "discarded")


class FakeBrowser:
    """Answers the page the way the recorder JS would: __kfwArm -> 'armed', __kfwFlush -> the current last_seq."""

    def __init__(self):
        self.calls, self.regs, self.closed, self.replies, self.rec = [], [], False, {}, None

    def send(self, method, session_id=None, timeout=30, **params):
        self.calls.append((method, session_id, params))
        if method == "Runtime.evaluate":
            expr = params.get("expression", "")
            if expr.startswith("__kfwArm"):
                return {"result": {"value": "armed"}}
            if expr.startswith("__kfwFlush") and self.rec is not None and self.rec.epoch is not None:
                return {"result": {"value": {"ok": True, "token": self.rec.epoch.token, "last_seq": self.rec.epoch.last_seq}}}
            return {"result": {"value": None}}
        if method == "Page.captureScreenshot":
            return {"data": "anBn"}
        r = self.replies.get(method, {})
        return r() if callable(r) else r

    def on(self, sid, method, cb):
        self.regs.append((sid, method, cb))

    def off(self, sid, method, cb):
        if (sid, method, cb) in self.regs:
            self.regs.remove((sid, method, cb))

    def on_disconnect(self, cb):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def rec(tmp_path):
    fb = FakeBrowser()
    store = Store(tmp_path / "a1b2c3d4e5f6")
    store.open({"id": "a1b2c3d4e5f6", "state": "starting"})
    r = Recording("a1b2c3d4e5f6", "http://a.test/", fb, store)
    fb.rec = r
    r.session, r.target_id, r.main_frame_id = "S", "T", "F"
    r._set_state("recording")
    r._boot_threads()
    yield r
    r._halt.set()
    r._jobs.put(None)
    store.close()


def new_ctx(rec, cid=5, uid="u5", name="kfw_rec", frame="F"):
    rec._on_ctx_created({"context": {"id": cid, "uniqueId": uid, "name": name, "auxData": {"frameId": frame, "isDefault": False}}})


def call(rec, msg, cid=5, raw=None, name="__kfwRec"):
    rec.on_binding({"name": name, "executionContextId": cid, "payload": raw if raw is not None else json.dumps(msg)})


HELLO = {"type": "hello", "doc_id": "d1", "href": "http://a.test/p", "restored": False, "persisted": False, "nav_type": "navigate", "ready_state": "loading"}


def hello_and_arm(rec, cid=5, pre=0, uid="u5"):
    new_ctx(rec, cid, uid)
    call(rec, {**HELLO, "doc_id": f"d{rec.epoch_n + 1}"}, cid)
    ep = rec.epoch
    call(rec, {"type": "armed", "token": ep.token, "pre_arm_inputs": pre, "pre_kinds": ["pointerdown"] * pre}, cid)
    return ep


def send(rec, ep, type_, cid=5, **kw):
    seq = kw.pop("seq", ep.last_seq + 1)
    call(rec, {"type": type_, "token": kw.pop("token", ep.token), "seq": seq, **kw}, cid)


def wait_calls(fb, pred, timeout=2):
    end = time.time() + timeout
    while time.time() < end:
        if any(pred(c) for c in fb.calls):
            return True
        time.sleep(0.01)
    return False


def test_illegal_transitions_raise(rec):
    with pytest.raises(record.InvalidTransition):
        rec._set_state("completed")                 # recording -> completed must go through stopping
    rec._set_state("stopping")
    rec._set_state("completed")
    with pytest.raises(record.InvalidTransition):
        rec._set_state("recording")
    rec._set_state("discarded")
    with pytest.raises(record.InvalidTransition):
        rec._set_state("completed")


# ---------- Recording message handling ----------

def test_only_main_frame_kfw_rec_contexts_are_known(rec):
    new_ctx(rec, 5, "u5")
    new_ctx(rec, 6, "u6", frame="IFRAME")              # a same-site iframe's kfw_rec world
    new_ctx(rec, 7, "u7", name="other")
    new_ctx(rec, 8, "u8", name="")
    assert rec._ctx == {5: "u5"}
    rec._on_ctx_cleared({})
    assert rec._ctx == {}


def test_hello_from_an_unknown_context_is_refused(rec):
    call(rec, HELLO, cid=99)
    assert rec.epoch is None and "bad_payload" in rec.reasons
    new_ctx(rec, 6, "u6", frame="IFRAME")
    call(rec, HELLO, cid=6)
    assert rec.epoch is None


def test_hello_grants_a_fresh_epoch_and_token_and_arms_through_the_worker(rec):
    new_ctx(rec)
    call(rec, HELLO)
    ep = rec.epoch
    assert ep.n == 1 and len(ep.token) == 16 and not ep.armed
    assert wait_calls(rec.browser, lambda c: c[0] == "Runtime.evaluate" and ep.token in c[2]["expression"] and c[2]["contextId"] == 5)
    call(rec, {**HELLO, "doc_id": "d2"})              # another hello (e.g. BFCache restore): new epoch, new token, old one retired
    ep2 = rec.epoch
    assert ep2.n == 2 and ep2.token != ep.token and ep.retired and ep.token in rec._retired
    call(rec, {"type": "armed", "token": ep.token, "pre_arm_inputs": 0, "pre_kinds": []})   # the old epoch's armed is stale
    assert not ep.armed and rec.stale_dropped == 1
    assert rec.reasons == ["gap"]                       # the first document was replaced before it was ever armed


def test_armed_with_pre_arm_input_is_incomplete(rec):
    ep = hello_and_arm(rec, pre=2)
    assert ep.armed and rec.reasons == ["pre_arm_input"]
    log = record.read_log(rec.store.dir)
    assert [r["pre_arm_inputs"] for r in log if r["type"] == "armed"] == [2]


def test_bad_token_wrong_context_bad_seq_and_junk_are_dropped_and_flagged(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "done", token="nope")                # wrong token
    assert rec.reasons == ["bad_payload"] and ep.last_seq == 0
    rec.reasons.clear()
    new_ctx(rec, 9, "u9")
    send(rec, ep, "flag", cid=9, reason="new_tab")     # right token, but from another (known) context
    assert rec.reasons == ["bad_payload"] and "new_tab" not in rec.reasons
    rec.reasons.clear()
    call(rec, {"type": "flag", "token": ep.token, "seq": 1, "reason": "new_tab"}, cid=123)   # unknown context
    assert rec.reasons == ["bad_payload"]
    rec.reasons.clear()
    send(rec, ep, "flag", seq=4, reason="new_tab")     # skips 1..3
    assert rec.reasons == ["seq_gap"] and ep.last_seq == 4
    rec.reasons.clear()
    send(rec, ep, "flag", seq=4, reason="new_tab")     # replay of a seq already seen
    assert rec.reasons == ["seq_gap"]
    rec.reasons.clear()
    send(rec, ep, "flag", seq="5", reason="new_tab")   # seq must be an int
    assert rec.reasons == ["seq_gap"]
    rec.reasons.clear()
    call(rec, None, raw="{oops")
    call(rec, None, raw=12345)
    call(rec, {"type": "bogus"})
    assert rec.reasons == ["bad_payload"] and rec._flag_counts["bad_payload"] == 6


def test_a_flag_message_in_sequence_is_accepted(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "flag", reason="new_tab")
    assert rec.reasons == ["new_tab"] and ep.last_seq == 1


def test_binding_with_another_name_is_ignored(rec):
    ep = hello_and_arm(rec)
    call(rec, {"type": "done"}, name="somethingElse")
    assert rec.reasons == [] and ep.last_seq == 0


def test_document_change_retires_the_epoch_and_late_data_is_dropped_quietly(rec):
    ep = hello_and_arm(rec)
    rec._on_ctx_cleared({})
    assert ep.retired and rec._ctx == {}
    send(rec, ep, "flag", reason="new_tab")            # late data of the dead document
    assert rec.reasons == [] and rec.stale_dropped == 1
    ep2 = hello_and_arm(rec, cid=5, uid="u5b")
    assert ep2.n == 2 and not ep2.retired and rec._gap_start is None


def test_snapshot_with_a_sensitive_value_blocks_and_deletes_everything(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "snapshot", id="aa", controls=[{"id": "k1", "kind": "text", "sensitive": False, "value": "ok", "has_value": True}], links_dropped=0)
    assert (rec.store.dir / "snapshots" / "aa.json").exists()
    send(rec, ep, "snapshot", id="bb", controls=[{"id": "k2", "kind": "text", "sensitive": True, "value": "", "has_value": True}], links_dropped=0)
    assert rec.state == "incomplete" and rec.reasons == ["blocked"]
    assert sorted(p.name for p in rec.store.dir.iterdir()) == ["meta.json"]
    meta = json.loads((rec.store.dir / "meta.json").read_text())
    assert meta == {"state": "incomplete", "reason": "blocked", "origin": "http://a.test"}
    assert rec.snaps == {} and rec.marks == []
    send(rec, ep, "flag", reason="new_tab")            # nothing is collected any more
    assert sorted(p.name for p in rec.store.dir.iterdir()) == ["meta.json"]
    assert rec.finish()["reason"] == "blocked"


def test_blocked_message_from_the_page_blocks(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "blocked", reason="sensitive_focus")
    assert rec.state == "incomplete" and rec.reasons == ["blocked"] and rec.store.sealed
    res = rec.finish()
    assert res["reason"] == "blocked" and res["demo_summary"] is None and "screenshot" not in res


def test_group_close_without_open_is_bad_payload(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "group_close", gid="g1", kind="pointer", snap=None, keys=[])
    assert rec.reasons == ["bad_payload"]


def test_group_open_close_lifecycle_and_custom_element_check(rec):
    ep = hello_and_arm(rec)
    field = {"id": "k1", "kind": "text", "label": "姓名", "value": ""}
    send(rec, ep, "snapshot", id="s0", controls=[field], links_dropped=0)
    send(rec, ep, "baseline", snap="s0")
    custom = {**TARGET, "tag": "MY-WIDGET", "native": False, "in_controls": False, "id": None, "is_button_like": False, "custom_element": True}
    send(rec, ep, "group_open", gid="g1", kind="pointer", target=custom, prev_snap="s0")
    send(rec, ep, "snapshot", id="s1", controls=[field], links_dropped=0)        # nothing native changed
    send(rec, ep, "group_close", gid="g1", kind="pointer", snap="s1", keys=[])
    assert rec.reasons == ["custom_element_interaction"]
    # a custom-element click that DID change a native field is fine
    rec.reasons.clear()
    send(rec, ep, "group_open", gid="g2", kind="pointer", target=custom, prev_snap="s1")
    send(rec, ep, "snapshot", id="s2", controls=[{**field, "value": "x"}], links_dropped=0)
    send(rec, ep, "group_close", gid="g2", kind="pointer", snap="s2", keys=[])
    assert rec.reasons == []


def test_iframe_target_is_incomplete(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "group_open", gid="g1", kind="pointer", target={**TARGET, "tag": "IFRAME", "iframe": True}, prev_snap=None)
    assert rec.reasons == ["iframe_interaction"]


def test_leaving_with_an_open_button_group_is_complete_but_an_open_input_group_is_incomplete(rec):
    ep = hello_and_arm(rec)
    send(rec, ep, "group_open", gid="g1", kind="pointer", target=TARGET, prev_snap=None)
    rec._on_ctx_cleared({})                            # document gone before the close arrived
    assert rec.reasons == []
    g = rec._groups[(1, "g1")]
    assert g["closed"] and g["synthetic"] and g["snap"] is None
    log = record.read_log(rec.store.dir)
    assert any(r["type"] == "group_close" and r.get("synthetic") and r["doc_navigated_after"] for r in log)
    ep2 = hello_and_arm(rec, uid="u5b")
    send(rec, ep2, "group_open", gid="g1", kind="text_input", target=FIELD_TARGET, prev_snap=None)
    rec._on_ctx_cleared({})
    assert rec.reasons == ["unclosed_input_group"]


def test_leaving_before_arm_is_a_gap(rec):
    new_ctx(rec)
    call(rec, HELLO)
    rec._on_ctx_cleared({})
    assert rec.reasons == ["gap"]


def test_gap_timer_flags_a_document_that_never_arms(rec, monkeypatch):
    monkeypatch.setattr(record, "GAP_S", 0.2)
    hello_and_arm(rec)
    rec._on_ctx_cleared({})                            # navigation: the next document must arm within GAP_S
    rec.reasons.clear()
    assert rec._gap_start is not None
    end = time.time() + 3
    while "gap" not in rec.reasons and time.time() < end:
        time.sleep(0.05)
    assert rec.reasons == ["gap"]


def test_bfcache_order_hello_before_frame_navigated_is_handled(rec):
    """Spike 7: hello{restored} arrives BEFORE Page.frameNavigated(BackForwardCacheRestore); contexts are re-emitted."""
    ep1 = hello_and_arm(rec)
    rec._on_ctx_cleared({})                            # leaving for B
    ep2 = hello_and_arm(rec, cid=6, uid="u6")          # B
    rec._on_ctx_cleared({})                            # back to A: cleared, then the SAME context id/uid re-created
    assert ep2.retired
    new_ctx(rec, 5, "u5")
    call(rec, {**HELLO, "doc_id": "d1", "restored": True, "persisted": True}, cid=5)
    ep3 = rec.epoch
    assert ep3.n == 3 and ep3.restored and ep3.token not in (ep1.token, ep2.token)
    call(rec, {"type": "armed", "token": ep3.token, "pre_arm_inputs": 0, "pre_kinds": []}, cid=5)
    assert ep3.armed and rec._gap_start is None
    rec._on_frame_navigated({"frame": {"id": "F", "url": "http://a.test/"}, "type": "BackForwardCacheRestore"})   # comes last
    assert rec._gap_start is None and rec.epoch is ep3 and not ep3.retired and rec.reasons == []
    send(rec, ep1, "flag", reason="new_tab")           # the first document's token: dead
    assert rec.reasons == [] and rec.stale_dropped == 1


def test_same_document_navigation_keeps_the_epoch(rec):
    ep = hello_and_arm(rec)
    rec._on_same_document({"frameId": "F", "url": "http://a.test/spa/1", "navigationType": "historyApi"})
    assert rec.epoch is ep and not ep.retired and rec._gap_start is None
    send(rec, ep, "flag", reason="new_tab")
    assert ep.last_seq == 1


def test_target_discovery_rules(rec):
    rec._known_targets = {"OLD"}
    rec._on_target_created({"targetInfo": {"targetId": "OLD", "type": "page"}})               # existed before: ignored
    rec._on_target_created({"targetInfo": {"targetId": "FR", "type": "iframe", "openerId": "T"}})   # not a page: ignored
    rec._on_target_created({"targetInfo": {"targetId": "T", "type": "page"}})                 # our own tab
    assert rec.reasons == []
    rec._on_target_created({"targetInfo": {"targetId": "NEW", "type": "page", "openerId": "T"}})
    assert rec.reasons == ["new_tab"]
    rec.reasons.clear()
    rec._on_target_created({"targetInfo": {"targetId": "NEW", "type": "page"}})               # already counted
    assert rec.reasons == []
    rec._on_target_created({"targetInfo": {"targetId": "UNRELATED", "type": "page"}})          # unattributable: still new_tab
    assert rec.reasons == ["new_tab"]


def test_early_target_events_wait_for_our_own_id(tmp_path):
    fb = FakeBrowser()
    store = Store(tmp_path / "b1b2c3d4e5f6")
    store.open({"id": "b1b2c3d4e5f6", "state": "starting"})
    r = Recording("b1b2c3d4e5f6", "http://a.test/", fb, store)
    r._on_target_created({"targetInfo": {"targetId": "MINE", "type": "page"}})
    assert r._early_targets and r.reasons == []


def test_limits_records_and_bytes_mark_truncated(rec, monkeypatch):
    monkeypatch.setattr(record, "MAX_RECORDS", 30)
    ep = hello_and_arm(rec)
    for i in range(60):
        send(rec, ep, "baseline", snap=f"{i:x}")
    assert rec.store.records == 30 and "truncated" in rec.reasons
    assert len(record.read_log(rec.store.dir)) == 30


def test_store_byte_limit_and_snapshot_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(record, "MAX_BYTES", 2000)
    st = Store(tmp_path / "c1b2c3d4e5f6")
    st.open({"state": "recording"})
    assert st.put_snapshot("a1", [{"id": "k1"}]) and st.put_snapshot("a1", [{"id": "k1"}])   # same content id: stored once
    n = st.records
    assert n == 1
    big = [{"id": f"k{i}", "label": "x" * 50} for i in range(100)]
    assert st.put_snapshot("a2", big) is False and st.full
    assert not st.put_snapshot("../../etc/passwd", []), "snapshot ids are content hashes, never paths"
    assert st.append({"type": "x"}) is True or st.full


def test_real_limits_are_the_designed_ones():
    assert (record.MAX_RECORDS, record.MAX_BYTES, record.MAX_PAYLOAD) == (5000, 5 * 1024 * 1024, 64 * 1024)
    assert (record.IDLE_S, record.MAX_S, record.GAP_S, record.RETENTION_DAYS) == (900, 1800, 3.0, 30)


def test_result_summary_is_small(rec):
    ep = hello_and_arm(rec)
    field = {"id": "k1", "kind": "text", "label": "姓名", "value": ""}
    send(rec, ep, "snapshot", id="a0", controls=[field], links_dropped=0)
    for i in range(80):
        send(rec, ep, "group_open", gid=f"g{i}", kind="pointer", target=TARGET, prev_snap="a0")
        send(rec, ep, "group_close", gid=f"g{i}", kind="pointer", snap="a0", keys=[])
    rows = [[f"c{i}-{j}" for j in range(30)] for i in range(200)]
    grp = {"rows": rows, "rows_sent": 200, "total": 250, "truncated": True, "fingerprint": "ff", "has_th": False, "same_signature_groups": 3}
    send(rec, ep, "mark", tag="TABLE", text="x" * 1500, text_truncated=False, href="http://a.test/", group=grp)
    res = rec.finish()
    assert res["state"] == "completed" and res["draft"] is None and res["unsupported"]["reason"] == "result_kind"   # truncated table: not a draft
    assert res["demo_summary"]["action_groups"] == 80 and len(res["demo_summary"]["steps"]) == 30
    ms = res["marked_summary"]
    assert len(ms["table"]["rows"]) == 20 and all(len(r) <= 12 for r in ms["table"]["rows"]) and len(ms["text"]) == 300
    assert ms["table"]["total_rows"] == 250 and ms["table"]["truncated"] is True
    assert len(json.dumps(res, ensure_ascii=False)) < 12000


def test_no_mark_and_many_marks_warn(rec):
    hello_and_arm(rec)
    res = rec.finish()
    assert any("沒有標記結果" in w for w in res["warnings"]) and res["marked_summary"] is None


# ---------- the in-page recorder source ----------

def test_recorder_js_is_built_from_the_shared_observation_code_and_obeys_csp_rules():
    from kfw import form
    js = record.RECORDER_JS
    assert form.OBSERVE_JS in js                                    # one observation code base, injected as-is
    assert "const KFW_RULES = " in js and "O.snapshot(" in js and "O.groups(" in js and "O.isSensitive(" in js
    body = js.replace(form.OBSERVE_JS, "")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "createElement('style')", "<style", "setAttribute('style'",
                      ".cssText", "eval(", "new Function", "document.write"):
        assert forbidden not in body, forbidden
    assert "attachShadow({mode: 'closed'})" in body and "style.setProperty" in body and ".textContent" in body
    assert "pagehide" not in body.replace("never on pagehide", "") or "'pagehide'" not in body   # pagehide is never a sender
    assert "window.top !== window" in body and "typeof B !== 'function'" in body
    assert record.build_recorder_js(1234).count("unarmedMs: 1234") == 1


# ---------- disk: tombstones, atomicity, recovery, retention ----------

def test_seal_writes_the_tombstone_first_and_leaves_only_it(tmp_path):
    st = Store(tmp_path / "d1b2c3d4e5f6")
    st.open({"state": "recording"})
    st.append({"type": "x", "secret": "hunter2"})
    st.put_snapshot("ab", [{"id": "k1", "value": "secret"}])
    (st.dir / "screenshot.jpg").write_bytes(b"jpg")
    st.seal({"state": "incomplete", "reason": "blocked", "origin": "http://a.test"})
    assert sorted(p.name for p in st.dir.iterdir()) == ["meta.json"]
    assert json.loads((st.dir / "meta.json").read_text()) == {"state": "incomplete", "reason": "blocked", "origin": "http://a.test"}
    assert st.append({"type": "late"}) is False and st.put_snapshot("cd", []) is False and st.write_meta({"state": "x"}) is False
    assert st.write_final({"state": "completed"}, {}) is False                  # a finishing thread cannot resurrect it
    assert sorted(p.name for p in st.dir.iterdir()) == ["meta.json"]


def test_recovery_marks_unfinished_directories_incomplete_and_finishes_interrupted_purges(tmp_path):
    root = tmp_path / "recordings"
    root.mkdir()
    for name, meta in (("aaaaaaaaaaaa", {"id": "aaaaaaaaaaaa", "state": "recording", "url": "http://a.test/"}),
                       ("bbbbbbbbbbbb", {"id": "bbbbbbbbbbbb", "state": "stopping"}),
                       ("cccccccccccc", None),                                                       # no meta at all
                       ("dddddddddddd", {"state": "completed", "digest": "x"}),
                       ("eeeeeeeeeeee", {"state": "incomplete", "reason": "blocked", "origin": "http://a.test"}),
                       ("ffffffffffff", {"state": "discarded"})):
        d = root / name
        d.mkdir()
        (d / "log.jsonl").write_text('{"type":"leftover"}\n')
        if meta is not None:
            (d / "meta.json").write_text(json.dumps(meta))
    (root / "not-an-id").mkdir()
    m = Manager(home=tmp_path, browser_factory=lambda: None)
    for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"):
        meta = json.loads((root / name / "meta.json").read_text())
        assert meta["state"] == "incomplete" and meta["reason"] == "server_restarted"
        r = m.stop(name)
        assert r["state"] == "incomplete" and r["reason"] == "server_restarted" and r["draft"] is None
        assert m.stop(name) == r                                                    # and stays that way
    assert json.loads((root / "dddddddddddd" / "meta.json").read_text())["state"] == "completed"
    assert (root / "dddddddddddd" / "log.jsonl").exists()
    for name in ("eeeeeeeeeeee", "ffffffffffff"):                                    # a purge that was cut short is completed
        assert sorted(p.name for p in (root / name).iterdir()) == ["meta.json"]
    assert m.stop("eeeeeeeeeeee")["reason"] == "blocked"
    assert m.stop("ffffffffffff") == {"recording_id": "ffffffffffff", "state": "discarded"}


def test_a_second_manager_sees_the_first_ones_unfinished_recording_as_incomplete(tmp_path):
    """Server restart simulation: a new manager over the same home reads a directory the old process never finished."""
    old = Manager(home=tmp_path, browser_factory=lambda: None)
    rid = "123456789abc"
    st = Store(old.root / rid)
    st.open({"id": rid, "state": "recording", "url": "http://a.test/"})
    st.append({"type": "hello"})
    st.close()
    new = Manager(home=tmp_path, browser_factory=lambda: None)
    r = new.stop(rid)
    assert (r["state"], r["reason"]) == ("incomplete", "server_restarted")
    assert any("重新啟動" in w for w in r["warnings"])


def test_manager_rejects_bad_ids_and_unknown_recordings(tmp_path):
    m = Manager(home=tmp_path, browser_factory=lambda: None)
    for bad in ("", "../../etc", "ABCDEF123456", "12345", "g" * 12, None, 5, "a" * 13):
        assert m.stop(bad) == {"state": "error", "reason": "bad_recording_id"}
    assert m.stop("0" * 12)["reason"] == "not_found"
    assert m.start("ftp://x/")["reason"] == "bad_url" and m.start("")["reason"] == "bad_url" and m.start("javascript:alert(1)")["reason"] == "bad_url"
    ids = {os.path.basename(p) for p in m.root.iterdir()}
    assert ids == set()


def test_recording_ids_are_12_hex(tmp_path):
    seen = set()
    for _ in range(50):
        rid = record.secrets.token_hex(6)
        assert record.ID_RE.fullmatch(rid)
        seen.add(rid)
    assert len(seen) == 50


def test_retention_deletes_only_old_directories(tmp_path):
    m = Manager(home=tmp_path, browser_factory=lambda: None)
    now = time.time()
    for name, age_days in (("111111111111", 31), ("222222222222", 29), ("333333333333", 100)):
        d = m.root / name
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"state": "completed", "finished": now - age_days * 86400}))
    (m.root / "444444444444").mkdir()                    # no meta: judged by its mtime
    os.utime(m.root / "444444444444", (now - 40 * 86400, now - 40 * 86400))
    gone = m.cleanup(now=now)
    assert sorted(gone) == ["111111111111", "333333333333", "444444444444"]
    assert [p.name for p in m.root.iterdir()] == ["222222222222"]
    assert m.cleanup(now=now + 2 * 86400) == ["222222222222"]


def test_digest_covers_log_and_snapshots(tmp_path):
    st = Store(tmp_path / "abcabcabcabc")
    st.open({"state": "recording"})
    st.append({"type": "a"})
    d1 = st.digest()
    st.put_snapshot("ff", [{"id": "k1"}])
    d2 = st.digest()
    st.append({"type": "b"})
    d3 = st.digest()
    assert len({d1, d2, d3}) == 3 and all(len(d) == 64 for d in (d1, d2, d3))
    st.sync()                                             # fsync path runs without error
    st.close()


def test_start_failure_is_incomplete_start_failed(tmp_path):
    class Boom(FakeBrowser):
        def send(self, method, session_id=None, timeout=30, **params):
            if method == "Target.createTarget":
                raise record.CDPError("no tab for you") if hasattr(record, "CDPError") else RuntimeError("no tab for you")
            return super().send(method, session_id, timeout, **params)
    fb = Boom()
    m = Manager(home=tmp_path, browser_factory=lambda: fb)
    out = m.start("http://a.test/")
    assert out["state"] == "incomplete" and out["reason"] == "start_failed" and fb.closed
    assert m.active() is None
    meta = json.loads((m.root / out["recording_id"] / "meta.json").read_text())
    assert meta["state"] == "incomplete" and meta["reason"] == "start_failed"
    assert m.stop(out["recording_id"])["reason"] == "start_failed"
