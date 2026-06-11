#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Teste completo do Docling (rapidocr + pytorch + pipeline)
# Uso: bash scripts/testar_docling.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/testar_docling_$(date +%Y-%m-%d_%H-%M-%S).txt"
PDF_TESTE="$SCRIPT_DIR/../tests/fixtures/tutorials/java-oo-3pgs.pdf"
PDF_TESTE="$(cd "$(dirname "$PDF_TESTE")" && pwd)/$(basename "$PDF_TESTE")"

exec > >(tee -a "$LOG_FILE") 2>&1

VERMELHO='\033[0;31m'
VERDE='\033[0;32m'
AMARELO='\033[1;33m'
AZUL='\033[0;34m'
NC='\033[0m'

passo()  { echo -e "${AZUL}[*]${NC} $1"; }
ok()     { echo -e "${VERDE}[OK]${NC} $1"; }
falha()  { echo -e "${VERMELHO}[FALHA]${NC} $1"; }
aviso()  { echo -e "${AMARELO}[AVISO]${NC} $1"; }
linha()  { echo "----------------------------------------"; }

trap 'echo -e "\n${AMARELO}[AVISO]${NC} Script interrompido. Log: $LOG_FILE"' ERR

# Ativar venv se existir
if [ -d "$SCRIPT_DIR/../venv" ]; then
    source "$SCRIPT_DIR/../venv/bin/activate"
    passo "Venv ativado: $(which python)"
fi

echo ""
passo "=== TESTE COMPLETO DOCLING ==="
echo ""

# --- 1. Verificar PDF de teste ---
passo "1. Verificando PDF de teste..."
if [ -f "$PDF_TESTE" ]; then
    ok "PDF encontrado: $PDF_TESTE"
    python -c "from pypdf import PdfReader; r=PdfReader('$PDF_TESTE'); print(f'   Paginas: {len(r.pages)}')"
else
    falha "PDF nao encontrado em: $PDF_TESTE"
    exit 1
fi
echo ""

# --- 2. Importar dependencias ---
passo "2. Importando dependencias..."
python -c "
from importlib.metadata import version, PackageNotFoundError

for pkg in ('rapidocr', 'docling', 'docling-core'):
    try:
        v = version(pkg)
    except PackageNotFoundError:
        v = '(nao instalado)'
    print(f'   {pkg}: {v}')

from docling.document_converter import DocumentConverter
print(f'   converter: {DocumentConverter.__module__}')
" 2>&1 && ok "Dependencias OK" || {
    falha "Falha na importacao"
    exit 1
}
echo ""

# --- 3. Inicializar DocumentConverter ---
passo "3. Inicializando DocumentConverter..."
START=$(date +%s%3N)
python -c "
import time
from docling.document_converter import DocumentConverter
t0 = time.time()
converter = DocumentConverter()
t1 = time.time()
print(f'   Inicializado em {t1-t0:.2f}s')
print(f'   Tipo: {type(converter).__name__}')
" 2>&1 && ok "Converter inicializado" || {
    falha "Falha ao inicializar DocumentConverter"
    echo ""
    passo "--- LOG COMPLETO DO ERRO (para debug) ---"
    python -c "
import traceback, sys
try:
    from docling.document_converter import DocumentConverter
    c = DocumentConverter()
except Exception:
    traceback.print_exc()
    sys.exit(1)
" 2>&1 || true
    echo "--- FIM DO LOG DE ERRO ---"
}
echo ""

# --- 4. Converter PDF ---
passo "4. Convertendo PDF com Docling..."
echo "   PDF: $(basename "$PDF_TESTE")"
python -c "
import time, sys
from docling.document_converter import DocumentConverter

t0 = time.time()
converter = DocumentConverter()
result = converter.convert('$PDF_TESTE')
doc = result.document
t1 = time.time()

print(f'   Tempo total: {t1-t0:.2f}s')

# Examinar estrutura
from collections import Counter

# Items totais
items = [item for item, level in doc.iterate_items()]
print(f'   Items totais: {len(items)}')
print()

# Funcao auxiliar inline
def _dt(item):
    text = getattr(item, 'text', '') or getattr(item, 'caption', '') or ''
    if not text:
        for attr in ('markdown', 'raw_text', 'content'):
            val = getattr(item, attr, None)
            if val:
                text = str(val)
                break
    return str(text).strip() or '(sem texto)'

