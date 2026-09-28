// Audio cues for event timers. We generate the tones with Web Audio
// rather than ship bundled audio files: simpler footprint, no asset
// pipeline, and the operator's browser autoplay policy only blocks
// AudioContext until the first user gesture (handled in
// TimerNotificationProvider by hooking the first click).

type AudioContextCtor = typeof AudioContext;

let ctx: AudioContext | null = null;

function getCtx(): AudioContext | null {
  if (typeof window === "undefined") return null;
  if (ctx && ctx.state !== "closed") return ctx;
  const Ctor: AudioContextCtor | undefined =
    globalThis.AudioContext ??
    (globalThis as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext;
  if (!Ctor) return null;
  ctx = new Ctor();
  return ctx;
}

export function unlockAudio(): void {
  // Must be called from a user-initiated event handler the first time;
  // afterwards we can produce sounds whenever we like.
  const c = getCtx();
  if (c && c.state === "suspended") {
    void c.resume();
  }
}

function beep(frequency: number, durationMs: number, gainAt = 0.18): void {
  const c = getCtx();
  if (!c || c.state !== "running") return;
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.connect(gain);
  gain.connect(c.destination);
  osc.type = "sine";
  osc.frequency.value = frequency;
  const start = c.currentTime;
  const end = start + durationMs / 1000;
  gain.gain.setValueAtTime(0, start);
  gain.gain.linearRampToValueAtTime(gainAt, start + 0.01);
  gain.gain.linearRampToValueAtTime(0, end);
  osc.start(start);
  osc.stop(end + 0.02);
}

// Pre-alert: a gentle two-note chime so the operator notices but isn't
// startled. Fires once when the timer enters the pre-alert window.
export function playPreAlert(): void {
  beep(660, 180);
  setTimeout(() => beep(880, 220), 220);
}

// Firing: a more urgent triple-beep, repeated every 30 seconds until
// the operator dismisses. Distinct from the pre-alert so a busy
// operator can tell from the next room which one fired.
export function playFiring(): void {
  beep(880, 140, 0.22);
  setTimeout(() => beep(880, 140, 0.22), 220);
  setTimeout(() => beep(1040, 240, 0.22), 440);
}
