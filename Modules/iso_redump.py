import os
import struct
import time
from pathlib import Path
from Modules.title_resolver import TitleResolver


class GDFXNode:
    def __init__(self, name: str, is_dir: bool, size: int = 0, path: Path = None):
        self.name = name
        self.is_dir = is_dir
        self.size = size
        self.path = path
        self.left = None
        self.right = None
        self.offset = 0
        self.start_sector = 0
        self.children = []
        self.bst_root = None
        self.dir_table_size = 0


class SVODRandomAccess:
    def __init__(self, data_parts):
        self.parts = data_parts
        self.MASTER = 0x1000
        self.DATA_PER_SUB = 0xCC000
        self.CHUNK = 0xCD000
        
        self._h = {}
        self.virtual_offsets = []
        
        curr_v_off = 0
        for p in self.parts:
            self.virtual_offsets.append(curr_v_off)
            size = p.stat().st_size
            if size <= self.MASTER:
                v_size = 0
            else:
                size -= self.MASTER
                subs = size // self.CHUNK
                rem = size % self.CHUNK
                data_in_rem = max(0, rem - 0x1000)
                v_size = (subs * self.DATA_PER_SUB) + data_in_rem
            curr_v_off += v_size
            
        self.total_virtual = curr_v_off

    def _handle(self, i):
        if i not in self._h:
            self._h[i] = open(self.parts[i], "rb")
        return self._h[i]

    def read(self, v_off, size):
        out = bytearray()
        while size > 0:
            if v_off >= self.total_virtual:
                break
                
            fi = 0
            for i, offset in enumerate(self.virtual_offsets):
                if v_off >= offset:
                    fi = i
                else:
                    break
                    
            local_v_off = v_off - self.virtual_offsets[fi]
            sub, rem = divmod(local_v_off, self.DATA_PER_SUB)
            phys = self.MASTER + (sub * self.CHUNK) + 0x1000 + rem
            n = min(size, self.DATA_PER_SUB - rem)
            
            file_size = self.parts[fi].stat().st_size
            if phys >= file_size:
                break
            n = min(n, file_size - phys)
            
            f = self._handle(fi)
            f.seek(phys)
            chunk = f.read(n)
            if not chunk:
                break
                
            out.extend(chunk)
            v_off += len(chunk)
            size -= len(chunk)
            
        return bytes(out)

    def close(self):
        for h in self._h.values():
            h.close()


