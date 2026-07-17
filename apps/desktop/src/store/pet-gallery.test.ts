import { beforeEach, describe, expect, it } from 'vitest'

import {
  $petGallery,
  type GatewayRequest,
  type PetGallery,
  removePet,
  resetPetGallery
} from '@/store/pet-gallery'

const activeLocalOverride = (): PetGallery => ({
  enabled: true,
  active: 'fabric-mascot',
  pets: [
    {
      slug: 'fabric-mascot',
      displayName: 'Local Mascot Override',
      installed: true,
      spritesheetUrl: '',
      generated: true,
      bundled: false
    }
  ]
})

describe('removePet', () => {
  beforeEach(() => {
    resetPetGallery()
    $petGallery.set(activeLocalOverride())
  })

  it('keeps the active pet enabled when removal reveals a bundled fallback', async () => {
    const calls: string[] = []

    const request: GatewayRequest = async <T>(method: string): Promise<T> => {
      calls.push(method)

      if (method === 'pet.remove') {
        return {
          ok: true,
          slug: 'fabric-mascot',
          fallback: {
            displayName: 'Fabric Mascot',
            bundled: true,
            generated: false
          }
        } as T
      }

      if (method === 'pet.info') {
        return null as T
      }

      throw new Error(`unexpected method: ${method}`)
    }

    await expect(removePet(request, 'fabric-mascot', 'remove failed')).resolves.toBe(true)

    expect(calls).toEqual(['pet.remove', 'pet.info'])
    expect($petGallery.get()).toEqual({
      enabled: true,
      active: 'fabric-mascot',
      pets: [
        {
          slug: 'fabric-mascot',
          displayName: 'Fabric Mascot',
          installed: true,
          spritesheetUrl: '',
          curated: true,
          generated: false,
          bundled: true
        }
      ]
    })
  })

  it('disables and removes an active local-only pet without a fallback', async () => {
    const request: GatewayRequest = async <T>(method: string): Promise<T> => {
      if (method === 'pet.remove') {
        return { ok: true, slug: 'fabric-mascot' } as T
      }

      if (method === 'pet.info') {
        return null as T
      }

      throw new Error(`unexpected method: ${method}`)
    }

    await expect(removePet(request, 'fabric-mascot', 'remove failed')).resolves.toBe(true)

    expect($petGallery.get()).toEqual({ enabled: false, active: '', pets: [] })
  })
})
