import ujson
import os

CONFIG_FILE = 'config.json'
CONFIG_TMP_FILE = CONFIG_FILE + '.tmp'
CONFIG_BACKUP_FILE = CONFIG_FILE + '.bak'
CONFIG_SCHEMA_VERSION = 3

class ConfigManager:
    """Manages application configuration with multi-profile support."""

    def __init__(self):
        self.config = self._load_config()
        self.read_only = self._schema_version_value() > CONFIG_SCHEMA_VERSION
        if self.read_only:
            print("Warning: Config schema is newer than this firmware; using read-only compatibility mode.")
            return
        self._migrate_legacy_config()
        self._normalize_config()

    def _load_config(self):
        """Loads configuration from the CONFIG_FILE."""
        for candidate in (CONFIG_FILE, CONFIG_TMP_FILE, CONFIG_BACKUP_FILE):
            if not self._path_exists(candidate):
                continue
            try:
                with open(candidate, 'r') as f:
                    config = ujson.load(f)
                if candidate != CONFIG_FILE:
                    try:
                        os.remove(CONFIG_FILE)
                    except OSError:
                        pass
                    os.rename(candidate, CONFIG_FILE)
                for stale in (CONFIG_TMP_FILE, CONFIG_BACKUP_FILE):
                    if stale == candidate:
                        continue
                    try:
                        os.remove(stale)
                    except OSError:
                        pass
                return config
            except (OSError, ValueError):
                continue
        return self._get_default_config()

    def _path_exists(self, path):
        try:
            os.stat(path)
            return True
        except OSError:
            return False

    def _get_default_config(self):
        """Returns a default configuration in new format."""
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "global": {
                "ap_mode": {
                    "ssid": "Pi_Clock_AP",
                    "password": "12345678"
                },
                "weather_api_key": "",
                "discord_webhook_url": "",
                "env_log": {
                    "enabled": True,
                    "interval_min": 15
                },
                "setup_complete": False,
                "lan_admin": {
                    "username": "admin",
                    "password": ""
                }
            },
            "profiles": [
                {
                    "name": "預設",
                    "wifi": {
                        "ssid": "",
                        "password": ""
                    },
                    "weather_location": "Taipei",
                    "user": {
                        "birthday": "0101",
                        "light_threshold": 56000,
                        "presence_leave_timeout_sec": 180,
                        "presence_return_timeout_sec": 10,
                        "image_interval_min": 2,
                        "timezone_offset": 8
                    },
                    "chime": {
                        "enabled": True,
                        "interval": "hourly",
                        "pitch": 880,
                        "volume": 80
                    }
                }
            ],
            "active_profile": "預設",
            "last_connected_profile": None
        }

    def _migrate_legacy_config(self):
        """Migrates legacy config format to new multi-profile format."""
        # Check if config is in legacy format (no "global" or "profiles" keys)
        if "global" not in self.config and "profiles" not in self.config:
            print("Info: Detecting legacy config format. Migrating to multi-profile format...")

            legacy = self.config
            legacy_leave_timeout_sec = self._clamp_int(
                legacy.get("user", {}).get("presence_timeout_min"), 1, 60, 3
            ) * 60
            new_config = {
                "schema_version": CONFIG_SCHEMA_VERSION,
                "global": {
                    "ap_mode": {
                        "ssid": legacy.get("ap_mode", {}).get("ssid", "Pi_Clock_AP"),
                        "password": legacy.get("ap_mode", {}).get("password", "12345678")
                    },
                    "weather_api_key": legacy.get("weather", {}).get("api_key", ""),
                    "discord_webhook_url": "",
                    "setup_complete": bool(legacy.get("wifi", {}).get("ssid", "")),
                    "lan_admin": {
                        "username": "admin",
                        "password": ""
                    }
                },
                "profiles": [
                    {
                        "name": "預設",
                        "wifi": {
                            "ssid": legacy.get("wifi", {}).get("ssid", ""),
                            "password": legacy.get("wifi", {}).get("password", "")
                        },
                        "weather_location": legacy.get("weather", {}).get("location", "Taipei"),
                        "user": {
                            "birthday": legacy.get("user", {}).get("birthday", "0101"),
                            "light_threshold": legacy.get("user", {}).get("light_threshold", 56000),
                            "presence_leave_timeout_sec": legacy_leave_timeout_sec,
                            "presence_return_timeout_sec": 10,
                            "image_interval_min": legacy.get("user", {}).get("image_interval_min", 2),
                            "timezone_offset": legacy.get("user", {}).get("timezone_offset", 8)
                        },
                        "chime": {
                            "enabled": legacy.get("chime", {}).get("enabled", True),
                            "interval": legacy.get("chime", {}).get("interval", "hourly"),
                            "pitch": legacy.get("chime", {}).get("pitch", 880),
                            "volume": legacy.get("chime", {}).get("volume", 80)
                        }
                    }
                ],
                "active_profile": "預設",
                "last_connected_profile": None
            }

            self.config = new_config
            self._save_config()
            print("Success: Config migrated to multi-profile format.")
        elif self._schema_version_value() < CONFIG_SCHEMA_VERSION:
            self.config["schema_version"] = CONFIG_SCHEMA_VERSION
            self._save_config()
        elif self._schema_version_value() > CONFIG_SCHEMA_VERSION:
            print("Warning: Config schema is newer than this firmware; preserving version.")

    def _normalize_config(self):
        """Fill required v3 keys and clamp hardware-facing numeric settings."""
        changed = False
        defaults = self._get_default_config()
        if not isinstance(self.config.get("global"), dict):
            self.config["global"] = defaults["global"]
            changed = True
        global_config = self.config["global"]
        for key, value in defaults["global"].items():
            if key not in global_config:
                global_config[key] = value
                changed = True
            elif isinstance(value, dict) and isinstance(global_config[key], dict):
                for child_key, child_value in value.items():
                    if child_key not in global_config[key]:
                        global_config[key][child_key] = child_value
                        changed = True

        profiles = self.config.get("profiles")
        if not isinstance(profiles, list) or not profiles:
            self.config["profiles"] = defaults["profiles"]
            profiles = self.config["profiles"]
            changed = True
        profile_default = defaults["profiles"][0]
        for profile in profiles:
            if "name" not in profile:
                profile["name"] = "預設"
                changed = True
            for section in ("wifi", "user", "chime"):
                if not isinstance(profile.get(section), dict):
                    profile[section] = dict(profile_default[section])
                    changed = True
                else:
                    for key, value in profile_default[section].items():
                        if key not in profile[section]:
                            profile[section][key] = value
                            changed = True
            if "weather_location" not in profile:
                profile["weather_location"] = profile_default["weather_location"]
                changed = True

            user = profile["user"]
            legacy_leave_timeout_min = user.get("presence_timeout_min")
            has_leave_timeout_sec = "presence_leave_timeout_sec" in user
            normalized = {
                "light_threshold": self._clamp_int(user.get("light_threshold"), 0, 65535, 56000),
                "presence_leave_timeout_sec": self._clamp_int(user.get("presence_leave_timeout_sec"), 60, 3600, 180),
                "presence_return_timeout_sec": self._clamp_int(user.get("presence_return_timeout_sec"), 0, 60, 10),
                "image_interval_min": self._clamp_int(user.get("image_interval_min"), 1, 60, 2),
                "timezone_offset": self._clamp_int(user.get("timezone_offset"), -12, 14, 8),
            }
            if not has_leave_timeout_sec and legacy_leave_timeout_min is not None:
                normalized["presence_leave_timeout_sec"] = self._clamp_int(
                    legacy_leave_timeout_min, 1, 60, 3
                ) * 60
            if "presence_timeout_min" in user:
                del user["presence_timeout_min"]
                changed = True
            chime = profile["chime"]
            normalized_chime = {
                "pitch": self._clamp_int(chime.get("pitch"), 100, 5000, 880),
                "volume": self._clamp_int(chime.get("volume"), 0, 100, 80),
            }
            for key, value in normalized.items():
                if user.get(key) != value:
                    user[key] = value
                    changed = True
            for key, value in normalized_chime.items():
                if chime.get(key) != value:
                    chime[key] = value
                    changed = True

        names = [profile.get("name") for profile in profiles]
        if self.config.get("active_profile") not in names:
            self.config["active_profile"] = names[0]
            changed = True
        if self.config.get("last_connected_profile") not in names:
            if self.config.get("last_connected_profile") is not None:
                self.config["last_connected_profile"] = None
                changed = True
        active = self.get_active_profile()
        if not global_config.get("setup_complete") and active and active.get("wifi", {}).get("ssid", ""):
            global_config["setup_complete"] = True
            changed = True
        if self._schema_version_value() < CONFIG_SCHEMA_VERSION:
            self.config["schema_version"] = CONFIG_SCHEMA_VERSION
            changed = True
        if changed:
            self._save_config()

    def _clamp_int(self, value, minimum, maximum, default):
        try:
            return min(maximum, max(minimum, int(value)))
        except (TypeError, ValueError):
            return default

    def _schema_version_value(self):
        try:
            return int(self.config.get("schema_version", 0))
        except (TypeError, ValueError):
            return 0

    def _save_config(self):
        """Saves the current configuration to the CONFIG_FILE."""
        if self.read_only:
            raise ValueError("Configuration schema is newer than this firmware.")
        with open(CONFIG_TMP_FILE, 'w') as f:
            ujson.dump(self.config, f)
        if hasattr(os, "sync"):
            os.sync()
        moved_existing = False
        try:
            os.remove(CONFIG_BACKUP_FILE)
        except OSError:
            pass
        try:
            if self._path_exists(CONFIG_FILE):
                os.rename(CONFIG_FILE, CONFIG_BACKUP_FILE)
                moved_existing = True
            os.rename(CONFIG_TMP_FILE, CONFIG_FILE)
            if hasattr(os, "sync"):
                os.sync()
            if moved_existing:
                try:
                    os.remove(CONFIG_BACKUP_FILE)
                except OSError:
                    pass
        except Exception:
            if moved_existing and not self._path_exists(CONFIG_FILE) and self._path_exists(CONFIG_BACKUP_FILE):
                try:
                    os.rename(CONFIG_BACKUP_FILE, CONFIG_FILE)
                except OSError:
                    pass
            raise

    def _require_writable(self):
        if self.read_only:
            raise ValueError("Configuration schema is newer than this firmware.")

    def _set_global_value(self, key, value):
        keys = key.split('.')
        if "global" not in self.config:
            self.config["global"] = {}
        target = self.config["global"]
        for index, part in enumerate(keys):
            if index == len(keys) - 1:
                target[part] = value
            else:
                if part not in target or not isinstance(target[part], dict):
                    target[part] = {}
                target = target[part]

    def apply_profile_update(self, original_name, profile_data, global_updates=None,
                             activate=True, mark_connected=True):
        """Validates and saves a profile plus global settings in one flash transaction."""
        self._require_writable()
        new_name = profile_data.get("name", "")
        if not new_name:
            raise ValueError("Profile name is required.")
        if original_name != new_name and self.get_profile(new_name) is not None:
            raise ValueError("Profile name already exists.")

        target_index = -1
        for index, profile in enumerate(self.config.get("profiles", [])):
            if profile.get("name") == original_name:
                target_index = index
                break
        if target_index < 0:
            raise ValueError("Profile does not exist.")

        self.config["profiles"][target_index] = profile_data
        for key, value in (global_updates or {}).items():
            if value is not None:
                self._set_global_value(key, value)
        if activate:
            self.config["active_profile"] = new_name
        elif self.config.get("active_profile") == original_name:
            self.config["active_profile"] = new_name
        if mark_connected:
            self.config["last_connected_profile"] = new_name
        elif self.config.get("last_connected_profile") == original_name:
            self.config["last_connected_profile"] = new_name
        if self._schema_version_value() <= CONFIG_SCHEMA_VERSION:
            self.config["schema_version"] = CONFIG_SCHEMA_VERSION
        try:
            self._save_config()
        except Exception:
            self.config = self._load_config()
            raise
        return True

    # ========== Profile Management Methods ==========

    def list_profiles(self):
        """Returns a list of all profile names."""
        return [p["name"] for p in self.config.get("profiles", [])]

    def get_profile(self, profile_name):
        """Returns the complete profile data for a given profile name."""
        for profile in self.config.get("profiles", []):
            if profile["name"] == profile_name:
                return profile
        return None

    def add_profile(self, profile_data):
        """
        Adds a new profile to the configuration.
        profile_data should be a complete profile dict with all required fields.
        """
        self._require_writable()
        # Check if profile name already exists
        if self.get_profile(profile_data["name"]) is not None:
            raise ValueError(f"Profile '{profile_data['name']}' already exists.")

        # Ensure profiles list exists
        if "profiles" not in self.config:
            self.config["profiles"] = []

        self.config["profiles"].append(profile_data)
        self._save_config()

    def update_profile(self, profile_name, profile_data):
        """Updates an existing profile with new data."""
        self._require_writable()
        for i, profile in enumerate(self.config.get("profiles", [])):
            if profile["name"] == profile_name:
                # If name is being changed, check for conflicts
                if profile_data["name"] != profile_name:
                    if self.get_profile(profile_data["name"]) is not None:
                        raise ValueError(f"Profile name '{profile_data['name']}' already exists.")

                self.config["profiles"][i] = profile_data

                # Update active_profile and last_connected_profile if necessary
                if self.config.get("active_profile") == profile_name:
                    self.config["active_profile"] = profile_data["name"]
                if self.config.get("last_connected_profile") == profile_name:
                    self.config["last_connected_profile"] = profile_data["name"]

                self._save_config()
                return True
        return False

    def delete_profile(self, profile_name):
        """Deletes a profile from the configuration."""
        self._require_writable()
        # Don't allow deleting the last profile
        if len(self.config.get("profiles", [])) <= 1:
            raise ValueError("Cannot delete the last profile.")

        for i, profile in enumerate(self.config.get("profiles", [])):
            if profile["name"] == profile_name:
                del self.config["profiles"][i]

                # If deleted profile was active, switch to first available
                if self.config.get("active_profile") == profile_name:
                    self.config["active_profile"] = self.config["profiles"][0]["name"]
                if self.config.get("last_connected_profile") == profile_name:
                    self.config["last_connected_profile"] = None

                self._save_config()
                return True
        return False

    def get_active_profile_name(self):
        """Returns the name of the currently active profile."""
        return self.config.get("active_profile", self.list_profiles()[0] if self.list_profiles() else None)

    def get_active_profile(self):
        """Returns the complete data of the currently active profile."""
        active_name = self.get_active_profile_name()
        return self.get_profile(active_name) if active_name else None

    def set_active_profile(self, profile_name):
        """Sets the active profile."""
        self._require_writable()
        if self.get_profile(profile_name) is None:
            raise ValueError(f"Profile '{profile_name}' does not exist.")

        self.config["active_profile"] = profile_name
        self._save_config()

    def set_last_connected_profile(self, profile_name):
        """Records the last successfully connected profile."""
        self._require_writable()
        if profile_name is not None and self.get_profile(profile_name) is None:
            raise ValueError(f"Profile '{profile_name}' does not exist.")

        self.config["last_connected_profile"] = profile_name
        self._save_config()

    def get_last_connected_profile_name(self):
        """Returns the name of the last successfully connected profile."""
        return self.config.get("last_connected_profile")

    def find_profile_by_ssid(self, ssid):
        """Finds and returns the first profile that matches the given WiFi SSID."""
        for profile in self.config.get("profiles", []):
            if profile.get("wifi", {}).get("ssid") == ssid:
                return profile
        return None

    # ========== Backward Compatible Methods ==========

    def get(self, key, default=None):
        """
        Retrieves a configuration value using a dot-separated key.
        Supports both legacy and new format.
        For new format, reads from active profile or global settings.
        """
        # Handle global settings
        if key.startswith("ap_mode."):
            sub_key = key[8:]  # Remove "ap_mode."
            val = self.config.get("global", {}).get("ap_mode", {})
            if sub_key in val:
                return val[sub_key]
            return default

        if key == "weather.api_key":
            return self.config.get("global", {}).get("weather_api_key", default)

        # Handle profile-specific settings from active profile
        active_profile = self.get_active_profile()
        if not active_profile:
            return default

        # Map legacy keys to new profile structure
        if key.startswith("wifi."):
            sub_key = key[5:]  # Remove "wifi."
            val = active_profile.get("wifi", {})
            if sub_key in val:
                return val[sub_key]
            return default

        if key == "weather.location":
            return active_profile.get("weather_location", default)

        if key.startswith("user."):
            sub_key = key[5:]  # Remove "user."
            val = active_profile.get("user", {})
            if sub_key in val:
                return val[sub_key]
            return default

        if key.startswith("chime."):
            sub_key = key[6:]  # Remove "chime."
            val = active_profile.get("chime", {})
            if sub_key in val:
                return val[sub_key]
            return default

        return default

    def set(self, key, value):
        """
        Sets a configuration value using a dot-separated key.
        Automatically determines whether to set in global or active profile.
        """
        self._require_writable()
        # Handle global settings
        if key.startswith("ap_mode."):
            sub_key = key[8:]
            if "global" not in self.config:
                self.config["global"] = {"ap_mode": {}}
            if "ap_mode" not in self.config["global"]:
                self.config["global"]["ap_mode"] = {}
            self.config["global"]["ap_mode"][sub_key] = value
            self._save_config()
            return

        if key == "weather.api_key":
            if "global" not in self.config:
                self.config["global"] = {}
            self.config["global"]["weather_api_key"] = value
            self._save_config()
            return

        # Handle profile-specific settings - update active profile
        active_profile = self.get_active_profile()
        if not active_profile:
            return

        if key.startswith("wifi."):
            sub_key = key[5:]
            if "wifi" not in active_profile:
                active_profile["wifi"] = {}
            active_profile["wifi"][sub_key] = value
        elif key == "weather.location":
            active_profile["weather_location"] = value
        elif key.startswith("user."):
            sub_key = key[5:]
            if "user" not in active_profile:
                active_profile["user"] = {}
            active_profile["user"][sub_key] = value
        elif key.startswith("chime."):
            sub_key = key[6:]
            if "chime" not in active_profile:
                active_profile["chime"] = {}
            active_profile["chime"][sub_key] = value

        # Update the profile in the config
        self.update_profile(active_profile["name"], active_profile)

    def get_global(self, key, default=None):
        """Gets a value from global settings."""
        keys = key.split('.')
        val = self.config.get("global", {})
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def set_global(self, key, value):
        """Sets a value in global settings."""
        self._require_writable()
        self._set_global_value(key, value)
        self._save_config()

config_manager = ConfigManager()
