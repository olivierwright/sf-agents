/**
 * E2E tests for the sf-agents run flow.
 *
 * Prerequisites (both must be running before you run these tests):
 *   API server:  .\start_api.ps1   (or: uvicorn api.main:app --reload-dir api --reload-dir src --port 8000)
 *   UI server:   cd ui && npm start (ng serve on port 4200)
 *
 * Run:  cd ui && npx playwright test
 */

import { test, expect, Page } from '@playwright/test';

// ── Helpers ──────────────────────────────────────────────────────────────────

/** Wait for the phase indicator to reach 'done' or 'error'. */
async function waitForRunComplete(page: Page, timeoutMs = 240_000): Promise<string> {
  const indicator = page.locator('.phase-indicator');
  await indicator.waitFor({ state: 'visible', timeout: 15_000 });

  await page.waitForFunction(
    () => {
      const el = document.querySelector('.phase-indicator');
      if (!el) return false;
      return el.classList.contains('phase-done') || el.classList.contains('phase-error');
    },
    { timeout: timeoutMs },
  );

  const isDone = await page.locator('.phase-indicator.phase-done').count();
  return isDone > 0 ? 'done' : 'error';
}

/** If a HITL clarification box is visible, submit option "1" (continue/skip). */
async function handleClarificationIfVisible(page: Page): Promise<boolean> {
  const clarBox = page.locator('.clarification-box');
  const isVisible = await clarBox.isVisible().catch(() => false);
  if (!isVisible) return false;

  // Type option "1" = continue without missing items
  await page.locator('textarea.clar-ta').fill('1');
  await page.locator('button.clar-submit-btn').click();
  return true;
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Run flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // Wait for the app to load initial deal data
    await expect(page.locator('.ask-panel')).toBeVisible({ timeout: 15_000 });
  });

  test('page loads and shows the ask panel', async ({ page }) => {
    await expect(page.locator('.ask-panel')).toBeVisible();
    await expect(page.locator('textarea.question-input')).toBeVisible();
    await expect(page.locator('button.run-btn')).toBeVisible();
  });

  test('run button is disabled when question is empty', async ({ page }) => {
    await expect(page.locator('button.run-btn')).toBeDisabled();
    await page.locator('textarea.question-input').fill('test');
    await expect(page.locator('button.run-btn')).not.toBeDisabled();
  });

  test('full run: asks a question and receives an answer', async ({ page }) => {
    const question =
      'What is the total pool balance and how many loans are in the Green Lion 2026-1 deal?';

    // Type the question
    await page.locator('textarea.question-input').fill(question);

    // Select minimal strategy (fastest)
    await page.locator('button.strategy-pill', { hasText: 'Minimal' }).click();

    // Submit the run
    await page.locator('button.run-btn').click();

    // The ask panel should collapse and the terminal should appear
    await expect(page.locator('.phase-indicator')).toBeVisible({ timeout: 10_000 });

    // Handle up to 3 clarification prompts if they appear
    for (let i = 0; i < 3; i++) {
      await page.waitForTimeout(3_000);
      const handled = await handleClarificationIfVisible(page);
      if (handled) {
        console.log(`Handled HITL clarification ${i + 1}`);
      }
    }

    // Wait for the run to finish
    const finalPhase = await waitForRunComplete(page);
    expect(finalPhase).toBe('done');

    // The answer panel should appear
    await expect(page.locator('section.answer-panel')).toBeVisible({ timeout: 30_000 });

    // The answer text should be non-empty
    const answerText = await page.locator('.verdict-content').innerText();
    expect(answerText.trim().length).toBeGreaterThan(50);

    console.log('Answer preview:', answerText.substring(0, 200));
  });

  test('definitions question finds arrears and handles missing terms gracefully', async ({
    page,
  }) => {
    const question =
      'How does the prospectus formally define arrears, default and cure, and where does the investor report diverge materially?';

    await page.locator('textarea.question-input').fill(question);
    await page.locator('button.strategy-pill', { hasText: 'Minimal' }).click();
    await page.locator('button.run-btn').click();

    await expect(page.locator('.phase-indicator')).toBeVisible({ timeout: 10_000 });

    // Poll for clarification for up to 60s, handling it if it appears
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline) {
      await page.waitForTimeout(2_000);
      await handleClarificationIfVisible(page);

      const phaseEl = page.locator('.phase-indicator');
      const isDone = await phaseEl
        .evaluate(
          (el) => el.classList.contains('phase-done') || el.classList.contains('phase-error'),
        )
        .catch(() => false);
      if (isDone) break;
    }

    await waitForRunComplete(page);

    // Answer panel must be visible and have text
    await expect(page.locator('section.answer-panel')).toBeVisible({ timeout: 30_000 });
    const answer = await page.locator('.verdict-content').innerText();
    expect(answer.trim().length).toBeGreaterThan(100);

    // The answer must mention "arrears" (we always find that one)
    expect(answer.toLowerCase()).toContain('arrears');

    // Confidence badge should show > 0
    const confBadge = page.locator('.confidence-badge, [class*="conf"]').first();
    if (await confBadge.isVisible()) {
      const confText = await confBadge.innerText();
      console.log('Confidence:', confText);
    }

    console.log('Answer preview:', answer.substring(0, 300));
  });

  test('use-case chip pre-fills the question', async ({ page }) => {
    const chips = page.locator('button.chip');
    const count = await chips.count();
    if (count === 0) {
      test.skip();
      return;
    }

    await chips.first().click();
    const draft = await page.locator('textarea.question-input').inputValue();
    expect(draft.trim().length).toBeGreaterThan(0);
  });

  test('reset button clears the run state', async ({ page }) => {
    await page.locator('textarea.question-input').fill('Quick test question');
    await page.locator('button.strategy-pill', { hasText: 'Minimal' }).click();
    await page.locator('button.run-btn').click();

    // Wait until the run starts (phase indicator appears)
    await expect(page.locator('.phase-indicator')).toBeVisible({ timeout: 10_000 });

    // Click reset
    await page.locator('button.reset-btn').click();

    // Ask panel should reappear (phase back to idle)
    await expect(page.locator('.ask-panel')).toBeVisible({ timeout: 5_000 });
    await expect(page.locator('section.answer-panel')).not.toBeVisible();
  });
});
