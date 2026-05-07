# main.py
import time
import gc
from wifi_manager import wifi_manager, create_lan_config_server
from netutils import sync_time
from file_manager import list_files, shuffle_files
from display_manager import update_page_loading
from app_state import AppState
from hardware_manager import HardwareManager
from app_controller import AppController

def main():
    """Main function to initialize and run the Pico Clock Weather Display application."""
    # 1. Initial Setup: Display loading screen
    update_page_loading(False)
    
    # Initialize application state and hardware components
    app_state = AppState()
    hardware = HardwareManager()

    # 2. Wi-Fi Connection: Attempt to connect to Wi-Fi
    wlan = wifi_manager()
    lan_server = None
    lan_ip = None
    if wlan and wlan.isconnected():
        lan_ip = wlan.ifconfig()[0]
        lan_server = create_lan_config_server()
        sync_time()
        gc.collect()

    # 3. Prepare Image List: Load and shuffle custom images
    image_directory = "/image/custom"
    app_state.image_name_list = list_files(image_directory)
    app_state.image_name_list = shuffle_files(app_state.image_name_list)

    # 4. Initialize Controller: Set up the main application controller
    controller = AppController(app_state, hardware, lan_server, lan_ip)

    # 5. Main Loop: Continuously run the application logic
    while True:
        controller.run_main_loop()
        time.sleep(1)

if __name__ == "__main__":
    main()
