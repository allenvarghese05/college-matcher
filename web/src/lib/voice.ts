/**
 * Browser side of the voice pipeline (SPEC §11).
 *
 *   mic -> AudioWorklet (downsample to 16 kHz mono PCM16, 20 ms frames) -> WebSocket
 *   WebSocket -> PCM16 frames -> Web Audio playback queue
 *
 * Also: an energy-based VAD that reports end of speech (t0) so the server can finalize
 * the transcript early, "first audio played" (t5) and per-sentence playback marks, and —
 * when the server enables barge-in — an `interrupt` as soon as the student talks over
 * the counselor (ducked by the VAD, confirmed by live-transcript words that aren't echo),
 * and soft "mhm" backchannels in the student's mid-answer pauses.
 * Protocol: backend/app/voice/gateway.py.
 */
import { API_BASE } from "@/lib/api";
import type { VoiceClientMessage, VoiceServerEvent, VoiceServerState, VoiceStatus } from "@/lib/types";

export type VoiceUiState = "connecting" | "listening" | "thinking" | "speaking";

export type VoiceCloseReason = { kind: "stopped" } | { kind: "error"; code: string; message: string };

export interface VoiceHandlers {
  onUiState?: (state: VoiceUiState) => void;
  /** Every JSON frame from the server, in order. */
  onEvent?: (event: VoiceServerEvent) => void;
  onClose?: (reason: VoiceCloseReason) => void;
}

export class MicPermissionError extends Error {
  constructor() {
    super("microphone permission denied");
    this.name = "MicPermissionError";
  }
}

/** No usable microphone on this device (none plugged in, or it can't do mono capture). */
export class MicMissingError extends Error {
  constructor() {
    super("no microphone found");
    this.name = "MicMissingError";
  }
}

const INPUT_RATE = 16000;
const FRAME_SAMPLES = 320; // 20 ms at 16 kHz

// Barge-in: the VAD hearing the student during playback only ducks the counselor; the
// live transcript confirms it (>= BARGE_MIN_WORDS words that aren't the counselor's own
// echo) and only then is the reply stopped. No confirmation -> volume comes back.
const BARGE_MIN_WORDS = 2;
const DUCK_GAIN = 0.2;
const DUCK_RELEASE_MS = 1500;
// ...or the student keeps talking loudly while the counselor is ducked (its echo is then
// far below the strict threshold), whichever comes first. Transcripts lag ~1-2 s.
const DUCKED_VOICE_MS = 600;
const ECHO_OVERLAP = 0.6; // share of heard words found in the reply being spoken = echo

// Backchannels: a soft "mhm" in a mid-answer pause, at most every BACKCHANNEL_GAP_MS.
const BACKCHANNEL_PAUSE_MS = 380; // pause long enough to react to...
const BACKCHANNEL_WINDOW_MS = 160; // ...but before the utterance would end
const BACKCHANNEL_MIN_TALK_MS = 2500;
const BACKCHANNEL_GAP_MS = 7000;
const BACKCHANNEL_CHANCE = 0.7;
const BACKCHANNEL_GAIN = 0.45;
const BACKCHANNEL_MUTE_TAIL_MS = 250; // keep the mic muted a bit past the clip (echo tail)

