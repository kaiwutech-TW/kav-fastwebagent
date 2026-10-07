"""Hand-built recordings in the exact on-disk format WP1 writes (kfw/record.py: log.jsonl records + snapshots/<id>.json control
lists + meta.json), for the WP2 unit tests. `Rec` assembles one in memory; write() puts it on disk under a recording directory
(tests/fixtures/recordings/<name>/ holds the committed scenarios, built by build_scenarios())."""

import hashlib
import json
import time
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "recordings"


def _base(id_, label, kind, **kw):
    return {"id": id_, "label": label, "kind": kind, "name": "", "autocomplete": "", "form_id": "f1", "form_has_sensitive": False,
            "sensitive": False, "native": kind in ("select", "text", "checkbox", "radio"), **kw}


def select(id_, label, value, options=None):
    return _base(id_, label, "select", value=value, options=options or [value], has_value=bool(value))


def text(id_, label, value="", readonly=False, input_type="text"):
    return _base(id_, label, "text", value=value, readonly=readonly, input_type=input_type, has_value=value != "")


def checkbox(id_, label, checked=False):
    return _base(id_, label, "checkbox", checked=checked, has_value=checked)


def button(id_, label):
    return _base(id_, label, "button", has_value=False)


def link(id_, label):
    return _base(id_, label, "link", has_value=False)


def target(id_=None, label="", tag="DIV", native=False, button_=False, custom=False, iframe=False, text_=""):
    return {"tag": tag, "native": native, "in_controls": bool(id_), "id": id_, "label": label, "text": text_ or (label if button_ else ""),
            "is_button_like": button_, "custom_element": custom, "iframe": iframe}


def field_target(id_, label, tag="INPUT"):
    return target(id_, label, tag=tag, native=True)


def button_target(id_, label, row=None):
    t = target(id_, label, tag="BUTTON", native=True, button_=True, text_=label)
    if row is not None:
        t["row"] = row
    return t


def list_row(rows, index, texts=None):
    """The `target.row` payload of a click on a control inside a repeating list row (what the recorder observes at pointerdown)."""
    texts = texts or ["".join(r) for r in rows]
    return {"cells": rows[index], "text": texts[index], "rows": rows, "texts": texts, "total": len(rows), "index": index}


def res(groups=(), heads=()):
    """A result-group observation: groups = [(fingerprint, total rows, columns, row signature)]."""
    return {"groups": [{"fp": fp, "n": n, "cols": cols, "sig": sig} for fp, n, cols, sig in groups], "heads": list(heads)}


def table_group(rows, headers=None, total=None, truncated=False, has_th=None, fingerprint="f00d", rows_sent=None, sig=None):
    g = {"rows": rows, "rows_sent": rows_sent if rows_sent is not None else len(rows), "total": total if total is not None else len(rows),
         "truncated": truncated, "fingerprint": fingerprint, "has_th": bool(headers) if has_th is None else has_th,
         "same_signature_groups": 1, "headers": headers}
    if sig is not None:
        g["sig"] = sig
    return g


