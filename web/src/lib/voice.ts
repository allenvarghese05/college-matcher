/**
 * Browser side of the voice pipeline (SPEC §11).
 *
 *   mic -> AudioWorklet (downsample to 16 kHz mono PCM16, 20 ms frames) -> WebSocket
 *   WebSocket -> PCM16 frames -> Web Audio playback queue
 *
 * Also: an energy-based VAD that reports end of speech (t0) so the server can finalize
 * the transcript early, "first audio played" (t5) and per-sentence playback marks, and —
 * when the server enables barge-in — an `interrupt` as soon as the student talks over
 * the counselor. Protocol: backend/app/voice/gateway.py.
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

const INPUT_RATE = 16000;
const FRAME_SAMPLES = 320; // 20 ms at 16 kHz

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
    private readonly hangMs = 700,
    private readonly startFrames = 3,
  ) {}

  push(rms: number, now: number, strict = false): "start" | "end" | null {
    const threshold = Math.max(strict ? 0.04 : 0.012, this.floor * (strict ? 6 : 3));
    const voiced = rms > threshold;
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
  private outputRate = 24000;
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

  /** Ask for the mic, open the socket. Throws MicPermissionError if the mic is refused. */
  async start(): Promise<void> {
    this.setUi("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch (e) {
      this.closed = true;
      const name = (e as DOMException).name;
      if (name === "NotAllowedError" || name === "SecurityError" || name === "NotFoundError") {
        throw new MicPermissionError();
      }
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
    const vad = this.vad.push(rms, now, this.playing);

    if (vad === "start" && this.playing && this.bargeIn) this.interrupt();
    if (vad === "end" && listening) {
      this.send({ type: "speech_end", t_ms: this.vad.lastVoicedAt, sent_ms: now });
    }
    if ((listening || this.bargeIn) && this.ws?.readyState === WebSocket.OPEN) this.ws.send(pcm);
  }

  private interrupt(): void {
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
        this.outputRate = ev.output_sample_rate;
        break;
      case "state":
        this.serverState = ev.state;
        break;
      case "audio_start":
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
