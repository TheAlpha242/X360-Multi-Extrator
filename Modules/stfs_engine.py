import os
import struct
from pathlib import Path


class VirtualNode:
    """Nó virtual para popular a TreeView da interface gráfica."""
    def __init__(self, name: str, is_dir: bool, size: int = 0, start_block: int = 0, parent_idx: int = 0xFFFF):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.start_block = start_block
        self.parent_idx = parent_idx
        self.children = []


class STFSEngine:
    """Motor Cirúrgico para pacotes STFS (XBLA, DLC, TU e Saves Transacionados)."""
    def __init__(self, filepath: str):
        self.filepath = Path(filepath).resolve()
        self.magic = ""
        self.content_type_hex = ""
        self.content_type_name = "STFS Desconhecido"
        self.title_id = ""
        self.display_name = ""
        self.is_style_1 = True
        self.root_block = 0
        self.dir_block_count = 1
        self.block_size = 0x1000
        self.entries = []
        self.tree_root = None

    def _read_utf16_be_string(self, data: bytes) -> str:
        """Lê uma string UTF-16 Big Endian terminada em nulo (padrão Xbox)."""
        text = ""
        for i in range(0, len(data), 2):
            char_bytes = data[i:i+2]
            if char_bytes == b'\x00\x00':
                break
            try:
                text += char_bytes.decode('utf-16-be')
            except Exception:
                pass
        return text.strip()

    def _parse_header(self, f):
        """Coleta assinaturas, Title ID, Tipo e Nome Interno."""
        # 1. MAGIC (CON, PIRS, LIVE)
        f.seek(0x00)
        self.magic = f.read(4).decode('ascii', errors='ignore')

        # 2. CONTENT TYPE
        f.seek(0x344)
        ctype_int = struct.unpack(">I", f.read(4))[0]
        self.content_type_hex = f"{ctype_int:08X}"

        tipos_conteudo = {
            "000D0000": "Xbox Live Arcade (XBLA)",
            "00007000": "Game on Demand (GOD)",
            "00000002": "Extra Content / DLC",
            "000B0000": "Title Update (Patch)",
            "00000001": "Save Game",
            "00090000": "Vídeo / Trailer",
            "00009000": "Avatar Item"
        }
        self.content_type_name = tipos_conteudo.get(self.content_type_hex, f"STFS ({self.content_type_hex})")

        # 3. TITLE ID
        f.seek(0x360)
        tid_int = struct.unpack(">I", f.read(4))[0]
        self.title_id = f"{tid_int:08X}"

        # 4. DISPLAY NAME (UTF-16 Big Endian)
        f.seek(0x411)
        self.display_name = self._read_utf16_be_string(f.read(128))

    def _block_to_offset(self, block: int) -> int:
        """Calcula o offset físico exato pulando apenas as tabelas de Hash necessárias."""
        multiplier = block
        if self.is_style_1:
            # Style 1 (XBLA/DLC): L0, L1 e L2 estão no meio dos dados.
            multiplier += (block // 170) + 1       # Pulo L0
            multiplier += (block // 28900) + 1     # Pulo L1
            multiplier += (block // 4913000) + 1   # Pulo L2
            return (multiplier * self.block_size) + 0x9000
        else:
            # Style 0 (Saves CON): L1 e L2 ficam no cabeçalho. Apenas a L0 está no meio dos dados.
            multiplier += (block // 170) + 1       # Pulo L0 (Hash)
            return (multiplier * self.block_size) + 0xB000

    def inspect(self) -> VirtualNode:
        if not self.filepath.is_file():
            raise FileNotFoundError(f"Arquivo não localizado: {self.filepath}")

        with open(self.filepath, "rb") as f:
            f.seek(0)
            magic_check = f.read(4)
            if magic_check not in (b"LIVE", b"PIRS", b"CON "):
                raise ValueError("Formato não é STFS compatível.")

            self._parse_header(f)

            # Lógica Bitwise do Style Byte (Offset 0x37B)
            f.seek(0x37B)
            flags = struct.unpack(">B", f.read(1))[0]
            self.is_style_1 = bool(flags & 0x01)       # Bit 0: Style
            active_index = (flags & 0x02) >> 1         # Bit 1: Tabela Transacional Ativa

            # Leitura do Volume Descriptor 1 (Tabela A) -> 0x379
            f.seek(0x37C)
            dir_count_A = struct.unpack("<H", f.read(2))[0]
            rbA = f.read(3)
            root_block_A = rbA[0] | (rbA[1] << 8) | (rbA[2] << 16)

            # Leitura do Volume Descriptor 2 (Tabela B) -> 0x39D (Usado em Saves CON)
            f.seek(0x3A0)
            dir_count_B = struct.unpack("<H", f.read(2))[0]
            rbB = f.read(3)
            root_block_B = rbB[0] | (rbB[1] << 8) | (rbB[2] << 16)

            # Seleciona o Diretório Ativo confiando na Flag do Sistema (Evita o Copy-On-Write)
            if active_index == 1 and root_block_B != 0xFFFFFF:
                self.dir_block_count = dir_count_B
                self.root_block = root_block_B
            elif active_index == 0 and root_block_A != 0xFFFFFF:
                self.dir_block_count = dir_count_A
                self.root_block = root_block_A
            else:
                # Fallback de segurança se o bit ativo estiver quebrado
                if root_block_B != 0xFFFFFF:
                    self.dir_block_count = dir_count_B
                    self.root_block = root_block_B
                else:
                    self.dir_block_count = dir_count_A
                    self.root_block = root_block_A

            self.tree_root = VirtualNode("ROOT", True)
            
            # Se o bloco raiz for 0xFFFFFF, o save está literalmente vazio (não há arquivos ainda)
            if self.root_block == 0xFFFFFF or self.dir_block_count == 0:
                return self.tree_root

            # Leitura da Tabela de Diretórios
            dir_data = bytearray()
            for b_idx in range(self.dir_block_count):
                offset = self._block_to_offset(self.root_block + b_idx)
                f.seek(offset)
                chunk = f.read(self.block_size)
                if not chunk: break
                dir_data.extend(chunk)

            total_entries = len(dir_data) // 64
            
            # Array estático pré-alocado (Protege a ordem para que os subdiretórios achem seus pais)
            self.entries = [None] * total_entries

            # Parseamento com tolerância a buracos de memória (Buracos são normais em saves deletados)
            for i in range(total_entries):
                raw = dir_data[i * 64 : (i + 1) * 64]
                if all(b == 0x00 for b in raw):
                    continue # Não usa break, pois pode haver arquivos mais à frente na tabela
                
                flags_entry = raw[0x28]
                name_len = flags_entry & 0x3F
                if name_len == 0 or name_len > 40:
                    continue
                    
                try:
                    name = raw[0:name_len].decode("ascii")
                    if not name.isprintable(): continue
                except Exception:
                    continue

                is_dir = bool(flags_entry & 0x80)
                
                # Offsets MS oficiais: 0x2C=StartBlock(3b), 0x2F=Parent(2b), 0x31=Size(4b)
                sb = raw[0x2C:0x2F]
                s_block = sb[0] | (sb[1] << 8) | (sb[2] << 16)
                parent_idx = struct.unpack(">H", raw[0x2F:0x31])[0]
                file_size = struct.unpack(">I", raw[0x31:0x35])[0]

                self.entries[i] = VirtualNode(name, is_dir, file_size, s_block, parent_idx)

            # Acoplando a árvore visual
            for node in self.entries:
                if node is None:
                    continue
                if node.parent_idx == 0xFFFF or node.parent_idx >= total_entries or self.entries[node.parent_idx] is None:
                    self.tree_root.children.append(node)
                else:
                    self.entries[node.parent_idx].children.append(node)

            return self.tree_root

    def extract_node(self, node: VirtualNode, target_path: Path, progress_cb=None, bytes_extracted_tracker=None):
        if bytes_extracted_tracker is None:
            bytes_extracted_tracker = [0]

        if node.is_dir:
            target_path.mkdir(parents=True, exist_ok=True)
            for child in node.children:
                self.extract_node(child, target_path / child.name, progress_cb, bytes_extracted_tracker)
            return

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.filepath, "rb") as f, open(target_path, "wb") as out_f:
            bytes_remaining = node.size
            curr_block = node.start_block
            while bytes_remaining > 0:
                f.seek(self._block_to_offset(curr_block))
                chunk = f.read(min(bytes_remaining, self.block_size))
                if not chunk: break
                out_f.write(chunk)
                bytes_remaining -= len(chunk)
                curr_block += 1
                bytes_extracted_tracker[0] += len(chunk)
                if progress_cb:
                    progress_cb(node.name, bytes_extracted_tracker[0])