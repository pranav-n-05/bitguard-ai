import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import LoginPage from '@/pages/LoginPage'

const login = vi.fn()
vi.mock('@/stores/auth', () => ({ useAuth: () => ({ user: null, login }) }))

function renderLogin() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><LoginPage /></MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('LoginPage', () => {
  it('validates fields before submitting', async () => {
    renderLogin()
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Enter your email')).toBeInTheDocument()
    expect(screen.getByText('Enter your password')).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })
  it('rejects a malformed OTP', async () => {
    renderLogin()
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.local')
    await userEvent.type(screen.getByLabelText('Password'), 'pw')
    await userEvent.type(screen.getByLabelText(/One-time code/), '12a')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Six digits')).toBeInTheDocument()
    expect(login).not.toHaveBeenCalled()
  })
  it('submits valid credentials and shows server errors', async () => {
    login.mockRejectedValueOnce(new Error('Invalid credentials'))
    renderLogin()
    await userEvent.type(screen.getByLabelText('Email'), 'a@b.local')
    await userEvent.type(screen.getByLabelText('Password'), 'pw')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(login).toHaveBeenCalledWith('a@b.local', 'pw', undefined)
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid credentials')
  })
})
