import { atom } from 'nanostores'

import { persistBoolean, storedBoolean } from '@/lib/storage'

// Whether to play an in-app attention cue when a blocking approval arrives for
// the *focused* active session. The native OS notification is intentionally
// suppressed in that case (see native-notifications.ts::shouldFire), so without
// this a user who steps away while Fabric stays focused can miss the prompt and
// leave the agent blocked. Device-local, like the other notification prefs.
const STORAGE_KEY = 'fabric.desktop.approvalSoundEnabled'

// On by default: it only ever fires for the focused active session (the one gap
// the native path leaves open) and is still gated behind the global mute toggle.
export const $approvalSoundEnabled = atom(storedBoolean(STORAGE_KEY, true))

$approvalSoundEnabled.subscribe(enabled => persistBoolean(STORAGE_KEY, enabled))

export function setApprovalSoundEnabled(enabled: boolean) {
  $approvalSoundEnabled.set(enabled)
}
