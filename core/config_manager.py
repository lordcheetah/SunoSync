import json
import logging
import os
import tempfile

from core.paths import get_data_dir

logger = logging.getLogger(__name__)


class ConfigManager:
    """User settings persisted as JSON in the per-user data directory.

    Note on the auth token: it is stored in plain text in this file. That is a
    deliberate, documented trade-off rather than an oversight — see SECURITY.md.
    The file is created with owner-only permissions where the platform supports
    it, and `clear_token()` exists so users can revoke it without hand-editing.
    """

    def __init__(self, config_filename="config.json"):
        self.data_dir = get_data_dir()
        self.config_file = os.path.join(self.data_dir, config_filename)
        self.config = {}
        self.load_config()

    def load_config(self):
        if not os.path.exists(self.config_file):
            self.config = {}
            return

        try:
            with open(self.config_file, encoding="utf-8") as f:
                loaded = json.load(f)
            self.config = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError) as e:
            # A corrupt config should not wipe the user's settings silently.
            logger.error("Could not read config (%s); backing it up and starting fresh", e)
            self._backup_corrupt_file()
            self.config = {}

    def _backup_corrupt_file(self):
        backup = self.config_file + ".corrupt"
        try:
            os.replace(self.config_file, backup)
            logger.info("Unreadable config moved to %s", backup)
        except OSError:
            logger.exception("Could not back up unreadable config")

    def save_config(self):
        """Write atomically so an interrupted save cannot truncate the config."""
        try:
            fd, tmp_path = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.config, f, indent=4)
                self._restrict_permissions(tmp_path)
                os.replace(tmp_path, self.config_file)
            except Exception:
                # Clean up the temp file rather than leaving litter behind.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            logger.error("Error saving config: %s", e)

    @staticmethod
    def _restrict_permissions(path):
        """Best-effort owner-only permissions on the config file."""
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Not fatal; NTFS ACLs are the real control on Windows.
            pass

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    def clear_token(self):
        """Forget the stored Suno session token."""
        if self.config.pop("token", None) is not None:
            self.save_config()
            logger.info("Stored session token cleared")

    def get_data_dir(self):
        """Return the directory where data should be stored"""
        return self.data_dir
