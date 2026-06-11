#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Corrige arch_config.yaml do RapidOCR (adiciona model_type faltante)
# Uso: bash scripts/corrigir_rapidocr.sh
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/corrigir_rapidocr_$(date +%Y-%m-%d_%H-%M-%S).txt"

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

if [ -d "$SCRIPT_DIR/../venv" ]; then
    source "$SCRIPT_DIR/../venv/bin/activate"
fi

echo ""
passo "=== CORRECAO DO ARCH_CONFIG.YAML ==="
echo ""

# --- 1. Localizar pacote rapidocr ---
passo "1. Localizando rapidocr..."
RAPIDOCR_DIR=$(python -c "
import rapidocr, os
print(os.path.dirname(rapidocr.__file__))
" 2>/dev/null) || {
    falha "rapidocr nao instalado"
    exit 1
}
ok "rapidocr em: $RAPIDOCR_DIR"
echo ""

# --- 2. Listar modelos .pth ---
passo "2. Modelos .pth disponiveis:"
MODELOS=()
while IFS= read -r f; do
    name=$(basename "$f" .pth)
    MODELOS+=("$name")
    echo "   $name"
done < <(find "$RAPIDOCR_DIR/models" -name '*.pth' 2>/dev/null | sort)

if [ ${#MODELOS[@]} -eq 0 ]; then
    falha "Nenhum modelo .pth encontrado em $RAPIDOCR_DIR/models/"
    echo "   Baixando modelos..."
    python -c "
from rapidocr.main import RapidOCR
r = RapidOCR()
" 2>&1 || true
    # Tentar de novo
    while IFS= read -r f; do
        name=$(basename "$f" .pth)
        MODELOS+=("$name")
        echo "   $name"
    done < <(find "$RAPIDOCR_DIR/models" -name '*.pth' 2>/dev/null | sort)
fi
echo ""

# --- 3. Determinar model_type para cada modelo ---
passo "3. Montando arch_config.yaml..."
ARCH_YAML="$RAPIDOCR_DIR/inference_engine/pytorch/networks/arch_config.yaml"
BACKUP="${ARCH_YAML}.bak.$(date +%Y%m%d_%H%M%S)"

if [ -f "$ARCH_YAML" ]; then
    cp "$ARCH_YAML" "$BACKUP"
    ok "Backup salvo: $BACKUP"
fi

cat > "$ARCH_YAML" << 'YAML'
# Gerado automaticamente por corrigir_rapidocr.sh
YAML

for modelo in "${MODELOS[@]}"; do
    # Determinar model_type baseado no nome
    case "$modelo" in
        *det*|*Det*|*DET*)
            MT="det"
            SHAPE="[1, 3, 736, 1280]"
            ;;
        *rec*|*Rec*|*REC*)
            MT="rec"
            SHAPE="[1, 3, 48, 320]"
            ;;
        *cls*|*Cls*|*CLS*)
            MT="cls"
            SHAPE="[1, 3, 48, 192]"
            ;;
        *)
            aviso "   Modelo '$modelo': tipo nao reconhecido, usando 'det'"
            MT="det"
            SHAPE="[1, 3, 736, 1280]"
            ;;
    esac

    cat >> "$ARCH_YAML" << YAML

${modelo}:
  model_type: ${MT}
  fp16: false
  max_batch_size: 1
  input_shape: ${SHAPE}
YAML
    echo "   ${modelo} -> model_type: ${MT}"
done

echo ""
ok "Arquivo gerado: $ARCH_YAML"
echo ""

# --- 4. Validar sintaxe YAML ---
passo "4. Validando arch_config.yaml..."
python -c "
from omegaconf import OmegaConf
cfg = OmegaConf.load('$ARCH_YAML')
for key, val in cfg.items():
    mt = val.get('model_type', 'AUSENTE')
    print(f'   {key}: model_type={mt}')
" 2>&1 && ok "Sintaxe valida!" || {
    falha "Erro de sintaxe no YAML"
    exit 1
}
echo ""

# --- 5. Testar inicializacao do RapidOCR com pytorch ---
passo "5. Testando RapidOCR com pytorch..."
python -c "
import time
t0 = time.time()
from rapidocr import RapidOCR
ocr = RapidOCR()
t1 = time.time()
print(f'   Inicializado em {t1-t0:.2f}s')
print(f'   Engine: pytorch')
" 2>&1 && ok "RapidOCR funcionando!" || {
    falha "RapidOCR ainda falha"
    echo "   Detalhes:"
    python -c "
import traceback, sys
try:
    from rapidocr import RapidOCR
    r = RapidOCR()
except Exception:
    traceback.print_exc()
" 2>&1 || true
}
echo ""

# --- 6. Mostrar estrutura final ---
linha
echo ""
passo "=== RESUMO ==="
echo ""
echo "  Arquivo: $ARCH_YAML"
echo "  Backup:  $BACKUP"
echo "  Modelos: ${#MODELOS[@]} configurados"
echo "  Log:     $LOG_FILE"
echo ""

if grep -q "RapidOCR funcionando" "$LOG_FILE" 2>/dev/null; then
    ok "RAPIDOCR CORRIGIDO!"
    aviso "Execute 'bash scripts/testar_docling.sh' para testar Docling completo"
else
    falha "CORRECAO INCOMPLETA"
fi

passo "=== FIM ==="
