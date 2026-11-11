"""``python -m acessilia_sdk``: see :mod:`acessilia_sdk.cli`."""

from acessilia_sdk.cli import main

# Guarded so that importing every module (tests/test_purity.py) runs nothing.
if __name__ == "__main__":
    raise SystemExit(main())
