import ujson
import os

CONFIG_FILE = 'config.json'

class ConfigManager:
    """Manages application configuration with multi-profile support."""

    def __init__(self):
        self.config = self._load_config()
        self._migrate_legacy_config()

    def _load_config(self):
        """Loads configuration from the CONFIG_FILE."""
        try:
            with open(CONFIG_FILE, 'r') as f:
                return ujson.load(f)
        except (OSError, ValueError):
            # Return new format default config
            return self._get_default_config()

    def _get_default_config(self):
        """Returns a default configuration in new format."""
        return {
            "global": {
                "ap_mode": {
                    "ssid": "Pi_Clock_AP",
                    "password": "12345678"
                },
                "weather_api_key": "",
                "discord_webhook_url": "",
                "lan_admin": {
                    "username": "admin",
                    "password": "admin"
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
            new_config = {
                "global": {
                    "ap_mode": {
                        "ssid": legacy.get("ap_mode", {}).get("ssid", "Pi_Clock_AP"),
                        "password": legacy.get("ap_mode", {}).get("password", "12345678")
                    },
                    "weather_api_key": legacy.get("weather", {}).get("api_key", ""),
                    "discord_webhook_url": "",
                    "lan_admin": {
                        "username": "admin",
                        "password": "admin"
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

    def _save_config(self):
        """Saves the current configuration to the CONFIG_FILE."""
        with open(CONFIG_FILE, 'w') as f:
            ujson.dump(self.config, f)

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
        if self.get_profile(profile_name) is None:
            raise ValueError(f"Profile '{profile_name}' does not exist.")

        self.config["active_profile"] = profile_name
        self._save_config()

    def set_last_connected_profile(self, profile_name):
        """Records the last successfully connected profile."""
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
        keys = key.split('.')
        if "global" not in self.config:
            self.config["global"] = {}
        val = self.config["global"]
        for i, k in enumerate(keys):
            if i == len(keys) - 1:
                val[k] = value
            else:
                if k not in val or not isinstance(val[k], dict):
                    val[k] = {}
                val = val[k]
        self._save_config()

config_manager = ConfigManager()
