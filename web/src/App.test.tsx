import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'

function ok(payload: unknown, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => payload } as Response)
}

function installApi(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)

    for (const [needle, payload] of Object.entries(overrides)) {
      if (url.includes(needle)) return ok(payload)
    }

    if (url === '/api/health') return ok({ ok: true, service: 'obsidian-memory', pages: 2 })
    if (url.startsWith('/api/pages?')) return ok({
      stats: { concept: 1, person: 1, decision: 0, entity: 0, environment: 0, answer: 0, preference: 0, source: 0 },
      pages: [
        { path: 'concepts/retry-policy.md', title: 'Deployment Retry Policy', type: 'concept', updated: '2026-09-21' },
        { path: 'people/test-user.md', title: 'Test User', type: 'person', updated: '2026-09-20' },
      ],
    })
    if (url.startsWith('/api/ingest/status')) return ok({
      running: null,
      jobs: [{ job_id: 'ingest-123', session_id: 'session-123', status: 'completed', submitted_at: '2026-09-21T10:00:00Z' }],
    })
    if (url.startsWith('/api/logs')) return ok({ log_tail: '2026-09-21 WRITE concepts/retry-policy\n' })
    if (url.startsWith('/api/search')) return ok({
      count: 1,
      results: [{ path: 'concepts/retry-policy.md', title: 'Deployment Retry Policy', type: 'concept', updated: '2026-09-21', snippet: 'Retry deployments carefully.' }],
    })
    if (url === '/api/reflect' && init?.method === 'POST') return ok({
      query: 'communication',
      reflection: 'Keep communication concise.',
      sources: [{ path: 'people/test-user.md' }],
    })
    if (url.includes('/api/pages/people/test-user.md')) return ok({
      path: 'people/test-user.md',
      content: '# Test User\n\nPrefers concise communication.',
      truncated: false,
      revision: 'def123456',
    })
    if (url.includes('/api/pages/concepts/retry-policy.md')) return ok({
      path: 'concepts/retry-policy.md',
      content: '# Deployment Retry Policy\n\nRetry deployments carefully.',
      truncated: false,
      revision: 'abc123456',
    })
    if (url === '/api/ingest/submit') return ok({ job_id: 'ingest-new', status: 'queued' }, 202)

    return ok({})
  })

  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('Memory workspace shell', () => {
  beforeEach(() => {
    localStorage.clear()
    installApi()
  })

  it('renders a professional workspace with all primary navigation', async () => {
    render(<App />)

    expect(screen.getByText('Obsidian Memory')).toBeInTheDocument()
    const nav = within(screen.getByRole('navigation', { name: 'Primary navigation' }))
    expect(nav.getByRole('button', { name: 'Overview' })).toBeInTheDocument()
    expect(nav.getByRole('button', { name: 'Search' })).toBeInTheDocument()
    expect(nav.getByRole('button', { name: 'Library' })).toBeInTheDocument()
    expect(nav.getByRole('button', { name: 'Reflect' })).toBeInTheDocument()
    expect(nav.getByRole('button', { name: 'Operations' })).toBeInTheDocument()
    expect(await screen.findByText('Recently updated')).toBeVisible()
  })

  it('submits search and opens a result page', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Search' }))
    await user.type(screen.getByRole('searchbox'), 'retry policy')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('Deployment Retry Policy')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /deployment retry policy/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Retry deployments carefully.')
  })

  it('shows a recoverable search error', async () => {
    const user = userEvent.setup()
    const fetchMock = installApi()
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/search')) return Promise.reject(new Error('API offline'))
      if (url === '/api/health') return ok({ ok: true, service: 'obsidian-memory', pages: 0 })
      if (url.startsWith('/api/pages?')) return ok({ stats: {}, pages: [] })
      if (url.startsWith('/api/ingest/status')) return ok({ running: null, jobs: [] })
      if (url.startsWith('/api/logs')) return ok({ log_tail: '' })
      return ok({})
    })

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Search' }))
    await user.type(screen.getByRole('searchbox'), 'anything')
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('alert')).toHaveTextContent('API offline')
  })

  it('browses the library and opens a page', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Library' }))
    expect(await screen.findByText('Deployment Retry Policy')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /deployment retry policy/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Retry deployments carefully.')
  })

  it('reflects over sources and opens a cited page', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: 'Reflect' }))
    await user.type(screen.getByRole('textbox'), 'communication')
    await user.keyboard('{Control>}{Enter}{/Control}')

    expect(await screen.findByText('Keep communication concise.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /people\/test-user\.md/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Prefers concise communication.')
  })

  it('shows ingest jobs and logs in operations', async () => {
    const user = userEvent.setup()
    render(<App />)

    await screen.findByText('Recently updated')
    const nav = within(screen.getByRole('navigation', { name: 'Primary navigation' }))
    await user.click(nav.getByRole('button', { name: 'Operations' }))
    expect(await screen.findByText('ingest-123')).toBeVisible()
    expect(screen.getByRole('log', { name: 'Vault operation log' })).toHaveTextContent('WRITE concepts/retry-policy')
  })

  it('exposes accessible landmarks and theme control', async () => {
    const user = userEvent.setup()
    render(<App />)

    expect(screen.getByRole('main', { name: 'Memory workspace' })).toBeInTheDocument()
    const theme = screen.getByRole('button', { name: 'Use light theme' })
    await user.click(theme)
    expect(screen.getByRole('button', { name: 'Use dark theme' })).toBeInTheDocument()
  })
})
