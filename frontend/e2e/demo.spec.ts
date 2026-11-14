import { expect, test, type Browser, type Page } from '@playwright/test'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

/** The demo script of Spec Section 18, driven through the real UI against a freshly seeded copy of
 *  the app. Screenshots of the key moments are saved to docs/screenshots for the deck. */

const root = path.resolve(import.meta.dirname, '..', '..')
const samples = path.join(root, '.e2e', 'samples')
const shots = path.join(root, 'docs', 'screenshots')
fs.mkdirSync(shots, { recursive: true })

const PASSWORDS = {
  doctor: 'Doctor-Login-2026',
  pharmacist: 'Pharma-Secret-2026',
  patient: 'Patient-Demo-2026',
  auditor: 'Auditor-Demo-2026',
  admin: 'Admin-Demo-2026',
}
const SIGNING = 'Doctor-Signing-Phrase-9'

async function signIn(browser: Browser, email: string, password: string, viewport = { width: 1280, height: 900 }) {
  const context = await browser.newContext({ viewport, colorScheme: 'light', baseURL: 'http://localhost:8002' })
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL('**/')
  return page
}

async function openUpload(page: Page) {
  await page.goto('/verify')
  await page.getByRole('tab', { name: /Upload photo or PDF/ }).click()
}

async function uploadAndExpect(page: Page, file: string, verdict: string) {
  await openUpload(page)
  await page.getByLabel(/Drop a photo or PDF/).setInputFiles(file)
  await expect(page.getByRole('heading', { name: verdict, exact: true })).toBeVisible({ timeout: 60_000 })
}

async function pasteAndExpect(page: Page, code: string, verdict: string) {
  await page.goto('/verify')
  await page.getByRole('tab', { name: /Paste code/ }).click()
  await page.getByLabel('Prescription code').fill(code)
  await page.getByRole('button', { name: 'Verify', exact: true }).click()
  await expect(page.getByRole('heading', { name: verdict, exact: true })).toBeVisible()
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true })

test.describe.configure({ mode: 'serial' })

test('1. genuine prescription: issue, verify the downloaded PDF, dispense with the patient PIN, replay is refused', async ({ browser }) => {
  // The doctor issues it through the form.
  const doctor = await signIn(browser, 'dr.shah@clinic.test', PASSWORDS.doctor, { width: 1440, height: 900 })
  await expect(doctor.getByRole('heading', { name: /Dr\. Shah$/ })).toBeVisible()
  await shot(doctor, '00-doctor-dashboard')
  await doctor.goto('/prescriptions/new')
  await doctor.getByLabel('Patient email').fill('sneha.rao@example.test')
  await doctor.getByRole('button', { name: 'Find' }).click()
  await expect(doctor.getByText('Sneha Rao').first()).toBeVisible()
  await doctor.getByLabel('Medicine', { exact: true }).first().fill('Amoxicillin')
  await doctor.getByLabel('Dose (mg)', { exact: true }).first().fill('500')
  await doctor.getByLabel('Days', { exact: true }).first().fill('5')
  await doctor.getByLabel('Notes for the pharmacist (optional)').fill('Take after food.')
  await shot(doctor, '01-doctor-new-prescription')
  await doctor.getByLabel('Signing password').fill(SIGNING)
  await doctor.getByRole('button', { name: 'Sign and issue' }).click()
  await expect(doctor.getByText('Signed and stored securely')).toBeVisible()
  await shot(doctor, '02-doctor-signed')
  const href = await doctor.getByRole('link', { name: /Open PDF/ }).getAttribute('href')
  const pdf = await doctor.context().request.get(`http://localhost:8002${href}`)
  expect(pdf.status()).toBe(200)
  const issued = path.join(root, '.e2e', 'issued.pdf')
  fs.writeFileSync(issued, await pdf.body())

  // The patient reads the PIN from their own account.
  const patient = await signIn(browser, 'sneha.rao@example.test', PASSWORDS.patient)
  await patient.goto('/prescriptions')
  await patient.getByRole('button', { name: 'Show PIN' }).first().click()
  const pin = (await patient.getByText(/^\d{3} \d{3}$/).first().textContent())!.replace(/\s/g, '')
  expect(pin).toMatch(/^\d{6}$/)
  await shot(patient, '03-patient-pin')

  // Pharmacy A uploads the PDF: Verified, then a wrong PIN, then the right one.
  const meera = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)
  await shot(meera, '03b-pharmacist-dashboard')
  await uploadAndExpect(meera, issued, 'Verified')
  await expect(meera.getByText('Page matches what was signed')).toBeVisible()
  await shot(meera, '04-pharmacist-verified')
  await meera.getByLabel(/PIN/).fill(pin === '000000' ? '111111' : '000000')
  await meera.getByRole('button', { name: 'Dispense' }).click()
  await expect(meera.getByText('That PIN is not correct.')).toBeVisible()
  await meera.getByLabel(/PIN/).fill(pin)
  await meera.getByRole('button', { name: 'Dispense' }).click()
  await expect(meera.getByText(/Dispensed \(fill 1\)/)).toBeVisible()
  await shot(meera, '05-pharmacist-dispensed')

  // Pharmacy B tries the same prescription.
  const rohan = await signIn(browser, 'rohan@medplus.test', PASSWORDS.pharmacist)
  await uploadAndExpect(rohan, issued, 'Already used')
  await shot(rohan, '06-replay-already-used')

  // The administrator sees the alert.
  const admin = await signIn(browser, 'admin@pramaan.test', PASSWORDS.admin)
  await admin.goto('/admin')
  await expect(admin.getByText('Possible replay at another pharmacy')).toBeVisible()
  await shot(admin, '07-admin-alert')
})

