import asyncio
from pathlib import Path
from typing import Callable, Coroutine

import edge_tts

from backend.i18n import t
from backend.log_messages import (
    LOG_AUDIO_EXPORTED,
    LOG_AUDIO_EXPORT_ERROR,
    LOG_AUDIO_EXPORT_PROGRESS,
    LOG_AUDIO_EXPORT_START,
)
from backend.tools.logger import logger


async def export_mp3(
    text: str,
    output_path: Path,
    voice: str = "pt-BR-ThalitaNeural",
    progress_callback: Callable[[int], Coroutine] | None = None,
) -> Path:
    """Generate a granular MP3 audio description of ``text`` through edge-tts.

    Args:
        text (str): Full plain-text content to convert into spoken audio; empty lines delimit the TTS chunks.
        output_path (Path): Destination file path for the assembled MP3 result.
        voice (str): edge-tts neural voice name used for synthesis (default "pt-BR-ThalitaNeural").
        progress_callback (Callable[[int], Coroutine] | None): Optional async callback receiving the completed-chunk percentage after each chunk finishes (default None).

    Returns:
        Path: The output file path once the complete MP3 is assembled.
    """
    try:
        logger.debug(
            t(LOG_AUDIO_EXPORT_START).format(
                voice=voice, path=output_path
            )
        )

        chunk_size = 1500
        paragraphs = text.split("\n")
        chunks = []
        current_chunk = ""

        for p in paragraphs:
            if len(current_chunk) + len(p) < chunk_size:
                current_chunk += p + "\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + "\n"
        if current_chunk:
            chunks.append(current_chunk.strip())

        total_chunks = len(chunks)
        completed_count = 0
        semaphore = asyncio.Semaphore(5)

        async def process_chunk(idx, text_chunk):
            nonlocal completed_count
            async with semaphore:
                chunk_p = output_path.with_suffix(f".part{idx}.mp3")
                communicate = edge_tts.Communicate(text_chunk, voice)
                await communicate.save(str(chunk_p))

                completed_count += 1
                percent = int((completed_count / total_chunks) * 100)
                logger.info(
                    t(LOG_AUDIO_EXPORT_PROGRESS).format(
                        completed=completed_count, total=total_chunks, percent=percent
                    )
                )

                if progress_callback:
                    await progress_callback(percent)
                return chunk_p

        tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks) if chunk]
        temp_files = await asyncio.gather(*tasks)

        with open(output_path, "wb") as final_file:
            for temp_path in temp_files:
                with open(temp_path, "rb") as f:
                    final_file.write(f.read())
                temp_path.unlink()

        logger.info(t(LOG_AUDIO_EXPORTED).format(path=output_path))
        return output_path
    except Exception as e:
        logger.error(t(LOG_AUDIO_EXPORT_ERROR).format(error=e))
        for p in output_path.parent.glob(f"{output_path.stem}.part*.mp3"):
            try:
                p.unlink()
            except Exception:
                pass
        raise
