// Approval attention cue.
//
// A short, deliberately *distinct* two-tone alert played when a blocking
// approval arrives for the focused active session — the one case the native OS
// notification is suppressed (native-notifications.ts::shouldFire). It reuses
// the enveloped-oscillator approach from lib/completion-sound.ts but is a rising
// attention gesture rather than a soft turn-end chime, so the two are never
// confused. Respects the global haptics/sounds mute and the approval-sound
// preference; the preview bypasses both so it can be auditioned in Settings.

import { $approvalSoundEnabled } from '@/store/approval-sound'
import { $hapticsMuted } from '@/store/haptics'

let ctx: AudioContext | null = null

function getCtx(): AudioContext | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    if (!ctx) {
      const Ctor =
        window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext

      if (!Ctor) {
        return null
      }

      ctx = new Ctor()
    }

    // Autoplay policies can leave the context suspended until a gesture; a
    // resume() here recovers it once the user has interacted with the window.
    if (ctx.state === 'suspended') {
      void ctx.resume().catch(() => undefined)
    }

    return ctx
  } catch {
    return null
  }
}

interface Tone {
  attack?: number
  dur: number
  freq: number
  gain: number
  start?: number
  type?: OscillatorType
}

// One enveloped oscillator voice → master. Linear-ish attack into an
// exponential decay keeps the tail smooth and avoids the click you get ramping
// straight to zero.
function voice(ac: AudioContext, master: GainNode, t0: number, tone: Tone) {
  const osc = ac.createOscillator()
  const env = ac.createGain()
  const start = t0 + (tone.start ?? 0)
  const attack = tone.attack ?? 0.006
  const end = start + tone.dur

  osc.type = tone.type ?? 'triangle'
  osc.frequency.setValueAtTime(tone.freq, start)

  env.gain.setValueAtTime(0.0001, start)
  env.gain.exponentialRampToValueAtTime(Math.max(tone.gain, 0.0002), start + attack)
  env.gain.exponentialRampToValueAtTime(0.0001, end)

  osc.connect(env)
  env.connect(master)
  osc.start(start)
  osc.stop(end + 0.02)
}

// Note frequencies (equal temperament). A brisk rising perfect-fourth doublet
// (A4 → D5) reads as "attention needed" without the harshness of a raw beep.
const A4 = 440
const D5 = 587.33

function playCue() {
  const ac = getCtx()

  if (!ac) {
    return
  }

  const master = ac.createGain()
  const tone = ac.createBiquadFilter()
  tone.type = 'lowpass'
  tone.frequency.setValueAtTime(4200, ac.currentTime)
  tone.Q.setValueAtTime(0.4, ac.currentTime)
  master.gain.setValueAtTime(0.5, ac.currentTime)
  master.connect(tone)
  tone.connect(ac.destination)

  const t0 = ac.currentTime + 0.01
  voice(ac, master, t0, { freq: A4, dur: 0.14, gain: 0.06, attack: 0.004, type: 'triangle' })
  voice(ac, master, t0, { freq: A4 / 2, dur: 0.12, gain: 0.02, attack: 0.006, type: 'sine' })
  voice(ac, master, t0 + 0.13, { freq: D5, dur: 0.22, gain: 0.06, attack: 0.004, type: 'triangle' })
}

// Audition the cue from Settings — bypasses both the enabled preference and the
// global mute so the sound can be compared even when it's off or silenced.
export function previewApprovalSound() {
  playCue()
}

// The sound preference gate: on only when the approval cue is enabled AND the
// global haptics/sounds mute is off. Exported so the muted/disabled behavior can
// be unit-tested without a Web Audio stub.
export function shouldPlayApprovalSound(): boolean {
  return $approvalSoundEnabled.get() && !$hapticsMuted.get()
}

// Play the approval cue if enabled and not globally muted. The decision about
// *whether an approval warrants* a sound (focused active session, de-duplicated)
// lives in native-notifications.ts; this only enforces the sound preferences.
export function playApprovalSound() {
  if (!shouldPlayApprovalSound()) {
    return
  }

  playCue()
}
