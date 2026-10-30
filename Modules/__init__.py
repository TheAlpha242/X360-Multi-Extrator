"""
Pacote Modules do X360 Multi Extrator.
Centraliza a interface gráfica (GUI), motores nativos de extração e suporte multi-idioma (i18n).
"""

from pathlib import Path
from .gui import X360MultiExtratorGUI
from .xex_extractor import XEXExtractor
from .god_extractor import GODExtractor
from .extractor import XboxBatchExtractor
from .i18n import lang_manager

__version__ = "2.1.0"
__app_name__ = "X360 Multi Extrator"

MODULES_DIR = Path(__file__).resolve().parent

__all__ = [
    "X360MultiExtratorGUI",
    "XboxBatchExtractor",
    "XEXExtractor",
    "GODExtractor",
    "lang_manager",
    "MODULES_DIR",
]