# main.py
import time
import gc
from wifi_manager import wifi_manager, create_lan_config_server
from netutils import sync_time
from display_manager import update_page_loading
from image_manager import image_store
from app_state import AppState
from hardware_manager import HardwareManager
from app_controller import AppController

def main():
    """Main function to initialize and run the Pico Clock Weather Display application."""
    recovered = image_store.recover_partial_uploads()
    if recovered:
        print("Recovered {} interrupted image transaction(s).".format(recovered))
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

    # 3. Initialize Controller: Set up the main application controller
    controller = AppController(app_state, hardware, lan_server, lan_ip)

    # 4. Main Loop: Continuously run the application logic
    while True:
        controller.run_main_loop()
        time.sleep(1)

if __name__ == "__main__":
    main()
