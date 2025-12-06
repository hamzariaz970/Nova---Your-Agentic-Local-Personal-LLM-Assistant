import os
import json
from typing import Dict, Any

from config import STORAGE_DIR  # reuse storage dir from config

# Where toggles are stored on disk
FEATURE_FLAGS_FILE = os.path.join(STORAGE_DIR, "feature_flags.json")

# These keys are what the web API exposes (see SettingsUpdate in web_app.py)
DEFAULT_FLAGS: Dict[str, Any] = {
    "use_web_search": False,   # allow http_get / web tools
    "use_gmail": False,        # (future) Gmail integration
    "use_calendar": False,     # (future) calendar integration
    "use_shell": False,        # allow run_shell_command
    "use_pdf_tables": True,    # allow PDF table extraction
}


class SettingsManager:
    """
    Small helper for storing / retrieving feature toggles.
    Backed by a JSON file in STORAGE_DIR.
    """

    def __init__(self, storage_dir: str = STORAGE_DIR):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self.path = FEATURE_FLAGS_FILE
        self._settings: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        flags = DEFAULT_FLAGS.copy()
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k in flags:
                            # Preserve boolean-ness where applicable
                            if isinstance(flags[k], bool):
                                flags[k] = bool(v)
                            else:
                                flags[k] = v
            except Exception:
                # Broken file? Just fall back to defaults.
                pass
        return flags

    def _save(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, ensure_ascii=False, indent=2)

    def get_settings(self) -> Dict[str, Any]:
        """Return a copy of current settings."""
        return dict(self._settings)

    def update_settings(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply updates (only keys in DEFAULT_FLAGS), persist, and return new settings.
        """
        for key, value in updates.items():
            if key in DEFAULT_FLAGS:
                if isinstance(DEFAULT_FLAGS[key], bool):
                    self._settings[key] = bool(value)
                else:
                    self._settings[key] = value
        self._save()
        return self.get_settings()
