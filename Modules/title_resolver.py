import json
import re
import struct
from pathlib import Path


class TitleResolver:
    """
    Resolvedor de Title IDs para nomes comerciais de jogos de Xbox 360.
    Suporta parsing nativo de cabeçalhos XEX2 e contêineres STFS/GOD.
    """
    def __init__(self, json_path: Path = None):
        base_dir = Path(__file__).resolve().parent
        self.json_path = json_path or (base_dir / "title_id.json")
        self.database = {}
        self._load_database()

    def _load_database(self):
        if not self.json_path.exists():
            return

        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)

            if isinstance(raw_data, list):
                for item in raw_data:
                    tid = item.get("titleid") or item.get("title_id")
                    title = item.get("title")
                    if tid and title:
                        self.database[str(tid).strip().upper()] = str(title).strip()
            elif isinstance(raw_data, dict):
                for k, v in raw_data.items():
                    self.database[str(k).strip().upper()] = str(v).strip()
        except Exception:
            self.database = {}

    def sanitize_filename(self, name: str) -> str:
        """Substitui caracteres inválidos no Windows mantendo a legibilidade."""
        name = name.replace(":", " - ")
        for ch in '<>"/\\|?*^':
            name = name.replace(ch, "")
        return " ".join(name.split()).strip(". ")

    def get_game_name(self, title_id: str, fallback: str = "") -> str:
        if not title_id:
            return fallback
        tid = title_id.strip().upper()
        if tid in self.database:
            return self.sanitize_filename(self.database[tid])
        return fallback

    def extract_title_id_from_xex(self, xex_path: Path) -> str:
        """Lê o cabeçalho XEX2 e extrai o Title ID da estrutura Execution Info."""
        try:
            if not xex_path.is_file():
                return ""

            with open(xex_path, "rb") as f:
                magic = f.read(4)
                if magic not in (b"XEX2", b"XEX1", b"XEX%"):
                    return ""

                # Número de cabeçalhos opcionais fica no offset 0x14
                f.seek(0x14)
                opt_count_data = f.read(4)
                if len(opt_count_data) < 4:
                    return ""
                opt_count = struct.unpack(">I", opt_count_data)[0]

                # A tabela de cabeçalhos opcionais inicia em 0x18 (cada entrada tem 8 bytes)
                f.seek(0x18)
                for _ in range(min(opt_count, 128)):
                    entry = f.read(8)
                    if len(entry) < 8:
                        break
                    key, val = struct.unpack(">II", entry)

                    # 0x00040006 = XEX_HEADER_EXECUTION_INFO
                    if key == 0x00040006:
                        # 'val' aponta para o struct XEX_EXECUTION_INFO no arquivo
                        # +0x00 Media ID (4B), +0x04 Version (4B), +0x08 Base Version (4B), +0x0C Title ID (4B)
                        f.seek(val + 12)
                        tid_bytes = f.read(4)
                        if len(tid_bytes) == 4:
                            tid_int = struct.unpack(">I", tid_bytes)[0]
                            return f"{tid_int:08X}"
        except Exception:
            pass
        return ""

    def extract_title_id_from_god(self, god_path: Path) -> str:
        """Busca o Title ID pela hierarquia de pastas ou dentro do container STFS."""
        # 1. Checagem por nome de pasta com 8 dígitos hexadecimais
        curr = god_path if god_path.is_dir() else god_path.parent
        for _ in range(4):
            if re.match(r"^[0-9A-Fa-f]{8}$", curr.name):
                return curr.name.upper()
            if curr.parent == curr:
                break
            curr = curr.parent

        # 2. Varredura do descritor de volume no arquivo de pacote STFS
        search_dir = god_path.parent if god_path.is_file() else god_path
        stfs_candidates = [
            f for f in search_dir.rglob("*")
            if f.is_file() and not f.name.lower().startswith("data") and not f.name.endswith(".iso")
        ]

        for pkg in stfs_candidates:
            try:
                with open(pkg, "rb") as f:
                    magic = f.read(4)
                    if magic in (b"CON ", b"LIVE", b"PIRS"):
                        # Checa os offsets comuns de Title ID no cabeçalho STFS (0x35C e 0x360)
                        f.seek(0x350)
                        block = f.read(0x30)
                        for offset in (0x0C, 0x10):  # 0x350 + 0x0C = 0x35C; 0x350 + 0x10 = 0x360
                            cand = struct.unpack(">I", block[offset:offset+4])[0]
                            cand_hex = f"{cand:08X}"
                            if cand_hex in self.database:
                                return cand_hex
            except Exception:
                continue

        return ""

    def resolve_game_name(self, target_path: Path, detected_fmt: str) -> tuple:
        """
        Retorna uma tupla (title_id, clean_game_name).
        """
        title_id = ""

        if detected_fmt == "XEX":
            xex_file = target_path / "default.xex" if target_path.is_dir() else target_path
            if not xex_file.exists() and target_path.is_dir():
                found = list(target_path.glob("**/default.xex")) or list(target_path.glob("**/DEFAULT.XEX"))
                if found:
                    xex_file = found[0]

            title_id = self.extract_title_id_from_xex(xex_file)
            if not title_id and re.match(r"^[0-9A-Fa-f]{8}$", target_path.name):
                title_id = target_path.name.upper()

        elif detected_fmt == "GOD":
            title_id = self.extract_title_id_from_god(target_path)

        clean_name = self.get_game_name(title_id, fallback="")
        return title_id, clean_name