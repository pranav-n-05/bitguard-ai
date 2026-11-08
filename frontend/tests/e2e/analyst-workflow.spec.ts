import { execFileSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

/**
 * Spec §18 end-to-end scenario on SYNTHETIC data:
 * upload → validate/normalise → store → features → graph → anomaly detection → risk → alerts →
 * dashboard → investigation → evidence + notes → report export.
 */
const EMAIL = process.env.BITGUARD_E2E_EMAIL ?? 'admin@bitguard.local'
const PASSWORD = process.env.BITGUARD_E2E_PASSWORD ?? ''

test('analyst workflow from upload to exported report', async ({ page }) => {
  test.skip(!PASSWORD, 'Set BITGUARD_E2E_PASSWORD to an administrator password')
  const root = resolve(fileURLToPath(new URL('.', import.meta.url)), '../../..')
  const out = mkdtempSync(join(tmpdir(), 'bitguard-e2e-'))
  const seed = String(Date.now() % 100000)
  execFileSync(join(root, 'backend/.venv/bin/python'), [join(root, 'scripts/generate_synthetic.py'), '--seed', seed, '--actors', '40',
    '--baseline-tx', '300', '--patterns', '1', '--formats', 'csv', '--out', out], { stdio: 'pipe' })
  const file = join(out, `bitguard_synthetic_seed${seed}.csv`)
  const labels = JSON.parse(readFileSync(file.replace('.csv', '.labels.json'), 'utf8'))
  const fanTx: string = labels.patterns.find((p: { pattern: string }) => p.pattern === 'fan_out_split').txids[0]

  // login
  await page.goto('/login')
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible()

  // 1-8: upload + full pipeline
  await page.getByRole('link', { name: 'Data Ingestion' }).click()
  await page.getByLabel('Dataset name').fill(`e2e synthetic ${seed}`)
  await page.getByLabel('Dataset files').setInputFiles(file)
  await page.getByRole('button', { name: /Upload & process/ }).click()
  await expect(page.getByText('Dataset registered.')).toBeVisible({ timeout: 170_000 })
  // processing runs asynchronously on the worker: wait until this dataset reaches `processed`
  const row = page.getByRole('row', { name: new RegExp(`e2e synthetic ${seed}`) })
  await expect(row).toBeVisible()
  await expect(async () => {
    await page.reload()
    await expect(row.getByText('processed', { exact: true })).toBeVisible({ timeout: 3_000 })
  }).toPass({ timeout: 170_000, intervals: [3_000] })

  // transaction view: features, graph, explainable risk
  await page.goto(`/transactions/${fanTx}`)
  await expect(page.getByRole('heading', { name: 'Transaction' })).toBeVisible()
  await page.getByRole('tab', { name: 'Features' }).click()
  await expect(page.getByText('fan_out', { exact: true })).toBeVisible()
  await page.getByRole('tab', { name: 'Graph' }).click()
  await expect(page.getByRole('img', { name: /Graph with \d+ nodes/ })).toBeVisible()
  await page.getByRole('tab', { name: 'Risk & explanation' }).click()
  await expect(page.getByText('Score components')).toBeVisible()
  await expect(page.getByText(/not evidence of criminal activity/).first()).toBeVisible()

  // 9: alerts on dashboard / queue
  await page.goto('/')
  await expect(page.getByText('Highest-risk open alerts')).toBeVisible()
  await page.goto(`/alerts?q=${fanTx}&status=all`)
  const alertLink = page.locator('table a').first()
  await expect(alertLink).toBeVisible()
  await alertLink.click()
  await expect(page.getByText('What remains uncertain:')).toBeVisible()

  // 10: create investigation from the alert
  await page.getByRole('button', { name: 'Add to case' }).click()
  await page.getByLabel('Title').fill(`E2E case ${seed}`)
  await page.getByLabel(/Evidence note/).fill('Automated alert attached during E2E run')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('heading', { name: new RegExp(`E2E case ${seed}`) })).toBeVisible()

  // 11: evidence + notes
  await page.getByRole('tab', { name: /Evidence/ }).click()
  await page.getByLabel('Reference').fill(fanTx)
  await page.getByLabel('Description').fill('Anchor transaction of fan-out')
  await page.getByRole('button', { name: 'Attach' }).click()
  await expect(page.getByRole('tab', { name: 'Evidence (2)' })).toBeVisible()
  await page.getByRole('button', { name: 'Verify' }).first().click()
  await expect(page.getByText('verified').first()).toBeVisible()
  await page.getByRole('tab', { name: /Notes/ }).click()
  await page.getByLabel('New note').fill('Outputs resemble a payout batch; verify with counterparties.')
  await page.getByRole('button', { name: 'Add note' }).click()
  await expect(page.getByText('Outputs resemble a payout batch')).toBeVisible()

  // 12: export report (PDF) and confirm it is stored with a hash
  const dl = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export PDF' }).click()
  const d = await dl
  expect(d.suggestedFilename()).toMatch(/\.pdf$/)
  await page.getByRole('tab', { name: 'Reports' }).click()
  await expect(page.getByRole('button', { name: 'Download' }).first()).toBeVisible()
})
