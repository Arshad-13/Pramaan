import { expect, test, type Browser, type Page } from '@playwright/test'
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

  const admin = await signIn(browser, 'admin@pramaan.test', PASSWORDS.admin)
  await expect(h1(admin)).toBeVisible()
  await audit(admin, 'admin dashboard')
  await admin.goto('/admin')
  await expect(admin.getByText('Security alerts')).toBeVisible()
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
})
