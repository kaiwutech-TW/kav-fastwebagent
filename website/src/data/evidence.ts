export const benchmarks = [
  { task: '高鐵時刻查詢', kav: '約 22 秒', browser: '約 116 秒', scope: '整趟對話，小樣本單站比較', detail: 'Kav 共 3 次（其中一次修正前誤讀抵達時間）；對照 4 次。Kav 列出 5 班，對照有時翻頁列出更多班次。' },
  { task: '台銀匯率讀表', kav: '19 秒', browser: '20 秒', scope: '各 1 次，未顯示速度優勢', detail: '只需要打開一頁讀表的任務，本次沒有看到明顯差距。' },
] as const;

export const historicalTrains = [
  { number: '0648', departure: '15:00', arrival: '15:59', duration: '59 分' },
  { number: '1234', departure: '15:08', arrival: '15:54', duration: '46 分' },
  { number: '0652', departure: '15:32', arrival: '16:33', duration: '61 分' },
] as const;

export const firstFlowPrompt = `幫我做一個流程：
網站：台灣高鐵時刻表
每次會換的：出發站、到達站、日期、時間
我要看到的結果：車次、出發時間、抵達時間
怎樣算對：站名和日期正確，每一欄都能對回官網。`;

export const evidenceDate = '2026-09-29';