test('2. edited pages are caught and the changed field is outlined', async ({ browser }) => {
  const page = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)

  await uploadAndExpect(page, path.join(samples, 'ready_forged_dose_800mg.png'), 'Tampered')
  const field = page.getByText('Medicine 1 dose').first().locator('xpath=ancestor::li[1]')
  await expect(field).toContainText('500 mg')
  await expect(field).toContainText('800')
  await expect(page.getByRole('img', { name: 'The uploaded prescription' })).toBeVisible()
  await shot(page, '08-tampered-dose-outlined')

  await uploadAndExpect(page, path.join(samples, 'ready_forged_dose_photo.jpg'), 'Tampered')
  await shot(page, '09-tampered-photo')

  await uploadAndExpect(page, path.join(samples, 'ready_forged_overlay.pdf'), 'Tampered')
  await uploadAndExpect(page, path.join(samples, 'ready_forged_hidden_text.pdf'), 'Tampered')
  await uploadAndExpect(page, path.join(samples, 'ready_forged_extra_medicine.png'), 'Tampered')
  await uploadAndExpect(page, path.join(samples, 'ready_forged_scribble.png'), 'Tampered')

  // Forged QR text.
  const forged = fs.readFileSync(path.join(samples, 'ready_forged_qr.qr.txt'), 'utf8').trim()
  await pasteAndExpect(page, forged, 'Tampered')
  await shot(page, '10-tampered-forged-qr')

  // A genuine photo of the same prescription is not accused.
  await uploadAndExpect(page, path.join(samples, 'ready_genuine_photo.jpg'), 'Verified')
})

test('3. expired, revoked, suspicious and controlled prescriptions each say what is wrong', async ({ browser }) => {
  const page = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)
  const code = (name: string) => fs.readFileSync(path.join(samples, `${name}.qr.txt`), 'utf8').trim()

  await pasteAndExpect(page, code('expired'), 'Expired')
  await shot(page, '11-expired')
  await pasteAndExpect(page, code('revoked'), 'Revoked')
  await pasteAndExpect(page, code('used'), 'Already used')
  await pasteAndExpect(page, code('suspicious'), 'Suspicious')
  await expect(page.getByText('Why this was flagged')).toBeVisible()
  await shot(page, '12-suspicious')
  await pasteAndExpect(page, code('controlled'), 'Verified')
  await expect(page.getByText(/controlled medicine/i).first()).toBeVisible()
})

