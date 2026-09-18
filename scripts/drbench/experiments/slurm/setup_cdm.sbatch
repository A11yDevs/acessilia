#!/bin/bash
#SBATCH --job-name=drb-setup-cdm
#SBATCH --partition=h100n2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:00:00
#SBATCH --output=/raid/user_marcospaulo/drdocbench/runs/slurm/logs/%x_%j.log
# Userspace install of everything the DrDocBench CDM metric shells out to:
# xelatex (TeX Live scheme-small + xeCJK), node (KaTeX tokenizer), `magick` shim over IM6 `convert`,
# Source Han Sans SC font. Everything under /raid/user_marcospaulo/opt. Reentrant.
set -uo pipefail
source /raid/user_marcospaulo/drdocbench/runs/slurm/env.sh
OPT=/raid/user_marcospaulo/opt
SRC=$OPT/src
mkdir -p "$OPT/bin" "$SRC" "$OPT/fonts" "$OPT/fontconfig/cache"
cd "$SRC"
step() { echo; echo "===== [$(date -u +%H:%M:%S)] $*"; }

# 1. node (portable)
step "node"
NODE_VER=v20.18.0
if [[ ! -x $OPT/node/bin/node ]]; then
  wget -q "https://nodejs.org/dist/$NODE_VER/node-$NODE_VER-linux-x64.tar.xz" -O node.tar.xz
  mkdir -p "$OPT/node" && tar -xJf node.tar.xz -C "$OPT/node" --strip-components=1 && rm node.tar.xz
fi
ln -sf "$OPT/node/bin/node" "$OPT/bin/node"
"$OPT/bin/node" -v

# 2. TeX Live (scheme-small, no docs/src) + packages used by the CDM templates
step "texlive"
TEXDIR=$OPT/texlive/2025
if [[ ! -x $TEXDIR/bin/x86_64-linux/xelatex ]]; then
  for m in https://mirror.ctan.org/systems/texlive/tlnet https://ctan.org/tex-archive/systems/texlive/tlnet https://mirrors.mit.edu/CTAN/systems/texlive/tlnet; do
    wget -q --tries=3 --timeout=60 "$m/install-tl-unx.tar.gz" -O install-tl-unx.tar.gz && [[ -s install-tl-unx.tar.gz ]] && { REPO=$m; break; }
  done
  [[ -s install-tl-unx.tar.gz ]] || { echo "install-tl download failed"; exit 1; }
  rm -rf install-tl-2* && tar -xzf install-tl-unx.tar.gz
  cat > texlive.profile <<EOF
selected_scheme scheme-small
TEXDIR $TEXDIR
TEXMFCONFIG $OPT/texlive/texmf-config
TEXMFVAR $OPT/texlive/texmf-var
TEXMFHOME $OPT/texlive/texmf-home
TEXMFLOCAL $OPT/texlive/texmf-local
TEXMFSYSCONFIG $OPT/texlive/texmf-config
TEXMFSYSVAR $OPT/texlive/texmf-var
instopt_adjustpath 0
instopt_letter 0
tlpdbopt_autobackup 0
tlpdbopt_install_docfiles 0
tlpdbopt_install_srcfiles 0
EOF
  ./install-tl-2*/install-tl --profile=texlive.profile --no-interaction --repository "$REPO"
fi
export PATH=$TEXDIR/bin/x86_64-linux:$PATH
tlmgr install was multirow booktabs xecjk geometry xcolor amsmath upgreek fontspec ctex zhnumber 2>&1 | tail -3
xelatex --version | head -1

# 3. Font: Source Han Sans SC (Regular) + fontconfig on /raid
step "font"
if [[ ! -f $OPT/fonts/SourceHanSansSC-Regular.otf ]]; then
  wget -q "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/SimplifiedChinese/SourceHanSansSC-Regular.otf" \
       -O "$OPT/fonts/SourceHanSansSC-Regular.otf"
fi
cat > "$OPT/fontconfig/fonts.conf" <<EOF
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <dir>$OPT/fonts</dir>
  <cachedir>$OPT/fontconfig/cache</cachedir>
</fontconfig>
EOF
export FONTCONFIG_FILE=$OPT/fontconfig/fonts.conf
fc-cache -f "$OPT/fonts" >/dev/null 2>&1 || true
fc-list | grep -i "source han sans" | head -2

# 4. magick shim -> IM6 convert (policy permitting) with a PyMuPDF fallback
step "magick shim"
cat > "$OPT/bin/magick" <<'EOF'
#!/bin/bash
# CDM calls: magick -density 200 -quality 100 in.pdf out.png
if convert "$@" 2>/dev/null; then exit 0; fi
pdf="${@: -2:1}"; png="${@: -1}"
exec "${CDM_PYTHON:-python3}" - "$pdf" "$png" <<'PY'
import sys, fitz
doc = fitz.open(sys.argv[1]); pix = doc[0].get_pixmap(dpi=200); pix.save(sys.argv[2])
PY
EOF
chmod +x "$OPT/bin/magick"

# 5. Python deps in the evaluator venv
step "python deps"
DRB=$WS/repos/DrDocBench/.venv/bin/python
# skimage>=0.23 renamed ransac(random_state)->rng and breaks CDM matching silently -> pin 0.22
uv pip install --python "$DRB" tqdm matplotlib "scikit-image==0.22.0" pymupdf 2>&1 | tail -1

# 6. env file for jobs that need CDM
cat > "$WS/runs/slurm/cdm_env.sh" <<EOF
export PATH=$TEXDIR/bin/x86_64-linux:$OPT/bin:\$PATH
export FONTCONFIG_FILE=$OPT/fontconfig/fonts.conf
export TEXMFVAR=$OPT/texlive/texmf-var
export TEXMFCONFIG=$OPT/texlive/texmf-config
export CDM_PYTHON=$DRB
EOF

# 7. smoke test: xelatex template -> pdf -> png -> CDM score on a trivial pair
step "smoke"
source "$WS/runs/slurm/cdm_env.sh"
T=$(mktemp -d -p /raid/user_marcospaulo/cache)
cat > "$T/t.tex" <<'EOF'
\documentclass[12pt]{article}
\usepackage[landscape]{geometry}\geometry{a5paper,scale=0.98}\pagestyle{empty}
\usepackage{amsmath}\usepackage{upgreek}\usepackage{amssymb}\usepackage{xcolor}\usepackage{xeCJK}
\setCJKmainfont{Source Han Sans SC}
\begin{document}\begin{displaymath}\textcolor[RGB]{255,0,0}{x}^2+\upalpha=\frac{1}{2}\end{displaymath}\end{document}
EOF
(cd "$T" && xelatex -interaction=nonstopmode t.tex >/dev/null 2>&1; ls -la t.pdf && magick -density 200 -quality 100 t.pdf t.png && ls -la t.png)
cd "$WS/repos/DrDocBench" && "$DRB" - <<'EOF'
import sys, os, tempfile
sys.path.insert(0, ".")
from metrics.cdm_metric import CDM
out = tempfile.mkdtemp(prefix="cdm_", dir="/raid/user_marcospaulo/cache")
c = CDM(output_root=out)
r1 = c.evaluate(r"\frac{a}{b} + c^2", r"\frac{a}{b} + c^2", "smoke1")
r2 = c.evaluate(r"\frac{a}{b} + c^2", r"\frac{a}{b} + d^3", "smoke2")
print("CDM identical:", r1["F1_score"], "| CDM different:", r2["F1_score"])
EOF
rm -rf "$T"
echo "[$(date -u +%H:%M:%S)] CDM_SETUP_DONE"
