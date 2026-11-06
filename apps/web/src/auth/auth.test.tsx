import { beforeEach, describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../App'
import { auth, installMockApi, resetAuth, seedDb, type Db } from '../test/mockApi'
import { renderWithProviders } from '../test/render'
import { setCsrfToken } from '../api/client'

let db: Db
let calls: ReturnType<typeof installMockApi>
beforeEach(() => {
  db = seedDb()
  setCsrfToken(null)
  calls = installMockApi(db)
})

describe('auth', () => {
  it('guard redirects to login on 401, then returns to the original page after sign-in', async () => {
    resetAuth({ signedIn: false })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/devices?status=active')
    expect(await screen.findByRole('form', { name: 'Sign in' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Email'), 'pat@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password')
    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), 'right')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('heading', { name: 'Devices' })).toBeInTheDocument()
    expect(calls.some((c) => c.url.startsWith('/devices?status=active'))).toBe(true)
    expect(screen.getByText('Admin')).toBeInTheDocument()
  })

  it('sends credentials and the in-memory CSRF token from /auth/me on unsafe requests', async () => {
    resetAuth({ csrf: 'tok-xyz' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/devices')
    await screen.findByText('web-01')
    await user.click(screen.getByRole('button', { name: 'Add device' }))
    await user.type(screen.getByLabelText('Hostname'), 'sw-09')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText('sw-09')).toBeInTheDocument()
    const post = calls.find((c) => c.method === 'POST' && c.url === '/devices')!
    expect(post.csrf).toBe('tok-xyz')
    expect(post.credentials).toBe('include')
    expect(calls.find((c) => c.method === 'GET')!.csrf).toBeNull()
  })

  it('read-only role hides write actions; logout returns to login', async () => {
    resetAuth({ role: 'read-only' })
    const user = userEvent.setup()
    renderWithProviders(<App />, '/devices')
    await screen.findByText('web-01')
    expect(screen.queryByRole('button', { name: 'Add device' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Edit' })).toBeNull()
    expect(screen.getByRole('note')).toHaveTextContent(/read-only/)
    await user.click(screen.getByRole('button', { name: 'Log out' }))
    expect(await screen.findByRole('form', { name: 'Sign in' })).toBeInTheDocument()
    expect(auth.signedIn).toBe(false)
  })

  it('technician sees edit but not delete; forced password change redirects', async () => {
    resetAuth({ role: 'technician' })
    renderWithProviders(<App />, '/devices')
    await screen.findByText('web-01')
    expect(screen.getAllByRole('button', { name: 'Edit' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Delete' })).toBeNull()
    expect(screen.getAllByRole('radiogroup', { name: /^Status of / }).length).toBeGreaterThan(0)
  })

  it('must_change_password sends the user to the change-password form', async () => {
    resetAuth({ mustChange: true })
    renderWithProviders(<App />, '/devices')
    await waitFor(() => expect(screen.getByRole('form', { name: 'Change password' })).toBeInTheDocument())
  })
})
