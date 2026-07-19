import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { MemoryProviderConfig } from '@/types/fabric'

const getMemoryProviderConfig = vi.fn()
const saveMemoryProviderConfig = vi.fn()

vi.mock('@/fabric', () => ({
  getMemoryProviderConfig: (provider: string) => getMemoryProviderConfig(provider),
  saveMemoryProviderConfig: (provider: string, values: unknown) => saveMemoryProviderConfig(provider, values)
}))

vi.mock('@/store/notifications', () => ({
  notify: vi.fn(),
  notifyError: vi.fn()
}))

function hindsightSchema(overrides: Partial<MemoryProviderConfig['fields'][number]>[] = []): MemoryProviderConfig {
  const fields: MemoryProviderConfig['fields'] = [
    {
      key: 'mode',
      label: 'Mode',
      kind: 'select',
      value: 'cloud',
      description: 'How Fabric connects to Hindsight.',
      placeholder: '',
      is_set: true,
      options: [
        { value: 'cloud', label: 'Cloud', description: 'Hindsight Cloud API (lightweight, just needs an API key)' },
        { value: 'local_external', label: 'Local External', description: 'Connect to an existing Hindsight instance' }
      ]
    },
    {
      key: 'api_key',
      label: 'API key',
      kind: 'secret',
      value: '',
      description: 'Used to authenticate with the Hindsight API.',
      placeholder: 'Enter Hindsight API key',
      is_set: false,
      options: []
    },
    {
      key: 'api_url',
      label: 'API URL',
      kind: 'text',
      value: 'https://api.hindsight.vectorize.io',
      description: '',
      placeholder: '',
      is_set: true,
      options: []
    },
    {
      key: 'bank_id',
      label: 'Bank ID',
      kind: 'text',
      value: 'fabric',
      description: '',
      placeholder: '',
      is_set: true,
      options: []
    },
    {
      key: 'recall_budget',
      label: 'Recall budget',
      kind: 'select',
      value: 'mid',
      description: '',
      placeholder: '',
      is_set: true,
      options: [
        { value: 'low', label: 'low', description: '' },
        { value: 'mid', label: 'mid', description: '' },
        { value: 'high', label: 'high', description: '' }
      ]
    }
  ]

  return {
    name: 'hindsight',
    label: 'Hindsight',
    fields: fields.map((field, index) => ({ ...field, ...overrides[index] }))
  }
}

beforeEach(() => {
  getMemoryProviderConfig.mockResolvedValue(hindsightSchema())
  saveMemoryProviderConfig.mockResolvedValue({ ok: true })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

async function renderPanel(provider = 'hindsight') {
  const { ProviderConfigPanel } = await import('./provider-config-panel')

  return render(<ProviderConfigPanel provider={provider} />)
}

describe('ProviderConfigPanel', () => {
  it('renders the declared provider fields generically', async () => {
    await renderPanel()

    expect(await screen.findByDisplayValue('https://api.hindsight.vectorize.io')).toBeTruthy()
    expect(screen.getByDisplayValue('fabric')).toBeTruthy()
    expect(screen.getByText('Cloud')).toBeTruthy()
    expect(screen.getAllByText('Hindsight Cloud API (lightweight, just needs an API key)').length).toBeGreaterThan(0)
    expect(screen.getByText('mid')).toBeTruthy()
  })

  it('collapses and expands the fields', async () => {
    await renderPanel()

    expect(await screen.findByLabelText('API URL')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: /Hindsight settings/ }))
    expect(screen.queryByLabelText('API URL')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Hindsight settings/ }))
    expect(await screen.findByLabelText('API URL')).toBeTruthy()
  })

  it('saves edited values without requiring a secret replacement', async () => {
    await renderPanel()

    const apiUrl = await screen.findByLabelText('API URL')
    fireEvent.change(apiUrl, { target: { value: 'http://localhost:8888' } })
    fireEvent.change(screen.getByLabelText('Bank ID'), { target: { value: 'ben-bank' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saveMemoryProviderConfig).toHaveBeenCalledWith('hindsight', {
        mode: 'cloud',
        api_key: '',
        api_url: 'http://localhost:8888',
        bank_id: 'ben-bank',
        recall_budget: 'mid'
      })
    )
  })

  it('renders nothing for a provider with no declared config surface', async () => {
    getMemoryProviderConfig.mockResolvedValue({ name: 'builtin', label: 'builtin', fields: [] })

    const { container } = await renderPanel('builtin')

    await waitFor(() => expect(getMemoryProviderConfig).toHaveBeenCalledWith('builtin'))
    expect(container.querySelector('section')).toBeNull()
  })

  it('renders booleans and hides fields outside the selected mode', async () => {
    getMemoryProviderConfig.mockResolvedValue({
      name: 'modeful',
      label: 'Modeful',
      fields: [
        {
          key: 'mode',
          label: 'Mode',
          kind: 'select',
          value: 'cloud',
          description: '',
          placeholder: '',
          is_set: true,
          options: [
            { value: 'cloud', label: 'Cloud', description: '' },
            { value: 'local', label: 'Local', description: '' }
          ]
        },
        {
          key: 'cloud_url',
          label: 'Cloud URL',
          kind: 'text',
          value: 'https://memory.example',
          description: '',
          placeholder: '',
          is_set: true,
          options: [],
          when: { mode: 'cloud' }
        },
        {
          key: 'local_url',
          label: 'Local URL',
          kind: 'text',
          value: 'http://127.0.0.1:9000',
          description: '',
          placeholder: '',
          is_set: true,
          options: [],
          when: { mode: 'local' }
        },
        {
          key: 'auto_recall',
          label: 'Automatic recall',
          kind: 'boolean',
          value: true,
          description: 'Recall before each turn',
          placeholder: '',
          is_set: true,
          options: []
        }
      ]
    } satisfies MemoryProviderConfig)

    await renderPanel('modeful')

    expect(await screen.findByLabelText('Cloud URL')).toBeTruthy()
    expect(screen.queryByLabelText('Local URL')).toBeNull()
    const toggle = screen.getByRole('switch')
    expect(toggle.getAttribute('data-state')).toBe('checked')
    fireEvent.click(toggle)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(saveMemoryProviderConfig).toHaveBeenCalledWith(
        'modeful',
        expect.objectContaining({ auto_recall: false, cloud_url: 'https://memory.example' })
      )
    )
  })
})