test('4. the auditor verifies the chain and sees the log', async ({ browser }) => {
  const page = await signIn(browser, 'auditor@pramaan.test', PASSWORDS.auditor)
  await page.goto('/audit')
  await expect(page.getByRole('list', { name: 'Audit log entries, newest first' })).toBeVisible()
  await page.getByRole('button', { name: 'Verify chain' }).click()
  await expect(page.getByText('Chain intact')).toBeVisible()
  await page.getByRole('list', { name: 'Audit log entries, newest first' }).getByRole('button').first().click()
  await expect(page.getByText('Seal of this entry')).toBeVisible()
  await shot(page, '13-audit-chain-intact')
})

test('5. verification works at phone width without sideways scrolling', async ({ browser }) => {
  const page = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist, { width: 390, height: 844 })
  await pasteAndExpect(page, fs.readFileSync(path.join(samples, 'ready.qr.txt'), 'utf8').trim(), 'Verified')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
  await shot(page, '14-phone-verified')
})

const h1 = (page: Page) => page.getByRole('heading', { level: 1 })

test('6. no serious accessibility violations on the main screens, in light and dark', async ({ browser }) => {
  const { default: AxeBuilder } = await import('@axe-core/playwright')
  const audit = async (page: Page, label: string) => {
    await page.waitForTimeout(700) // let entrance animations finish: mid-fade colours would be measured
    const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
    const serious = results.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(
      serious.map((v) => {
        const data = v.nodes[0]?.any[0]?.data as { fgColor?: string; bgColor?: string; contrastRatio?: number } | undefined
        return `${label}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target.join(' ')} ${data ? `fg ${data.fgColor} on ${data.bgColor} = ${data.contrastRatio}` : ''}`
      }),
      `accessibility problems on ${label}`,
    ).toEqual([])
  }

  const anonymous = await (await browser.newContext({ baseURL: 'http://localhost:8002' })).newPage()
  await anonymous.goto('/login')
  await audit(anonymous, 'login')
  await anonymous.goto('/register')
  await audit(anonymous, 'register')

  const pharmacist = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)
  await expect(h1(pharmacist)).toBeVisible()
  await audit(pharmacist, 'pharmacist dashboard')
  await pharmacist.goto('/verify')
  await audit(pharmacist, 'verify (scan)')
  await pharmacist.getByRole('tab', { name: /Paste code/ }).click()
  await audit(pharmacist, 'verify (paste)')
  await pharmacist.goto('/verify/history')
  await expect(pharmacist.getByRole('heading', { name: 'History', level: 1 })).toBeVisible()
  await audit(pharmacist, 'pharmacist history')
  await pasteAndExpect(pharmacist, fs.readFileSync(path.join(samples, 'suspicious.qr.txt'), 'utf8').trim(), 'Suspicious')
  await audit(pharmacist, 'verify result (suspicious)')
  await uploadAndExpect(pharmacist, path.join(samples, 'ready_forged_dose_800mg.png'), 'Tampered')
  await audit(pharmacist, 'verify result (tampered, outlined)')

  const doctor = await signIn(browser, 'dr.shah@clinic.test', PASSWORDS.doctor)
  await expect(h1(doctor)).toBeVisible()
  await audit(doctor, 'doctor dashboard')
  await doctor.goto('/prescriptions/new')
  await audit(doctor, 'new prescription')
  await doctor.goto('/prescriptions')
  await audit(doctor, 'my prescriptions')
  await doctor.goto('/account')
  await expect(doctor.getByRole('heading', { name: 'Account', exact: true })).toBeVisible()
  await expect(doctor).toHaveTitle('Account · Pramaan')
  await audit(doctor, 'account')

  const admin = await signIn(browser, 'admin@pramaan.test', PASSWORDS.admin)
  await expect(h1(admin)).toBeVisible()
  await audit(admin, 'admin dashboard')
  await admin.goto('/admin')
  await expect(admin.getByRole('heading', { name: 'Security alerts' })).toBeVisible()
  await audit(admin, 'admin')

  const auditor = await signIn(browser, 'auditor@pramaan.test', PASSWORDS.auditor)
  await expect(h1(auditor)).toBeVisible()
  await audit(auditor, 'auditor dashboard')
  await auditor.goto('/audit')
  await expect(auditor.getByRole('list', { name: 'Audit log entries, newest first' })).toBeVisible()
  await audit(auditor, 'audit log')

  // Dark theme: the same checks (colour contrast is where themes usually go wrong).
  await auditor.getByRole('radio', { name: 'Dark theme' }).first().click()
  await audit(auditor, 'audit log (dark)')
  await pharmacist.getByRole('radio', { name: 'Dark theme' }).first().click()
  await audit(pharmacist, 'verify result (dark)')
  await doctor.getByRole('radio', { name: 'Dark theme' }).first().click()
  await audit(doctor, 'account (dark)')
})

