import os
import ctypes
import platform
import shutil
import multiprocessing
from pathlib import Path


class GODExtractor:
    """
    Conversor GOD de alta performance (Engine FFI).
    Orquestra a DLL nativa em Rust aplicando paralelismo dinâmico,
    validação de hardware e otimização de I/O.
    """

    def __init__(self, log_cb=None, progress_cb=None):
        self.log_cb = log_cb or (lambda msg, tag="INFO": print(f"[{tag}] {msg}"))
        self.progress_cb = progress_cb or (lambda pct: None)
        self._cancel_requested = False
        self._lib = None

    def cancel(self):
        """Sinaliza interrupção da conversão."""
        self._cancel_requested = True

    def _get_optimal_threads(self) -> int:
        """
        Otimização: Calcula o número de threads ideal baseado no hardware.
        Deixa 1 núcleo livre para garantir que a interface (GUI) e o SO não engasguem.
        """
        try:
            cores = multiprocessing.cpu_count()
            return max(1, cores - 1)
        except NotImplementedError:
            return 4  # Fallback seguro para 4 threads

    def _check_disk_space(self, iso_path: Path, output_dir: Path) -> bool:
        """
        Otimização: Pre-check instantâneo de espaço livre.
        Impede que a engine aloque memória e inicie processos se o disco for falhar no meio.
        """
        try:
            iso_size = iso_path.stat().st_size
            free_space = shutil.disk_usage(output_dir).free
            
            # Margem de segurança de 100MB além do tamanho da ISO
            if free_space < (iso_size + 104_857_600):
                gb_needed = iso_size / (1024**3)
                self.log_cb(f"❌ Espaço insuficiente em {output_dir.drive}. Necessário: {gb_needed:.2f} GB", "ERROR")
                return False
            return True
        except Exception as e:
            self.log_cb(f"⚠️ Aviso ao checar espaço em disco: {e}", "WARN")
            return True

    def _load_library(self) -> bool:
        """Carrega a DLL nativa apenas uma vez para evitar vazamento de memória."""
        if self._lib is not None:
            return True

        system = platform.system()
        # Aponta para a pasta 'dll' na raiz do projeto X360 Multi Extrator
        project_root = Path(__file__).resolve().parent.parent
        dll_dir = project_root / "dll"

        lib_name = "iso2god-x86_64-windows.dll" if system == "Windows" else "iso2god-x86_64-linux.so"
        lib_path = dll_dir / lib_name

        if not lib_path.exists():
            self.log_cb(f"❌ Engine nativa não encontrada: {lib_path}", "ERROR")
            return False

        try:
            # WinDLL no Windows garante o chamamento correto da convenção C
            self._lib = ctypes.WinDLL(str(lib_path)) if system == "Windows" else ctypes.CDLL(str(lib_path))
            
            # Assinatura de memória da função FFI em Rust
            self._lib.run_iso2god.argtypes = [ctypes.c_char_p]
            self._lib.run_iso2god.restype = ctypes.c_int
            return True
        except Exception as e:
            self.log_cb(f"❌ Erro ao inicializar a engine na memória: {e}", "ERROR")
            return False

    def convert(self, iso_path: Path, output_dir: Path) -> bool:
        """
        Inicia a esteira de conversão de alta velocidade.
        """
        self._cancel_requested = False
        iso_path = Path(iso_path)
        output_dir = Path(output_dir)

        # 1. Validações Preliminares Ultrarrápidas
        if not iso_path.exists():
            self.log_cb(f"❌ Arquivo ISO ausente: {iso_path.name}", "ERROR")
            return False

        output_dir.mkdir(parents=True, exist_ok=True)

        if not self._check_disk_space(iso_path, output_dir):
            return False

        if not self._load_library():
            return False

        try:
            threads = self._get_optimal_threads()
            self.log_cb(f"🚀 Iniciando extração acelerada ({threads} Threads): {iso_path.name}", "INFO")
            self.progress_cb(10)

            # 2. Configuração dos Argumentos FFI
            abs_iso = iso_path.absolute().as_posix()
            abs_dest = output_dir.absolute().as_posix()

            # Passa a flag '-j' para a DLL explorar o paralelismo Rayon
            args_str = f". -j {threads} \"{abs_iso}\" \"{abs_dest}\""
            args_encoded = args_str.encode('utf-8')

            if self._cancel_requested:
                return False

            self.log_cb("⚙️ Engine STFS/Merkle Tree em execução (Operação intensiva no disco)...", "INFO")
            self.progress_cb(50)  # Progresso visual aguardando o processo bloqueante

            # 3. Execução Bruta (A DLL assume o I/O)
            result_code = self._lib.run_iso2god(ctypes.c_char_p(args_encoded))

            if self._cancel_requested:
                self.log_cb("🛑 Processo abortado com sucesso.", "WARN")
                return False

            # 4. Verificação de Sucesso
            if result_code == 0:
                self.progress_cb(100)
                self.log_cb(f"✅ Conversão GOD finalizada sem erros!", "SUCCESS")
                return True
            else:
                self.log_cb(f"❌ Engine retornou código de falha: {result_code} (Verifique se a ISO está corrompida)", "ERROR")
                return False

        except Exception as e:
            self.log_cb(f"❌ Falha crítica de execução FFI: {e}", "ERROR")
            return False