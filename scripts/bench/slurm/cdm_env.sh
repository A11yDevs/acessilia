# Source before running the official evaluator with CDM. TeX Live and fonts
# live under $OPT (userspace install); override OPT to relocate.
export OPT=${OPT:-$WS/opt}
export PATH=$OPT/texlive/2025/bin/x86_64-linux:$OPT/bin:$PATH
export FONTCONFIG_FILE=$OPT/fontconfig/fonts.conf
export TEXMFVAR=$OPT/texlive/texmf-var
export TEXMFCONFIG=$OPT/texlive/texmf-config
export CDM_PYTHON=${CDM_PYTHON:-$WS/repos/DrDocBench/.venv/bin/python}