/** A time-based one-time code (RFC 6238), as an authenticator app would show it. */
function totp(secretBase32: string, offsetSteps = 0): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const ch of secretBase32.replace(/[\s=]/g, '').toUpperCase()) bits += alphabet.indexOf(ch).toString(2).padStart(5, '0')
  const bytes = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)))
  const counter = Buffer.alloc(8)
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + offsetSteps))
  const digest = crypto.createHmac('sha1', bytes).update(counter).digest()
  const o = digest[19] & 0xf
  const value = ((digest[o] & 0x7f) << 24) | (digest[o + 1] << 16) | (digest[o + 2] << 8) | digest[o + 3]
  return String(value % 1_000_000).padStart(6, '0')
}

test('7. a doctor corrects a prescription: the original stops verifying and says why', async ({ browser }) => {
  const doctor = await signIn(browser, 'dr.shah@clinic.test', PASSWORDS.doctor, { width: 1440, height: 900 })
  await doctor.goto('/prescriptions/new')
  await doctor.getByLabel('Patient email').fill('kabir.khan@example.test')
  await doctor.getByRole('button', { name: 'Find' }).click()
  await expect(doctor.getByText('Kabir Khan').first()).toBeVisible()
  await doctor.getByLabel('Medicine', { exact: true }).first().fill('Amoxicillin')
  await doctor.getByLabel('Dose (mg)', { exact: true }).first().fill('250')
  await doctor.getByLabel('Days', { exact: true }).first().fill('3')
  await doctor.getByLabel('Signing password').fill(SIGNING)
  await doctor.getByRole('button', { name: 'Sign and issue' }).click()
  await expect(doctor.getByText('Signed and stored securely')).toBeVisible()
  const href = (await doctor.getByRole('link', { name: /Open PDF/ }).getAttribute('href'))!
  const original = path.join(root, '.e2e', 'original.pdf')
  fs.writeFileSync(original, await (await doctor.context().request.get(`http://localhost:8002${href}`)).body())
  const id = href.split('/')[3]

  // The dose was wrong: correct it. The form opens filled in, with a warning about what signing does.
  await doctor.goto(`/prescriptions/new?correct=${id}`)
  await expect(doctor.getByText(/withdraws the original/)).toBeVisible()
  await expect(doctor.getByLabel('Medicine', { exact: true }).first()).toHaveValue('Amoxicillin')
  await expect(doctor.getByText('Kabir Khan').first()).toBeVisible()
  await doctor.getByLabel('Dose (mg)', { exact: true }).first().fill('500')
  await shot(doctor, '15-doctor-correct')
  await doctor.getByLabel('Signing password').fill(SIGNING)
  await doctor.getByRole('button', { name: 'Sign and issue' }).click()
  await expect(doctor.getByText('Signed and stored securely')).toBeVisible()
  await expect(doctor.getByText(/earlier prescription was withdrawn/)).toBeVisible()

  // The pharmacist is told it was replaced, not just "revoked".
  const meera = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)
  await uploadAndExpect(meera, original, 'Revoked')
  await expect(meera.getByText(/replaced this prescription with a corrected one/).first()).toBeVisible()
  await expect(meera.getByText(/Ask the patient for the corrected prescription/)).toBeVisible()
  await shot(meera, '16-superseded')
})

