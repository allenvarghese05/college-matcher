"""Live voice round trip: macOS `say` -> 16 kHz PCM -> WS -> Deepgram STT/TTS.

Run `make voice-probe` with the API up and DEEPGRAM_API_KEY set.

Streams each utterance in real time (20 ms frames), marks speech_end at the last speech
frame, keeps streaming silence until the final transcript, and reports playback_start the
moment the first reply audio frame arrives (no speaker, so playback ~= network).
"""

import asyncio
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
import wave

import httpx
import websockets

API = os.environ.get("API_BASE", "http://localhost:8000")
WS = API.replace("http", "ws", 1)
UTTERANCES = [
    "Hi, I'm a junior in Ohio and I want to study nursing.",
    "If money weren't involved, I'd work in a children's hospital.",
    "I like biology and chemistry, and I volunteer at a clinic on weekends.",
    "Math is my best class and I run the robotics club at school.",
    "My family makes about fifty thousand a year, so cost really matters.",
]
FRAME = 640  # 20 ms of PCM16 @ 16 kHz


def now_ms() -> float:
    return time.perf_counter() * 1000.0


def synth(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(["say", "-o", f.name, "--data-format=LEI16@16000", text], check=True)
        with wave.open(f.name) as w:
            assert w.getframerate() == 16000 and w.getsampwidth() == 2 and w.getnchannels() == 1
            return w.readframes(w.getnframes())


async def turn(ws, pcm: bytes, text: str) -> dict:
    for i in range(0, len(pcm), FRAME):
        await ws.send(pcm[i : i + FRAME])
        await asyncio.sleep(0.02)
    t0 = now_ms()
    await ws.send(json.dumps({"type": "speech_end", "t_ms": t0, "sent_ms": now_ms()}))
    silence = bytes(FRAME)
    final = asyncio.Event()

    async def pad():
        while not final.is_set():
            await ws.send(silence)
            await asyncio.sleep(0.02)

    padder = asyncio.create_task(pad())
    out: dict = {"said": text}
    first_audio = None
    cur_turn = None
    try:
        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=60)
            if isinstance(msg, bytes):
                if first_audio is None:
                    first_audio = now_ms()
                    await ws.send(
                        json.dumps(
                            {
                                "type": "playback_start",
                                "turn": cur_turn,
                                "t_ms": first_audio,
                                "sent_ms": now_ms(),
                            }
                        )
                    )
                continue
            m = json.loads(msg)
            k = m.get("type")
            if k == "transcript_final":
                final.set()
                cur_turn = m["turn"]
                out["heard"] = m["text"]
            elif k == "error":
                print("ERROR", m, file=sys.stderr)
                if m.get("fatal"):
                    break
            elif k == "done":
                out["reply"] = m.get("assistant_text", "")[:120]
                out["audio"] = m.get("audio")
            elif k == "metrics":
                out["metrics"] = m
                out["client_ttfa_ms"] = round(first_audio - t0, 1) if first_audio else None
                break
    finally:
        final.set()
        padder.cancel()
    return out


async def main() -> None:
    sid = httpx.post(f"{API}/api/sessions", json={}).json()["id"]
    async with websockets.connect(f"{WS}/api/sessions/{sid}/voice", max_size=None) as ws:
        hello = json.loads(await ws.recv())
        print("hello", hello)
        results = []
        for text in UTTERANCES:
            r = await turn(ws, synth(text), text)
            results.append(r)
            print(json.dumps(r, indent=1))
            await asyncio.sleep(1.0)
        await ws.send(json.dumps({"type": "stop"}))
    tt = [
        r["metrics"]["ttfa_total_ms"] for r in results if r.get("metrics", {}).get("ttfa_total_ms")
    ]
    if tt:
        print("ttfa_total_ms", tt, "median", statistics.median(tt))


asyncio.run(main())
