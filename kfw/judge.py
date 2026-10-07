"""Is this listing the product the caller asked for?

Split by what each side is good at (TRAPS kev-weak-at-literal-model-matching):
  code  — literal model constraints the planner supplies: `must` (every group needs one hit)
          and `must_not`, on NFKC-lowercased text with spaces removed;
  Kev   — semantic checks it answers well: accessory / bundle / refurbished / instalment price.
On evals/price v0 this scored 0.949 accuracy, recall 1.0 (evals/price/README.md).
"""

import threading
import time
import unicodedata

import httpx

SEMANTIC = {
    "accessory": "這筆商品是不是配件、耗材、周邊或遊戲軟體,而不是規格中的主商品本身?",
    "bundle": "除了主商品之外,是否另外搭售其他要一起付錢的商品(例如遊戲片、充電器、保護殼組、第二件相同商品)?"
              "贈品、商品卡、P幣、點數、贈送的收納架或耳機架、帆布袋都不算。",
    "refurb": "這是福利品、整新品或二手商品嗎?",
    "installment": "標示的價格是分期或訂閱的每期金額,而不是一次付清的售價嗎?",
}
NONE_ID = "none"  # the reserved "none of these" option of choice_dist
KIND_NAMES = {"E": "match", "O": "other_model", "A": "accessory", "B": "bundle", "R": "refurbished", "X": "instalment"}


def normalize(s):
    return unicodedata.normalize("NFKC", s or "").lower().replace(" ", "")


def literal_match(title, must, must_not):
    t = normalize(title)
    return all(any(normalize(w) in t for w in group) for group in must) and not any(normalize(w) in t for w in must_not)


class Judge:
    def __init__(self, kev_url="http://127.0.0.1:8009", timeout=60):
        self.url = kev_url.rstrip("/") + "/v1/systemone"
        self.client = httpx.Client(timeout=timeout)
        self._lock = threading.Lock()
        self._usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "call_ms_sum": 0.0, "model_ms_sum": 0.0}

    def _post(self, body):
        """One Kev call, tallied so a run can report what the local model cost (tokens and time)."""
        t0 = time.perf_counter()
        r = self.client.post(self.url, json=body)
        r.raise_for_status()
        j = r.json()
        wall = (time.perf_counter() - t0) * 1000
        with self._lock:
            u = self._usage
            u["calls"] += 1
            u["input_tokens"] += j.get("usage", {}).get("input_tokens", 0)
            u["output_tokens"] += j.get("usage", {}).get("output_tokens", 0)
            u["call_ms_sum"] += wall
            u["model_ms_sum"] += j.get("latency_ms") or 0
        return j, wall

    def usage(self):
        """Kev cost so far: calls, tokens, and time summed over calls — as kfw waited (incl. queueing, HTTP) and as Kev
        reports its own model time. Sites run in parallel, so these sums can exceed the run's total_ms."""
        with self._lock:
            return {k: round(v) if isinstance(v, float) else v for k, v in self._usage.items()}

    def healthy(self):
        try:
            return self.client.get(self.url.rsplit("/v1/", 1)[0] + "/v1/models", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def judge(self, spec, card, must, must_not):
        """Returns (kind, p_match, model_ms). kind is one of KIND_NAMES; model_ms is 0 when code decided."""
        if not literal_match(card["title"], must, must_not):
            return "O", 0.0, 0.0
        state = {"規格": spec, "商品標題": card["title"], "商品卡片文字": card.get("text", "")}
        qs = {k: {"type": "noul", "instructions": v} for k, v in SEMANTIC.items()}
        j, ms = self._post({"model": "kev-latest", "state": state, "questions": qs})
        a = {k: v["noul"] for k, v in j["answers"].items()}
        kind = ("X" if a["installment"] >= 0.5 else "A" if a["accessory"] >= 0.5 else
                "R" if a["refurb"] >= 0.5 else "B" if a["bundle"] >= 0.5 else "E")
        p_match = min(1 - a["accessory"], 1 - a["bundle"], 1 - a["refurb"], 1 - a["installment"])
        return kind, p_match, ms

    def choice(self, question, options, state=None):
        """Generic fuzzy pick for recipes (e.g. which option means "Taipei"). Returns {choice, p}."""
        crit = {o: None for o in options}
        j, _ = self._post({"model": "kev-latest", "state": state or {},
                           "questions": {"q": {"type": "choice", "instructions": question, "criteria": crit}}})
        a = j["answers"]["q"]
        return {"choice": a["choice"], "p": a["probabilities"][a["choice"]]}

    def row_match(self, want, options, state=None):
        """Which rows satisfy `want`, as ONE yes/no (noul) question per row, sent in one request (design 6.4).
        Kev answers independent per-row questions far more decisively than one multiple choice over the list
        (2026-09-29, 5 colloquial Chinese wants over 4 rows: choice stopped on 4/4 answerable ones, per-row noul
        put the right row first on 4/4 at p >= 0.92 and every row <= 0.007 when nothing fit).
        Returns {id: p} plus NONE_ID = 1 - max(p): "no row fits" is as likely as the best row is not."""
        if NONE_ID in options:
            raise ValueError(f"{NONE_ID!r} is reserved for 'none of these'")
        qs = {cid: {"type": "noul", "instructions": f"使用者要找的是「{want}」。這個項目「{text}」是不是使用者要找的?"}
              for cid, text in options.items()}
        j, _ = self._post({"model": "kev-latest", "state": state or {}, "questions": qs})
        answers = j.get("answers") or {}
        if set(answers) != set(options) or any(not isinstance((answers[k] or {}).get("noul"), (int, float)) for k in options):
            raise ValueError(f"Kev's answers do not cover exactly the rows {sorted(options)}: {answers!r}")
        probs = {k: float(answers[k]["noul"]) for k in options}
        probs[NONE_ID] = 1.0 - max(probs.values(), default=0.0)
        return probs

    def choice_dist(self, question, options, state=None):
        """Fuzzy pick with the FULL probability distribution (design 6.4). `options` maps a stable id (c1..cn) to its
        text; the ids are the answer keys, so two options with the same text are never merged. "none" (reserved,
        "none of these") is added here. Kev returns answers.q.probabilities for every criterion; a response that
        does not cover exactly those is refused (ValueError) rather than filled in. Returns {id: p} incl. "none"."""
        if NONE_ID in options:
            raise ValueError(f"{NONE_ID!r} is reserved for 'none of these'")
        crit = {**options, NONE_ID: "以上都不是"}
        j, _ = self._post({"model": "kev-latest", "state": state or {},
                           "questions": {"q": {"type": "choice", "instructions": question, "criteria": crit}}})
        probs = ((j.get("answers") or {}).get("q") or {}).get("probabilities")
        if not isinstance(probs, dict) or set(probs) != set(crit):
            raise ValueError(f"Kev's probabilities do not cover exactly the options {sorted(crit)}: {probs!r}")
        return {k: float(v) for k, v in probs.items()}
