#!/usr/bin/env python3

import sqlite3

DB_PATH = "C:\\Users\\JHONATA\\bot-acess\\data\\history.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("ALTER TABLE download_tokens ADD COLUMN formats TEXT DEFAULT '[]'")
conn.commit()
print("Coluna 'formats' adicionada com sucesso!")