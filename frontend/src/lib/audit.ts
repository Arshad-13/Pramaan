/** Plain-language labels for audit actions and security events. */

const ACTION_LABEL: Record<string, string> = {
  USER_REGISTER: 'Account registered',
  LOGIN_SUCCESS: 'Signed in',
  LOGIN_FAIL: 'Sign-in failed',
  LOGOUT: 'Signed out',
  ACCOUNT_LOCKED: 'Account locked',
  ADMIN_USER_CREATED: 'Doctor account created',
  ACCOUNT_ACTIVATED: 'Doctor account activated',
  PASSWORD_CHANGED: 'Password changed',
  KEY_GENERATED: 'Signing key created',
  RX_PIN_VIEWED: 'Patient PIN shown',
  AUDIT_CHECKPOINT: 'Signed checkpoint',
  PHARMACIST_APPROVED: 'Pharmacist approved',
  PHARMACIST_REJECTED: 'Pharmacist rejected',
  ADMIN_USER_DEACTIVATED: 'Account deactivated',
  KEY_ROTATED: 'Signing key rotated',
  KEY_REVOKED: 'Signing key revoked',
  SIGN_UNLOCK_FAIL: 'Wrong signing password',
  SIGN_LOCKED: 'Signing locked',
  RX_ISSUED: 'Prescription issued',
  RX_ISSUED_WITH_OVERRIDE: 'Prescription issued despite a warning',
  RX_REVOKED: 'Prescription withdrawn',
  RX_VERIFIED: 'Prescription verified',
  RX_VERIFY_FAILED: 'Verification failed',
  RX_DISPENSED: 'Prescription dispensed',
  RX_DISPENSE_HELD: 'Dispensing held after a mismatching page',
  RX_PDF_DOWNLOADED: 'Prescription PDF downloaded',
  PIN_FAIL: 'Wrong patient PIN',
  SECURITY_ALERT: 'Security alert raised',
  CHECKPOINT: 'Signed checkpoint',
  AUDIT_VERIFIED: 'Audit chain checked',
  KEK_ROTATED: 'Master key rotated',
}

export function actionLabel(action: string): string {
  return ACTION_LABEL[action] ?? action.toLowerCase().replace(/_/g, ' ')
}

const EVENT_LABEL: Record<string, string> = {
  FAILED_VERIFICATIONS: 'Repeated failed verifications',
  FAILED_LOGINS: 'Account locked after wrong passwords',
  SIGNING_LOCKED: 'Signing key locked',
  PIN_LOCKED: 'Patient PIN locked',
  POSSIBLE_REPLAY: 'Possible replay at another pharmacy',
  MULTI_PHARMACY_SCANS: 'Scanned by several pharmacists',
  RISK_OVERRIDE: 'Doctor issued despite a risk warning',
  AUDIT_CHAIN_BROKEN: 'Audit chain failed verification',
  MODEL_FILE_INVALID: 'Anomaly model file failed verification',
}

export function eventLabel(type: string): string {
  return EVENT_LABEL[type] ?? type.toLowerCase().replace(/_/g, ' ')
}

/** Parse a details JSON string into short "key: value" facts (never throws). */
export function detailFacts(json: string): string[] {
  try {
    const parsed = JSON.parse(json) as Record<string, unknown>
    return Object.entries(parsed)
      .filter(([, v]) => v !== null && typeof v !== 'object')
      .map(([k, v]) => `${k.replace(/_/g, ' ')}: ${String(v)}`)
  } catch {
    return []
  }
}
