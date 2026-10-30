import os
import struct
import shutil
from pathlib import Path


class _DirNode:
    """Representa a struct dir_node para controle de pilha na travessia."""
    __slots__ = (
        "parent", "r_offset", "attributes", "filename_length", 
        "file_size", "start_sector", "filename"
    )

    def __init__(self, parent=None):
        self.parent = parent
        self.r_offset = 0
        self.attributes = 0
        self.filename_length = 0
        self.file_size = 0
        self.start_sector = 0
        self.filename = ""


class XEXExtractor:
    """
    Extrator XEX de Alta Performance.
    Une a varredura rigorosa do extract-xiso (C) com extração linear (Sector-Sorted)
    e Mega Buffers de 8MB em Python.
    """

    GLOBAL_LSEEK_OFFSET = 0x0FD90000
    XGD3_LSEEK_OFFSET = 0x02080000
    XGD1_LSEEK_OFFSET = 0x18300000

    XISO_HEADER_DATA = b"MICROSOFT*XBOX*MEDIA"
    XISO_HEADER_DATA_LENGTH = 20
    XISO_HEADER_OFFSET = 0x10000

    XISO_OPTIMIZED_TAG_OFFSET = 31337
    XISO_OPTIMIZED_TAG_MIN = b"in!xiso"

    XISO_SECTOR_SIZE = 2048
    XISO_UNUSED_SIZE = 0x7C8
    XISO_FILETIME_SIZE = 8
    XISO_DWORD_SIZE = 4

    XISO_ATTRIBUTE_DIR = 0x10
    XISO_PAD_SHORT = 0xFFFF
    
    # Mega buffer para maximizar banda do disco (8 MB)
    CHUNK_SIZE = 8 * 1024 * 1024
    SYSTEM_UPDATE_FOLDER = "$SystemUpdate"

    def __init__(self, log_cb=None, progress_cb=None):
        self.log_cb = log_cb or (lambda msg, tag="INFO": print(f"[{tag}] {msg}"))
        self.progress_cb = progress_cb or (lambda pct: None)
        self._cancel_requested = False
        self.xbox_disc_lseek = 0
        self.files_to_extract = []

    def cancel(self):
        self._cancel_requested = True

    def _check_optimized_tag(self, f) -> bool:
        try:
            f.seek(self.XISO_OPTIMIZED_TAG_OFFSET, os.SEEK_SET)
            return f.read(len(self.XISO_OPTIMIZED_TAG_MIN)) == self.XISO_OPTIMIZED_TAG_MIN
        except Exception:
            return False

    def _verify_xiso(self, f, iso_name: str) -> tuple[bool, int, int]:
        candidate_offsets = [
            (0, "Padrão / XISO Limpa"),
            (self.GLOBAL_LSEEK_OFFSET, "XGD2 (0x0FD90000)"),
            (self.XGD3_LSEEK_OFFSET, "XGD3 (0x02080000)"),
            (self.XGD1_LSEEK_OFFSET, "XGD1 (0x18300000)"),
        ]

        matched_lseek = None
        part_label = ""

        for lseek_offset, label in candidate_offsets:
            try:
                f.seek(self.XISO_HEADER_OFFSET + lseek_offset, os.SEEK_SET)
                if f.read(self.XISO_HEADER_DATA_LENGTH) == self.XISO_HEADER_DATA:
                    matched_lseek = lseek_offset
                    part_label = label
                    break
            except Exception:
                continue

        if matched_lseek is None:
            self.log_cb(f"❌ '{iso_name}' não é uma ISO Xbox válida.", "ERROR")
            return False, 0, 0

        self.xbox_disc_lseek = matched_lseek
        header_info = f.read(8)
        
        if len(header_info) != 8:
            return False, 0, 0

        root_dir_sector, root_dir_size = struct.unpack("<II", header_info)
        
        self.log_cb(f"✅ Volume XDVDFS [{part_label}] validado.", "INFO")
        return True, root_dir_sector, root_dir_size

    def _collect_files(self, f, in_dir_start: int, current_out_dir: Path, rel_path: str, in_ll_compat: bool, remove_sys_update: bool):
        """Varre a tabela de diretórios rigorosamente e armazena os metadados."""
        dir_node = _DirNode()
        l_offset = 0
        state = "READ_ENTRY"

        while not self._cancel_requested:
            if state == "READ_ENTRY":
                raw_tmp = f.read(2)
                if len(raw_tmp) != 2:
                    break

                tmp = struct.unpack("<H", raw_tmp)[0]

                if tmp == self.XISO_PAD_SHORT:
                    if l_offset == 0:
                        state = "END_TRAVERSE"
                        continue

                    byte_off = l_offset * self.XISO_DWORD_SIZE
                    byte_off += self.XISO_SECTOR_SIZE - (byte_off % self.XISO_SECTOR_SIZE)
                    f.seek(in_dir_start + byte_off, os.SEEK_SET)
                    continue
                else:
                    l_offset = tmp

                entry_header = f.read(12)
                (
                    dir_node.r_offset, dir_node.start_sector, dir_node.file_size,
                    dir_node.attributes, dir_node.filename_length,
                ) = struct.unpack("<HIIBB", entry_header)

                raw_name = f.read(dir_node.filename_length)
                dir_node.filename = raw_name.decode("latin-1", errors="replace")

                if l_offset != 0:
                    in_ll_compat = False
                    f.seek(in_dir_start + l_offset * self.XISO_DWORD_SIZE, os.SEEK_SET)
                    left_child = _DirNode(parent=dir_node)
                    dir_node = left_child
                    state = "READ_ENTRY"
                    continue

                state = "LEFT_PROCESSED"

            elif state == "LEFT_PROCESSED":
                curpos = f.tell()

                skip_item = remove_sys_update and (
                    self.SYSTEM_UPDATE_FOLDER.lower() in rel_path.lower() or
                    self.SYSTEM_UPDATE_FOLDER.lower() in dir_node.filename.lower()
                )

                if not skip_item:
                    if dir_node.attributes & self.XISO_ATTRIBUTE_DIR:
                        if dir_node.file_size > 0:
                            sub_dir_start = dir_node.start_sector * self.XISO_SECTOR_SIZE + self.xbox_disc_lseek
                            f.seek(sub_dir_start, os.SEEK_SET)
                            self._collect_files(
                                f, sub_dir_start, current_out_dir / dir_node.filename,
                                f"{rel_path}{dir_node.filename}\\", in_ll_compat, remove_sys_update
                            )
                    else:
                        if dir_node.file_size > 0:
                            self.files_to_extract.append({
                                'path': current_out_dir / dir_node.filename,
                                'sector': dir_node.start_sector,
                                'size': dir_node.file_size
                            })

                if dir_node.r_offset != 0:
                    sector = (curpos - in_dir_start) // self.XISO_SECTOR_SIZE
                    if in_ll_compat and (dir_node.r_offset * self.XISO_DWORD_SIZE) // self.XISO_SECTOR_SIZE > sector:
                        dwords_per_sector = self.XISO_SECTOR_SIZE // self.XISO_DWORD_SIZE
                        dir_node.r_offset = (sector * dwords_per_sector) + dwords_per_sector

                    f.seek(in_dir_start + dir_node.r_offset * self.XISO_DWORD_SIZE, os.SEEK_SET)
                    l_offset = dir_node.r_offset
                    state = "READ_ENTRY"
                    continue

                state = "END_TRAVERSE"

            elif state == "END_TRAVERSE":
                dir_node = dir_node.parent
                if dir_node is not None:
                    state = "LEFT_PROCESSED"
                    continue
                else:
                    break

    def extract(self, iso_path: Path, output_dir: Path, remove_sys_update: bool = True) -> bool:
        self._cancel_requested = False
        self.files_to_extract = []
        iso_path = Path(iso_path)
        output_dir = Path(output_dir)

        if not iso_path.exists():
            return False

        try:
            self.log_cb(f"🚀 Iniciando extração XEX acelerada para: {iso_path.name}", "INFO")

            with open(iso_path, "rb") as f:
                in_ll_compat = not self._check_optimized_tag(f)
                valid, root_sector, root_size = self._verify_xiso(f, iso_path.name)
                
                if not valid or (root_sector == 0 and root_size == 0):
                    return False

                self.log_cb("🔍 Mapeando estrutura e isolando lixo ($SystemUpdate)...", "INFO")
                self.progress_cb(5)

                root_dir_start = root_sector * self.XISO_SECTOR_SIZE + self.xbox_disc_lseek
                f.seek(root_dir_start, os.SEEK_SET)
                
                # Coleta todos os metadados dos arquivos
                self._collect_files(f, root_dir_start, output_dir, "\\", in_ll_compat, remove_sys_update)

                if not self.files_to_extract:
                    self.log_cb("⚠️ Nenhum arquivo válido encontrado.", "WARN")
                    return False

                total_bytes = sum(file_info['size'] for file_info in self.files_to_extract)
                gb_total = total_bytes / (1024**3)

                # Pre-check de disco
                try:
                    free_space = shutil.disk_usage(output_dir).free
                    if free_space < (total_bytes + 104_857_600):
                        self.log_cb(f"❌ Espaço insuficiente. Necessário: {gb_total:.2f} GB livres.", "ERROR")
                        return False
                except Exception:
                    pass

                self.log_cb(f"✅ Mapeamento concluído: {len(self.files_to_extract)} arquivos ({gb_total:.2f} GB).", "INFO")
                
                # A Mágica do I/O: Ordena por setor físico (A agulha do disco nunca volta para trás)
                self.files_to_extract.sort(key=lambda x: x['sector'])

                extracted_bytes = 0
                self.log_cb(f"⚙️ Extraindo sequencialmente com Mega Buffers ({self.CHUNK_SIZE // (1024*1024)}MB)...", "INFO")

                for file_info in self.files_to_extract:
                    if self._cancel_requested:
                        return False

                    target_file = file_info['path']
                    target_file.parent.mkdir(parents=True, exist_ok=True)

                    start_offset = self.xbox_disc_lseek + (file_info['sector'] * self.XISO_SECTOR_SIZE)
                    f.seek(start_offset, os.SEEK_SET)

                    bytes_remaining = file_info['size']

                    with open(target_file, "wb") as out_f:
                        while bytes_remaining > 0 and not self._cancel_requested:
                            to_read = min(self.CHUNK_SIZE, bytes_remaining)
                            chunk = f.read(to_read)
                            if not chunk: break
                            
                            out_f.write(chunk)
                            bytes_remaining -= len(chunk)
                            extracted_bytes += len(chunk)

                            pct = 5 + int((extracted_bytes / total_bytes) * 95)
                            self.progress_cb(pct)

            if self._cancel_requested:
                self.log_cb("🛑 Extração cancelada.", "WARN")
                return False

            self.progress_cb(100)
            self.log_cb(f"🎉 Extração XEX finalizada perfeitamente!", "SUCCESS")
            return True

        except Exception as e:
            self.log_cb(f"❌ Erro crítico na extração: {e}", "ERROR")
            return False