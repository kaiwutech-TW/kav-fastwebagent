import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test('流程示意會跟隨條件，攔截相同站名且不發送真實查詢', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', request => { if (!request.url().startsWith('http://127.0.0.1:4321')) requests.push(request.url()); });
  await page.goto('/');
  await page.getByLabel('從哪裡出發').selectOption('新竹');
  await page.getByLabel('要去哪裡').selectOption('台南');
  await expect(page.locator('#demo-request')).toContainText('新竹到台南');
  await expect(page.locator('#demo-rows tr')).toHaveCount(0);
  await page.getByRole('button', { name: '播放流程示意' }).click();
  await expect(page.locator('#result-status')).toContainText('演示完成');
  await expect(page.locator('#result-title')).toHaveText('新竹到台南');
  await expect(page.locator('#demo-rows tr')).toHaveCount(3);
  await page.getByLabel('從哪裡出發').selectOption('台中');
  await page.getByLabel('要去哪裡').selectOption('台中');
  await page.getByRole('button', { name: '再播放一次' }).click();
  await expect(page.getByRole('alert')).toContainText('出發站和到達站相同');
  expect(requests).toEqual([]);
});

test('錄製說明可標記、取消、完成與重設，並保留驗證邊界', async ({ page }) => {
  await page.goto('/#recording');
  const mark = page.getByRole('button', { name: '標記這張結果表' });
  const finish = page.getByRole('button', { name: '完成示範' });
  await expect(finish).toBeDisabled();
  await mark.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#record-mark')).toHaveAttribute('aria-pressed', 'true');
  await expect(finish).toBeEnabled();
  await page.getByRole('button', { name: '取消標記' }).click();
  await expect(finish).toBeDisabled();
  await mark.click();
  await finish.click();
  await expect(page.locator('#recording-next')).toContainText('不會錄下操作或儲存流程');
  await expect(page.getByRole('button', { name: '再試一次標記' })).toBeFocused();
  await page.getByRole('button', { name: '再試一次標記' }).click();
  await expect(mark).toBeFocused();
  await expect(finish).toBeDisabled();
  await expect(page.locator('.recording-proof')).toContainText('仍待真人驗收');
});

test('頁面導覽、圖片與文字入口有效，窄螢幕無橫向溢出', async ({ page, request }) => {
  for (const route of ['/', '/how-it-works/', '/evidence/', '/get-started/', '/technical/']) {
    const response = await page.goto(route);
    expect(response?.status()).toBe(200);
    await expect(page.locator('main h1')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const img of await page.locator('img').all()) {
      await img.scrollIntoViewIfNeeded();
      await expect.poll(() => img.evaluate(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0)).toBe(true);
    }
    const links = await page.locator('a[href^="/"]').evaluateAll(links => links.map(link => link.getAttribute('href')!));
    for (const link of new Set(links)) expect((await request.get(link.split('#')[0] || '/')).status(), link).toBe(200);
    const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    expect(accessibility.violations.map(v => `${v.id}: ${v.nodes.map(n => n.target).join(',')}`)).toEqual([]);
  }
  for (const path of ['/llms.txt', '/evidence-notes.txt']) expect((await request.get(path)).status()).toBe(200);
});

test('複製需求可用，剪貼簿失敗時保留手動操作說明', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write']);
  await page.goto('/get-started/');
  await page.getByRole('button', { name: '複製需求範例' }).click();
  await expect(page.locator('#copy-status')).toContainText('已複製');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain('幫我做一個流程');
  await page.evaluate(() => { Object.defineProperty(navigator.clipboard, 'writeText', { value: () => Promise.reject(new Error('denied')), configurable: true }); });
  await page.getByRole('button', { name: '複製需求範例' }).click();
  await expect(page.locator('#copy-status')).toContainText('手動複製');
});

test('reduced-motion 仍可操作，沒有 JavaScript 仍可讀取主要內容', async ({ page, browser }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await page.getByRole('button', { name: '播放流程示意' }).click();
  await expect(page.locator('#result-status')).toContainText('演示完成');
  const context = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await context.newPage();
  await staticPage.goto('http://127.0.0.1:4321/');
  await expect(staticPage.locator('h1')).toContainText('查過的事');
  expect(await staticPage.locator('.flow-demo noscript').textContent()).toContain('目前顯示靜態示意');
  expect(await staticPage.locator('.recording-demo noscript').textContent()).toContain('靜態錄製說明');
  await expect(staticPage.locator('.flow-demo .demo-table')).toBeVisible();
  await expect(staticPage.locator('.recording-demo .demo-table')).toBeVisible();
  await context.close();
});
