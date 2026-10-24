/** How the app addresses someone: "Dr. A. Shah" -> "Dr. Shah"; "Ravi Patel" -> "Ravi". */
export function greetingName(name: string | undefined): string {
  if (!name) return ''
  const parts = name.trim().split(/\s+/)
  if (/^dr\.?$/i.test(parts[0]) && parts.length > 1) return `Dr. ${parts[parts.length - 1]}`
  return parts[0]
}
