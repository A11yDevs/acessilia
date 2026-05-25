import edge_tts
import asyncio
from pathlib import Path
from typing import Callable, Coroutine
from bot.utils.logger import logger

async def export_mp3(
    text: str,
    output_path: Path,
    voice: str = "pt-BR-ThalitaNeural",
    progress_callback: Callable[[int], Coroutine] | None = None,
) -> Path:
    """
    Gera um arquivo MP3 a partir do texto usando edge-tts com progresso real.
    Divide o texto em blocos para fornecer feedback granular.
    """
    try:
        logger.debug("Iniciando geração de áudio granular (TTS): {} -> {}", voice, output_path)
        
        # Divide o texto em blocos de aproximadamente 1500 caracteres
        # (respeitando quebras de linha para não cortar palavras)
        chunk_size = 1500
        paragraphs = text.split('\n')
        chunks = []
        current_chunk = ""
        
        for p in paragraphs:
            if len(current_chunk) + len(p) < chunk_size:
                current_chunk += p + '\n'
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = p + '\n'
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        total_chunks = len(chunks)
        completed_count = 0
        semaphore = asyncio.Semaphore(5) # Processa até 5 blocos simultaneamente

        async def process_chunk(idx, text_chunk):
            nonlocal completed_count
            async with semaphore:
                chunk_p = output_path.with_suffix(f".part{idx}.mp3")
                communicate = edge_tts.Communicate(text_chunk, voice)
                await communicate.save(chunk_p)
                
                completed_count += 1
                percent = int((completed_count / total_chunks) * 100)
                logger.info("Gerando áudio (TTS): {}/{} blocos concluídos ({}%)", completed_count, total_chunks, percent)
                
                if progress_callback:
                    await progress_callback(percent)
                return chunk_p

        # Executa todos os blocos em paralelo
        tasks = [process_chunk(i, chunk) for i, chunk in enumerate(chunks) if chunk]
        temp_files = await asyncio.gather(*tasks)
        
        # Concatena os arquivos na ordem correta (idx)
        # O gather retorna na ordem das tasks, mas vamos garantir
        with open(output_path, 'wb') as final_file:
            for temp_path in temp_files:
                with open(temp_path, 'rb') as f:
                    final_file.write(f.read())
                temp_path.unlink() # Remove arquivo temporário
        
        logger.info("Áudio (MP3) granular exportado com sucesso: {}", output_path)
        return output_path
    except Exception as e:
        logger.error("Erro ao exportar MP3 granular: {}", e)
        # Limpeza em caso de erro
        for p in output_path.parent.glob(f"{output_path.stem}.part*.mp3"):
            try: p.unlink()
            except: pass
        raise
