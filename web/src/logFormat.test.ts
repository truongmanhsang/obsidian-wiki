import { describe, expect, it } from 'vitest'
import { formatLogEntry, logLines } from './logFormat'

describe('Vault log formatting', () => {
  it('includes local time down to seconds', () => {
    const rendered = formatLogEntry({
      date: '2026-09-22',
      kind: 'LINT',
      message: '2 ops (latest: structure migration)',
      is_auto: true,
      created_at: '2026-09-22T14:36:05+00:00',
    })

    expect(rendered).toMatch(/^- \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} LINT \(auto\):/)
  })

  it('keeps legacy log_tail compatibility', () => {
    expect(logLines({ log_tail: 'oldest\nnewest' })).toEqual(['newest', 'oldest'])
  })
})
