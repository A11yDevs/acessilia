-- Storage DDL extracted from the actual production 0.1.0 commit 535b22e9b07a99b3090e2fcfc6862299de2b5c69
CREATE TABLE IF NOT EXISTS conversoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            arquivo TEXT NOT NULL,
            extensao TEXT NOT NULL,
            tamanho_bytes INTEGER DEFAULT 0,
            modo TEXT DEFAULT 'normal',
            pipeline TEXT DEFAULT '',
            status TEXT DEFAULT 'processing',
            tempo_segundos REAL DEFAULT 0,
            erro TEXT DEFAULT '',
            resultado_resumo TEXT DEFAULT '',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluido_em TIMESTAMP
        );
CREATE TABLE IF NOT EXISTS ocr_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            fonte TEXT DEFAULT 'tesseract',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE IF NOT EXISTS ocr_revised (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            modelo TEXT DEFAULT 'qwen2.5:3b',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
CREATE TABLE IF NOT EXISTS ocr_translated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            modelo TEXT DEFAULT 'qwen2.5:1.5b',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
CREATE INDEX IF NOT EXISTS idx_ocr_raw_task ON ocr_raw(task_id);
CREATE INDEX IF NOT EXISTS idx_ocr_revised_task ON ocr_revised(task_id);
CREATE INDEX IF NOT EXISTS idx_ocr_translated_task ON ocr_translated(task_id);
CREATE TABLE IF NOT EXISTS download_tokens (
                    token TEXT PRIMARY KEY,
                    output_dir TEXT NOT NULL DEFAULT '',
                    filename TEXT NOT NULL DEFAULT '',
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    formats TEXT NULL DEFAULT '[]',
                    task_id TEXT NULL DEFAULT '',
                    owner TEXT NULL DEFAULT ''
                );
CREATE INDEX idx_download_tokens_token ON download_tokens(token);
