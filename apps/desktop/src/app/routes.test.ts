import { describe, expect, it } from 'vitest'

import { appViewForPath, routeSessionId, VOICE_NOTES_ROUTE } from './routes'

describe('voice notes route', () => {
  it('resolves as a reserved app view instead of a session id', () => {
    expect(appViewForPath(VOICE_NOTES_ROUTE)).toBe('voice-notes')
    expect(routeSessionId(VOICE_NOTES_ROUTE)).toBeNull()
  })
})