const words = (text: string): string[] => text.toLowerCase().match(/[a-z0-9']+/g) ?? [];

// Common words say nothing about echo ("no I want to..." shares "I", "to" with anything).
const STOPWORDS = new Set(
  "a an and are as at be but by do for from i i'm in is it it's me my no not of on or so that the to we you".split(" "),
);

/** Mostly words the counselor is saying right now -> the mic is hearing the speaker. */
export function looksLikeEcho(heard: string, spoken: string): boolean {
  const all = words(heard);
  if (!all.length) return true;
  const s = new Set(words(spoken));
  if (!s.size) return false;
  const content = all.filter((w) => !STOPWORDS.has(w));
  const h = content.length ? content : all;
  const hits = h.filter((w) => s.has(w)).length;
  return hits / h.length >= ECHO_OVERLAP;
}

export function isBargeIn(heard: string, spoken: string): boolean {
  return words(heard).length >= BARGE_MIN_WORDS && !looksLikeEcho(heard, spoken);
}

export async function fetchVoiceStatus(signal?: AbortSignal): Promise<VoiceStatus> {
  try {
    const res = await fetch(`${API_BASE}/voice/status`, { signal });
    if (!res.ok) return { available: false, provider: null, barge_in: false };
    return (await res.json()) as VoiceStatus;
  } catch {
    return { available: false, provider: null, barge_in: false };
  }
}

export function voiceSocketUrl(sessionId: string): string {
  const base = API_BASE.startsWith("http")
    ? API_BASE.replace(/^http/, "ws")
    : `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${API_BASE}`;
  return `${base}/sessions/${sessionId}/voice`;
}

// ----------------------------------------------------------------------------- capture

/** AudioWorklet: boxcar-average down to 16 kHz (a crude low-pass), emit 20 ms PCM16 frames + RMS. */
const CAPTURE_WORKLET = `
class PcmCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.ratio = sampleRate / options.processorOptions.targetRate;
    this.acc = 0; this.cnt = 0; this.pos = 0;
    this.frame = new Int16Array(${FRAME_SAMPLES}); this.n = 0; this.sumSq = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i]; this.cnt++; this.pos += 1;
      if (this.pos < this.ratio) continue;
      this.pos -= this.ratio;
      const s = Math.max(-1, Math.min(1, this.acc / this.cnt));
      this.acc = 0; this.cnt = 0;
      this.sumSq += s * s;
      this.frame[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
      if (this.n === ${FRAME_SAMPLES}) {
        const rms = Math.sqrt(this.sumSq / ${FRAME_SAMPLES});
        this.port.postMessage({ pcm: this.frame.buffer, rms }, [this.frame.buffer]);
        this.frame = new Int16Array(${FRAME_SAMPLES}); this.n = 0; this.sumSq = 0;
      }
    }
    return true;
  }
}
registerProcessor("pcm-capture", PcmCapture);
`;

/** Energy VAD with an adaptive noise floor. `strict` (during playback) resists echo. */
export class EnergyVad {
  private floor = 0.004;
  private voicedRun = 0;
  speaking = false;
  lastVoicedAt = 0;

  constructor(
    private readonly hangMs = 1000,
    private readonly startFrames = 3,
  ) {}

  isVoiced(rms: number, strict = false): boolean {
    return rms > Math.max(strict ? 0.04 : 0.012, this.floor * (strict ? 6 : 3));
  }

  push(rms: number, now: number, strict = false): "start" | "end" | null {
    const voiced = this.isVoiced(rms, strict);
    if (!voiced && !this.speaking) this.floor = this.floor * 0.95 + rms * 0.05;
    if (voiced) {
      this.voicedRun += 1;
      this.lastVoicedAt = now;
      if (!this.speaking && this.voicedRun >= (strict ? this.startFrames + 2 : this.startFrames)) {
        this.speaking = true;
        return "start";
      }
      return null;
    }
    this.voicedRun = 0;
    if (this.speaking && now - this.lastVoicedAt > this.hangMs) {
      this.speaking = false;
      return "end";
    }
    return null;
  }

  reset(): void {
    this.speaking = false;
    this.voicedRun = 0;
  }
}

// ----------------------------------------------------------------------------- session

interface SentenceMark {
  turn: number;
  sentence: number;
  endAt: number; // AudioContext time the sentence finishes playing
}

export class VoiceSession {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private worklet: AudioWorkletNode | null = null;
  private outGain: GainNode | null = null;
  private analyser: AnalyserNode | null = null;
  private analyserBuf: Float32Array<ArrayBuffer> | null = null;
  private ticker: number | null = null;
  private readonly vad = new EnergyVad();

  private serverState: VoiceServerState | null = null;
  private ui: VoiceUiState = "connecting";
  private bargeIn = false;
  private backchannel = false;
  private outputRate = 24000;
  private spokenText = ""; // what the counselor is saying this turn (echo filter)
  private duckTimer: number | null = null;
  private duckedVoiceMs = 0;
  private bcClips: AudioBuffer[] = [];
  private bcTexts: string[] = [];
  private bcGain: GainNode | null = null;
  private bcLastAt = 0;
  private bcLastIdx = -1;
  private bcThisPause = false;
  private bcMutedUntil = 0;
  private speechVoicedAt = 0; // last really-voiced frame (not bumped across clips): t0 // performance.now() until which mic upload/VAD ignore the clip
  private utteranceStartAt = 0;
  private micLevel = 0;
  private closed = false;
  private closeError: { code: string; message: string } | null = null;

  // playback bookkeeping
  private sources = new Set<AudioBufferSourceNode>();
  private queueEnd = 0;
  private audioTurn = 0; // turn of the most recent audio_start
  private discardTurn = -1; // turn cut off by barge-in: drop its late audio
  private reportedT5 = new Set<number>();
  private marks: SentenceMark[] = [];
  private lastPlayed = { turn: 0, sentence: -1 };

  constructor(
    private readonly sessionId: string,
    private readonly handlers: VoiceHandlers = {},
  ) {}

  get state(): VoiceUiState {
    return this.ui;
  }

  /** 0..1 — mic level while listening, counselor output level while speaking. */
  readonly level = (): number => {
    if (this.playing && this.analyser && this.analyserBuf) {
      this.analyser.getFloatTimeDomainData(this.analyserBuf);
      let sum = 0;
      for (const v of this.analyserBuf) sum += v * v;
      return Math.min(1, Math.sqrt(sum / this.analyserBuf.length) * 5);
    }
    return Math.min(1, this.micLevel * 6);
  };

  private get playing(): boolean {
    return this.sources.size > 0;
  }

  /** Ask for the mic, open the socket. Throws MicPermissionError / MicMissingError. */
  async start(): Promise<void> {
    this.setUi("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this.closed = true;
      const name = (e as DOMException).name;
      if (name === "NotAllowedError" || name === "SecurityError") throw new MicPermissionError();
      if (name === "NotFoundError" || name === "OverconstrainedError") throw new MicMissingError();
      throw e;
    }
    try {
      const ctx = new AudioContext({ latencyHint: "interactive" });
      this.ctx = ctx;
      const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "application/javascript" }));
      try {
        await ctx.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      const src = ctx.createMediaStreamSource(this.stream);
      this.worklet = new AudioWorkletNode(ctx, "pcm-capture", {
        processorOptions: { targetRate: INPUT_RATE },
      });
      const mute = ctx.createGain();
      mute.gain.value = 0;
      src.connect(this.worklet).connect(mute).connect(ctx.destination);
      this.worklet.port.onmessage = (e: MessageEvent<{ pcm: ArrayBuffer; rms: number }>) =>
        this.onMicFrame(e.data.pcm, e.data.rms);

      this.outGain = ctx.createGain();
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyserBuf = new Float32Array(new ArrayBuffer(this.analyser.fftSize * 4));
      this.outGain.connect(this.analyser);
      this.analyser.connect(ctx.destination);
      this.bcGain = ctx.createGain();
      this.bcGain.gain.value = BACKCHANNEL_GAIN;
      this.bcGain.connect(ctx.destination);
      if (ctx.state === "suspended") await ctx.resume();
    } catch (e) {
      this.teardown();
      throw e;
    }

    const ws = new WebSocket(voiceSocketUrl(this.sessionId));
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (e: MessageEvent<string | ArrayBuffer>) => {
      if (typeof e.data === "string") this.onServerJson(e.data);
      else this.onServerAudio(e.data);
    };
    ws.onclose = () => this.finish();
    ws.onerror = () => {
      this.closeError ??= { code: "socket_error", message: "Lost the voice connection." };
    };
    this.ticker = window.setInterval(() => this.tick(), 50);
  }

  /** End the voice session (the reply in flight is saved as interrupted by the server). */
  stop(): void {
    if (this.closed) return;
    this.send({ type: "stop" });
    this.closeError = null;
    this.ws?.close(1000);
    this.finish();
  }

  // ------------------------------------------------------------------ outgoing

  private send(msg: VoiceClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  private onMicFrame(pcm: ArrayBuffer, rms: number): void {
    this.micLevel = rms;
    if (this.closed || !this.serverState) return;
    const now = performance.now();
    const listening = this.serverState === "listening" && !this.playing;
    // While our own "mhm" plays (plus its echo tail) keep the VAD out of it. The real mic
    // audio is still sent (the student may start talking again right then); the server
    // drops a transcript that is just the clip's echo (we tell it via `backchannel`).
    const muted = now < this.bcMutedUntil;
    // Keep the hang clock moving across the clip: the pause it filled isn't silence
    // the student owes us, so the end-of-speech countdown restarts after the clip.
    if (muted && this.vad.speaking) this.vad.lastVoicedAt = now;
    const vad = muted ? null : this.vad.push(rms, now, this.playing);
    if (!muted && this.vad.isVoiced(rms, this.playing)) this.speechVoicedAt = now; // true t0

    if (vad === "start") this.utteranceStartAt = now;
    if (!muted && this.playing && this.bargeIn && this.vad.isVoiced(rms, true)) {
      if (this.duckTimer !== null) this.duckedVoiceMs += 20;
      this.duck(); // (re)duck on every loud frame: stays down while they keep talking
      if (this.duckedVoiceMs >= DUCKED_VOICE_MS) this.interrupt();
    }
    if (listening) this.maybeBackchannel(now);
    if (vad === "end" && !this.playing) {
      // Also while the server is thinking: a continuation that restarts the turn
      // still gets its end-of-speech mark (t0).
      this.send({ type: "speech_end", t_ms: this.speechVoicedAt || this.vad.lastVoicedAt, sent_ms: now });
    }
    if ((listening || this.bargeIn) && this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }

  /** Student may be talking over the counselor: turn it down until the transcript says. */
  private duck(): void {
    if (!this.outGain || !this.ctx) return;
    this.outGain.gain.setTargetAtTime(DUCK_GAIN, this.ctx.currentTime, 0.03);
    if (this.duckTimer === null) this.duckedVoiceMs = 0;
    if (this.duckTimer !== null) window.clearTimeout(this.duckTimer);
    this.duckTimer = window.setTimeout(() => this.unduck(), DUCK_RELEASE_MS);
  }

  private unduck(): void {
    if (this.duckTimer !== null) window.clearTimeout(this.duckTimer);
    this.duckTimer = null;
    this.duckedVoiceMs = 0;
    if (this.outGain && this.ctx) this.outGain.gain.setTargetAtTime(1, this.ctx.currentTime, 0.05);
  }

  /** A soft "mhm" when the student pauses mid-answer (never while the counselor talks). */
  private maybeBackchannel(now: number): void {
    if (!this.backchannel || !this.bcClips.length || !this.vad.speaking) return;
    const silent = now - this.vad.lastVoicedAt;
    if (silent < BACKCHANNEL_PAUSE_MS) {
      this.bcThisPause = false;
      return;
    }
    if (this.bcThisPause || silent > BACKCHANNEL_PAUSE_MS + BACKCHANNEL_WINDOW_MS) return;
    this.bcThisPause = true;
    if (now - this.utteranceStartAt < BACKCHANNEL_MIN_TALK_MS) return;
    if (now - this.bcLastAt < BACKCHANNEL_GAP_MS || Math.random() > BACKCHANNEL_CHANCE) return;
    this.playBackchannel(now);
  }

  private playBackchannel(now: number): void {
    const ctx = this.ctx;
    if (!ctx || !this.bcGain) return;
    let idx = Math.floor(Math.random() * this.bcClips.length);
    if (idx === this.bcLastIdx) idx = (idx + 1) % this.bcClips.length;
    const clip = this.bcClips[idx];
    if (!clip) return;
    const src = ctx.createBufferSource();
    src.buffer = clip;
    src.connect(this.bcGain);
    src.start();
    this.bcMutedUntil = now + clip.duration * 1000 + BACKCHANNEL_MUTE_TAIL_MS;
    this.send({ type: "backchannel", text: this.bcTexts[idx] ?? "" });
    this.bcLastAt = now;
    this.bcLastIdx = idx;
  }

  private async loadBackchannels(): Promise<void> {
    try {
      const res = await fetch(`${API_BASE}/voice/backchannels`);
      if (!res.ok) return;
      const body = (await res.json()) as { sample_rate: number; clips: { text: string; pcm16_b64: string }[] };
      const ctx = this.ctx;
      if (!ctx) return;
      const usable = body.clips.filter((c) => c.pcm16_b64.length > 0);
      this.bcTexts = usable.map((c) => c.text);
      this.bcClips = usable
        .map((c) => {
          const bin = atob(c.pcm16_b64);
          const pcm = new Int16Array(bin.length >> 1);
          for (let i = 0; i < pcm.length; i++) {
            const lo = bin.charCodeAt(2 * i);
            const hi = bin.charCodeAt(2 * i + 1);
            pcm[i] = (hi << 8) | lo;
          }
          const buf = ctx.createBuffer(1, pcm.length, body.sample_rate);
          const data = buf.getChannelData(0);
          for (let i = 0; i < pcm.length; i++) data[i] = (pcm[i] ?? 0) / 0x8000;
          return buf;
        });
    } catch {
      this.bcClips = [];
    }
  }

  private interrupt(): void {
    this.unduck();
    const turn = this.audioTurn;
    const lastPlayed = this.lastPlayed.turn === turn ? this.lastPlayed.sentence : -1;
    this.stopPlayback();
    this.discardTurn = turn;
    this.send({ type: "interrupt", turn, last_played: lastPlayed, sent_ms: performance.now() });
    this.refreshUi();
  }

  // ------------------------------------------------------------------ incoming

  private onServerJson(raw: string): void {
    let ev: VoiceServerEvent;
    try {
      ev = JSON.parse(raw) as VoiceServerEvent;
    } catch {
      return;
    }
    switch (ev.type) {
      case "hello":
        this.bargeIn = ev.barge_in;
        this.backchannel = ev.backchannel ?? false;
        this.outputRate = ev.output_sample_rate;
        if (this.backchannel) void this.loadBackchannels();
        break;
      case "transcript_interim":
        if (ev.during_reply) {
          // Heard while the counselor is thinking/speaking: echo, or a real barge-in?
          if (!isBargeIn(ev.text, this.spokenText)) return;
          // Speaking includes the gap between two sentences (nothing queued yet).
          if (this.bargeIn && (this.playing || this.serverState === "speaking")) this.interrupt();
        }
        break;
      case "transcript_final":
        this.spokenText = "";
        break;
      case "state":
        this.serverState = ev.state;
        break;
      case "audio_start":
        if (ev.turn !== this.audioTurn) this.spokenText = "";
        this.spokenText += ` ${ev.text}`;
        this.audioTurn = ev.turn;
        this.outputRate = ev.sample_rate;
        break;
      case "audio_end":
        if (ev.turn !== this.discardTurn) {
          this.marks.push({ turn: ev.turn, sentence: ev.sentence, endAt: this.queueEnd });
        }
        break;
      case "error":
        if (ev.fatal) this.closeError = { code: ev.code, message: ev.message };
        break;
    }
    this.handlers.onEvent?.(ev);
    this.refreshUi();
  }

  private onServerAudio(buf: ArrayBuffer): void {
    const ctx = this.ctx;
    if (!ctx || !this.outGain || this.audioTurn === this.discardTurn || buf.byteLength < 2) return;
    const pcm = new Int16Array(buf, 0, buf.byteLength >> 1);
    const audio = ctx.createBuffer(1, pcm.length, this.outputRate);
    const data = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) data[i] = (pcm[i] ?? 0) / 0x8000;
    const src = ctx.createBufferSource();
    src.buffer = audio;
    src.connect(this.outGain);
    const startAt = Math.max(ctx.currentTime + 0.03, this.queueEnd);
    src.start(startAt);
    this.queueEnd = startAt + audio.duration;
    this.sources.add(src);
    src.onended = () => {
      this.sources.delete(src);
      this.refreshUi();
    };

    const turn = this.audioTurn;
    if (!this.reportedT5.has(turn)) {
      this.reportedT5.add(turn);
      const latency = (ctx.outputLatency || 0) + (startAt - ctx.currentTime);
      window.setTimeout(() => {
        const t = performance.now();
        this.send({ type: "playback_start", turn, t_ms: t, sent_ms: t });
      }, latency * 1000);
    }
    this.refreshUi();
  }

  // ------------------------------------------------------------------ playback

  private tick(): void {
    const ctx = this.ctx;
    if (!ctx) return;
    while (this.marks.length && (this.marks[0]?.endAt ?? Infinity) <= ctx.currentTime) {
      const m = this.marks.shift();
      if (!m) break;
      this.lastPlayed = { turn: m.turn, sentence: m.sentence };
      this.send({ type: "played", turn: m.turn, sentence: m.sentence });
    }
  }

  private stopPlayback(): void {
    for (const s of this.sources) {
      s.onended = null;
      try {
        s.stop();
      } catch {
        /* already stopped */
      }
    }
    this.sources.clear();
    this.marks = [];
    this.queueEnd = 0;
  }

  private refreshUi(): void {
    if (this.closed) return;
    let next: VoiceUiState;
    if (!this.serverState) next = "connecting";
    else if (this.playing) next = "speaking";
    else if (this.serverState === "listening") next = "listening";
    else next = "thinking";
    this.setUi(next);
  }

  private setUi(state: VoiceUiState): void {
    if (state === this.ui) return;
    this.ui = state;
    this.handlers.onUiState?.(state);
  }

  // ------------------------------------------------------------------ teardown

  private finish(): void {
    if (this.closed && !this.ctx && !this.ws) return;
    const wasOpen = !this.closed;
    this.closed = true;
    this.teardown();
    if (wasOpen) {
      this.handlers.onClose?.(this.closeError ? { kind: "error", ...this.closeError } : { kind: "stopped" });
    }
  }

  private teardown(): void {
    if (this.duckTimer !== null) window.clearTimeout(this.duckTimer);
    this.duckTimer = null;
    if (this.ticker !== null) window.clearInterval(this.ticker);
    this.ticker = null;
    this.stopPlayback();
    if (this.worklet) this.worklet.port.onmessage = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    if (this.ws) {
      this.ws.onmessage = null;
      this.ws.onclose = null;
      if (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING) this.ws.close();
    }
    this.ws = null;
  }
}
