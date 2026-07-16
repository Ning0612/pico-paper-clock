import importlib.util
import sys
import types
import unittest
from pathlib import Path


class WeatherDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_modules = {
            name: sys.modules.get(name)
            for name in ("display_utils", "image_manager", "display_manager")
        }
        cls.draw_images = []
        cls.draw_text = []

        display_utils_module = types.ModuleType("display_utils")
        display_utils_module.draw_scaled_text = lambda _canvas, *args: cls.draw_text.append(args)
        display_utils_module.draw_image = lambda _canvas, *args: cls.draw_images.append(args)
        display_utils_module.display_rotated_screen = lambda draw, **_kwargs: draw(object())
        sys.modules["display_utils"] = display_utils_module

        image_manager_module = types.ModuleType("image_manager")
        image_manager_module.image_catalog = types.SimpleNamespace()
        sys.modules["image_manager"] = image_manager_module

        source = Path(__file__).resolve().parents[1] / "src" / "display_manager.py"
        spec = importlib.util.spec_from_file_location("display_manager_test_target", source)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        for name, module in cls.original_modules.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def setUp(self):
        self.draw_images.clear()
        self.draw_text.clear()

    def test_weather_page_renders_four_future_days(self):
        forecast = [
            ("07-17", 30, "Clear", 10),
            ("07-18", 31, "Clouds", 20),
            ("07-19", 32, "Rain", 30),
            ("07-20", 29, "Drizzle", 40),
            ("07-21", 28, "Fog", 50),
        ]

        self.module.update_page_weather(
            (30, "Clear"),
            forecast,
            "/image/custom/test.bin",
            False,
            (2026, 7, 17, 12, 0, 0, 4, 198),
        )

        future_images = [
            args for args in self.draw_images
            if args[0].startswith("/image/weather_icons/") and args[4] == 80
        ]
        self.assertEqual(
            [args[0] for args in future_images],
            [
                "/image/weather_icons/Clouds.bin",
                "/image/weather_icons/Rain.bin",
                "/image/weather_icons/Drizzle.bin",
                "/image/weather_icons/Fog.bin",
            ],
        )
        self.assertEqual([args[3] for args in future_images], [8, 48, 88, 128])


if __name__ == "__main__":
    unittest.main()
