#!/usr/bin/env bash
# setup-rulesets.sh — Aplica ou atualiza rulesets do GitHub via API REST.
#
# Uso:
#   ./scripts/setup-rulesets.sh              # Aplica/atualiza rulesets
#   DRY_RUN=1 ./scripts/setup-rulesets.sh     # Apenas mostra o payload sem enviar
#
# Pré-requisitos:
#   - gh (GitHub CLI) autenticado com escopo 'repo' e 'admin:org' (se organizacional)
#   - jq instalado
#
# Arquivos de definição:
#   .github/rulesets/*.json.example  — modelos de rulesets (renameie para .json)

set -euo pipefail
cd "$(dirname "$0")/.."

DRY_RUN="${DRY_RUN:-0}"

REPO="A11yDevs/acessilia"
RULESETS_DIR=".github/rulesets"

if ! command -v jq &>/dev/null; then
  echo "❌ jq é necessário. Instale com: brew install jq"
  exit 1
fi

if ! gh auth status &>/dev/null; then
  echo "❌ gh CLI não autenticada. Execute: gh auth login"
  exit 1
fi

apply_ruleset() {
  local file="$1"
  local name
  name="$(jq -r '.name' "$file")"

  if [[ -z "$name" || "$name" == "null" ]]; then
    echo "  ⚠️  Pulando '$file' — sem campo 'name' válido."
    return
  fi

  echo "  → Ruleset: $name"

  # Verifica se já existe um ruleset com este nome
  local existing_id
  existing_id=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$name\") | .id" 2>/dev/null || true)

  local payload
  payload="$(jq '{name, target, enforcement, bypass_actors, conditions, rules}' "$file")"

  # O unique_by mantém a primeira entrada: o bypass do template, e seu
  # bypass_mode, prevalece; o bypass admin só é adicionado quando falta.
  payload="$(echo "$payload" | jq -f scripts/rulesets-bypass.jq)"

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "    [DRY RUN] Payload para $( [[ -n "$existing_id" ]] && echo 'UPDATE' || echo 'CREATE' ):"
    echo "$payload" | jq '.'
    return
  fi

  if [[ -n "$existing_id" ]]; then
    echo "    Atualizando ruleset existente (id=$existing_id)..."
    gh api --method PUT "repos/$REPO/rulesets/$existing_id" \
      --input <(echo "$payload") --jq '{id, name, enforcement}' 2>&1
  else
    echo "    Criando novo ruleset..."
    gh api --method POST "repos/$REPO/rulesets" \
      --input <(echo "$payload") --jq '{id, name, enforcement}' 2>&1
  fi
}

echo "🔧 Aplicando rulesets do diretório $RULESETS_DIR..."

if [[ ! -d "$RULESETS_DIR" ]]; then
  echo "  Diretório $RULESETS_DIR não encontrado."
  exit 0
fi

shopt -s nullglob
for file in "$RULESETS_DIR"/*.json; do
  apply_ruleset "$file"
done

for file in "$RULESETS_DIR"/*.json.example; do
  echo ""
  echo "📄 Modelo encontrado: $file"
  echo "  (renomeie para .json e execute novamente para aplicar)"
done

echo ""
echo "✅ Concluído."