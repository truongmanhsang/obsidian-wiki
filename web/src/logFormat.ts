import type { LogEntry, LogResponse } from './types'

export function formatLogTimestamp(value?: string, fallbackDate = '') {
  if (!value) return fallbackDate
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return fallbackDate || value

  const parts = new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date)
  const get = (type: Intl.DateTimeFormatPartTypes) => parts.find(part => part.type === type)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
}

export function formatLogEntry(entry: LogEntry) {
  const timestamp = formatLogTimestamp(entry.created_at, entry.date)
  const auto = entry.is_auto ? ' (auto)' : ''
  return `- ${timestamp} ${entry.kind}${auto}: ${entry.message}`
}

export function logLines(response: LogResponse) {
  if (response.entries?.length) return response.entries.map(formatLogEntry).reverse()
  return response.log_tail.split('\n').filter(Boolean).reverse()
}
