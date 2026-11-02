"""Acessilia SDK: uniform access to Acessilia capabilities.

The SDK sits between the core and the services it uses. It depends on the
Toolbox only through its published HTTP contract and never imports the core
(``backend``) or the Toolbox package (``acessilia_toolbox``).
"""

__version__ = "0.1.0"
