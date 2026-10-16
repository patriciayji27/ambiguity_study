/* eslint-disable no-await-in-loop */
import { test, expect } from '@playwright/test';

// This study's .env uses Firebase. Run with VITE_STORAGE_ENGINE=localStorage so the test
// does not write participants (or consume sequence assignments) in the production project.
test.skip(process.env.VITE_STORAGE_ENGINE !== 'localStorage', 'Run with VITE_STORAGE_ENGINE=localStorage');

test('demo-headline records HTML choices, risk precheck, and Prolific ID', async ({ page }) => {
  test.setTimeout(300000);

  await page.goto('/demo-headline');
  const next = page.getByRole('button', { name: 'Next', exact: true });
  const frame = page.frameLocator('iframe');

  // Consent and instructions
  await page.getByRole('radio', { name: 'Yes, I consent to participate' }).click();
  await page.getByRole('button', { name: 'I agree to participate' }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();

  // Risk precheck: Next stays disabled until all 16 answers are submitted
  await frame.getByRole('button', { name: 'Start questions' }).click();
  await expect(next).toBeDisabled();
  for (let i = 0; i < 16; i += 1) {
    await frame.locator('#ceInput').fill('10');
    await frame.locator('.actions button:not(.secondary)').click();
  }
  await expect(frame.getByText('Decision questions complete')).toBeVisible();
  await expect(next).toBeEnabled();
  await next.click();

  // 2 practice trials + 32 main trials: Next stays disabled until an option is chosen
  for (let trial = 0; trial < 34; trial += 1) {
    await expect(frame.locator('#btn-a')).toBeEnabled();
    await expect(next).toBeDisabled();
    await frame.locator(trial % 2 === 0 ? '#btn-a' : '#btn-b').click();

    const outcome = frame.locator('#fb .main');
    await expect(outcome).toContainText('Generated outcome:');
    await expect(outcome).not.toContainText('<i>');
    await expect(next).toBeEnabled();
    await next.click();
  }

  // Post-study free response
  await expect(page.getByText('Post-study feedback')).toBeVisible();
  await page.getByPlaceholder('Briefly describe what you focused on when reading the charts.').fill('chart features');
  await page.getByPlaceholder('Briefly describe your decision process.').fill('strategy');
  await page.getByRole('button', { name: 'Continue to debrief' }).click();

  // Post-study survey
  await page.getByRole('radio', { name: 'Man', exact: true }).click();
  await page.getByRole('checkbox', { name: 'Asian / Asian American' }).click();
  await page.getByRole('radio', { name: '25–34' }).click();
  await page.getByRole('radio', { name: 'Bachelor’s degree' }).click();
  await page.getByRole('radio', { name: 'Weekly', exact: true }).nth(0).click();
  await page.getByRole('radio', { name: '1–3 years' }).click();
  await page.getByRole('radio', { name: 'Under $1,000' }).click();
  await page.getByRole('radio', { name: 'Weekly', exact: true }).nth(1).click();
  await page.getByRole('radio', { name: '4', exact: true }).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();

  // Final page: Prolific ID is required
  const finish = page.getByRole('button', { name: 'Finish', exact: true });
  const prolificId = page.getByPlaceholder('Your Prolific ID');
  await expect(prolificId).toBeEditable();
  await expect(finish).toBeDisabled();
  await prolificId.fill('E2E_PROLIFIC_ID');
  await expect(finish).toBeEnabled();
  await finish.click();

  // Read back what the localStorage engine persisted (saves are throttled to 3s)
  await expect.poll(async () => page.evaluate(async () => {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const req = indexedDB.open('revisit');
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    const store = db.transaction('keyvaluepairs', 'readonly').objectStore('keyvaluepairs');
    const keys = await new Promise<IDBValidKey[]>((resolve) => {
      const req = store.getAllKeys();
      req.onsuccess = () => resolve(req.result);
    });
    const key = keys.find((k) => String(k).includes('demo-headline/participants/'));
    if (!key) return null;
    const data = await new Promise<{ completed: boolean; answers: Record<string, { componentName: string; answer: Record<string, unknown> }> }>((resolve) => {
      const req = store.get(key);
      req.onsuccess = () => resolve(req.result);
    });
    const answers = Object.values(data.answers);
    const precheck = answers.find((a) => a.componentName.endsWith('-risk-precheck'));
    const arm = precheck?.componentName.slice(0, 3);
    return {
      completed: data.completed,
      trialsWithChoice: answers.filter((a) => ['optionA', 'optionB'].includes(a.answer['investment-choice'] as string)).length,
      precheckComplete: precheck?.answer[`risk-precheck-${arm}-complete`],
      precheckEntered: Object.keys(precheck?.answer || {}).filter((k) => k.includes('-entered-amount-')).length,
      prolificId: answers.find((a) => a.componentName === 'debrief')?.answer.prolific_id,
    };
  }), { timeout: 15000 }).toEqual({
    completed: true,
    trialsWithChoice: 34,
    precheckComplete: true,
    precheckEntered: 16,
    prolificId: 'E2E_PROLIFIC_ID',
  });
});
