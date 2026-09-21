import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'

describe('Memory workspace shell', () => {
  it('renders navigation and the search input', () => {
    vi.stubGlobal('fetch', vi.fn())

    render(<App />)

    expect(screen.getByText('Memory')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Search' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Browse' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reflect' })).toBeInTheDocument()
    expect(screen.getByRole('searchbox')).toBeInTheDocument()
  })

  it('submits search and opens a result page', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.startsWith('/api/search')) {
        return Promise.resolve({ ok: true, json: async () => ({ count: 1, results: [{ path: 'concepts/retry-policy.md', title: 'Deployment Retry Policy', type: 'concept', updated: '2026-09-21', snippet: 'Retry deployments carefully.' }] }) })
      }
      return Promise.resolve({ ok: true, json: async () => ({ path: 'concepts/retry-policy.md', content: '# Deployment Retry Policy\n\nRetry deployments carefully.', truncated: false, revision: 'abc' }) })
    }))

    render(<App />)
    await user.type(screen.getByRole('searchbox'), 'retry policy')
    await user.keyboard('{Enter}')

    expect(await screen.findByText('Deployment Retry Policy')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /deployment retry policy/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Retry deployments carefully.')
  })

  it('shows a recoverable search error', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('API offline')))

    render(<App />)
    await user.type(screen.getByRole('searchbox'), 'anything')
    await user.keyboard('{Enter}')

    expect(await screen.findByRole('alert')).toHaveTextContent('API offline')
  })

  it('browses the catalog and opens a page', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.startsWith('/api/pages?')) return Promise.resolve({ ok: true, json: async () => ({ stats: { pages: 1 }, pages: [{ path: 'concepts/retry-policy.md', title: 'Deployment Retry Policy', type: 'concept', updated: '2026-09-21' }] }) })
      return Promise.resolve({ ok: true, json: async () => ({ path: 'concepts/retry-policy.md', content: '# Deployment Retry Policy\n\nRetry deployments carefully.', truncated: false, revision: 'abc' }) })
    }))

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Browse' }))
    expect(await screen.findByText('Deployment Retry Policy')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /deployment retry policy/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Retry deployments carefully.')
  })

  it('reflects over sources and opens a cited page', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/reflect') return Promise.resolve({ ok: true, json: async () => ({ query: 'communication', reflection: 'Keep communication concise.', sources: [{ path: 'people/test-user.md' }] }) })
      if (url.includes('people/test-user.md')) return Promise.resolve({ ok: true, json: async () => ({ path: 'people/test-user.md', content: '# Test User\n\nPrefers concise communication.', truncated: false, revision: 'def' }) })
      return Promise.resolve({ ok: true, json: async () => ({}) })
    }))

    render(<App />)
    await user.click(screen.getByRole('button', { name: 'Reflect' }))
    await user.type(screen.getByRole('textbox'), 'communication')
    await user.keyboard('{Control>}{Enter}{/Control}')
    expect(await screen.findByText('Keep communication concise.')).toBeVisible()
    await user.click(screen.getByRole('button', { name: /people\/test-user\.md/i }))
    expect(await screen.findByRole('article')).toHaveTextContent('Prefers concise communication.')
  })

  it('exposes accessible workspace landmarks and theme control', async () => {
    const user = userEvent.setup()
    vi.stubGlobal('fetch', vi.fn())
    render(<App />)

    expect(screen.getByRole('main', { name: 'Memory workspace' })).toBeInTheDocument()
    const theme = screen.getByRole('button', { name: 'Use dark theme' })
    await user.click(theme)
    expect(screen.getByRole('button', { name: 'Use light theme' })).toBeInTheDocument()
  })
})