class ISORedump:
    SECTOR_SIZE = 2048
    ROOT_SECTOR_START = 0x108
    HEADER_OFFSET = 0x10000
    MEDIA_MAGIC = b"MICROSOFT*XBOX*MEDIA"

    def __init__(self, log_cb=None, progress_cb=None):
        self.log_cb = log_cb or (lambda msg, tag="INFO": print(f"[{tag}] {msg}"))
        self.progress_cb = progress_cb or (lambda pct: None)
        self._cancel_requested = False
        self.resolver = TitleResolver()

    def cancel(self):
        self._cancel_requested = True

    def detect_format(self, input_path: Path) -> str:
        p = Path(input_path)
        if not p.exists(): return "UNKNOWN"
        if p.is_file():
            if p.name.lower().startswith("data") or len(p.name) == 42 or p.name.endswith(".0") or "." not in p.name:
                return "GOD"
            return "UNKNOWN"
        if p.is_dir():
            if (p / "default.xex").exists() or (p / "DEFAULT.XEX").exists() or list(p.glob("**/default.xex")):
                return "XEX"
            has_data = any(f.name.lower().startswith("data") for f in p.rglob("*") if f.is_file())
            has_sig = any("." not in f.name and len(f.name) > 8 for f in p.rglob("*") if f.is_file())
            if has_data or has_sig or list(p.glob("**/00007000*")):
                return "GOD"
        return "UNKNOWN"

    def rebuild(self, input_path: Path, output_iso_path: Path) -> bool:
        self._cancel_requested = False
        target = Path(input_path)
        fmt = self.detect_format(target)
        self.log_cb(f"🔍 Analisando formato em: '{target.name}'...", "INFO")

        if fmt == "UNKNOWN":
            self.log_cb(f"❌ Estrutura não reconhecida: {target.name}", "ERROR")
            return False

        # Resolução do Title ID e do Nome Oficial do Jogo
        tid, game_title = self.resolver.resolve_game_name(target, fmt)
        if game_title:
            self.log_cb(f"🎮 Jogo identificado: '{game_title}' (Title ID: {tid})", "SUCCESS")
            final_iso_name = f"{game_title}.iso"
        elif tid:
            self.log_cb(f"🏷️ Title ID detectado: {tid} (Nome não localizado no banco)", "WARN")
            final_iso_name = f"{tid}.iso"
        else:
            final_iso_name = f"{target.name}.iso"

        # Ajuste inteligente do caminho de destino
        out_iso = Path(output_iso_path)
        if out_iso.is_dir() or not out_iso.suffix:
            out_iso = out_iso / final_iso_name
        else:
            out_iso = out_iso.parent / final_iso_name

        self.log_cb(f"💾 Arquivo final configurado como: '{out_iso.name}'", "INFO")

        if fmt == "GOD":
            return self._rebuild_from_god(target, out_iso)
        elif fmt == "XEX":
            return self._rebuild_from_xex(target, out_iso)

    def _rebuild_from_god(self, god_path: Path, out_iso: Path) -> bool:
        try:
            search_dir = god_path.parent if god_path.is_file() else god_path
            data_parts = sorted(
                [f for f in search_dir.rglob("*") if f.is_file() and f.name.lower().startswith("data")],
                key=lambda x: x.name.lower()
            )

            if not data_parts:
                self.log_cb("❌ Nenhum pacote DataXXXX localizado.", "ERROR")
                return False

            self.log_cb(f"🧠 Sincronizando blocos da memória SVOD ({len(data_parts)} arquivos)...", "INFO")
            svod = SVODRandomAccess(data_parts)
            
            check_buffer = svod.read(0x10000, 24)
            if self.MEDIA_MAGIC in check_buffer:
                self.log_cb("📑 Volume Descriptor validado com sucesso!", "SUCCESS")
            else:
                self.log_cb("⚠️ Volume Descriptor não encontrado no offset padrão.", "WARN")

            out_iso.parent.mkdir(parents=True, exist_ok=True)
            self.log_cb(f"🚀 Iniciando espelhamento RAW ({svod.total_virtual / (1024**2):.2f} MB)...", "INFO")
            
            pos = 0
            chunk_size = 8 * 1024 * 1024
            
            with open(out_iso, "wb") as o:
                while pos < svod.total_virtual:
                    if self._cancel_requested:
                        self.log_cb("🛑 Operação GOD cancelada pelo usuário.", "WARN")
                        svod.close()
                        return False
                        
                    b = svod.read(pos, chunk_size)
                    if not b:
                        break
                    
                    o.write(b)
                    pos += len(b)
                    
                    pct = int((pos / svod.total_virtual) * 100) if svod.total_virtual > 0 else 0
                    self.progress_cb(min(pct, 99))
                    
            svod.close()
            self.progress_cb(100)
            self.log_cb(f"✅ Conversão GOD ➔ ISO concluída: {out_iso.name}", "SUCCESS")
            return True

        except Exception as e:
            self.log_cb(f"❌ Erro Crítico no motor SVOD ➔ ISO: {e}", "ERROR")
            return False

    def _rebuild_from_xex(self, root_dir: Path, out_iso: Path) -> bool:
        try:
            target_dir = root_dir if root_dir.is_dir() else root_dir.parent
            out_iso.parent.mkdir(parents=True, exist_ok=True)
            self.log_cb("📑 Mapeando arquivos XEX e gerando estrutura GDFX...", "INFO")
            
            root_node = GDFXNode(name="root", is_dir=True, path=target_dir)
            self._scan_and_build_tree(root_node)
            self._calculate_directory_sizes(root_node)

            curr_sector = self.ROOT_SECTOR_START
            curr_sector = self._assign_sectors(root_node, curr_sector)

            total_payload = sum(f.stat().st_size for f in target_dir.rglob("*") if f.is_file())
            bytes_payload_written = 0

            with open(out_iso, "wb") as f_out:
                f_out.write(b"\x00" * self.HEADER_OFFSET)
                self._write_volume_descriptor(f_out, root_node)
                
                pos = f_out.tell()
                target_root_pos = root_node.start_sector * self.SECTOR_SIZE
                if target_root_pos > pos:
                    f_out.write(b"\x00" * (target_root_pos - pos))

                bytes_payload_written = self._write_tree_to_iso(
                    node=root_node, f_out=f_out, total_bytes=total_payload, bytes_written=bytes_payload_written
                )

                final_pos = f_out.tell()
                pad_final = (0x10000 - (final_pos % 0x10000)) % 0x10000
                if pad_final > 0:
                    f_out.write(b"\x00" * pad_final)

            self.progress_cb(100)
            self.log_cb(f"✅ Conversão XEX ➔ ISO concluída: {out_iso.name}", "SUCCESS")
            return True
        except Exception as e:
            self.log_cb(f"❌ Erro Crítico ao compilar XEX ➔ GDFX: {e}", "ERROR")
            return False

    def _scan_and_build_tree(self, dir_node: GDFXNode):
        items = []
        for p in dir_node.path.iterdir():
            if p.name.startswith("."): continue
            is_dir = p.is_dir()
            size = p.stat().st_size if not is_dir else 0
            node = GDFXNode(name=p.name, is_dir=is_dir, size=size, path=p)
            if is_dir: self._scan_and_build_tree(node)
            items.append(node)
        items.sort(key=lambda x: x.name.upper())
        dir_node.children = items
        dir_node.bst_root = self._build_balanced_bst(items)

    def _build_balanced_bst(self, items: list) -> GDFXNode:
        if not items: return None
        mid = len(items) // 2
        root = items[mid]
        root.left = self._build_balanced_bst(items[:mid])
        root.right = self._build_balanced_bst(items[mid + 1:])
        return root

    def _calculate_directory_sizes(self, dir_node: GDFXNode):
        offset = 0
        def traverse_calc(node: GDFXNode):
            nonlocal offset
            if not node: return
            name_len = len(node.name.encode("latin-1", errors="replace"))
            entry_len = 14 + name_len
            entry_len += (4 - (entry_len % 4)) % 4
            if (offset % self.SECTOR_SIZE) + entry_len > self.SECTOR_SIZE:
                offset += self.SECTOR_SIZE - (offset % self.SECTOR_SIZE)
            node.offset = offset
            offset += entry_len
            traverse_calc(node.left)
            traverse_calc(node.right)
            
        traverse_calc(dir_node.bst_root)
        if offset == 0:
            dir_node.dir_table_size = self.SECTOR_SIZE
        else:
            remainder = offset % self.SECTOR_SIZE
            dir_node.dir_table_size = offset + ((self.SECTOR_SIZE - remainder) if remainder != 0 else 0)

        for child in dir_node.children:
            if child.is_dir: self._calculate_directory_sizes(child)

    def _assign_sectors(self, dir_node: GDFXNode, current_sector: int) -> int:
        dir_node.start_sector = current_sector
        current_sector += dir_node.dir_table_size // self.SECTOR_SIZE
        for child in dir_node.children:
            if not child.is_dir:
                child.start_sector = current_sector
                sectors_needed = (child.size + self.SECTOR_SIZE - 1) // self.SECTOR_SIZE
                current_sector += max(1, sectors_needed) if child.size > 0 else 0
        for child in dir_node.children:
            if child.is_dir: current_sector = self._assign_sectors(child, current_sector)
        return current_sector

    def _write_volume_descriptor(self, f_out, root_node: GDFXNode):
        now = time.time()
        filetime = int((now + 11644473600) * 10000000)
        ft_low = filetime & 0xFFFFFFFF
        ft_high = (filetime >> 32) & 0xFFFFFFFF
        header = bytearray(self.SECTOR_SIZE)
        header[0:20] = self.MEDIA_MAGIC
        header[20:24] = struct.pack("<I", root_node.start_sector)
        header[24:28] = struct.pack("<I", root_node.dir_table_size)
        header[28:36] = struct.pack("<II", ft_low, ft_high)
        header[2028:2048] = self.MEDIA_MAGIC
        f_out.seek(self.HEADER_OFFSET)
        f_out.write(header)

    def _write_tree_to_iso(self, node: GDFXNode, f_out, total_bytes: int, bytes_written: int) -> int:
        if self._cancel_requested: return bytes_written
        table_buf = bytearray(b"\xFF" * node.dir_table_size)

        def write_dir_entry(entry: GDFXNode):
            if not entry: return
            l_off = (entry.left.offset // 4) if entry.left else 0
            r_off = (entry.right.offset // 4) if entry.right else 0
            file_sz = entry.dir_table_size if entry.is_dir else entry.size
            attr = 0x10 if entry.is_dir else 0x80
            name_bytes = entry.name.encode("latin-1", errors="replace")
            entry_bytes = struct.pack("<HHIIBB", l_off, r_off, entry.start_sector, file_sz, attr, len(name_bytes)) + name_bytes
            entry_bytes += b"\xFF" * ((4 - (len(entry_bytes) % 4)) % 4)
            table_buf[entry.offset:entry.offset + len(entry_bytes)] = entry_bytes
            write_dir_entry(entry.left)
            write_dir_entry(entry.right)

        write_dir_entry(node.bst_root)
        f_out.seek(node.start_sector * self.SECTOR_SIZE)
        f_out.write(table_buf)

        chunk_size = 4 * 1024 * 1024
        for child in node.children:
            if self._cancel_requested: return bytes_written
            if not child.is_dir:
                f_out.seek(child.start_sector * self.SECTOR_SIZE)
                if child.size > 0:
                    with open(child.path, "rb") as f_src:
                        while True:
                            if self._cancel_requested: return bytes_written
                            chunk = f_src.read(chunk_size)
                            if not chunk: break
                            f_out.write(chunk)
                            bytes_written += len(chunk)
                            if total_bytes > 0:
                                self.progress_cb(min(int((bytes_written / total_bytes) * 100), 99))
                remainder = f_out.tell() % self.SECTOR_SIZE
                if remainder != 0: f_out.write(b"\x00" * (self.SECTOR_SIZE - remainder))

        for child in node.children:
            if child.is_dir: bytes_written = self._write_tree_to_iso(child, f_out, total_bytes, bytes_written)
        return bytes_written