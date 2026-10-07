# Kav-FastwebAgent

**繁體中文** | [English](README.en.md) | [简体中文](README.zh-CN.md)

**常做的網頁查詢，說一次就變成「流程」;之後一句話，本機約 6 秒跑完，結果由程式核對過。**

叫 AI agent 幫你查高鐵，它會看截圖、點一下、再看截圖……每次都從頭摸索一遍：兩分鐘，將近百萬 token。
可是你每週查的都是同一個網站、同一張表，只是日期和站名不同。

Kav 的做法是：第一次由 Claude 看懂網頁、寫成一份「流程」,試跑給你確認；之後同樣的事直接在你的 Mac 上用專屬 Chrome 執行，
程式負責確認「真的查到了」;需要語意判斷(從列表挑哪一筆)時,簡單的題目可交給本機小模型 [Kev](https://github.com/jaredpalmer/kev)(選配),其餘交回給 Claude。網站改版壞了，你只要說「結果不對」,Claude 會修好再回報。


<sub>同一句話「幫我查 10/12 下午三點以後台中到台北的高鐵班次」。上:Kav 流程；下:Claude in Chrome 一步步操作。2026-09-29 實測，兩邊答案都和官網一致。</sub>

## 它能幫你什麼

### 如果你不寫程式

你只要會說話，再判斷結果對不對。

- **重複的查詢一句話完成**:高鐵時刻、今天匯率、幾家電商比價、包裹追蹤、各種「填表 → 查詢 → 讀結果」的網頁。
- **結果附證據**:每次都有截圖；查不到、要登入、被網站擋，它會直接說原因，不會假裝做完。
- **壞了不用找工程師**:說「結果不對，應該是…」,Claude 自己修好流程、重跑、再告訴你改了什麼。

### 如果你已經在用 Claude Code / Codex

| 你現在的痛點 | 用 Kav 之後 |
|---|---|
| 叫 agent 操作網頁很慢，每次都在看截圖、試錯 | 固定的網頁動作變成流程，本機直接跑。高鐵查詢約 **22 秒 vs 116 秒**(約 5 倍) |
| 一次網頁任務燒掉幾十萬到上百萬 token | 同一題輸入 token **17–27 萬 vs 77–128 萬**(約 4 倍);抓資料不經過模型,判斷題只把抓好的文字交給模型 |
| agent 說「完成了」,其實頁面還沒載完、讀錯欄 | 「完成」由程式判斷：載入偵測、送出後讀回確認、每格附欄名、日期要是今天、價格回商品頁再核對一次 |
| 寫爬蟲要工程師，網站一改版就壞 | 流程是資料(JSON),不是程式；壞了 Claude 照固定方法修 |
| 擔心 agent 亂點：登入、付款、繞過驗證 | 這些禁止規則寫在本機程式裡，不交給模型判斷 |

### 適合 / 不適合

| 適合 | 不適合 |
|---|---|
| **多步驟、會重複做**的網頁動作：填表查詢(時刻表、包裹、查詢系統)、多站搜尋比對 | 只做一次的事、單純打開一頁看看(直接用 Claude in Chrome 一樣快，台銀匯率實測兩邊都約 20 秒) |
| 固定網址讀資料，而且要確認是最新的(今天的匯率、公告) | 登入、付款、下單、解驗證碼(不做，這是設計) |
| 你在 Kav 專用 Chrome 自己登入過的網站 | 擋自動化的網站(例：蝦皮)、遊戲、非網頁的桌面程式 |

## 實際做過的例子

**高鐵時刻(填表查詢)**:「查 10/12 下午三點以後台中到台北的高鐵」→ 約 6 秒,Kev 呼叫 0 次。

![高鐵查詢結果截圖](docs/images/thsr-result.jpg)

**台銀今天匯率(讀固定網頁、檢查是不是今天的)**:使用者一句「幫我做一個流程：查台灣銀行今天的美金跟日圓匯率」,
Claude 從零寫出流程，第一次試跑就通過(約 36 秒)。使用者再說「加上檢查是不是今天的」,之後頁面上的掛牌日期不是今天，就會回報「還沒掛牌」,不會拿舊資料充數。

![台銀牌告匯率截圖](docs/images/bot-fx-rates.jpg)

**四家電商比價(搜尋 + 語意判斷)**:PChome / momo / Yahoo / 酷澎同時搜尋。「主機」和「主機 + 遊戲組合包」、配件、福利品的差別由本機 Kev 判斷。
Switch 2 一趟 5.6–7.8 秒,Kev 呼叫 18–31 次、約 6–11 千 token(全在本機)。最低價還會打開商品頁再核對一次。

![酷澎搜尋結果截圖](docs/images/compare-coupang.jpg)

<details>
<summary>數字怎麼量的、還不夠的地方</summary>

- 對照組：同一句話分別交給「Kav 流程」和「Claude in Chrome 一步步操作」,各開全新 Claude Code session。高鐵 Kav 3 次、對照 4 次；台銀各 1 次。**樣本還小**,5 倍只來自高鐵一個網站。
- 建立流程是一次性成本(台銀約 36 秒、3 次工具呼叫);修一次壞掉的流程約 1.2–2.6 萬輸出 token。修流程目前只在一個網站、兩種壞法上盲測過。
- 高鐵、匯率這兩個流程**完全沒用到 Kev**,它們的速度來自「流程 + 本機程式」;Kev 目前只在比價這種需要語意判斷的流程出力。
- **Kev 是選配,不是賣點**。2026-10-07 在 591 租屋列表(30 筆、18 題口語需求)實測「挑哪一筆」:Kev 零錯選、該停的全停,但兩個條件並列或「最便宜」這類題目都會停下,唯一解只答對 4/11;Claude 讀同一份文字全對。抓資料這段引擎 31 毫秒,Claude 自己開瀏覽器做同一件事 21–162 秒、每題 45–91 萬 token。所以省時省 token 的是「引擎抓資料」,判斷題最划算的做法是交給 Claude;Kev 只在單一屬性的題目、或要離線時有用。紀錄:`.flightwake/records/261007-pick-judgment-experiment.md`。
- 完整紀錄在 `.flightwake/records/`(`260929-control-experiment-and-demo`、`260929-kev-usage-accounting`)。

</details>

## 它怎麼運作

![第一次用說的建立流程；之後每次一句話在本機跑](docs/images/how-it-works.svg)

- **Claude**:聽懂你的需求、寫流程、流程壞了負責修。
- **Kav(本機程式)**:用專屬 Chrome 執行流程，判斷頁面載好了沒、欄位有沒有填進去、結果是不是真的出現；做不到就回報 `needs_help` 附原因和截圖。
- **Kev(本機小模型)**:只回答模糊的判斷題，例如「這個商品是主機本體還是組合包?」。

## 適合的電腦

Kav 本身(Chrome + 本機程式)很輕，吃資源的是本機小模型 Kev。先看你要跑的流程需不需要 Kev:

| 你要跑的流程 | 需要 Kev 嗎 | 建議配備 |
|---|---|---|
| 填表查詢、讀固定網頁(高鐵、匯率) | 不需要 | 任何跑得動 Chrome 和 Claude Code 的 Mac |
| 比價、需要判斷「是不是同一個東西」 | 需要 | Apple Silicon(M1 以後)Mac,**32GB 記憶體**跑 Kev-4B |

### 選哪個 Kev

| 模型 | 硬體(Kev 官方標示) | 準確率(Kev 官方評測，沒訓練過的題型) | 建議 |
|---|---|---|---|
| Kev-0.8B | 任何 Apple Silicon Mac | 0.648 | 16GB 的 Mac 可以試；Kav 還沒用它實測過 |
| **Kev-4B** | 32GB Mac | 0.817 | **預設**,Kav 的實測都用它 |
| Kev-9B | 32GB Mac | 0.822 | 比 4B 準一點點、模型大一倍，一般不需要 |
| Kev-27B | 80GB 資料中心 GPU | 0.848 | 沒有 Mac 版本 |

換模型只要改啟動指令的 `--run`,例如 `--run jaredpalmer/kev-0.8b`,Kav 不用改設定。

**我們的實測機器**:Apple M5 Max、36GB 記憶體。Kev-4B 自動走 MLX(bf16),執行中約佔 4.5GB 記憶體；比價一趟 4 個網站並行,Kev 呼叫 18–31 次。

**Claude 那端**:我們的實測都用 Claude Opus 5.5。跑已經存好的流程很省(只要填參數);寫新流程和修流程比較吃模型能力，其他模型還沒測過。

### Mac 要注意的

- **Apple Silicon(M1 以後)才建議跑 Kev**:Kev 在 Apple Silicon 上自動用 MLX 加速。Intel Mac 沒有 MLX,只能用 CPU 跑，會很慢；不跑 Kev 的流程不受影響。
- Chrome 要裝在預設位置(`/Applications/Google Chrome.app`);裝在別的地方就設定 `KFW_CHROME` 指向它。
- Kav 會另外開一個 Chrome 視窗(專屬設定檔、除錯埠 9333),不會動到你平常的 Chrome。

### Windows 要注意的(還沒實測)

Kav 目前只在 Mac 上測過。程式沒有綁死 macOS,但以下幾點一定要處理:

- **Chrome 位置**:預設路徑是 Mac 的，要設定 `KFW_CHROME`,例如註冊 MCP 時加上
  `-e KFW_CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"`。
- **資料夾**:截圖、流程、Chrome 設定檔會放在 `%USERPROFILE%\.kav-fastweb\`。
- **Kev 要有 NVIDIA 顯示卡(CUDA)**:Windows 上沒有 MLX,沒有 GPU 只能用 CPU 跑，實際上太慢。Kev 官方只標示資料中心 GPU(L4 / L40S / H100),一般遊戲顯示卡能不能跑 4B 我們沒測過。
  沒有合適的顯示卡，可以只跑不需要 Kev 的流程；或者在另一台 Mac 上跑 Kev(`--host 0.0.0.0`),再把 `KFW_KEV` 設成 `http://<那台 Mac 的 IP>:8009`。這種做法也還沒實測過，而且只適合在家裡或公司內網用：Kav 目前不支援 Kev 的 API 金鑰。
- 下面的安裝指令是 macOS / Linux 的寫法;Windows 請在 PowerShell 裡照著改，或直接把「貼給 Claude Code」那段交給它處理。

## 安裝

需要:Google Chrome、[uv](https://docs.astral.sh/uv/)、Claude Code。Kev-4B 第一次要下載約 9GB。

### 最簡單：把這段貼給你的 Claude Code

````text
請幫我安裝 Kav-FastwebAgent,每一步做完告訴我結果：
1. 把 https://github.com/kaiwutech-TW/Kav-FastwebAgent clone 到 ~/Kav-FastwebAgent,在裡面執行 uv sync。
2. 問我要不要裝 Kev(本機小模型，約 9GB,比價才需要)。要的話：
   git clone https://github.com/jaredpalmer/kev ~/Kav-FastwebAgent/vendor/kev
   然後在 vendor/kev 裡執行 uv sync --extra serve
3. 讓我在任何資料夾都能用：
   - 用 claude mcp add --scope user kav-fastweb -- uv run --project <~/Kav-FastwebAgent 的絕對路徑> python -m kfw.mcp_server 註冊 MCP
   - 把 ~/Kav-FastwebAgent/.claude/skills/kav-fastweb 整個資料夾複製到 ~/.claude/skills/
   - 如果這台是 Windows:註冊 MCP 時加上 -e KFW_CHROME="<chrome.exe 的完整路徑>"
4. 告訴我以後怎麼啟動 Kev,並提醒我重開 Claude Code。
````

重開 Claude Code 後說「kav 的狀態」,它會告訴你 Chrome 和 Kev 有沒有在跑。

> 第 3 步(在任何資料夾都能用)還沒實測過。目前實測過的用法是：在 Kav 資料夾裡開 Claude Code,專案內建的 `.mcp.json` 和 skill 會自動載入。

### 手動安裝

```bash
git clone https://github.com/kaiwutech-TW/Kav-FastwebAgent ~/Kav-FastwebAgent && cd ~/Kav-FastwebAgent && uv sync
# 選用：Kev(比價才需要,第一次下載約 9GB)
git clone https://github.com/jaredpalmer/kev vendor/kev
cd vendor/kev && uv sync --extra serve && uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port 8009
```

在 `~/Kav-FastwebAgent` 開 Claude Code,核准 `.mcp.json` 裡的 `kav-fastweb`。
Chrome 沒開的話會自動開一個獨立的設定檔(`~/.kav-fastweb/chrome-profile`,不是你平常用的 Chrome)。截圖存在 `~/.kav-fastweb/runs/`。

<details>
<summary>Codex 使用者(未實測)</summary>

Kav 是標準的 MCP server,理論上 Codex 也能用。在 `~/.codex/config.toml` 加上：

```toml
[mcp_servers.kav-fastweb]
command = "uv"
args = ["run", "--project", "/你的路徑/Kav-FastwebAgent", "python", "-m", "kfw.mcp_server"]
```

再把 `.claude/skills/kav-fastweb` 複製到 Codex 讀得到的 skills 資料夾(例如專案裡的 `.agents/skills/`)。

</details>

## 設定你固定要做的網頁操作

### 1. 用這個句型告訴 Claude

````text
幫我做一個流程：
- 網站:<網址>
- 每次會換的:<例:出發站、到達站、日期>
- 我要看到的結果:<例:車次、出發和抵達時間>
- 怎樣算對:<選填，例：日期一定要是今天>
````

說不完整也沒關係，缺什麼 Claude 會一次問完。

### 2. Claude 試跑，給你看結果

Claude 會打開網頁看有哪些欄位、寫好流程、試跑一次，然後給你看重點結果和截圖，問「這是你要的結果嗎?」。
你只要判斷結果對不對：

- 對 → 說「對」,它存起來，並告訴你以後怎麼叫。
- 不對 → 直接說哪裡不對(「少了票價」「要看的是現金賣出」),它改好再給你看一次。

### 3. 之後一句話就能用

| 你想… | 就說 |
|---|---|
| 用流程 | 直接問，例如「查 10/20 新竹到台南早上九點以後的高鐵」 |
| 結果不對、網站改版 | 「結果不對，應該是…」 → Claude 修好、重跑、再告訴你改了什麼 |
| 看有哪些流程 | 「我有哪些流程?」 |
| 刪掉流程 | 「刪掉 <某個> 流程」(移到 `~/.kav-fastweb/trash/`,可以救回) |
| 用要登入的網站 | 先在 Kav 專用的 Chrome 視窗自己登入一次(建議用副帳號)。Kav 不會替你登入 |

**寫流程的小訣竅**:「怎樣算對」寫得越具體，流程越可靠。例如匯率流程加了「日期是今天」,舊資料就不會被當成答案。

### 說不清楚?示範一次給它看(新功能,驗收中)

有些網站要點好幾頁、從列表挑一筆、或用了特殊的選單,用說的很難講清楚。這時說「**我示範給你看**」:

1. Claude 在 Kav 的 Chrome 開好網頁,你照平常的方式**用一組真實的例子**做一次(不要輸入密碼、卡號等個資)。
2. 結果出現後,按頁面上方的「**標記結果**」,點你要的那一塊,再按「**完成**」。
3. Claude 把你做的轉成流程,在一個**乾淨的瀏覽器環境**重播一次:結果必須和你標記的一模一樣,才會給你確認、存起來。

限制:只能在同一個分頁裡操作;開新分頁、在內嵌框架(iframe)裡填表、要輸入密碼的頁面、結果一直在變(價格、剩餘名額)的任務,會直接告訴你錄不了。
流程壞了、Claude 修兩次都修不好時,它也會問你要不要示範一次。

### 不做的事

替你登入、破解驗證碼、付款或下單、高頻大量抓取。有些網站會擋自動化操作(例：蝦皮),遇到時它會停下來告訴你原因，不會嘗試繞過。
開著 Cloudflare WARP 或 VPN 時，部分網站(例：酷澎)會拒絕存取。

## 給開發者

Claude 照 `kav-fastweb` skill(`.claude/skills/kav-fastweb/`)為「網站 × 動作」寫**配方**(使用者看到的「流程」),試跑通過並附證據才存起來。
MCP 工具:`find_recipe`、`run_recipe`、`inspect_page`、`dry_run`、`save_recipe`、`list_recipes`、`delete_recipe`、`start_recording`、`stop_recording`、`status`。

內建配方(`recipes/`);使用者自己存的放在 `~/.kav-fastweb/recipes/`,同名時使用者的優先。

| 配方 | 類型 | 做什麼 |
|---|---|---|
| `tw-shop-compare` | search_compare | PChome / momo / Yahoo 購物 / 酷澎同時比價，回傳商品頁驗證過的最低價 |
| `thsr-timetable` | form_submit | 高鐵時刻表(起訖站、日期、時間 → 車次列表) |

每次執行都回傳 `kev`(Kev 呼叫次數、token、耗時加總)。

### 價格規則

`price` = 任何人都買得到的一次付清售價。首購價、刷卡回饋、點數只放在 `conditional_offers` / `notes`,不參與排序。
價格離中位數太遠(< 0.5× 或 > 2×)的商品移到 `suspicious`,不參與排序,需要 Claude 複核。

### 開發

```bash
uv run pytest -q          # 單元測試(價格規則用 83 張真實卡片)
uvx pyright               # 型別檢查
uv run python tests/mcp_e2e.py "PS5 Pro" "Sony PlayStation 5 Pro 主機(全新)" "ps5pro,playstation5pro;主機"   # 走 MCP 跑比價配方
uv run python tests/mcp_recipe_flow.py <recipe.json> '<params json>' [--save]   # 照 skill 的流程:dry_run → save → find
```

評測與數字見 `evals/price/README.md`;過程紀錄在 `.flightwake/`。
