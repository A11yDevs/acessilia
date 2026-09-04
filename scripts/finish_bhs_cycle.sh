#!/usr/bin/env bash
# finish_bhs_cycle.sh — Fecha o ciclo de BHS (release/x.y.z -> main + develop)
#
# Uso:
#   ./scripts/finish_bhs_cycle.sh 0.1.0            # abre os PRs de fechamento
#   ./scripts/finish_bhs_cycle.sh 0.1.0 --cleanup   # apos ambos os PRs mesclados,
#                                                     # apaga a branch e lembra os
#                                                     # passos finais (tag + staging)
#
# Pré-requisitos: GitHub CLI (`gh`) autenticado com acesso ao repositório.

set -euo pipefail

VERSION="${1:-}"
MODE="${2:-open}"
if [ -z "$VERSION" ]; then
  echo "Uso: $0 <versao> [--cleanup]   (ex: $0 0.1.0)"
  exit 1
fi

BRANCH="release/${VERSION}"
REPO="A11yDevs/acessilia"

cd "$(dirname "$0")/.."

if ! command -v gh &>/dev/null; then
  echo "[finish-bhs] ❌ GitHub CLI (gh) não encontrado."
  exit 1
fi

if [ "$MODE" = "--cleanup" ]; then
  echo "[finish-bhs] Verificando estado dos PRs de ${BRANCH}..."
  MAIN_STATE=$(gh pr list -R "$REPO" --head "$BRANCH" --base main --state all --json state --jq '.[0].state // "NONE"')
  DEVELOP_STATE=$(gh pr list -R "$REPO" --head "$BRANCH" --base develop --state all --json state --jq '.[0].state // "NONE"')

  echo "  main:    ${MAIN_STATE}"
  echo "  develop: ${DEVELOP_STATE}"

  if [ "$MAIN_STATE" != "MERGED" ] || [ "$DEVELOP_STATE" != "MERGED" ]; then
    echo "[finish-bhs] ⏳ Ainda há PR(s) pendente(s). Aguarde aprovação/merge antes de limpar."
    exit 1
  fi

  echo "[finish-bhs] ✅ Ambos os PRs mesclados. Removendo ${BRANCH}..."
  git fetch origin --quiet
  git push origin --delete "${BRANCH}" || echo "  (branch remota já removida)"
  git branch -D "${BRANCH}" 2>/dev/null || true

  echo ""
  echo "Últimos passos manuais:"
  echo "  1. Criar a tag oficial na main: git checkout main && git pull && git tag v${VERSION} && git push origin v${VERSION}"
  echo "  2. No .env do servidor de homologação, remova/reverta TRACK_BRANCH para voltar a rastrear develop."
  exit 0
fi

echo "[finish-bhs] Abrindo PRs de fechamento do BHS para ${BRANCH}..."

gh pr create -R "$REPO" \
  --head "$BRANCH" --base main \
  --title "release: ${VERSION}" \
  --body "Fecha o ciclo de BHS de \`${BRANCH}\`. Gera a release oficial \`v${VERSION}\` após o merge (ver CONTRIBUTING.md seção 6)."

gh pr create -R "$REPO" \
  --head "$BRANCH" --base develop \
  --title "chore(release): propaga fixes de ${BRANCH} para develop" \
  --body "Propaga as correções acumuladas durante o BHS de \`${BRANCH}\` para a \`develop\`."

echo ""
echo "[finish-bhs] PRs abertos. Após ambos serem revisados e mesclados, rode:"
echo "  ./scripts/finish_bhs_cycle.sh ${VERSION} --cleanup"
