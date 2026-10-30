import os
import struct
from pathlib import Path
from .stfs_engine import VirtualNode
from .iso_redump import SVODRandomAccess


class SVODFileWrapper:
    """Envolve o SVODRandomAccess para que se comporte como um arquivo comum (file-like object)."""
    def __init__(self, svod: SVODRandomAccess):
        self.svod = svod
        self.pos = 0

    def seek(self, offset: int, whence: int = os.SEEK_SET):
        if whence == os.SEEK_SET:
            self.pos = offset
        elif whence == os.SEEK_CUR:
            self.pos += offset
        elif whence == os.SEEK_END:
            self.pos = self.svod.total_virtual + offset

    def read(self, size: int) -> bytes:
        data = self.svod.read(self.pos, size)
        self.pos += len(data)
        return data

    def close(self):
        self.svod.close()


class GDFXEngine:
    """
    Motor universal de leitura e extração do Sistema de Arquivos GDFX (Xbox).
    Suporta imagens .ISO convencionais e contêineres GOD montados em memória.
    """
    XISO_MAGIC = b"MICROSOFT*XBOX*MEDIA"

    def __init__(self, filepath: str = None, file_obj=None):
        self.filepath = Path(filepath) if filepath else None
        self.f = file_obj
        self.tree_root = VirtualNode("ROOT", True)
        self.xbox_disc_lseek = 0
        self.own_file = False

    def inspect(self) -> VirtualNode:
        if self.f is None:
            self.f = open(self.filepath, "rb")
            self.own_file = True

        try:
            valid, root_sector, root_size = self._find_and_validate_header()
            if not valid:
                raise ValueError("O arquivo não contém um sistema GDFX/XISO válido.")

            self._parse_dir(root_sector, root_size, self.tree_root)
            return self.tree_root
        finally:
            if self.own_file and self.f:
                self.f.close()
                self.f = None

    def _find_and_validate_header(self):
        candidate_offsets = [0, 0x0FD90000, 0x02080000, 0x18300000]

        for offset in candidate_offsets:
            try:
                self.f.seek(offset + 0x10000)
                if self.f.read(20) == self.XISO_MAGIC:
                    self.xbox_disc_lseek = offset
                    self.f.seek(offset + 0x10000 + 20)
                    root_sector, root_size = struct.unpack("<II", self.f.read(8))
                    return True, root_sector, root_size
            except Exception:
                continue

        return False, 0, 0

    def _parse_dir(self, sector: int, size: int, parent_node: VirtualNode):
        offset = sector * 2048 + self.xbox_disc_lseek
        self.f.seek(offset)
        dir_data = self.f.read(size)

        def traverse(node_offset: int):
            if node_offset < 0 or node_offset + 14 > len(dir_data):
                return

            l_off, r_off, start_sec, f_size, attr, name_len = struct.unpack(
                "<HHIIBB", dir_data[node_offset:node_offset + 14]
            )

            if l_off == 0xFFFF:
                return

            name_bytes = dir_data[node_offset + 14:node_offset + 14 + name_len]
            name = name_bytes.decode("latin-1", errors="replace")
            is_dir = bool(attr & 0x10)

            node = VirtualNode(name, is_dir, f_size, start_sec)
            parent_node.children.append(node)

            if l_off != 0:
                traverse(l_off * 4)
            if is_dir and f_size > 0:
                self._parse_dir(start_sec, f_size, node)
            if r_off != 0:
                traverse(r_off * 4)

        if dir_data:
            traverse(0)

    def get_total_size(self, node: VirtualNode = None) -> int:
        """Calcula o tamanho cumulativo em bytes de toda a árvore ou de um diretório."""
        target = node or self.tree_root
        total = 0
        if not target.is_dir:
            return target.size
        for child in target.children:
            total += self.get_total_size(child)
        return total

    def extract_node(self, node: VirtualNode, target_path: Path, progress_cb=None, bytes_extracted_tracker=None):
        """Extrai o nó (arquivo individual ou pasta inteira) lendo setores e enviando o progresso."""
        if bytes_extracted_tracker is None:
            bytes_extracted_tracker = [0]

        if node.is_dir:
            target_path.mkdir(parents=True, exist_ok=True)
            for child in node.children:
                self.extract_node(child, target_path / child.name, progress_cb, bytes_extracted_tracker)
            return

        target_path.parent.mkdir(parents=True, exist_ok=True)
        chunk_size = 4 * 1024 * 1024  # 4 MB

        close_after = False
        if self.f is None:
            self.f = open(self.filepath, "rb")
            close_after = True

        try:
            start_offset = (node.start_block * 2048) + self.xbox_disc_lseek
            self.f.seek(start_offset)
            bytes_remaining = node.size

            with open(target_path, "wb") as out_f:
                while bytes_remaining > 0:
                    to_read = min(chunk_size, bytes_remaining)
                    chunk = self.f.read(to_read)
                    if not chunk:
                        break
                    out_f.write(chunk)
                    bytes_remaining -= len(chunk)
                    bytes_extracted_tracker[0] += len(chunk)

                    if progress_cb:
                        progress_cb(node.name, bytes_extracted_tracker[0])
        finally:
            if close_after and self.f:
                self.f.close()
                self.f = None