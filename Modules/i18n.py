import json
import locale
from pathlib import Path

class LanguageManager:
    def __init__(self):
        # Resolve caminhos relativos de forma segura a partir da pasta Modules
        self.root_dir = Path(__file__).resolve().parent.parent
        self.locales_dir = self.root_dir / "locales"
        self.config_file = self.root_dir / "config.json"
        
        self.strings = {}
        self.current_lang = "pt" # Fallback global
        
        self._initialize_language()

    def _initialize_language(self):
        saved_lang = self.load_preference()
        if saved_lang:
            self.current_lang = saved_lang
        else:
            try:
                sys_lang = locale.getdefaultlocale()[0][:2].lower()
                if (self.locales_dir / f"{sys_lang}.json").exists():
                    self.current_lang = sys_lang
            except Exception:
                pass

        if not self.load_language(self.current_lang):
            self.load_language("en")
            self.current_lang = "en"

    def load_preference(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("language")
            except Exception:
                pass
        return None

    def save_preference(self, lang_code):
        config = {}
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
            except Exception:
                pass
        
        config["language"] = lang_code
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=4)
            self.current_lang = lang_code
            self.load_language(lang_code)
        except Exception:
            pass

    def load_language(self, lang_code):
        file_path = self.locales_dir / f"{lang_code}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.strings = json.load(f)
                return True
            except Exception:
                pass
        return False

    def get(self, key, default=""):
        return self.strings.get(key, default if default else key)

# Instância global pronta para ser importada
lang_manager = LanguageManager()