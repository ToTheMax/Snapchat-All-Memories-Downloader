import asyncio
import json
from pathlib import Path
import os

from . import config
from . import args as args_module
from .memory import Memory
from .ffmpeg import check_ffmpeg
from .download import download_all
from .local_import import import_all


def load_memories(json_path: Path) -> list[Memory]:
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw_memories = data.get("Saved Media", [])

    # Single-pass: keep a pointer to last seen memory per timestamp
    last_by_key: dict[str, Memory] = {}
    memories: list[Memory] = []
    for item in raw_memories:
        memory = Memory(**item)
        # Prefer original 'Date' string when present, else snake_case, else parsed datetime string
        key = item.get("Date") or item.get("date") or str(memory.date)

        if key in last_by_key:
            prev = last_by_key[key]
            # When we see the second occurrence, bump the previous from 0 -> 1
            if prev.occurrence == 0:
                prev.occurrence = 1
            # Current is previous + 1 (v2, v3, ...)
            memory.occurrence = prev.occurrence + 1
            # Update pointer to the latest for this key
            last_by_key[key] = memory
        else:
            # First time seen: no suffix until we know there's a duplicate
            memory.occurrence = 0
            last_by_key[key] = memory

        memories.append(memory)

    print(f"Found {len(memories)} memories in {json_path.name}")
    return memories

async def main():
    json_path = args_module.setup_config()
    if json_path is None:
        return

    # Check ffmpeg availability
    if not check_ffmpeg(config.ffmpeg_path, config.overlay_mode):
        return

    memories = load_memories(json_path)
    if config.from_zips:
        await import_all(memories)
    else:
        await download_all(memories)


if __name__ == "__main__":
    asyncio.run(main())