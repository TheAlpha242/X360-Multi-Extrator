import os
import time
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

from .extractor import XboxBatchExtractor
from .i18n import lang_manager

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("green")


class X360MultiExtratorGUI:
    def __init__(self, root):
        self.root = root
        
        # Variáveis da Aba 1 (Extração e Conversão)
        self.input_paths_list = []
        self.input_display = ctk.StringVar()
        self.output_path = ctk.StringVar()
        
        # A escolha padrão é definida diretamente pelo JSON carregado no i18n
        self.format_choice = ctk.StringVar(value=lang_manager.get("opt_xex"))
        self.remove_sys_update = ctk.BooleanVar(value=True)
        self.status_text = ctk.StringVar(value=lang_manager.get("status_wait"))
        self.batch_counter_text = ctk.StringVar(value="Lote: (0/0) | 0%")
        self.is_running = False

        # Variáveis da Aba 2 (Inspetor / Modding)
        self.inspect_file_path = None
        self.inspect_node_map = {}
        self.current_inspector_engine = None
        self.inspect_total_bytes = 0

        # Janela Base
        self.root.title(lang_manager.get("app_title"))
        self.root.geometry("1050x820")
        self.root.minsize(950, 750)
        self.root.configure(fg_color="#18181B")

        try:
            ico_path = Path(__file__).resolve().parent.parent / "img" / "logo.ico"
            if ico_path.exists():
                self.root.iconbitmap(str(ico_path))
        except Exception:
            pass

        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
            except Exception:
                pass

        self.backend = XboxBatchExtractor(
            log_cb=self.thread_safe_log,
            progress_cb=self.thread_safe_progress,
            finish_cb=self.thread_safe_finish,
        )

        self._build_ui()
        self.atualizar_textos() # Força a injeção do idioma detectado na primeira execução
        self._log_welcome()

    def mudar_idioma(self, novo_idioma):
        """Captura o ComboBox, converte para minúsculo e salva a preferência."""
        sigla = novo_idioma.lower()
        lang_manager.save_preference(sigla)
        self.atualizar_textos()

    def atualizar_textos(self):
        """Varre a interface traduzindo todos os widgets registrados."""
        t = lang_manager.get
        
        # Janela e Header
        self.root.title(t("app_title"))
        self.lbl_workspace.configure(text=t("workspace"))
        
        # Aba 1 - IO Card
        self.lbl_io_title.configure(text=t("io_title"))
        self.lbl_input.configure(text=t("lbl_in"))
        self.btn_sel_file.configure(text=t("btn_sel_file"))
        self.btn_sel_dir.configure(text=t("btn_sel_dir"))
        self.lbl_output.configure(text=t("lbl_out"))
        self.btn_sel_out.configure(text=t("btn_sel_out"))
        
        # Aba 1 - Config Card
        self.lbl_cfg_title.configure(text=t("cfg_title"))
        self.lbl_op.configure(text=t("lbl_op"))
        
        # Preservar estado da combobox após trocar o idioma das opções
        escolha_atual = self.format_choice.get()
        novas_opcoes = [t("opt_xex"), t("opt_god"), t("opt_rebuild")]
        self.format_combo.configure(values=novas_opcoes)
        if escolha_atual not in novas_opcoes:
            self.format_choice.set(novas_opcoes[0])

        self.chk_sys_update.configure(text=t("chk_sysup"))
        
        # Aba 1 - Console
        self.lbl_term_title.configure(text=t("term_title"))
        self.btn_start.configure(text=t("btn_cancel") if self.is_running else t("btn_start"))
        self.btn_clear.configure(text=t("btn_clear"))

        # Atualizar a barra de status principal apenas se não estiver rodando
        if not self.is_running:
            self.status_text.set(t("status_wait"))

        # Aba 2 - Inspetor Superior
        self.btn_inspect.configure(text=t("btn_insp"))
        
        if not self.inspect_file_path:
            self.lbl_insp_game.configure(text=t("lbl_game"))
            self.lbl_insp_tid.configure(text=t("lbl_tid"))
            self.lbl_insp_size.configure(text=t("lbl_size"))
            self.lbl_insp_fmt.configure(text=t("lbl_fmt"))
            self.lbl_node_name.configure(text=t("lbl_nome"))
            self.lbl_node_size.configure(text=t("lbl_size"))
            self.lbl_node_block.configure(text=t("col_block") + ": -")

        # Aba 2 - Painel Lateral
        self.lbl_det_title.configure(text=t("det_title"))
        self.btn_extract_sel.configure(text=t("btn_ext_sel"))
        self.lbl_mod_title.configure(text=t("mod_title"))
        self.btn_extract_proj.configure(text=t("btn_unpack"))
        self.btn_repack_proj.configure(text=t("btn_repack"))

        # Aba 2 - Treeview Headings
        self.tree.heading("#0", text=t("col_struct"))
        self.tree.heading("size", text=t("col_size"))
        self.tree.heading("block", text=t("col_block"))

    def _build_ui(self):
        # 1. HEADER
        header_frame = ctk.CTkFrame(self.root, fg_color="#107C10", corner_radius=0, height=70)
        header_frame.pack(fill="x", side="top")
        header_frame.pack_propagate(False)

        # Restaurado o nome da marca padrão independentemente do idioma
        self.lbl_app_title = ctk.CTkLabel(
            header_frame, text="🟢 X360 MULTI EXTRATOR", font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"), text_color="#FFFFFF"
        )
        self.lbl_app_title.pack(side="left", padx=20, pady=15)
        
        # COMBOBOX DE IDIOMA NO HEADER
        self.combo_idioma = ctk.CTkOptionMenu(
            header_frame, values=["PT", "EN", "ES"], command=self.mudar_idioma,
            fg_color="#18181B", button_color="#242429", button_hover_color="#3F3F46",
            width=70, height=28, font=ctk.CTkFont(size=12, weight="bold")
        )
        self.combo_idioma.set(lang_manager.current_lang.upper())
        self.combo_idioma.pack(side="right", padx=20, pady=20)

        self.lbl_workspace = ctk.CTkLabel(
            header_frame, text="", font=ctk.CTkFont(family="Segoe UI", size=11, slant="italic"), text_color="#E4E4E7"
        )
        self.lbl_workspace.pack(side="right", padx=20)

        main_container = ctk.CTkFrame(self.root, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=15, pady=(15, 0))

        # 2. SISTEMA DE ABAS
        self.tabview = ctk.CTkTabview(
            main_container, fg_color="#242429", segmented_button_selected_color="#107C10",
            segmented_button_selected_hover_color="#168a16", segmented_button_unselected_color="#18181B", text_color="#F4F4F5"
        )
        self.tabview.pack(fill="both", expand=True, pady=(0, 10))

        # RESTAURADOS OS NOMES ORIGINAIS DAS ABAS
        self.tab_extrator = self.tabview.add("📦 Extração e Conversão")
        self.tab_inspetor = self.tabview.add("🔍 Inspetor/Modding")

        self._build_tab_extrator()
        self._build_tab_inspetor()

        # 3. BARRA DE STATUS GLOBAL
        prog_header = ctk.CTkFrame(self.root, fg_color="transparent")
        prog_header.pack(fill="x", padx=15, pady=(0, 5))
        
        self.status_lbl = ctk.CTkLabel(
            prog_header, textvariable=self.status_text, font=ctk.CTkFont(size=11, weight="bold"), text_color="#F4F4F5", anchor="w"
        )
        self.status_lbl.pack(side="left")
        
        self.counter_lbl = ctk.CTkLabel(
            prog_header, textvariable=self.batch_counter_text, fg_color="#121215", text_color="#22C55E",
            font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), corner_radius=6, padx=8, height=24
        )
        self.counter_lbl.pack(side="right")
        
        self.progress_bar = ctk.CTkProgressBar(
            self.root, orientation="horizontal", fg_color="#121215", progress_color="#22C55E", height=14
        )
        self.progress_bar.pack(fill="x", padx=15, pady=(0, 15))
        self.progress_bar.set(0.0)

    def _build_tab_extrator(self):
        tab = self.tab_extrator
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # IO CARD
        io_card = ctk.CTkFrame(tab, fg_color="transparent")
        io_card.grid(row=0, column=0, sticky="ew", pady=(10, 5))
        
        self.lbl_io_title = ctk.CTkLabel(io_card, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22C55E")
        self.lbl_io_title.grid(row=0, column=0, columnspan=4, sticky="w", padx=15, pady=(0, 8))

        self.lbl_input = ctk.CTkLabel(io_card, text="", font=ctk.CTkFont(size=11, weight="bold"), text_color="#F4F4F5")
        self.lbl_input.grid(row=1, column=0, sticky="w", padx=15, pady=6)
        
        self.input_entry = ctk.CTkEntry(
            io_card, textvariable=self.input_display, fg_color="#121215", text_color="#F4F4F5",
            border_color="#3F3F46", font=ctk.CTkFont(family="Consolas", size=11), height=32
        )
        self.input_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        
        self.btn_sel_file = ctk.CTkButton(
            io_card, text="", command=self.browse_input_files, fg_color="#3F3F46", hover_color="#52525B", height=32, width=120
        )
        self.btn_sel_file.grid(row=1, column=2, padx=(0, 5), pady=6)
        
        self.btn_sel_dir = ctk.CTkButton(
            io_card, text="", command=self.browse_input_folder, fg_color="#3F3F46", hover_color="#52525B", height=32, width=120
        )
        self.btn_sel_dir.grid(row=1, column=3, padx=(0, 15), pady=6)

        self.lbl_output = ctk.CTkLabel(io_card, text="", font=ctk.CTkFont(size=11, weight="bold"), text_color="#F4F4F5")
        self.lbl_output.grid(row=2, column=0, sticky="w", padx=15, pady=6)
        
        self.output_entry = ctk.CTkEntry(
            io_card, textvariable=self.output_path, fg_color="#121215", text_color="#F4F4F5",
            border_color="#3F3F46", font=ctk.CTkFont(family="Consolas", size=11), height=32
        )
        self.output_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=(6, 12))
        
        self.btn_sel_out = ctk.CTkButton(
            io_card, text="", command=self.browse_output_folder, fg_color="#3F3F46", hover_color="#52525B", height=32
        )
        self.btn_sel_out.grid(row=2, column=2, columnspan=2, sticky="ew", padx=(0, 15), pady=(6, 12))
        io_card.columnconfigure(1, weight=1)

        # CONFIG CARD
        opt_card = ctk.CTkFrame(tab, fg_color="transparent")
        opt_card.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        
        self.lbl_cfg_title = ctk.CTkLabel(opt_card, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22C55E")
        self.lbl_cfg_title.grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(0, 8))
        
        self.lbl_op = ctk.CTkLabel(opt_card, text="", font=ctk.CTkFont(size=11, weight="bold"), text_color="#F4F4F5")
        self.lbl_op.grid(row=1, column=0, sticky="w", padx=15, pady=6)
        
        self.format_combo = ctk.CTkComboBox(
            opt_card, variable=self.format_choice, values=[], state="readonly", fg_color="#121215",
            button_color="#107C10", button_hover_color="#22C55E", border_color="#3F3F46",
            font=ctk.CTkFont(size=11, weight="bold"), width=340, height=32
        )
        self.format_combo.grid(row=1, column=1, sticky="w", padx=8, pady=6)
        
        self.chk_sys_update = ctk.CTkCheckBox(
            opt_card, text="", variable=self.remove_sys_update, font=ctk.CTkFont(size=11), text_color="#F4F4F5",
            checkmark_color="#FFFFFF", fg_color="#107C10", hover_color="#22C55E"
        )
        self.chk_sys_update.grid(row=2, column=0, columnspan=2, sticky="w", padx=15, pady=(8, 12))

        # TERMINAL CARD
        term_card = ctk.CTkFrame(tab, fg_color="transparent")
        term_card.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        
        self.lbl_term_title = ctk.CTkLabel(term_card, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22C55E")
        self.lbl_term_title.pack(anchor="w", padx=15, pady=(0, 5))
        
        term_container = ctk.CTkFrame(term_card, fg_color="#121215", corner_radius=6)
        term_container.pack(fill="both", expand=True, padx=15)
        
        self.terminal = tk.Text(
            term_container, bg="#121215", fg="#E4E4E7", font=("Consolas", 10),
            relief="flat", padx=10, pady=8, state="disabled", wrap="word", bd=0, highlightthickness=0
        )
        scrollbar = ctk.CTkScrollbar(term_container, command=self.terminal.yview, button_color="#3F3F46", button_hover_color="#52525B")
        self.terminal.configure(yscrollcommand=scrollbar.set)
        self.terminal.pack(side="left", fill="both", expand=True, padx=(2, 0), pady=2)
        scrollbar.pack(side="right", fill="y", padx=2, pady=2)
        
        self.terminal.tag_config("INFO", foreground="#60A5FA")
        self.terminal.tag_config("SUCCESS", foreground="#4ADE80")
        self.terminal.tag_config("WARN", foreground="#FACC15")
        self.terminal.tag_config("ERROR", foreground="#F87171")
        self.terminal.tag_config("PROGRESS", foreground="#A78BFA")

        # FOOTER
        footer_frame = ctk.CTkFrame(tab, fg_color="transparent")
        footer_frame.grid(row=3, column=0, sticky="ew", pady=(5, 10))
        
        self.btn_start = ctk.CTkButton(
            footer_frame, text="", command=self.on_start_or_cancel_clicked, fg_color="#107C10",
            hover_color="#168a16", font=ctk.CTkFont(size=12, weight="bold"), height=40
        )
        self.btn_start.pack(side="left", fill="x", expand=True, padx=(15, 5))
        
        self.btn_clear = ctk.CTkButton(
            footer_frame, text="", command=self.clear_terminal, fg_color="#3F3F46",
            hover_color="#52525B", font=ctk.CTkFont(size=11, weight="bold"), height=40, width=140
        )
        self.btn_clear.pack(side="right", padx=(5, 15))

    def _build_tab_inspetor(self):
        tab = self.tab_inspetor
        tab.grid_columnconfigure(0, weight=2)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # BARRA SUPERIOR DE INFORMAÇÕES
        top_bar = ctk.CTkFrame(tab, fg_color="#18181B", corner_radius=6, border_width=1, border_color="#3F3F46")
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=10)

        self.btn_inspect = ctk.CTkButton(
            top_bar, text="", command=self.on_inspect_clicked, fg_color="#107C10",
            hover_color="#168a16", font=ctk.CTkFont(size=11, weight="bold"), height=34
        )
        self.btn_inspect.pack(side="left", padx=10, pady=8)

        self.lbl_insp_game = ctk.CTkLabel(top_bar, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#FFFFFF")
        self.lbl_insp_game.pack(side="left", padx=12)

        self.lbl_insp_tid = ctk.CTkLabel(top_bar, text="", font=ctk.CTkFont(family="Consolas", size=11, weight="bold"), text_color="#60A5FA")
        self.lbl_insp_tid.pack(side="left", padx=12)

        self.lbl_insp_size = ctk.CTkLabel(top_bar, text="", font=ctk.CTkFont(family="Consolas", size=11), text_color="#FACC15")
        self.lbl_insp_size.pack(side="left", padx=12)

        self.lbl_insp_fmt = ctk.CTkLabel(top_bar, text="", font=ctk.CTkFont(size=11, slant="italic"), text_color="#22C55E")
        self.lbl_insp_fmt.pack(side="right", padx=15)

        # TREEVIEW
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview", background="#121215", foreground="#F4F4F5", fieldbackground="#121215",
            borderwidth=0, rowheight=25, font=("Consolas", 10)
        )
        style.map("Treeview", background=[("selected", "#107C10")])
        style.configure("Treeview.Heading", background="#242429", foreground="#22C55E", font=("Segoe UI", 10, "bold"), borderwidth=1, relief="flat")
        style.map("Treeview.Heading", background=[("active", "#3F3F46")])

        tree_frame = ctk.CTkFrame(tab, fg_color="#121215", corner_radius=6)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(tree_frame, columns=("size", "block"), show="tree headings")
        self.tree.column("#0", width=280)
        self.tree.column("size", width=90, anchor="e")
        self.tree.column("block", width=90, anchor="e")
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree.yview, button_color="#3F3F46", button_hover_color="#52525B")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(2, 0), pady=2)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=2, pady=2)

        # PAINEL DE DETALHES
        side_panel = ctk.CTkFrame(tab, fg_color="#18181B", corner_radius=6, border_width=1, border_color="#3F3F46")
        side_panel.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=(0, 10))

        self.lbl_det_title = ctk.CTkLabel(side_panel, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22C55E")
        self.lbl_det_title.pack(pady=(15, 10))
        
        self.lbl_node_name = ctk.CTkLabel(side_panel, text="", anchor="w", font=ctk.CTkFont(size=11))
        self.lbl_node_name.pack(fill="x", padx=15, pady=2)
        
        self.lbl_node_size = ctk.CTkLabel(side_panel, text="", anchor="w", font=ctk.CTkFont(size=11))
        self.lbl_node_size.pack(fill="x", padx=15, pady=2)
        
        self.lbl_node_block = ctk.CTkLabel(side_panel, text="", anchor="w", font=ctk.CTkFont(size=11))
        self.lbl_node_block.pack(fill="x", padx=15, pady=2)

        self.btn_extract_sel = ctk.CTkButton(
            side_panel, text="", command=self.extract_selected_node, fg_color="#3F3F46", hover_color="#52525B", font=ctk.CTkFont(size=11, weight="bold")
        )
        self.btn_extract_sel.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkFrame(side_panel, height=2, fg_color="#3F3F46").pack(fill="x", padx=15, pady=20)
        
        self.lbl_mod_title = ctk.CTkLabel(side_panel, text="", font=ctk.CTkFont(size=12, weight="bold"), text_color="#22C55E")
        self.lbl_mod_title.pack(pady=(0, 10))

        self.btn_extract_proj = ctk.CTkButton(
            side_panel, text="", command=self.extract_full_project, fg_color="#3F3F46", hover_color="#52525B", font=ctk.CTkFont(size=11, weight="bold")
        )
        self.btn_extract_proj.pack(fill="x", padx=15, pady=5)

        self.btn_repack_proj = ctk.CTkButton(
            side_panel, text="", state="disabled", fg_color="#107C10", font=ctk.CTkFont(size=11, weight="bold")
        )
        self.btn_repack_proj.pack(fill="x", padx=15, pady=5)

    def on_inspect_clicked(self):
        filepath = filedialog.askopenfilename(
            title="Select File",
            filetypes=[("All Supported Formats", "*.*")],
        )
        if not filepath:
            return

        self.log(f"🔍 Inspecting: {Path(filepath).name}", "INFO")
        self.tree.delete(*self.tree.get_children())
        self.inspect_node_map.clear()
        
        t = lang_manager.get
        self.lbl_node_name.configure(text=t("lbl_nome"))
        self.lbl_node_size.configure(text=t("lbl_size"))
        self.lbl_node_block.configure(text=t("col_block") + ": -")

        info = self.backend.inspect_file(Path(filepath))

        if info["format"] == "Desconhecido" or not info["tree_root"]:
            messagebox.showwarning("Warning", t("msg_incomp"))
            self.lbl_insp_game.configure(text=t("lbl_game"))
            self.lbl_insp_tid.configure(text=t("lbl_tid"))
            self.lbl_insp_size.configure(text=t("lbl_size"))
            self.lbl_insp_fmt.configure(text=t("lbl_fmt"))
            return

        self.inspect_file_path = Path(filepath)
        self.current_inspector_engine = info["engine"]
        self.inspect_total_bytes = info.get("total_size_mb", 0.0) * (1024 * 1024)

        self.lbl_insp_game.configure(text=f"🎮 Jogo: {info['game_name']}")
        self.lbl_insp_tid.configure(text=f"🏷️ Title ID: {info['title_id']}")
        self.lbl_insp_size.configure(text=f"💾 {info.get('total_size_mb', 0.0):.2f} MB")
        self.lbl_insp_fmt.configure(text=f"⚡ {info['format']}")

        self._populate_tree(info["tree_root"], "")
        self.log(f"✅ Tree loaded: {info['game_name']} [{info['format']}]", "SUCCESS")

    def _populate_tree(self, node, parent_item_id):
        if node.name == "ROOT":
            for child in node.children:
                self._populate_tree(child, "")
            return

        size_mb = f"{node.size / (1024 * 1024):.2f}" if not node.is_dir else "-"
        block = str(node.start_block) if not node.is_dir else "-"
        icon = "📁 " if node.is_dir else "📄 "

        item_id = self.tree.insert(parent_item_id, "end", text=icon + node.name, values=(size_mb, block))
        self.inspect_node_map[item_id] = node

        for child in node.children:
            self._populate_tree(child, item_id)

    def on_tree_select(self, event):
        selected = self.tree.selection()
        if not selected:
            return
        node = self.inspect_node_map.get(selected[0])
        if node:
            t = lang_manager.get
            self.lbl_node_name.configure(text=t("lbl_nome").replace("-", "") + node.name)
            self.lbl_node_size.configure(
                text=t("lbl_size").replace("-", "") + f"{node.size / (1024 * 1024):.2f} MB" if not node.is_dir else t("lbl_size")
            )
            self.lbl_node_block.configure(
                text=t("col_block") + ": " + f"{node.start_block}" if not node.is_dir else t("col_block") + ": -"
            )

    def extract_selected_node(self):
        selected = self.tree.selection()
        if not selected or not self.current_inspector_engine:
            return
        node = self.inspect_node_map.get(selected[0])

        save_path = filedialog.askdirectory(title="Save...")
        if not save_path:
            return

        target = Path(save_path) / node.name
        self._start_async_extraction(node, target, is_full_project=False)

    def extract_full_project(self):
        if not self.current_inspector_engine:
            return
        save_path = filedialog.askdirectory(title="Save Project...")
        if not save_path:
            return

        root_node = self.current_inspector_engine.tree_root
        target = Path(save_path) / f"ModProject_{self.inspect_file_path.name}"
        self._start_async_extraction(root_node, target, is_full_project=True)

    def _start_async_extraction(self, node, target, is_full_project):
        self.btn_extract_sel.configure(state="disabled")
        self.btn_extract_proj.configure(state="disabled")
        self.progress_bar.set(0.0)

        def worker():
            total_bytes = self.inspect_total_bytes if is_full_project else (node.size if not node.is_dir else 1)
            if total_bytes == 0:
                total_bytes = 1

            def progress_callback(filename, bytes_done):
                pct = min(1.0, bytes_done / total_bytes)
                pct_100 = int(pct * 100)
                self.root.after(0, lambda: self.progress_bar.set(pct))
                self.root.after(0, lambda: self.status_text.set(f"⚡ Extracting: {filename} ({pct_100}%)"))
                self.root.after(0, lambda: self.batch_counter_text.set(f"{pct_100}%"))

            self.log(f"🚀 Iniciando extração: {target.name}...", "INFO")
            try:
                if is_full_project:
                    target.mkdir(parents=True, exist_ok=True)
                    tracker = [0]
                    for child in node.children:
                        self.current_inspector_engine.extract_node(
                            child, target / child.name, progress_callback, tracker
                        )
                else:
                    self.current_inspector_engine.extract_node(node, target, progress_callback)

                self.root.after(0, lambda: self.progress_bar.set(1.0))
                self.root.after(0, lambda: self.status_text.set("🎉 Finalizado com sucesso!"))
                self.root.after(0, lambda: self.batch_counter_text.set("100%"))
                self.log(f"✅ Extração concluída!", "SUCCESS")
                self._play_completion_sound()
            except Exception as e:
                self.log(f"❌ Erro na extração: {e}", "ERROR")
            finally:
                self.root.after(0, lambda: self.btn_extract_sel.configure(state="normal"))
                self.root.after(0, lambda: self.btn_extract_proj.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _play_completion_sound(self):
        if not PYGAME_AVAILABLE:
            return
        def _play():
            try:
                sound_path = Path(__file__).resolve().parent.parent / "sounds" / "complete.mp3"
                if sound_path.exists():
                    pygame.mixer.music.load(str(sound_path))
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        pygame.time.Clock().tick(10)
            except Exception:
                pass
        threading.Thread(target=_play, daemon=True).start()

    def _log_welcome(self):
        self.log("==========================================================", "INFO")
        self.log(" 🎮 X360 MULTI EXTRATOR & REDUMP ", "SUCCESS")
        self.log("==========================================================", "INFO")

    def thread_safe_log(self, message, tag="INFO"):
        self.root.after(0, self.log, message, tag)

    def thread_safe_progress(self, game_name, current_idx, total_games, percent):
        self.root.after(0, self.update_realtime_progress, game_name, current_idx, total_games, percent)

    def thread_safe_finish(self, success_count, total_games, cancelled):
        self.root.after(0, self._on_batch_finished, success_count, total_games, cancelled)

    def log(self, message, tag="INFO"):
        self.terminal.configure(state="normal")
        timestamp = time.strftime("%H:%M:%S")
        self.terminal.insert(tk.END, f"[{timestamp}] {message}\n", tag)
        self.terminal.see(tk.END)
        self.terminal.configure(state="disabled")

    def update_realtime_progress(self, game_name, current_idx, total_games, percent):
        line_text = f"⚡ Processando: {game_name} ({current_idx}/{total_games}) {percent}%"
        self.status_text.set(line_text)
        self.batch_counter_text.set(f"Batch: ({current_idx}/{total_games}) | {percent}%")
        self.progress_bar.set(percent / 100.0)

        self.terminal.configure(state="normal")
        last_line_index = self.terminal.index("end-2c linestart")
        last_line_content = self.terminal.get(last_line_index, "end-1c")

        if "Processando:" in last_line_content:
            self.terminal.delete(last_line_index, "end-1c")
            self.terminal.insert(last_line_index, f"{line_text}\n", "PROGRESS")
        else:
            self.terminal.insert(tk.END, f"{line_text}\n", "PROGRESS")
        self.terminal.see(tk.END)
        self.terminal.configure(state="disabled")

    def clear_terminal(self):
        self.terminal.configure(state="normal")
        self.terminal.delete("1.0", tk.END)
        self.terminal.configure(state="disabled")
        self._log_welcome()

    def browse_input_files(self):
        file_paths = filedialog.askopenfilenames(
            title="Select File",
            filetypes=[("All Supported", "*.* *.iso *.ISO"), ("ISO", "*.iso *.ISO")],
        )
        if file_paths:
            self.input_paths_list = list(file_paths)
            qtd = len(self.input_paths_list)
            if qtd == 1:
                self.input_display.set(self.input_paths_list[0])
                self.log(f"📄 Arquivo selecionado: {Path(self.input_paths_list[0]).name}", "INFO")
            else:
                self.input_display.set(f"<{qtd} files selected>")
                self.log(f"📄 Files: {qtd}", "INFO")

    def browse_input_folder(self):
        folder_path = filedialog.askdirectory(title="Select Folder")
        if folder_path:
            self.input_paths_list = [folder_path]
            self.input_display.set(folder_path)
            self.log(f"📁 Pasta selecionada: {folder_path}", "SUCCESS")

    def browse_output_folder(self):
        folder_path = filedialog.askdirectory(title="Output Folder")
        if folder_path:
            self.output_path.set(folder_path)
            self.log(f"💾 Saída: {folder_path}", "INFO")

    def on_start_or_cancel_clicked(self):
        t = lang_manager.get
        
        if self.is_running:
            if messagebox.askyesno("Confirm", t("msg_cancel")):
                self.backend.cancel()
            return

        if not self.input_paths_list:
            text_val = self.input_display.get().strip()
            if text_val and "<" not in text_val:
                self.input_paths_list = [text_val]

        out = self.output_path.get().strip()
        if not self.input_paths_list or not out:
            messagebox.showwarning("Warning", t("msg_warn_io"))
            return

        escolha = self.format_choice.get()
        if escolha == t("opt_rebuild"):
            modo = "REBUILD_ISO"
        elif escolha == t("opt_god"):
            modo = "GOD"
        else:
            modo = "XEX"

        limpar = self.remove_sys_update.get()
        self.is_running = True
        self.btn_start.configure(text=t("btn_cancel"), fg_color="#DC2626", hover_color="#B91C1C")

        threading.Thread(
            target=self.backend.run_batch, args=(self.input_paths_list, out, modo, limpar), daemon=True
        ).start()

    def _on_batch_finished(self, success_count, total_games, cancelled):
        self.is_running = False
        t = lang_manager.get
        self.btn_start.configure(text=t("btn_start"), fg_color="#107C10", hover_color="#168a16")
        
        if cancelled:
            self.status_text.set(f"🛑 Cancelled ({success_count}/{total_games}).")
        elif total_games > 0 and success_count == total_games:
            self.status_text.set(f"🎉 100% Completo!")
            self._play_completion_sound()
        elif total_games > 0:
            self.status_text.set(f"⚠️ Warnings ({success_count}/{total_games}).")
            self._play_completion_sound()