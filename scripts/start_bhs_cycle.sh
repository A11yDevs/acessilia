#!/usr/bin/env bash
# start_bhs_cycle.sh — Corta a branch release/x.y.z a partir da develop (início do BHS)
#
# Uso:
#   ./scripts/start_bhs_cycle.sh 0.1.0
#
# O que este script faz:
#   1. Atualiza a develop local (git pull --ff-only)
#   2. Cria a branch release/<versao> a partir de origin/develop
#   3. Publica a branch no remoto
#   4. Imprime os próximos passos (apontar staging + rotear fix/*)
#
# Pré-requisitos: git configurado com acesso de push ao repositório.

set -euo pipefail

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  echo "Uso: $0 <versao>   (ex: $0 0.1.0)"
  exit 1
fi

BRANCH="release/${VERSION}"

cd "$(dirname "$0")/.."

echo "[start-bhs] Atualizando develop..."
git fetch origin --quiet
git checkout develop
git pull --ff-only

if git show-ref --quiet "refs/heads/${BRANCH}" || git ls-remote --exit-code --heads origin "${BRANCH}" &>/dev/null; then
  echo "[start-bhs] ❌ A branch ${BRANCH} já existe (local ou remota)."
  exit 1
fi

echo "[start-bhs] Criando ${BRANCH} a partir de origin/develop..."
git checkout -b "${BRANCH}" origin/develop
git push -u origin "${BRANCH}"

echo ""
echo "[start-bhs] ✅ Ciclo de BHS iniciado: ${BRANCH}"
echo ""
echo "Próximos passos:"
echo "  1. No servidor de homologação, defina TRACK_BRANCH=${BRANCH} no .env"
echo "     e rode ./scripts/update_scripts.sh (ou aguarde o timer) para aplicar."
echo "  2. PRs fix/* que corrigem bugs achados no staging devem mirar ${BRANCH}."
echo "  3. PRs feat/* continuam mirando develop normalmente."
echo "  4. Ao encerrar o ciclo, rode: ./scripts/finish_bhs_cycle.sh ${VERSION}"