test('8. the interface can be used in Hindi and Gujarati', async ({ browser }) => {
  const context = await browser.newContext({ baseURL: 'http://localhost:8002', viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Language').selectOption('hi')
  await expect(page.getByRole('heading', { name: 'साइन इन' })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'hi')
  await page.getByLabel('ईमेल', { exact: true }).fill('meera@citypharm.test')
  await page.getByLabel('पासवर्ड', { exact: true }).fill(PASSWORDS.pharmacist)
  await page.getByRole('button', { name: 'साइन इन' }).click()
  await page.waitForURL('**/')
  await page.getByRole('link', { name: 'जाँच', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'पर्चे की जाँच' })).toBeVisible()
  await page.getByRole('tab', { name: 'कोड पेस्ट करें' }).click()
  await page.getByLabel('पर्चे का कोड').fill(fs.readFileSync(path.join(samples, 'revoked.qr.txt'), 'utf8').trim())
  await page.getByLabel('पर्चे का कोड').press('Enter') // Enter verifies, as the Verify button does
  await expect(page.getByRole('heading', { name: 'रद्द', exact: true })).toBeVisible()
  await expect(page.getByText(/अगला कदम: दवा न दें/)).toBeVisible()
  await shot(page, '17-hindi-verify')

  await page.getByLabel('भाषा').selectOption('gu')
  await expect(page.getByRole('heading', { name: 'રદ', exact: true })).toBeVisible()
  await shot(page, '18-gujarati-verify')
  await page.reload() // the choice is remembered
  await expect(page.locator('html')).toHaveAttribute('lang', 'gu')
  await context.close()
})

test('9. the administrator acknowledges and resolves a security alert', async ({ browser }) => {
  const admin = await signIn(browser, 'admin@pramaan.test', PASSWORDS.admin)
  await admin.goto('/admin')
  const alert = admin.getByRole('listitem').filter({ hasText: 'Possible replay at another pharmacy' }).first()
  await expect(alert).toBeVisible()
  await alert.getByRole('button', { name: 'Acknowledge' }).click()
  await expect(admin.getByText('Alert acknowledged.')).toBeVisible()

  await admin.getByRole('group', { name: 'Filter alerts' }).getByRole('button', { name: 'Acknowledged' }).click()
  const acknowledged = admin.getByRole('listitem').filter({ hasText: 'Possible replay at another pharmacy' }).first()
  await expect(acknowledged.getByText('Acknowledged')).toBeVisible()
  await acknowledged.getByRole('button', { name: 'Resolve' }).click()
  await acknowledged.getByLabel(/What was done/).fill('Spoke to both pharmacies: the first fill was genuine.')
  await acknowledged.getByRole('button', { name: 'Mark resolved' }).click()
  await expect(admin.getByText('Alert resolved.')).toBeVisible()

  await admin.getByRole('group', { name: 'Filter alerts' }).getByRole('button', { name: 'Resolved' }).click()
  await expect(admin.getByText('Note: Spoke to both pharmacies')).toBeVisible()
  await shot(admin, '19-alert-resolved')

  // The people list can be searched.
  await admin.getByLabel('Search people').fill('iyer')
  await expect(admin.getByText('dr.iyer@clinic.test')).toBeVisible()
  await expect(admin.getByText('dr.shah@clinic.test')).toHaveCount(0)
})

test('10. two-step sign-in: set up with an authenticator code, then sign in with it', async ({ browser }) => {
  const patient = await signIn(browser, 'anita.desai@example.test', PASSWORDS.patient)
  await patient.goto('/account')
  const card = patient.getByRole('region', { name: 'Two-factor sign-in' })
  await card.getByRole('button', { name: 'Set up' }).click()
  await card.getByLabel('Current password').fill(PASSWORDS.patient)
  await card.getByRole('button', { name: 'Continue' }).click()
  const secret = (await patient.getByTestId('mfa-secret').textContent())!
  await shot(patient, '20-mfa-setup')
  await patient.getByLabel('Code from the app').fill(totp(secret))
  await patient.getByRole('button', { name: 'Turn on' }).click()
  await expect(patient.getByRole('list', { name: 'Recovery codes' })).toBeVisible()
  const recovery = (await patient.getByRole('list', { name: 'Recovery codes' }).getByRole('listitem').first().textContent())!.trim()
  await shot(patient, '21-mfa-recovery-codes')
  await patient.getByRole('button', { name: 'I have saved them' }).click()

  // Signing in again now needs the second step. The next time-step is used so the code that
  // switched it on cannot be replayed.
  const again = await (await browser.newContext({ baseURL: 'http://localhost:8002' })).newPage()
  await again.goto('/login')
  await again.getByLabel('Email', { exact: true }).fill('anita.desai@example.test')
  await again.getByLabel('Password', { exact: true }).fill(PASSWORDS.patient)
  await again.getByRole('button', { name: 'Sign in' }).click()
  await expect(again.getByRole('heading', { name: 'Check your authenticator app' })).toBeVisible()
  await again.getByLabel('Code', { exact: true }).fill('000000')
  await again.getByRole('button', { name: 'Verify and sign in' }).click()
  await expect(again.getByRole('alert')).toBeVisible() // a wrong code is refused
  await again.getByLabel('Code', { exact: true }).fill(totp(secret, 1))
  await again.getByRole('button', { name: 'Verify and sign in' }).click()
  await again.waitForURL('**/')
  await expect(again.getByRole('heading', { level: 1 })).toBeVisible()

  // A recovery code also works, once.
  const third = await (await browser.newContext({ baseURL: 'http://localhost:8002' })).newPage()
  await third.goto('/login')
  await third.getByLabel('Email', { exact: true }).fill('anita.desai@example.test')
  await third.getByLabel('Password', { exact: true }).fill(PASSWORDS.patient)
  await third.getByRole('button', { name: 'Sign in' }).click()
  await third.getByLabel('Code', { exact: true }).fill(recovery)
  await third.getByRole('button', { name: 'Verify and sign in' }).click()
  await third.waitForURL('**/')
})

test('11. the pharmacist sees only their own history', async ({ browser }) => {
  const meera = await signIn(browser, 'meera@citypharm.test', PASSWORDS.pharmacist)
  await meera.getByRole('link', { name: 'History', exact: true }).click()
  await expect(meera.getByRole('heading', { name: 'History', exact: true, level: 1 })).toBeVisible()
  const table = meera.getByRole('table', { name: /recent verification checks/ })
  await expect(table.getByText('Verified').first()).toBeVisible()
  await meera.getByLabel('Show').selectOption('REVOKED')
  await expect(table.getByText('Revoked').first()).toBeVisible()
  await expect(table.getByText('Verified')).toHaveCount(0)
  await shot(meera, '22-pharmacist-history')
  await meera.getByRole('button', { name: 'Dispensed' }).click()
  await expect(meera.getByRole('table', { name: /Medicines you dispensed/ })).toContainText('#1')

  // The other pharmacy never sees Meera's dispense.
  const rohan = await signIn(browser, 'rohan@medplus.test', PASSWORDS.pharmacist)
  await rohan.goto('/verify/history')
  await rohan.getByRole('button', { name: 'Dispensed' }).click()
  await expect(rohan.getByText('Nothing dispensed yet')).toBeVisible()
})

test('12. the auditor filters the log and exports it as CSV', async ({ browser }) => {
  const auditor = await signIn(browser, 'auditor@pramaan.test', PASSWORDS.auditor)
  await auditor.goto('/audit')
  const filters = auditor.getByRole('form', { name: 'Filter the log' })
  await filters.getByLabel('Done by').selectOption('pharmacist')
  await filters.getByLabel('Action').selectOption('RX_DISPENSED')
  const list = auditor.getByRole('list', { name: 'Audit log entries, newest first' })
  await expect(list.getByRole('button').first()).toContainText('dispensed')
  await expect(auditor.getByText(/Verify chain always checks the whole log/)).toBeVisible()
  await shot(auditor, '23-audit-filtered')

  const download = auditor.waitForEvent('download')
  await auditor.getByRole('link', { name: /Export CSV/ }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^pramaan-audit-\d{8}-\d{6}\.csv$/)
  const csv = fs.readFileSync((await file.path())!, 'utf8')
  expect(csv.split('\n')[0]).toBe('seq,time_utc,actor_id,actor_role,action,resource,details,entry_hash')
  expect(csv).toContain('RX_DISPENSED')
  expect(csv).not.toContain('RX_ISSUED,') // the export follows the filters on screen

  // The export itself is on the record.
  await filters.getByRole('button', { name: 'Clear filters' }).click()
  await filters.getByLabel('Action').selectOption('AUDIT_EXPORTED')
  await expect(list.getByRole('button').first()).toBeVisible()
})