# Paginas
try:
    if hasattr(doc, 'pages') and isinstance(doc.pages, dict):
        print(f'   Paginas: {len(doc.pages)} (dict)')
        page_numbers = sorted(doc.pages.keys())
    else:
        page_nums = set()
        for item in items:
            for prov in getattr(item, 'prov', []) or []:
                pno = getattr(prov, 'page_no', None) or getattr(prov, 'page_number', None)
                if pno is not None:
                    page_nums.add(pno)
        page_numbers = sorted(page_nums)
        print(f'   Paginas detectadas: {len(page_numbers)} (via prov)')
except Exception as e:
    page_numbers = []
    print(f'   Paginas: erro -> {e}')
print()

# Labels dos items
try:
    labels = Counter()
    for item in items:
        label = str(getattr(item, 'label', '?'))
        labels[label] += 1
    print(f'   Distribuicao por label:')
    for label, count in labels.most_common():
        print(f'     {label}: {count}')
except Exception as e:
    print(f'   Labels: erro -> {e}')
print()

# Amostra por pagina
try:
    for pno in page_numbers[:3]:
        page_items = []
        for item in items:
            for prov in getattr(item, 'prov', []) or []:
                pn = getattr(prov, 'page_no', None) or getattr(prov, 'page_number', None)
                if pn == pno:
                    page_items.append(item)
                    break
        print(f'   Pagina {pno}: {len(page_items)} items')
        for item in page_items[:3]:
            texto = _dt(item)
            label = str(getattr(item, 'label', '?'))
            print(f'       [{label}] {texto[:60]}')
        if len(page_items) > 3:
            print(f'       ... e mais {len(page_items)-3} items')
except Exception as e:
    print(f'   Amostra por pagina: erro -> {e}')
print()

# Verificar marcadores semanticos
print(f'   Marcadores semanticos disponiveis:')
try:
    from docling_core.types.doc.labels import DocItemLabel
    for lbl in DocItemLabel:
        print(f'     .{lbl.value}')
except ImportError:
    print('     (docling_core.labels nao disponivel)')
" 2>&1 && ok "Conversao Docling OK" || {
    falha "Falha na conversao com Docling"
    echo "ERRO DETALHADO:"
    python -c "
import traceback, sys
from docling.document_converter import DocumentConverter
try:
    c = DocumentConverter()
    r = c.convert('$PDF_TESTE')
except Exception:
    traceback.print_exc()
" 2>&1 || true
}
echo ""

# --- 5. Testar fallback PyMuPDF ---
linha
passo "5. Testando fallback PyMuPDF (mesmo PDF)"
linha
python -c "
import time, sys
t0 = time.time()
import fitz
doc = fitz.open('$PDF_TESTE')
print(f'   PyMuPDF abriu: {len(doc)} paginas')
for i, page in enumerate(doc):
    texto = page.get_text()[:100].replace(chr(10), ' ')
    print(f'     Pagina {i+1}: {len(page.get_text())} chars | \"{texto}...\"')
    if i >= 2:
        break
t1 = time.time()
print(f'   Tempo: {t1-t0:.2f}s')
" 2>&1 && ok "PyMuPDF OK (fallback funcional)" || aviso "PyMuPDF falhou"
echo ""

# --- 6. Mostrar estrutura do rapidocr ---
passo "6. Estado do rapidocr (arquivos-chave)..."
python -c "
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent

checks = [
    ('inference_engine/pytorch/torch.py', p / 'inference_engine' / 'pytorch' / 'torch.py'),
    ('inference_engine/pytorch/networks/arch_config.yaml', p / 'inference_engine' / 'pytorch' / 'networks' / 'arch_config.yaml'),
    ('inference_engine/pytorch/', p / 'inference_engine' / 'pytorch'),
    ('models/', p / 'models'),
    ('default_models.yaml', p / 'default_models.yaml'),
    ('config.yaml', p / 'config.yaml'),
]
for nome, caminho in checks:
    existe = caminho.exists()
    status = 'EXISTE' if existe else 'AUSENTE'
    print(f'   {status} - {nome}')
" 2>&1
echo ""

# --- 7. Resumo final ---
linha
passo "=== RESUMO ==="
echo ""
echo "  PDF usado:     $(basename "$PDF_TESTE")"
echo "  Log salvo em:  $LOG_FILE"
echo ""

# Verificar se teve sucesso
if grep -q "Conversao Docling OK" "$LOG_FILE" 2>/dev/null; then
    ok "DOCLING FUNCIONANDO!"
elif grep -q "Falha na conversao" "$LOG_FILE" 2>/dev/null; then
    falha "DOCLING FALHOU"
    aviso "O fallback PyMuPDF esta disponivel (testado acima)"
fi

passo "=== TESTE CONCLUIDO ==="
