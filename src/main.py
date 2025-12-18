import asyncio
import json
from pathlib import Path
import os

from . import config
from . import args as args_module
from .memory import Memory
from .ffmpeg import check_ffmpeg
from .download import download_all




def load_memories(json_path: Path) -> tuple[dict, list[Memory]]:
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
    return data, memories


def _atomic_write_json(out_path: Path, data: dict):
    """Atomically write JSON to file to avoid corruption."""
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, out_path)


def save_processed_memories(json_path: Path, original_data: dict, memories: list[Memory]) -> Path:
    """Save processed memories to a new output file with '_processed' suffix."""
    # Create output filename: memories_history.json -> memories_history_processed.json
    out_path = json_path.parent / (json_path.stem + "_processed.json")
    
    # Ensure Pydantic applies json encoders (e.g., datetime -> UTC string)
    items = [m.model_dump(by_alias=True, mode="json") for m in memories]
    out_data = dict(original_data)
    out_data["Saved Media"] = items
    _atomic_write_json(out_path, out_data)
    print(f"Saved processed memories: {out_path.name}")
    return out_path


async def main():
    json_path = args_module.setup_config()
    if json_path is None:
        return

    # Check ffmpeg availability
    if not check_ffmpeg(config.ffmpeg_path, config.overlay_mode):
        return

    original_data, memories = load_memories(json_path)
    await download_all(memories)
    # Save processed memories (includes OCR if enabled, plus any other processing)
    save_processed_memories(json_path, original_data, memories)



if __name__ == "__main__":
    asyncio.run(main())
