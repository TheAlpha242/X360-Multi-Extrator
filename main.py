import sys
import ctypes
import tkinter.messagebox as messagebox
import customtkinter as ctk
from Modules import X360MultiExtratorGUI

def verificar_compatibilidade_so():
    """
    Verifica se o sistema operacional é compatível.
    Na versão 1.0, o software é restrito ao Windows devido às dependências 
    nativas (DLLs) necessárias para a conversão ISO2GOD.
    """
    if sys.platform != "win32":
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Sistema Operacional Não Suportado", 
            "O X360 Multi Extrator v1.0 requer o ambiente Windows devido aos submódulos "
            "nativos de conversão de mídia.\n\nO suporte multiplataforma (Linux/macOS) "
            "está planejado para atualizações futuras."
        )
        root.destroy()
        sys.exit(1)

def configurar_nitidez_windows():
    """Ativa o High-DPI no Windows para deixar as fontes da interface mais nítidas."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

def main():
    # 1. Trava de segurança para Sistema Operacional
    verificar_compatibilidade_so()
    
    # 2. Otimização de renderização (Windows High-DPI)
    configurar_nitidez_windows()
    
    # 3. Configurações Globais Visuais (Identidade Visual Xbox)
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("green")
    
    # 4. Inicialização da Aplicação CustomTkinter
    root = ctk.CTk()
    app = X360MultiExtratorGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()