class Rec:
    """Builds log records + snapshots. Snapshot ids are hex (Store refuses anything else)."""

    def __init__(self):
        self.log, self.snaps, self.epoch, self._n, self._g, self._t = [], {}, 0, 0, 0, 0.0

    def _add(self, type_, **kw):
        self._t += 0.1
        self.log.append({"t": round(self._t, 3), "epoch": self.epoch, "type": type_, **kw})

    def snap(self, controls):
        sid = hashlib.sha256(json.dumps(controls, sort_keys=True).encode()).hexdigest()[:12]
        if sid not in self.snaps:
            self.snaps[sid] = controls
            self._add("snapshot", id=sid, links_dropped=0)
        return sid

    def doc(self, href, controls=None, res=None):
        self.epoch += 1
        self._add("hello", doc_id=f"d{self.epoch}", href=href, restored=False, persisted=False, nav_type="navigate")
        self._add("armed", pre_arm_inputs=0, pre_kinds=[])
        sid = self.snap(controls if controls is not None else [])
        self._add("baseline", snap=sid, **({"res": res} if res is not None else {}))
        return sid

    def group(self, kind, tgt, prev, cur=None, keys=(), nav=False, res=None):
        """One action group. prev/cur: control lists (snapshotted here) or snapshot ids. cur None = the document went away."""
        self._g += 1
        gid = f"g{self._g}"
        p = prev if isinstance(prev, str) else self.snap(prev)
        self._add("group_open", gid=gid, kind=kind, target=tgt, prev_snap=p, **({"res": res} if res is not None else {}))
        if cur is None:
            self._add("group_close", gid=gid, synthetic=True, snap=None, doc_navigated_after=True)
            return p, None
        c = cur if isinstance(cur, str) else self.snap(cur)
        self._add("group_close", gid=gid, kind=kind, snap=c, keys=list(keys), **({"doc_navigated_after": True} if nav else {}))
        return p, c

    def mark(self, text_="", group=None, href=None, tag="TABLE", truncated=False):
        self._add("mark", tag=tag, text=text_, text_truncated=truncated, href=href or "", group=group)

    def done(self):
        self._add("done")

    def incomplete(self, reason):
        self._add("incomplete", reason=reason)

    def write(self, path: Path, state="completed", finished=None):
        path = Path(path)
        (path / "snapshots").mkdir(parents=True, exist_ok=True)
        (path / "log.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in self.log), encoding="utf-8")
        for sid, ctl in self.snaps.items():
            (path / "snapshots" / f"{sid}.json").write_text(json.dumps({"controls": ctl}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        from kfw.record import Store
        meta = {"id": path.name, "state": state, "reason": None, "reasons": [], "url": "http://a.test/", "finished": finished or time.time(),
                "records": len(self.log), "bytes": 0, "digest": Store(path).digest()}
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return meta


CITIES = ["Taipei", "Taichung", "Kaohsiung"]
ROWS = [["0101", "08:00", "Taichung"], ["0103", "09:00", "Taichung"], ["0105", "10:30", "Taichung"]]


def form_recording(city="Taichung", date="2026-10-05", name="王小明", via_widget=True, headers=("車次", "時間", "目的地"), rows=None, href="http://a.test/form.html"):
    """The canonical A-version demonstration: pick a city (select), type a name, pick a date on a home-made date picker (a plain
    grid cell, not a field), click 查詢, then mark the result table on the next document."""
    r = Rec()
    fields0 = [select("k1", "城市", "Taipei", CITIES), text("k2", "姓名", ""), text("k3", "日期", ""), button("k4", "查詢")]
    base = r.doc(href, fields0)
    after_city = [select("k1", "城市", city, CITIES), *fields0[1:]]
    r.group("keyboard", field_target("k1", "城市", "SELECT"), base, after_city)
    after_name = [after_city[0], text("k2", "姓名", name), *after_city[2:]]
    r.group("text_input", field_target("k2", "姓名"), after_city, after_name)
    after_date = [*after_name[:2], text("k3", "日期", date), after_name[3]]
    if via_widget:
        r.group("pointer", target(None, "", tag="TD"), after_name, after_date)
    else:
        r.group("text_input", field_target("k3", "日期"), after_name, after_date)
    r.group("pointer", button_target("k4", "查詢"), after_date, None)
    r.doc("http://a.test/result.html", [button("k9", "回表單")])
    rows = rows or ROWS
    r.mark("車次 時間 目的地 " + " ".join(" ".join(x) for x in rows),
           table_group(rows, headers=list(headers) if headers else None), href="http://a.test/result.html")
    r.done()
    return r


def detail_recording(text_="今日公告 本週停駛班次:無 更新時間 08:00", href="http://a.test/notice.html"):
    r = Rec()
    r.doc(href, [button("k1", "重新整理")])
    r.mark(text_, None, href=href, tag="DIV")
    r.done()
    return r


def build_scenarios():
    """(Re)write the committed scenario directories under tests/fixtures/recordings/."""
    scenarios = {"form_basic": form_recording(), "form_no_widget": form_recording(via_widget=False),
                 "detail_text": detail_recording()}
    for name, rec in scenarios.items():
        d = FIXTURE_DIR / name
        d.mkdir(parents=True, exist_ok=True)
        rec.write(d, finished=1_780_000_000)


if __name__ == "__main__":
    build_scenarios()
