import { describe, expect, it } from 'vitest'

import {
  appViewForPath,
  routeSessionId,
  SOCIAL_ROUTE,
  VOICE_NOTES_ROUTE,
  VOICE_SETTINGS_ROUTE
} from './routes'

describe('voice notes route', () => {
  it('resolves as a reserved app view instead of a session id', () => {
    expect(appViewForPath(VOICE_NOTES_ROUTE)).toBe('voice-notes')
    expect(routeSessionId(VOICE_NOTES_ROUTE)).toBeNull()
  })

  it('deep-links speech-to-text setup to the Voice settings section', () => {
    expect(VOICE_SETTINGS_ROUTE).toBe('/settings?tab=config:voice')
  })

  it('keeps Social Studio reserved instead of treating it as a session id', () => {
    expect(appViewForPath(SOCIAL_ROUTE)).toBe('social')
    expect(routeSessionId(SOCIAL_ROUTE)).toBeNull()
  })
})
