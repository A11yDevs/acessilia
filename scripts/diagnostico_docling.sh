#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Diagnostico e correcao do RapidOCR + Docling
# Uso: bash scripts/diagnostico_docling.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR"
LOG_FILE="$LOG_DIR/diagnostico_docling_$(date +%Y-%m-%d_%H-%M-%S).txt"
mkdir -p "$LOG_DIR"

# Redireciona toda a saida (stdout + stderr) para o console E para o arquivo
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

# Ativar venv se existir
if [ -d "venv" ]; then
    source venv/bin/activate
    passo "Venv ativado: $(which python)"
fi

echo ""
passo "=== DIAGNOSTICO RAPIDOCR + DOCLING ==="
echo ""

# 1. Versoes instaladas
passo "1. Verificando versoes..."
python -c "
import rapidocr; print(f'   rapidocr: {rapidocr.__version__}')
" 2>/dev/null && ok "rapidocr encontrado" || aviso "rapidocr nao instalado"

python -c "
import docling; print(f'   docling: {docling.__version__}')
" 2>/dev/null && ok "docling encontrado" || aviso "docling nao instalado"

echo ""

# 2. Estrutura do rapidocr
passo "2. Verificando estrutura de arquivos do rapidocr..."
python -c "
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent

# Caminhos importantes
caminhos = {
    'inference_engine/': p / 'inference_engine',
    'inference_engine/pytorch/': p / 'inference_engine' / 'pytorch',
    'inference_engine/pytorch/networks/arch_config.yaml': p / 'inference_engine' / 'pytorch' / 'networks' / 'arch_config.yaml',
    'inference_engine/pytorch/torch.py': p / 'inference_engine' / 'pytorch' / 'torch.py',
    'models/': p / 'models',
    'default_models.yaml': p / 'default_models.yaml',
    'config.yaml': p / 'config.yaml',
}

for nome, caminho in caminhos.items():
    existe = caminho.exists()
    status = 'EXISTE' if existe else 'AUSENTE'
    cor = '\\033[0;32m' if existe else '\\033[0;31m'
    print(f'   {cor}{status}\\033[0m {nome}')
" 2>&1

echo ""

# 3. Teste de importacao do RapidOCR
passo "3. Testando importacao do RapidOCR..."
python -c "
from rapidocr import RapidOCR
print('   Import OK')
" 2>&1 && ok "RapidOCR importa sem erro" || falha "RapidOCR falha ao importar"

# 4. Teste de inicializacao do Docling converter
passo "4. Testando inicializacao do Docling DocumentConverter..."
python -c "
from docling.document_converter import DocumentConverter
print('   Import OK')
" 2>&1 && ok "DocumentConverter importa" || falha "DocumentConverter falha"

echo ""

# 5. Verificar se pytorch esta instalado (necessario para engine pytorch)
passo "5. Verificando pytorch (necessario para engine pytorch do rapidocr)..."
python -c "
try:
    import torch
    print(f'   pytorch {torch.__version__}')
except ImportError:
    print('   pytorch NAO INSTALADO')
" 2>&1

echo ""

# --- CORRECOES ---
echo "========================================"
passo "CORRECOES DISPONIVEIS"
echo "========================================"
echo ""

# Se o arquivo arch_config.yaml nao existe, podemos criar um minimal
python -c "
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent
target = p / 'inference_engine' / 'pytorch' / 'networks' / 'arch_config.yaml'

if not target.exists():
    print('   arch_config.yaml AUSENTE - precisa criar')
    print('   Solucao 1: pip install --force-reinstall rapidocr')
    print('   Solucao 2: criar manualmente o arquivo')
else:
    print('   arch_config.yaml OK')
" 2>&1

echo ""
echo "Para corrigir, escolha uma opcao:"
echo "  1) Reinstalar rapidocr (recomendado)"
echo "  2) Criar arch_config.yaml manualmente"
echo "  3) Sair sem corrigir"
echo ""

read -rp "Opcao [1-3]: " opcao

case "$opcao" in
    1)
        passo "Reinstalando rapidocr..."
        pip install --force-reinstall rapidocr 2>&1 | tail -5
        echo ""
        passo "Verificando se o problema foi resolvido..."
        python -c "
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent
target = p / 'inference_engine' / 'pytorch' / 'networks' / 'arch_config.yaml'

if target.exists():
    print('   arch_config.yaml AGORA EXISTE!')
else:
    print('   arch_config.yaml continua ausente.')
    print('   Tente a opcao 2 (criar manualmente).')
" 2>&1
        ;;
    2)
        passo "Criando arch_config.yaml manualmente..."
        python -c "
import rapidocr
from pathlib import Path
p = Path(rapidocr.__file__).parent
target_dir = p / 'inference_engine' / 'pytorch' / 'networks'
target_dir.mkdir(parents=True, exist_ok=True)

# arch_config.yaml minimal para rapidocr 3.8+
config = '''ch_PP-OCRv4_det_mobile:
  fp16: false
  max_batch_size: 1
  input_shape: [1, 3, 736, 1280]

ch_PP-OCRv4_rec_mobile:
  fp16: false
  max_batch_size: 1
  input_shape: [1, 3, 48, 320]

ch_ppocr_mobile_v2.0_cls_mobile:
  fp16: false
  max_batch_size: 1
  input_shape: [1, 3, 48, 192]
'''

target = target_dir / 'arch_config.yaml'
target.write_text(config)
print(f'   Criado: {target}')
print(f'   {config}')
" 2>&1

        # Testar se o Docling agora funciona
        echo ""
        passo "Testando Docling apos correcao..."
        python -c "
from docling.document_converter import DocumentConverter
converter = DocumentConverter()
print('   DocumentConverter inicializou sem erro!')
" 2>&1 && ok "Docling funcionando!" || falha "Docling ainda falha"
        ;;
    3)
        aviso "Nenhuma correcao aplicada."
        exit 0
        ;;
esac

echo ""
passo "=== DIAGNOSTICO CONCLUIDO ==="
passo "Relatorio salvo em: $LOG_FILE"
