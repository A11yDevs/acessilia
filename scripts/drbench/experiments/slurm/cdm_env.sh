# Source before running the official CDM metric. Everything lives under $OPT
# (userspace install by setup_cdm.sbatch); override OPT to relocate.
export OPT=${OPT:-/raid/user_marcospaulo/opt}
export PATH=$OPT/texlive/2025/bin/x86_64-linux:$OPT/bin:$PATH
export FONTCONFIG_FILE=$OPT/fontconfig/fonts.conf
export TEXMFVAR=$OPT/texlive/texmf-var
export TEXMFCONFIG=$OPT/texlive/texmf-config
export CDM_PYTHON=${CDM_PYTHON:-${WS:-/raid/user_marcospaulo/drdocbench}/repos/DrDocBench/.venv/bin/python}
