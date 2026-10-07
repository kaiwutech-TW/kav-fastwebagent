# 繁中(台灣)評測 — 基準線 v0

以 [zh-decision-bench v0.2](https://github.com/CodyQin/zh-decision-bench)(CC BY 4.0)為底,加上 Kev 與台灣繁中變體。
Jev / NeoHorse / Laya / Qwen 的數字取自該 repo 公開的 raw predictions(`results/raw/v02*_*.jsonl`),
Kev-4B 是本機實跑(M5 Max 36GB,MLX bf16,`jaredpalmer/kev-4b@139fdd9`),用同一支 `report.py` 計分。

## 結果(accuracy / ECE,簡中原題)

| 題組 | n | Jev API | **Kev-4B(本機)** | NeoHorse-4B | Laya-multi 322M | Qwen3.5-2B probe |
|---|---|---|---|---|---|---|
| 語音指令路由 | 323 | **0.960** / 0.035 | 0.954 / 0.076 | 0.950 / 0.031 | 0.870 / 0.056 | 0.938 / 0.020 |
| 電商客服路由 | 25 | 0.920 / 0.064 | **0.960** / 0.137 | **0.960** / 0.068 | 0.640 / 0.293 | 0.920 / 0.058 |
| 客服緊急度(score) | 25 | **0.680** / 0.207 | 0.480 / 0.202 | 0.520 / 0.172 | 0.560 / 0.091 | 0.640 / 0.243 |
| 詐騙/違法推廣(noul) | 15 | **0.933** / 0.081 | 0.867 / 0.179 | 0.733 / 0.221 | 0.667 / 0.311 | 0.533 / 0.421 |
| 是否轉人工(noul) | 40 | 0.525 / 0.216 | 0.550 / 0.214 | 0.550 / 0.280 | 0.550 / 0.230 | 0.400 / 0.486 |
| **簡→繁翻轉率**(語音) | 323 | 1.7% | **1.5%** | 3.4% | 12.8% | 2.2% |

## Kev-4B 繁中變體

| 資料 | 對照 | 翻轉率 | 準確率(簡 → 繁) |
|---|---|---|---|
| `massive_tw_statecn` 台灣原生語句 + 簡中選項 | v02 語音 | 1.5% | 0.954 → 0.957 |
| `massive_tw_full` 台灣原生語句 + 繁中選項 | v02 語音 | 2.8% | 0.954 → 0.963 |
| `synthetic_tw_s2twp` 客服/審核(機器轉繁) | v02s | 10.5% | 0.676 → 0.657 |

延遲:本機每題約 70 ms(含 HTTP,重複文字走 cache),冷啟動第一次請求約 3 s。

## 解讀與限制

- 路由類(choice)Kev-4B 已與 Jev 同級;**弱點是 score 題(緊急度)與 noul 題的校準**,ECE 約是 Jev 的 2 倍 → 上線前要在繁中資料重擬 temperature。
- 客服/審核題組 n=15–25,CI 很寬,只能看方向。
- 語音題是 MASSIVE 的在地化翻譯,不是台灣真實客服語料;`synthetic_tw_s2twp` 只是字形轉換,用語仍是陸用(見 TRAPS `opencc-s2twp-keeps-mainland-vocab`)。
- **下一步**:台灣原生商業題組(客服、LINE 訊息、電商、詐騙簡訊、個資),人工標註,每組 n≥100。

## 重現

```bash
cd vendor/kev && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009   # 另一個 terminal
uv run bench/make_tw.py
uv run bench/run_kev.py --data vendor/zh-decision-bench/data/massive_items.jsonl --out v02_kev-4b
uv run bench/run_kev.py --data evals/massive_tw_full.jsonl --out tw_massive_tw_full_kev-4b
uv run bench/compare.py results/raw/v02_kev-4b.jsonl results/raw/tw_massive_tw_full_kev-4b.jsonl
cd vendor/zh-decision-bench && uv run --with numpy --with scikit-learn python src/report.py results/raw/v02_jev.jsonl ../../results/raw/v02_kev-4b.jsonl
```

`vendor/`(kev、zh-decision-bench、MASSIVE)不進 git,依上方來源 clone/下載。
