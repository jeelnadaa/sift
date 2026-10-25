"""Narration: one clip per line with word timings (for the captions), Andrew neural voice."""
import asyncio
import json
import subprocess
import sys

import edge_tts

VOICE = "en-US-AndrewMultilingualNeural"
LINES = [
    ("hook", "Your inbox is loud. One email actually matters."),
    ("reveal", "Sift finds it, and buzzes your phone the second it lands."),
    ("rules", "Your rules run first. Bank noise stays quiet. Fraud alerts still get through."),
    ("timeline", "Placement mail lands on one timeline per company, filed into its own folder, automatically."),
    ("live", "Read it on your phone, it's read everywhere. Reply, schedule, undo."),
    ("outro", "Your own AI key. Your own server. Stop digging. Start sifting."),
]


async def one(key: str, text: str) -> dict:
    com = edge_tts.Communicate(text, VOICE, rate="+4%", pitch="-2Hz", boundary="WordBoundary")
    words, audio = [], bytearray()
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
        elif chunk["type"] == "WordBoundary":
            words.append({"w": chunk["text"], "t": chunk["offset"] / 1e7, "d": chunk["duration"] / 1e7})
    mp3 = f"vo_{key}.mp3"
    open(mp3, "wb").write(audio)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ar", "48000", "-ac", "1", f"vo_{key}.wav"], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f"vo_{key}.wav"],
                               capture_output=True, text=True).stdout)
    return {"key": key, "text": text, "words": words, "duration": dur}


async def main():
    out = [await one(k, t) for k, t in LINES]
    json.dump(out, open("narration.json", "w"), indent=1)
    for o in out:
        print(f'{o["key"]:9} {o["duration"]:.2f}s  {len(o["words"])} words')
    print("total", round(sum(o["duration"] for o in out), 2))


asyncio.run(main())
