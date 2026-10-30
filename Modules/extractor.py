import os
from pathlib import Path
from .xex_extractor import XEXExtractor
from .god_extractor import GODExtractor
from .iso_redump import ISORedump
from .title_resolver import TitleResolver


class XboxBatchExtractor:
    """
    Orquestrador Central:
    - Conversão em lote (ISO ⇄ XEX/GOD)[cite: 6]
    - Identificação e inspeção avançada de arquivos (ISO, GOD, XBLA, DLC, TU)
    """

    def __init__(self, log_cb=None, progress_cb=None, finish_cb=None):
        self.log_cb = log_cb or (lambda msg, tag="INFO": print(f"[{tag}] {msg}"))
        self.progress_cb = progress_cb or (lambda game, idx, total, pct: None)
        self.finish_cb = finish_cb or (lambda ok, total, aborted: None)
        self._cancel_requested = False
        self._current_worker = None
        self.resolver = TitleResolver()

    def cancel(self):
        self._cancel_requested = True
        if self._current_worker:
            try:
                self._current_worker.cancel()
            except AttributeError:
                pass

    def inspect_file(self, filepath: Path) -> dict:
        """
        Inspeciona qualquer arquivo suportado de Xbox 360, extraindo Title ID,
        nome comercial, tipo de conteúdo e montando a árvore de arquivos virtual.
        """
        result = {
            "format": "Desconhecido",
            "title_id": "-",
            "game_name": "-",
            "total_size_mb": 0.0,
            "tree_root": None,
            "engine": None,
        }

        from .stfs_engine import STFSEngine
        from .gdfx_engine import GDFXEngine, SVODFileWrapper
        from .iso_redump import SVODRandomAccess

        filepath = Path(filepath).resolve()

        # --------------------------------------------------
        # 1. IMAGEM DE DISCO (.ISO)
        # --------------------------------------------------
        if filepath.suffix.lower() == ".iso":
            result["format"] = "Imagem de Disco (ISO / GDFX)"
            result["game_name"] = filepath.stem

            try:
                engine = GDFXEngine(filepath=filepath)
                result["tree_root"] = engine.inspect()
                result["engine"] = engine
                result["total_size_mb"] = engine.get_total_size() / (1024 * 1024)

                # Busca automática por Title ID em default.xex na raiz da ISO
                for child in result["tree_root"].children:
                    if child.name.lower() == "default.xex":
                        pass
            except Exception as e:
                self.log_cb(f"Falha ao inspecionar ISO: {e}", "ERROR")
            return result

        # --------------------------------------------------
        # 2. PACOTE STFS (XBLA, GOD, DLC, TITLE UPDATE, SAVE)
        # --------------------------------------------------
        try:
            with open(filepath, "rb") as f:
                magic = f.read(4)

            if magic in (b"LIVE", b"PIRS", b"CON "):
                stfs_meta = STFSEngine(filepath)
                with open(filepath, "rb") as f_meta:
                    stfs_meta._parse_header(f_meta)

                # Extrai o Title ID de 8 caracteres hexadecimais (offset 0x360)[cite: 14]
                tid = stfs_meta.title_id if (stfs_meta.title_id and stfs_meta.title_id != "00000000") else ""

                # Nome do jogo: Prioridade 1 (UTF-16 do cabeçalho) -> Prioridade 2 (Banco JSON) -> Prioridade 3 (Arquivo)[cite: 14]
                game_name = stfs_meta.display_name
                if not game_name and tid:
                    game_name = self.resolver.get_game_name(tid, "")
                if not game_name:
                    game_name = filepath.parent.name if filepath.parent.name.upper() != tid else filepath.name

                result["title_id"] = tid or "Desconhecido"
                result["game_name"] = game_name

                # Verifica se é um contêiner Games on Demand (presença de subpasta .data)
                data_folder = filepath.parent / f"{filepath.name}.data"
                if data_folder.exists():
                    result["format"] = "Games on Demand (GOD / SVOD)"
                    data_parts = sorted(
                        [p for p in data_folder.rglob("*") if p.is_file() and p.name.lower().startswith("data")]
                    )

                    if data_parts:
                        svod = SVODRandomAccess(data_parts)
                        virtual_file = SVODFileWrapper(svod)
                        engine = GDFXEngine(file_obj=virtual_file)
                        result["tree_root"] = engine.inspect()
                        result["engine"] = engine
                        result["total_size_mb"] = engine.get_total_size() / (1024 * 1024)
                else:
                    # Pacote STFS autossuficiente (XBLA, DLC, TU, Save)
                    result["format"] = stfs_meta.content_type_name
                    result["tree_root"] = stfs_meta.inspect()
                    result["engine"] = stfs_meta
                    total_bytes = sum(e.size for e in stfs_meta.entries if not e.is_dir)
                    result["total_size_mb"] = total_bytes / (1024 * 1024)

                return result
        except Exception as e:
            self.log_cb(f"Falha na detecção de pacote: {e}", "ERROR")

        return result

    def collect_targets(self, input_paths: list, mode: str) -> list[Path]:
        target_list = []
        if mode == "REBUILD_ISO":
            detector = ISORedump()
            for path_str in input_paths:
                p = Path(path_str)
                if not p.exists():
                    continue
                if p.is_file():
                    target_list.append(p)
                elif p.is_dir():
                    fmt = detector.detect_format(p)
                    if fmt in ["GOD", "XEX"]:
                        target_list.append(p)
                    else:
                        for root, dirs, files in os.walk(p):
                            curr_dir = Path(root)
                            if "00007000" in dirs or "default.xex" in (f.lower() for f in files):
                                target_list.append(curr_dir)
        else:
            for path_str in input_paths:
                p = Path(path_str)
                if p.is_file() and p.suffix.lower() == ".iso":
                    target_list.append(p)
                elif p.is_dir():
                    for f in p.rglob("*.iso"):
                        target_list.append(f)
        return target_list

    def run_batch(self, input_paths: list, output_dir: str, mode: str, remove_sys_update: bool):
        self._cancel_requested = False
        out_path = Path(output_dir)
        targets = self.collect_targets(input_paths, mode)
        total_items = len(targets)

        if total_items == 0:
            self.log_cb("❌ Nenhum jogo válido encontrado para processamento.", "ERROR")
            self.finish_cb(0, 0, False)
            return

        out_path.mkdir(parents=True, exist_ok=True)
        self.log_cb(f"🚀 Iniciando fila com {total_items} item(ns) [Modo: {mode}]...", "INFO")
        success_count = 0

        for idx, target in enumerate(targets, start=1):
            if self._cancel_requested:
                break
            item_title = target.stem if target.is_file() else target.name
            self.log_cb(f"💿 [{idx}/{total_items}] Processando: {target.name}", "INFO")
            self.progress_cb(target.name, idx, total_items, 0)

            ok = False
            if mode == "REBUILD_ISO":
                out_iso = out_path / f"{item_title}.iso"
                self._current_worker = ISORedump(
                    log_cb=self.log_cb,
                    progress_cb=lambda pct: self.progress_cb(target.name, idx, total_items, pct),
                )
                ok = self._current_worker.rebuild(target, out_iso)
            elif mode == "XEX":
                self._current_worker = XEXExtractor(
                    log_cb=self.log_cb,
                    progress_cb=lambda pct: self.progress_cb(target.name, idx, total_items, pct),
                )
                ok = self._current_worker.extract(
                    iso_path=target, output_dir=out_path / item_title, remove_sys_update=remove_sys_update
                )
            elif mode == "GOD":
                self._current_worker = GODExtractor(
                    log_cb=self.log_cb,
                    progress_cb=lambda pct: self.progress_cb(target.name, idx, total_items, pct),
                )
                ok = self._current_worker.convert(iso_path=target, output_dir=out_path)

            if ok and not self._cancel_requested:
                success_count += 1
                self.progress_cb(target.name, idx, total_items, 100)
                self.log_cb(f"✅ Concluído: {item_title}", "SUCCESS")

        self.finish_cb(success_count, total_items, self._cancel_requested)