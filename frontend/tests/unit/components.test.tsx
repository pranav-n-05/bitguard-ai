import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { BandBadge, RiskScore } from '@/components/badges'
import { DataState } from '@/components/states'

function q<T>(over: Partial<{ isLoading: boolean; isError: boolean; error: unknown; data: T | undefined }>) {
  return { isLoading: false, isError: false, error: null, data: undefined as T | undefined, refetch: vi.fn(), ...over }
}

describe('DataState', () => {
  it('renders loading', () => {
    render(<DataState query={q({ isLoading: true })}>{() => <p>x</p>}</DataState>)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
  })
  it('renders error with retry', async () => {
    const query = q({ isError: true, error: new Error('boom') })
    render(<DataState query={query}>{() => <p>x</p>}</DataState>)
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(query.refetch).toHaveBeenCalled()
  })
  it('renders empty and data states', () => {
    const { rerender } = render(<DataState query={q({ data: [] as number[] })} isEmpty={(d) => d.length === 0}>{() => <p>data</p>}</DataState>)
    expect(screen.getByText('Nothing to show')).toBeInTheDocument()
    rerender(<DataState query={q({ data: [1] })} isEmpty={(d) => d.length === 0}>{(d) => <p>data {d[0]}</p>}</DataState>)
    expect(screen.getByText('data 1')).toBeInTheDocument()
  })
  it('renders unavailable when no data returned', () => {
    render(<DataState query={q({})}>{() => <p>x</p>}</DataState>)
    expect(screen.getByText(/Unavailable/)).toBeInTheDocument()
  })
})

describe('risk display', () => {
  it('risk score links to its explanation', () => {
    render(<MemoryRouter><RiskScore score={63} band="elevated" entityType="transaction" entityKey="ab" /></MemoryRouter>)
    expect(screen.getByRole('link')).toHaveAttribute('href', '/transactions/ab?tab=risk')
    expect(screen.getByText('elevated')).toBeInTheDocument()
  })
  it('missing score is shown as unscored, not zero', () => {
    render(<MemoryRouter><RiskScore score={null} entityType="address" entityKey="bc1q" /></MemoryRouter>)
    expect(screen.getByText('unscored')).toBeInTheDocument()
    render(<BandBadge band={null} />)
    expect(screen.getAllByText('unscored').length).toBe(2)
  })
})
