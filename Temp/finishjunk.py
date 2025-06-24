import os
os.environ['BLINKA_MCP2221'] = '1'

import argparse

from collections import deque


import logging

import json
import os
import pygame
import socketio # Or from socketio import Client if you only use Client directly
import subprocess
import sys
import time
from datetime import datetime
import requests

import config # Local application import



# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants from config
LIGHT_SENSOR_THRESHOLD = config.LIGHT_SENSOR_THRESHOLD
TRACK_LENGTH_INCHES = config.TRACK_LENGTH_INCHES
MAX_RACE_DURATION = config.MAX_RACE_DURATION
SCREEN_WIDTH = config.SCREEN_WIDTH
SCREEN_HEIGHT = config.SCREEN_HEIGHT
FULLSCREEN = config.FULLSCREEN
CENTRAL_SERVER_URL = config.CENTRAL_SERVER_URL
#INITIAL_RACE_IN_PROGRESS = config.INITIAL_RACE_IN_PROGRESS
USE_ADAPTIVE_THRESHOLD = config.USE_ADAPTIVE_THRESHOLD
USE_DYNAMIC_THRESHOLD = config.USE_DYNAMIC_THRESHOLD
LIGHT_REDUCTION_PERCENTAGE = config.LIGHT_REDUCTION_PERCENTAGE
BASELINE_SAMPLES = config.BASELINE_SAMPLES
PYGAME_DISPLAY_INDEX = config.PYGAME_DISPLAY_INDEX

# Sensor calibration constants - now from config file
ROLLING_WINDOW_SIZE = getattr(config, 'ROLLING_WINDOW_SIZE', 10)
MIN_ABSOLUTE_CHANGE = getattr(config, 'MIN_ABSOLUTE_CHANGE', 5.0)  # in lux
MIN_PERCENT_CHANGE = getattr(config, 'MIN_PERCENT_CHANGE', 20)    # in %
NOISE_THRESHOLD = getattr(config, 'NOISE_THRESHOLD', 2.0)         # below this, apply stricter filtering

weather_cache = {'temp': '--', 'humidity': '--', 'last_update': 0}
WEATHER_CACHE_DURATION = 600  # Update weather every 10 minutes

track_record = None
TRACK_RECORD_FILE = "track_record.json"

placement_counter = 1  # Starts from 1st place

def parse_arguments():
        parser = argparse.ArgumentParser(
            description='I2C Sensor Calibration and Testing Tool',
            epilog='Without arguments, runs in fully automated mode'
        )
        parser.add_argument('-m', '--manual', action='store_true', 
                        help='Run in manual/interactive menu mode')
        return parser.parse_args()

def print_header(message):
        """Print a header message with separators."""
        print("\n" + "=" * 60)
        print(message)
        print("=" * 60)

def sync_system_time():
    """Synchronize system time with NTP servers at startup."""
    logger.info("Attempting to synchronize system time with NTP servers...")
    try:
        # Check if ntpdate is available
        result = subprocess.run(['which', 'ntpdate'], capture_output=True, text=True)
        if result.returncode == 0:
            # Use ntpdate to sync time with NTP servers
            sync_result = subprocess.run(['sudo', 'ntpdate', '-u', 'pool.ntp.org'], 
                                         capture_output=True, text=True)
            if sync_result.returncode == 0:
                logger.info("System time successfully synchronized with NTP servers")
                return True
            else:
                logger.warning(f"Failed to sync time with ntpdate: {sync_result.stderr}")
                # Fall back to systemd-timesyncd if available
                fallback = subprocess.run(['sudo', 'systemctl', 'restart', 'systemd-timesyncd'], 
                                          capture_output=True, text=True)
                if fallback.returncode == 0:
                    logger.info("Attempted time sync via systemd-timesyncd")
                    return True
                else:
                    logger.warning("Failed to sync time with systemd-timesyncd")
        else:
            logger.warning("ntpdate not found. Trying timedatectl...")
            # Try timedatectl as an alternative
            sync_result = subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'],
                                         capture_output=True, text=True)
            if sync_result.returncode == 0:
                logger.info("Enabled NTP synchronization via timedatectl")
                return True
            else:
                logger.warning(f"Failed to enable NTP sync with timedatectl: {sync_result.stderr}")
    except Exception as e:
        logger.error(f"Error during time synchronization: {e}")
    
    logger.warning("Could not synchronize system time. Timestamps may be inaccurate.")
    return False

def get_weather_data():
    """Fetch weather data from OpenWeatherMap API with caching."""
    global weather_cache
    
    current_time = time.time()
    
    # Return cached data if it's still fresh
    if current_time - weather_cache['last_update'] < WEATHER_CACHE_DURATION:
        return weather_cache['temp'], weather_cache['humidity']
    
    try:
        # Get API key and city ID from config
        api_key = getattr(config, 'WEATHER_API_KEY', None)
        city_id = getattr(config, 'WEATHER_CITY_ID', '4699066')  # Irving, Texas default
        
        if not api_key or api_key == 'xxxxxxxxxxxxxxxx':
            return '--', '--'
        
        # OpenWeatherMap Current Weather API (simpler than One Call 3.0)
        url = f"https://api.openweathermap.org/data/2.5/weather?id={city_id}&appid={api_key}&units=imperial"
        
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        data = response.json()
        temp = round(data['main']['temp'])
        humidity = data['main']['humidity']
        
        # Update cache
        weather_cache['temp'] = temp
        weather_cache['humidity'] = humidity
        weather_cache['last_update'] = current_time
        
        return temp, humidity
        
    except Exception as e:
        logger.warning(f"Failed to fetch weather data: {e}")
        return weather_cache['temp'], weather_cache['humidity']

def load_track_record():
    """Load track record from JSON file at startup."""
    global track_record
    try:
        if os.path.exists(TRACK_RECORD_FILE):
            with open(TRACK_RECORD_FILE, 'r') as f:
                data = json.load(f)
                track_record = data.get('track_record')
                logger.info(f"Loaded local track record: {track_record:.3f}s" if track_record else "No local track record found")
        else:
            logger.info("No local track record file found - will request from server if connected")
    except Exception as e:
        logger.error(f"Error loading track record: {e}")

def request_track_record_from_server():
    """Request the current track record from the central server"""
    offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv
    
    if not offline_mode and sio.connected:
        try:
            sio.emit('get_track_record')
            logger.info("Requested current track record from central server")
            return True
        except Exception as e:
            logger.error(f"Error requesting track record from server: {e}")
            return False
    else:
        logger.info("Cannot request track record from server (offline mode or not connected)")
        return False

# Function to save track record
def save_track_record():
    """Save track record to JSON file."""
    try:
        with open(TRACK_RECORD_FILE, 'w') as f:
            json.dump({'track_record': track_record}, f)
        logger.info(f"Saved track record: {track_record:.3f}s")
    except Exception as e:
        logger.error(f"Error saving track record: {e}")


class I2CSystemChecker:
    """Class for checking I2C system components with improved detection from diag.py"""
    
    
    
    def detect_connection_type():
        print_header("Connection Type Detection")
        print("Detecting I2C interface type...")
        
        # Check if we're on a Raspberry Pi
        is_raspberry_pi = False
        is_mcp2221a_available = False
        connection_type = None
        
        try:
            # Try to identify if we're on a Raspberry Pi
            if os.path.exists('/proc/device-tree/model'):
                with open('/proc/device-tree/model', 'r') as f:
                    model = f.read()
                    if 'Raspberry Pi' in model:
                        print(f"Detected Raspberry Pi hardware: {model.strip()}")
                        is_raspberry_pi = True
                        connection_type = "Raspberry Pi HAT"
                    else:
                        print(f"Not a Raspberry Pi. Model: {model.strip()}")
            else:
                print("Not a Raspberry Pi (no /proc/device-tree/model)")
        except Exception as e:
            print(f"Error detecting Raspberry Pi: {e}")
        
        # Check for MCP2221A device
        print("\nChecking for MCP2221A device...")
        try:
            # Use lsusb to check for MCP2221A
            result = subprocess.run(['lsusb'], capture_output=True, text=True, check=False)
            if "04d8:00dd" in result.stdout:
                print("MCP2221A device detected via USB (VID:PID 04D8:00DD)")
                is_mcp2221a_available = True
                connection_type = "MCP2221A"
            else:
                print("No MCP2221A device detected via USB")
                
                # Try checking with hidapi library if available
                try:
                    import hid
                    devices = hid.enumerate(0x04D8, 0x00DD)
                    if devices:
                        print("MCP2221A detected via HID library")
                        is_mcp2221a_available = True
                        connection_type = "MCP2221A"
                    else:
                        print("No MCP2221A devices found via HID library")
                except ImportError:
                    print("HID library not available for checking MCP2221A")
                except Exception as e:
                    print(f"Error checking for MCP2221A via HID: {e}")
        except Exception as e:
            print(f"Error checking for MCP2221A: {e}")
        
        # Determine connection method
        if not connection_type:
            if is_raspberry_pi:
                print("\nAssuming Raspberry Pi HAT connection (native I2C)")
                connection_type = "Raspberry Pi HAT"
            elif is_mcp2221a_available:
                print("\nAssuming MCP2221A connection (USB-to-I2C)")
                connection_type = "MCP2221A"
            else:
                # Ask the user for input
                print("\nCould not auto-detect connection type.")
                user_input = input("Enter connection type (1 for Raspberry Pi HAT, 2 for MCP2221A): ")
                if user_input == "2":
                    connection_type = "MCP2221A"
                else:
                    connection_type = "Raspberry Pi HAT"
        
        print(f"\nUsing connection type: {connection_type}")
        
        # Set up environment for the selected connection type
        if connection_type == "MCP2221A":
            print("Setting BLINKA_MCP2221=1 environment variable for MCP2221A support")
            os.environ['BLINKA_MCP2221'] = '1'
        else:
            # Ensure the variable is not set for Raspberry Pi HAT
            os.environ.pop('BLINKA_MCP2221', None)
            print("Using native Raspberry Pi I2C interface")
        
        return connection_type

    def detect_i2c_buses():
        print_header("I2C Bus Detection")
        print("\nChecking for I2C devices...")
        try:
            result = subprocess.run(['ls', '-l', '/dev/i2c*'], capture_output=True, text=True, check=False)
            if "No such file" in result.stderr:
                print("No I2C devices found in /dev. Make sure I2C is enabled on your Raspberry Pi.")
            else:
                print(result.stdout)
        except Exception as e:
            print(f"Error checking I2C devices: {e}")
        
        # Detect all available I2C buses
        print("\nDetecting available I2C buses...")
        try:
            result = subprocess.run(['i2cdetect', '-l'], capture_output=True, text=True, check=False)
            
            if result.returncode == 0:
                print(result.stdout)
                
                # Parse bus numbers
                bus_numbers = []
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split()
                    if parts and parts[0].startswith('i2c-'):
                        try:
                            bus_number = int(parts[0].split('-')[1])
                            bus_numbers.append(bus_number)
                        except ValueError:
                            continue
                
                if bus_numbers:
                    print(f"Found {len(bus_numbers)} I2C buses: {', '.join(map(str, bus_numbers))}")
                else:
                    print("No I2C buses detected")
                    
                # Scan each detected I2C bus
                for bus in bus_numbers:
                    print(f"\nScanning I2C bus {bus}...")
                    try:
                        result = subprocess.run(['i2cdetect', '-y', str(bus)], capture_output=True, text=True, check=False)
                        
                        if result.returncode == 0:
                            # Print the full detection grid
                            print(f"Full I2C bus {bus} detection grid:")
                            print(result.stdout)
                            
                            # Parse the output to extract just the detected addresses
                            lines = result.stdout.strip().split('\n')
                            detected = []
                            for line in lines[1:]:  # Skip the header line
                                parts = line.split(':')
                                if len(parts) > 1:
                                    row = parts[0].strip()
                                    values = parts[1].strip().split()
                                    for i, val in enumerate(values):
                                        if val != "--":
                                            col = format(i, 'x')
                                            detected.append(f"0x{row}{col}")
                            
                            if detected:
                                print(f"Detected I2C devices on bus {bus} at addresses: {', '.join(detected)}")
                            else:
                                print(f"No I2C devices detected on bus {bus}")
                        else:
                            print(f"Error scanning I2C bus {bus}")
                    except Exception as e:
                        print(f"Error scanning I2C bus {bus}: {e}")
            else:
                print("Error running i2cdetect -l. Try installing with: sudo apt-get install i2c-tools")
        except Exception as e:
            print(f"Error detecting I2C buses: {e}")

    def check_libraries():
        print_header("Library Detection")
        
        # Check if required libraries are available
        libraries_ok = True
        
        try:
            import board
            print("✓ Successfully imported board")
            
            # List available board pins
            print("\nAvailable board pins:")
            board_pins = []
            for item in dir(board):
                # Skip private attributes and non-pin items
                if not item.startswith('_') and item not in ['ap_board', 'board_id', 'detector', 'pin', 'sys']:
                    board_pins.append(item)
            
            # Sort pins for better readability
            board_pins.sort()
            # Print in a grid format for better readability
            pins_per_row = 5
            for i in range(0, len(board_pins), pins_per_row):
                print('  ' + '  '.join(board_pins[i:i+pins_per_row]))
            
            # Print specific pins for common uses
            if hasattr(board, 'SCL') and hasattr(board, 'SDA'):
                print("\nI2C pins:")
                print(f"  SCL: {board.SCL}")
                print(f"  SDA: {board.SDA}")
            
            if hasattr(board, 'MOSI') and hasattr(board, 'MISO') and hasattr(board, 'SCK'):
                print("\nSPI pins:")
                print(f"  MOSI: {board.MOSI}")
                print(f"  MISO: {board.MISO}")
                print(f"  SCK: {board.SCK}")
            
        except Exception as e:
            libraries_ok = False
            print(f"✗ Error importing board: {e}")
            print("  Try installing with: pip3 install adafruit-blinka")
        
        try:
            import busio
            print("✓ Successfully imported busio")
        except Exception as e:
            libraries_ok = False
            print(f"✗ Error importing busio: {e}")
            print("  Try installing with: pip3 install adafruit-blinka")
        
        try:
            import adafruit_tca9548a
            print("✓ Successfully imported adafruit_tca9548a")
        except Exception as e:
            libraries_ok = False
            print(f"✗ Error importing adafruit_tca9548a: {e}")
            print("  Try installing with: pip3 install adafruit-circuitpython-tca9548a")
        
        try:
            import adafruit_bh1750
            print("✓ Successfully imported adafruit_bh1750")
        except Exception as e:
            libraries_ok = False
            print(f"✗ Error importing adafruit_bh1750: {e}")
            print("  Try installing with: pip3 install adafruit-circuitpython-bh1750")
        
        return libraries_ok

    # Global variables to store state between test functions
    #sensor_results = []
    #tca = None
    #mux_type = None

    def detect_multiplexer_and_sensors(): # If these are module globals
        global sensor_results, tca, mux_type # This line indicates they are module-level globals

        # Initialize to default values at the start of the function
        sensor_results = []  # Ensures sensor_results is always a list
        tca = None           # Ensures tca has a default value
        mux_type = "N/A"     # Ensures mux_type has a default value

        print_header("Multiplexer and Sensor Detection")
        
        try:
            import board
            import busio
            from adafruit_blinka.microcontroller.mcp2221 import pin  # <----SOLUTION
            # This import should be at the top of your file, not inside the function
            # import adafruit_tca9548a # Moved for clarity, though Python allows local import

            # Create I2C bus
            i2c = busio.I2C(pin.SCL, pin.SDA)# This is where Blinka talks to the hardware <<<<---SOLUTION
            print("✓ Successfully created I2C object")
            
            # Scan for I2C devices
            print("\nScanning for I2C devices directly...")
            devices = []
            
            # Correct I2C lock/scan/unlock sequence
            locked = False
            try:
                locked = i2c.try_lock()
                if locked:
                    devices = i2c.scan()
                else:
                    print("✗ Failed to acquire I2C lock for scanning.") # More informative
            finally:
                if locked:
                    i2c.unlock()
            
            if devices: # If Blinka found any devices on the bus it's using
                print(f"Found {len(devices)} I2C devices:")
                for device in devices:
                    print(f"  Device at address: 0x{device:02X}")
                
                mux_found_flag = False # Renamed for clarity from mux_found
                
                if 0x70 in devices:
                    print("Found a multiplexer at address 0x70")
                    print("Attempting to identify multiplexer type...")
                    
                    try:
                        # Ensure adafruit_tca9548a is imported (ideally at script top)
                        from adafruit_tca9548a import TCA9548A
                        # Assign to the global 'tca' if successful
                        tca_instance = TCA9548A(i2c) # Use a local var first
                        tca = tca_instance # Assign to global 'tca'
                        print("✓ Successfully initialized as TCA9548A")
                        mux_found_flag = True
                        mux_type = "TCA9548A" # Assign to global 'mux_type'
                    except Exception as e_tca:
                        print(f"Failed to initialize as TCA9548A: {e_tca}")
                        # The nested try-except for PCA9548A might be problematic if the first init failed badly
                        # For simplicity, if TCA9548A init fails, we might not proceed to PCA with the same lib here
                        # unless the library explicitly supports distinguishing or handling both robustly.
                        # The original code's PCA attempt might re-assign 'tca' and 'mux_type'.
                        # If the goal is just to get a working MUX object, the first success is enough.
                        # The original PCA try block is omitted here for clarity on fixing the NameError path,
                        # assuming the TCA9548A library is the primary target.
                        # If you need the PCA9548A differentiation, it can be re-added carefully.
                    
                    if mux_found_flag and tca: # Check the global 'tca'
                        print(f"✓ Using {mux_type} multiplexer at address 0x70")
                        
                        sensor_results = [] # Initialize/clear the global list for this run
                        
                        for channel in range(6):
                            print(f"\nTesting channel {channel}...")
                            try:
                                # Ensure adafruit_bh1750 is imported (ideally at script top)
                                from adafruit_bh1750 import BH1750
                                channel_bus = tca[channel] # Use the global 'tca'
                                print(f"✓ Channel {channel} accessible")
                                
                                channel_devices_scan = []
                                ch_locked = False
                                try:
                                    ch_locked = channel_bus.try_lock()
                                    if ch_locked:
                                        channel_devices_scan = channel_bus.scan()
                                    else:
                                        print(f"✗ Failed to acquire I2C lock for channel {channel}.")
                                finally:
                                    if ch_locked:
                                        channel_bus.unlock()
                                
                                if channel_devices_scan:
                                    print(f"Found {len(channel_devices_scan)} devices on channel {channel}:")
                                    for dev_addr_ch in channel_devices_scan: # Renamed dev_addr_ch
                                        print(f"  Device at address: 0x{dev_addr_ch:02X}")
                                    
                                    if 0x23 in channel_devices_scan:
                                        sensor_instance = BH1750(channel_bus) # Use local var
                                        lux = sensor_instance.lux
                                        print(f"✓ BH1750 sensor found on channel {channel}")
                                        print(f"  Light reading: {lux:.2f} lux")
                                        sensor_results.append((channel, True, lux)) # Appends to global
                                    else:
                                        print(f"✗ No BH1750 sensor found at 0x23 on channel {channel}")
                                        sensor_results.append((channel, False, 0))
                                else:
                                    print(f"No devices found on channel {channel}")
                                    sensor_results.append((channel, False, 0))
                            except Exception as e_ch_scan:
                                print(f"✗ Error accessing/scanning channel {channel}: {e_ch_scan}")
                                sensor_results.append((channel, False, 0))
                        
                        print_header("Sensor Test Summary")
                        # ... (rest of your summary printing) ...

                    else: # This 'else' corresponds to 'if mux_found_flag and tca:'
                        # This means MUX was detected at 0x70, but initialization failed.
                        print(f"✗ Multiplexer at 0x70 detected, but could not initialize {mux_type} object (tca is {tca}).")
                        # sensor_results is already [], tca is None, mux_type is "N/A" or last error type
                
                else: # This 'else' corresponds to 'if 0x70 in devices:'
                    print("✗ No multiplexer found at address 0x70.")
                    # sensor_results is [], tca is None, mux_type is "N/A"
            
            else: # This 'else' corresponds to 'if devices:' -> Blinka scan found nothing on the bus
                print("No I2C devices found by Blinka scan on the configured I2C bus.")
                logger.warning("I2CSystemChecker: Blinka's i2c.scan() found no devices. This indicates an issue with I2C communication via Blinka for the selected bus/interface (e.g., MCP2221A or RPi native). Check hardware, pull-ups, and Blinka setup.")
                # sensor_results is [], tca is None, mux_type is "N/A" (already defaulted)
        
        except RuntimeError as e_runtime: # Catch specific Blinka/busio runtime errors
            print(f"Error during I2C testing (RuntimeError): {e_runtime}")
            logger.error(f"I2CSystemChecker: RuntimeError during I2C setup: {e_runtime}. This often means Blinka cannot access the hardware I2C bus correctly.")
            # sensor_results, tca, mux_type will have their default initial values
        except ImportError as e_imp: # Catch missing library errors if imports are local
             print(f"Error during I2C testing (ImportError): {e_imp}. Make sure Adafruit libraries are installed.")
             logger.error(f"I2CSystemChecker: ImportError: {e_imp}.")
        except Exception as e: # General catch-all
            print(f"General error during I2C testing: {e}")
            logger.error(f"I2CSystemChecker: General Exception: {e}", exc_info=True)
            # sensor_results, tca, mux_type will have their default initial values

        # This return will now always work because sensor_results, tca, and mux_type were initialized
        return sensor_results, tca, mux_type
    
    

class LightSensor:
    """Enhanced light sensor class with auto-calibration for outdoor environments"""
    
    def __init__(self, lane, sensor, window_size=BASELINE_SAMPLES, 
                 trigger_percentage=LIGHT_REDUCTION_PERCENTAGE, 
                 static_threshold=LIGHT_SENSOR_THRESHOLD, 
                 sensitivity=1.5):
        self.lane = lane
        self.sensor = sensor
        self.window_size = window_size
        self.trigger_percentage = trigger_percentage
        self.static_threshold = static_threshold # Kept for potential future use or alternative mode
        self.sensitivity = sensitivity # Kept for potential future use with dynamic_threshold std dev logic
        self.baseline = [] # For rolling average calculation
        self.current_average = None # Current rolling average of light levels
        self.dynamic_threshold = None # Threshold calculated based on conditions

        # Enhanced threshold detection from diag.py / sensor_calibration_done.py
        self.rolling_buffer = deque(maxlen=ROLLING_WINDOW_SIZE) # More responsive rolling window
        self.stable_average = None # Average from the ROLLING_WINDOW_SIZE buffer
        self.last_reading = None
        self.last_trigger_time = 0
        self.is_ready = False # Becomes true after initial samples fill rolling_buffer
        
        # Outdoor environment adaptation
        self.ambient_readings = deque(maxlen=50) # For tracking recent ambient light for adjustments
        self.ambient_trend = deque(maxlen=30)  # Track light changes over time (percentage change)
        self.last_recalibration_time = time.time()
        self.calibration_interval = 120  # Recalibrate every 2 minutes if ambient light changed significantly
        self.significant_ambient_change_flag = False # Flag if a large, sudden ambient change occurred
        self.adaptive_trigger_percentage = float(trigger_percentage)  # Starts with config value but adapts

    def update(self, value):
        """Update the sensor with a new light value and recalculate states."""
        current_time = time.time()
        self.last_reading = value
        
        self.ambient_readings.append(value) # Track for overall ambient conditions
        
        # Original baseline logic (can be used for a slower-moving average if needed)
        self.baseline.append(value)
        if len(self.baseline) > self.window_size: # BASELINE_SAMPLES window
            self.baseline.pop(0)
        if self.baseline: # Ensure baseline is not empty
            self.current_average = sum(self.baseline) / len(self.baseline)

        # Enhanced rolling window from diag.py for more immediate baseline
        self.rolling_buffer.append(value)
        if len(self.rolling_buffer) == ROLLING_WINDOW_SIZE:
            old_stable_average = self.stable_average
            self.stable_average = sum(self.rolling_buffer) / ROLLING_WINDOW_SIZE
            if not self.is_ready:
                logger.info(f"Lane {self.lane}: Sensor ready. Initial stable average: {self.stable_average:.2f} lux")
                self.is_ready = True # Sensor is now ready after collecting initial samples

            # Calculate ambient light trend if old_stable_average exists
            if old_stable_average is not None and old_stable_average > 0: # Avoid division by zero
                percent_change = ((self.stable_average - old_stable_average) / old_stable_average) * 100
                self.ambient_trend.append(percent_change)
                
                # Detect significant ambient changes (e.g., sun going behind clouds)
                # Using a threshold like 25-30% change in the stable average could indicate this
                if abs(percent_change) > 25 and not self.significant_ambient_change_flag: # Example threshold
                    logger.info(f"Lane {self.lane}: Significant ambient light change detected: {percent_change:.2f}% (new stable avg: {self.stable_average:.2f} lux)")
                    self.significant_ambient_change_flag = True # Flag this to potentially trigger faster recalibration or adjustment
        
        # Auto-adjust thresholds based on current ambient conditions
        self.adjust_thresholds() # This will set self.dynamic_threshold
        
        # Automatic recalibration logic for outdoor conditions
        if self.should_recalibrate(current_time):
            self.quick_recalibrate_baseline()

    def adjust_thresholds(self):
        """Dynamically adjust trigger percentage and calculate dynamic_threshold based on current lighting."""
        if not self.is_ready or not self.ambient_readings: # Need stable average and ambient history
            return

        current_light_level = self.stable_average # Use the more responsive stable_average
        if current_light_level is None:
            return

        # Adjust adaptive_trigger_percentage based on light stability/level
        # More stable/higher light might allow a less sensitive percentage (higher number)
        # More variable/lower light might need a more sensitive percentage (lower number)
        # Example:
        if current_light_level > 200: # Bright light
            self.adaptive_trigger_percentage = float(LIGHT_REDUCTION_PERCENTAGE) # Use configured base
        elif current_light_level > 50: # Moderate light
            self.adaptive_trigger_percentage = max(15.0, float(LIGHT_REDUCTION_PERCENTAGE) * 0.8)
        else: # Low light
            self.adaptive_trigger_percentage = max(10.0, float(LIGHT_REDUCTION_PERCENTAGE) * 0.6)

        # In very low light, absolute change might be more reliable or percentage needs to be very sensitive
        if current_light_level < NOISE_THRESHOLD * 2: # e.g., < 4 lux if NOISE_THRESHOLD is 2
             self.adaptive_trigger_percentage = max(5.0, self.adaptive_trigger_percentage * 0.5) # More sensitive

        # Calculate the dynamic threshold for triggering
        # Trigger occurs if new_value < self.dynamic_threshold
        self.dynamic_threshold = current_light_level * (1 - (self.adaptive_trigger_percentage / 100.0))

        if self.significant_ambient_change_flag:
            # If a very recent significant ambient change happened, be more aggressive or reset faster
            # This might mean forcing a baseline recalibration sooner or using even more sensitive temporary settings
            logger.debug(f"Lane {self.lane}: Operating with adjusted thresholds post-significant ambient change. Trigger %: {self.adaptive_trigger_percentage:.1f}, Dyn_Thresh: {self.dynamic_threshold:.2f}")
            # Reset the flag after acknowledging it, so adjustments are temporary unless conditions persist
            # self.significant_ambient_change_flag = False 
            # Decision: Recalibration handles baseline resetting, so flag helps inform adjust_thresholds.

    def should_recalibrate(self, current_time):
        """Determine if sensor should recalibrate its baseline based on time and ambient light changes."""
        time_since_last_recal = current_time - self.last_recalibration_time

        # If a significant ambient change was flagged recently, recalibrate sooner
        if self.significant_ambient_change_flag and time_since_last_recal > 30: # e.g. recalibrate 30s after a big change
            logger.info(f"Lane {self.lane}: Triggering recalibration due to recent significant ambient light change.")
            self.significant_ambient_change_flag = False # Reset flag after acting on it
            return True
        
        # Periodic recalibration, especially if light conditions have been drifting
        if time_since_last_recal > self.calibration_interval:
            # Check if the ambient trend shows significant drift
            if self.ambient_trend and len(self.ambient_trend) > 10: # Need enough trend data
                # Example: if average trend over last minute indicates > 15-20% total change
                accumulated_trend = sum(list(self.ambient_trend)[-15:]) # Sum of last 15 trend points (approx 3 secs if 0.2s updates)
                                                                       # This might need adjustment based on update frequency
                if abs(accumulated_trend) > 20: # If accumulated change percentage is high
                    logger.info(f"Lane {self.lane}: Recalibrating due to gradual ambient light drift (trend sum: {accumulated_trend:.2f}%).")
                    return True
            logger.info(f"Lane {self.lane}: Performing periodic recalibration.")
            return True # Standard periodic recalibration
        
        return False

    def quick_recalibrate_baseline(self):
        """Perform a quick recalibration of the baseline using current rolling_buffer data."""
        self.last_recalibration_time = time.time()
        
        if self.rolling_buffer: # Ensure buffer has data
            self.stable_average = sum(self.rolling_buffer) / len(self.rolling_buffer)
            # Optionally, could also reset self.baseline to self.rolling_buffer if used elsewhere
            # self.baseline = list(self.rolling_buffer)
            # if self.baseline: self.current_average = sum(self.baseline) / len(self.baseline)

        self.ambient_trend.clear() # Reset trend history after recalibration
        self.significant_ambient_change_flag = False # Reset this flag too
        
        logger.info(f"Lane {self.lane}: Quick recalibration performed. New stable average: {self.stable_average:.2f} lux. Adaptive Trigger %: {self.adaptive_trigger_percentage:.1f}")

    def is_triggered(self, current_lux_value):
        """Check if the current light value triggers a finish detection."""
        if not self.is_ready or self.stable_average is None or self.dynamic_threshold is None:
            # logger.debug(f"Lane {self.lane}: Not ready or no stable average/dynamic threshold. Value: {current_lux_value}")
            return False
        
        # Debounce: Prevent multiple rapid triggers
        now = time.time()
        if now - self.last_trigger_time < 0.5:  # 500ms debounce period
            return False

        # Primary trigger condition: current light drops below dynamic threshold
        triggered_by_dynamic_threshold = current_lux_value < self.dynamic_threshold

        # Stricter check for very low light (noise reduction)
        # If current average is already very low, require a more substantial absolute drop
        is_low_light_condition = self.stable_average < NOISE_THRESHOLD 
        
        if is_low_light_condition:
            abs_change_in_low_light = self.stable_average - current_lux_value
            # In low light, trigger if it meets dynamic_threshold OR a significant absolute drop happens
            # (e.g., drops by at least MIN_ABSOLUTE_CHANGE / 2, or some factor of NOISE_THRESHOLD)
            triggered_in_low_light = triggered_by_dynamic_threshold and (abs_change_in_low_light > max(MIN_ABSOLUTE_CHANGE * 0.5, NOISE_THRESHOLD * 0.5))
            if not triggered_in_low_light and triggered_by_dynamic_threshold: # Was triggered by percentage but not by stricter absolute check
                 logger.debug(f"Lane {self.lane}: Low light ({self.stable_average:.2f}lx). Trigger by % ({current_lux_value:.2f} < {self.dynamic_threshold:.2f}) but abs_change ({abs_change_in_low_light:.2f}lx) too small. Not triggering.")
                 return False # Override if dynamic threshold met but absolute change is too small in low light
            triggered = triggered_in_low_light
        else: # Not a low light condition, rely on dynamic threshold primarily
            triggered = triggered_by_dynamic_threshold

        if triggered:
            self.last_trigger_time = now # Update time of last trigger
            reduction_from_stable = self.stable_average - current_lux_value
            reduction_percentage = (reduction_from_stable / self.stable_average) * 100 if self.stable_average > 0 else 0
            logger.info(f"Lane {self.lane}: Detection TRIGGERED! Lux: {current_lux_value:.2f}, StableAvg: {self.stable_average:.2f}, DynThresh: {self.dynamic_threshold:.2f} (Target Reduc%: {self.adaptive_trigger_percentage:.1f}%, Actual Reduc%: {reduction_percentage:.1f}%)")
            return True
        
        return False

    def calibrate(self):
        """Calibrate the sensor by taking initial baseline readings to populate rolling_buffer."""
        logger.info(f"Lane {self.lane}: Starting calibration - collecting initial {ROLLING_WINDOW_SIZE} samples...")
        
        self.baseline.clear()
        self.rolling_buffer.clear()
        self.stable_average = None
        self.is_ready = False
        self.ambient_readings.clear()
        self.ambient_trend.clear()
        self.significant_ambient_change_flag = False
        self.last_recalibration_time = time.time() # Set initial calibration time
        
        samples_collected = 0
        calibration_start_time = time.time()
        
        # Collect initial samples to fill the rolling buffer
        try:
            while samples_collected < ROLLING_WINDOW_SIZE:
                try:
                    lux = self.sensor.lux
                    # self.update(lux) will handle adding to rolling_buffer
                    # For calibration, we mainly need to fill rolling_buffer to establish the first stable_average
                    self.rolling_buffer.append(lux)
                    self.ambient_readings.append(lux) # Also populate ambient readings
                    samples_collected += 1
                    
                    if samples_collected % 5 == 0 or samples_collected == ROLLING_WINDOW_SIZE:
                        logger.info(f"Lane {self.lane} calibration: {samples_collected}/{ROLLING_WINDOW_SIZE} samples. Current lux: {lux:.2f}")
                    
                    time.sleep(0.05)  # Approx 20Hz sampling
                except Exception as e:
                    logger.error(f"Error reading sensor during calibration for lane {self.lane}: {e}")
                    time.sleep(0.1) # Wait a bit before retrying
                    # Consider a limit on retries or time for calibration sample collection
                    if time.time() - calibration_start_time > 10: # Timeout for sample collection
                        logger.error(f"Lane {self.lane}: Calibration timed out for sample collection.")
                        return False

            # After buffer is full, calculate the initial stable average and adaptive thresholds
            if len(self.rolling_buffer) == ROLLING_WINDOW_SIZE:
                self.stable_average = sum(self.rolling_buffer) / len(self.rolling_buffer)
                self.is_ready = True
                self.adjust_thresholds() # Calculate initial dynamic_threshold
                
                # Also populate the slower self.baseline and self.current_average if desired
                self.baseline = list(self.rolling_buffer)
                self.current_average = self.stable_average

                calibration_duration = time.time() - calibration_start_time
                logger.info(f"Lane {self.lane} calibration complete in {calibration_duration:.2f}s.")
                logger.info(f"  Initial Stable Average: {self.stable_average:.2f} lux")
                logger.info(f"  Initial Adaptive Trigger %: {self.adaptive_trigger_percentage:.1f}%")
                logger.info(f"  Initial Dynamic Threshold: {self.dynamic_threshold:.2f} lux")
                return True
            else:
                logger.error(f"Lane {self.lane}: Failed to collect enough samples for calibration ({len(self.rolling_buffer)}/{ROLLING_WINDOW_SIZE}).")
                return False

        except Exception as e:
            logger.error(f"Critical error during sensor calibration for lane {self.lane}: {e}")
            return False


# Initialize Socket.IO client
sio = socketio.Client(logger=True, engineio_logger=True)

# Global hardware and state variables
screen = None
font = None
race_in_progress = False
start_time = None
finish_times = [None] * 6 # For 6 lanes
current_race_number = None
formatted_race = None
light_sensors = {} # Dictionary to hold LightSensor objects, keyed by lane number
max_race_duration_config = MAX_RACE_DURATION # From config.py
i2c_bus_global = None # To hold the I2C busio.I2C object
mux_global = None # To hold the TCA9548A object

def initialize_hardware(num_lanes=6, tca_from_checker=None):
    """
    Initialize application hardware components.
    Uses TCA MUX object from I2CSystemChecker if provided and valid.
    Otherwise, attempts manual setup for direct sensor (if 1 lane) or fails.
    Assumes I2CSystemChecker.detect_connection_type() has already run.
    """
    global light_sensors, i2c_bus_global, mux_global, logger, LightSensor

    logger.info(f"Initializing application hardware for {num_lanes} lanes...")
    light_sensors.clear()
    mux_global = None # Reset globals
    i2c_bus_global = None

    # These imports are safe IF I2CSystemChecker.detect_connection_type() was successful
    try:
        import board
        import busio
        from adafruit_tca9548a import TCA9548A # Needed for fallback if tca_from_checker is None
        from adafruit_bh1750 import BH1750
    except ImportError as e_imp:
        logger.error(f"AppHW: Critical import error (board, busio, etc.): {e_imp}. Blinka env likely not set.")
        return False

    if tca_from_checker:
        logger.info("AppHW: Using TCA MUX object provided by I2CSystemChecker.")
        # The tca_from_checker IS the multiplexer object.
        # It was initialized with an I2C bus inside I2CSystemChecker.detect_multiplexer_and_sensors
        mux_global = tca_from_checker
        # We don't get direct access to the 'i2c' bus variable that tca_from_checker was created with,
        # but tca_from_checker[channel] will give us channel-specific I2C buses.

        sensors_on_mux_count = 0
        for channel in range(num_lanes):
            lane_id = channel + 1
            logger.info(f"AppHW: Processing MUX channel {channel} (Lane {lane_id}) using checker's MUX.")
            try:
                channel_i2c_bus = tca_from_checker[channel] # Get I2C interface for this MUX channel
                
                channel_scan_devices = []
                while not channel_i2c_bus.try_lock():
                    time.sleep(0.01)
                try:
                    channel_scan_devices = channel_i2c_bus.scan()
                finally:
                    channel_i2c_bus.unlock()

                if not channel_scan_devices:
                    logger.info(f"AppHW: No I2C devices on checker's MUX channel {channel}.")
                    continue

                if 0x23 in channel_scan_devices: # BH1750 default address
                    logger.info(f"AppHW: BH1750 (0x23) detected on checker's MUX channel {channel}.")
                    sensor_hw = BH1750(channel_i2c_bus)
                    lux = sensor_hw.lux # Attempt a read to confirm
                    logger.info(f"✓ AppHW: BH1750 on checker's MUX channel {channel} responsive. Lux: {lux:.2f}")
                    light_sensors[lane_id] = LightSensor(lane_id, sensor_hw)
                    sensors_on_mux_count += 1
                else:
                    logger.warning(f"✗ AppHW: No BH1750 (0x23) found on checker's MUX channel {channel}.")
            except Exception as e_ch:
                logger.error(f"✗ AppHW: Error on checker's MUX channel {channel}: {e_ch}")
        
        # Check if we found the required number of sensors
        if sensors_on_mux_count == num_lanes:
            logger.info(f"AppHW: Successfully initialized all {num_lanes} required LightSensors using checker's MUX.")
            return True
        elif sensors_on_mux_count > 0:
            # Found some sensors but not all required ones
            logger.warning(f"AppHW: Initialized {sensors_on_mux_count}/{num_lanes} required LightSensors. System will operate with reduced lanes.")
            return True
        else:
            logger.error("AppHW: Checker provided a MUX, but no sensors were successfully initialized on its channels.")
            return False # Failed to init any sensors even with checker's MUX

    else: # No MUX object provided by I2CSystemChecker.detect_multiplexer_and_sensors()
        logger.warning("AppHW: No MUX object provided by I2CSystemChecker. Attempting manual I2C setup for direct sensor (if 1 lane).")
        
        if num_lanes == 1:
            logger.info("AppHW: Attempting to initialize a single, direct-connected BH1750 sensor...")
            try:
                # We MUST create a new I2C bus instance here, as the checker didn't provide one
                # if it didn't find/return a MUX.
                app_level_i2c_bus = busio.I2C(board.SCL, board.SDA)
                i2c_bus_global = app_level_i2c_bus # Store this as the main bus
                logger.info("AppHW: Created new I2C bus for direct sensor check.")

                devices = []
                while not app_level_i2c_bus.try_lock():
                    time.sleep(0.01)
                try:
                    devices = app_level_i2c_bus.scan()
                finally:
                    app_level_i2c_bus.unlock()

                if not devices:
                    logger.error("✗ AppHW: No I2C devices found on manually created bus for direct sensor.")
                    return False

                if 0x23 in devices: # BH1750 default address
                    logger.info("AppHW: Direct BH1750 (0x23) detected on manually created bus.")
                    sensor_hw = BH1750(app_level_i2c_bus)
                    lux = sensor_hw.lux
                    logger.info(f"✓ AppHW: Direct BH1750 responsive. Lux: {lux:.2f}")
                    light_sensors[1] = LightSensor(1, sensor_hw)
                    logger.info("AppHW: LightSensor object created for direct Lane 1.")
                    return True
                else:
                    logger.error("✗ AppHW: Single lane, but no direct BH1750 (0x23) found on manually created bus.")
                    return False
            except RuntimeError as e_rt_direct:
                logger.error(f"AppHW: Runtime error during direct sensor I2C init: {e_rt_direct}. Check Blinka/Hardware.")
                return False
            except Exception as e_direct:
                logger.error(f"AppHW: Error initializing direct BH1750: {e_direct}")
                return False
        elif num_lanes > 1:
            logger.error(f"AppHW: Multiple lanes ({num_lanes}) configured, but no MUX object was provided by checker, and cannot proceed.")
            return False
        else: # num_lanes is 0 or invalid, but no MUX from checker
            logger.info("AppHW: 0 lanes specified or invalid count, and no MUX from checker. No sensors to initialize.")
            return True # Technically successful if 0 lanes were intended

    # Fallback if none of the conditions above led to a successful return
    logger.error("AppHW: Hardware initialization failed due to unhandled conditions.")
    return False



def initialize_display():
    """Initialize the display for showing race results on a specific monitor."""
    global screen, font
    logger.info("Initializing display...")
    
    # Attempt to get PYGAME_DISPLAY_INDEX from config, default to 0 if not found
    display_index_to_use = getattr(config, 'PYGAME_DISPLAY_INDEX', 0)
    logger.info(f"Attempting to use display index: {display_index_to_use}")

    try:
        pygame.init()

        # Get display info (optional, for logging/debugging)
        try:
            num_displays = pygame.display.get_num_displays()
            logger.info(f"Number of available displays: {num_displays}")
            if num_displays > 1 and display_index_to_use >= num_displays:
                logger.warning(f"Configured PYGAME_DISPLAY_INDEX ({display_index_to_use}) is out of range. Max index is {num_displays - 1}. Defaulting to 0.")
                display_index_to_use = 0
        except pygame.error as e:
            logger.warning(f"Could not get display info from Pygame: {e}. Will proceed with configured/default index.")

        # Create the display window
        screen_flags = 0
        if hasattr(config, 'FULLSCREEN') and config.FULLSCREEN:
            screen_flags = pygame.FULLSCREEN
            logger.info(f"Setting display mode: {config.SCREEN_WIDTH}x{config.SCREEN_HEIGHT}, Fullscreen, on display {display_index_to_use}")
        else:
            logger.info(f"Setting display mode: {config.SCREEN_WIDTH}x{config.SCREEN_HEIGHT}, Windowed, on display {display_index_to_use}")

        screen = pygame.display.set_mode(
            (config.SCREEN_WIDTH, config.SCREEN_HEIGHT),
            screen_flags,
            display=display_index_to_use
        )
        pygame.display.set_caption("Race Results Display")
        
        # Load font directly using the full path we found
        try:
            font = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
            
            logger.info("Font loaded successfully from system path")
        except pygame.error as e:
            logger.warning(f"Could not load DejaVuSans-Bold.ttf: {e}. Using system default font.")
            font = pygame.font.SysFont(None, 24)  # Default system font
        
        # Initial screen content
        screen.fill((40, 40, 40))  # Dark gray
        initial_message_lines = [
            "FINISH GATE SYSTEM INITIALIZED", "",
            "Press SPACE to Start a Local Race", "Press 'r' to Reset Gate Status",
        ]
        if not getattr(config, 'OFFLINE_MODE', False) and getattr(config, 'CENTRAL_SERVER_URL', None):
             initial_message_lines.insert(3, "(Or await server commands if connected)")
        
        line_y_offset = config.SCREEN_HEIGHT // 2 - (font.get_height() * len(initial_message_lines)) // 2
        for line_text in initial_message_lines:
            if line_text:
                text_surface = font.render(line_text, True, (200, 200, 200))
                text_rect = text_surface.get_rect(center=(config.SCREEN_WIDTH // 2, line_y_offset))
                screen.blit(text_surface, text_rect)
            line_y_offset += font.get_height() + 5
        
        pygame.display.flip()
        logger.info(f"Display initialized successfully on display index {display_index_to_use}.")
        return True
    except Exception as e:
        logger.error(f"Error initializing Pygame display on index {display_index_to_use}: {e}", exc_info=True)
        screen = None
        font = None
        return False

def display_on_screen(race_results_list, current_formatted_race_id, num_lanes_to_display=6):
    """Display live race results on screen - ENHANCED VERSION WITH TIME AND WEATHER"""
    global screen, font
    if not screen or not font:
        logger.warning("Display not available, cannot show results on screen.")
        return

    screen.fill((0, 0, 0))  # Black background

    # Create smaller font for header line
    small_font = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)  # Even smaller for more info

    # Get weather data (cached)
    temp, humidity = get_weather_data()
    
    # Get current date and time
    current_datetime = datetime.now()
    current_date = current_datetime.strftime("%m/%d/%Y")  # Format as MM/DD/YYYY
    current_time = current_datetime.strftime("%I:%M:%S%f")[:-5] + " " + current_datetime.strftime("%p")

    # Build track record string
    track_record_str = f"Track Record: {track_record:.3f}s" if track_record is not None else "Track Record: --"

    # Display enhanced header with Race ID, status, date, time, weather, track record, and reset instruction
    if current_formatted_race_id:
        try:
            # Get race status from global variable if available
            race_status = "Racing" if race_in_progress else "Finished"
            
            # Check if we're running in offline mode
            offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv
            
            # Build weather string
            weather_str = f"Dallas,Texas | {temp}°F {humidity}%" if temp != '--' else "Dallas,Texas | --"
            
            # Build the comprehensive header with date included
            if race_status == "Finished" and offline_mode:
                combined_text = f"Race: {current_formatted_race_id} | Status: {race_status} | Date: {current_date} | Time: {current_time} | {weather_str} | {track_record_str} | Press 'R' to start new race"
            else:
                combined_text = f"Race: {current_formatted_race_id} | Status: {race_status} | Date: {current_date} | Time: {current_time} | {weather_str} | {track_record_str}"
                
            text_surface = small_font.render(combined_text, True, (255, 255, 255))
            screen.blit(text_surface, (SCREEN_WIDTH // 2 - text_surface.get_width() // 2, 5))
        except Exception as e:
            logger.error(f"Error rendering race ID: {e}")

    # Calculate layout (adjust top_offset for smaller header)
    column_width = SCREEN_WIDTH // num_lanes_to_display
    top_offset = 25  # Reduced slightly since header font is smaller
    row_spacing = 3
    
    # Blinking effect for winner (changes every 500ms)
    blink_cycle = int(time.time() * 2) % 2  # 0 or 1, changes every 500ms

    # Find winner time for gap calculations
    winner_time = None
    for result in race_results_list:
        if result and result[1] == 1 and result[2] is not None:  # Winner with valid time
            winner_time = result[2]
            break

    for i in range(num_lanes_to_display):
        lane_number = i + 1
        result = next((r for r in race_results_list if r[0] == lane_number), None)
        x = i * column_width
        y = top_offset

        # *** SIMPLE DNF DETECTION - ONLY AFTER RACE TIMEOUT ***
        is_any_dnf = False
        if result and not race_in_progress:  # Race must be finished to have DNF
            is_any_dnf = result[1] is None

        # Background color - WINNER BLINKS CONTINUOUSLY ONCE THEY WIN
        is_winner = result and result[1] == 1
        
        if is_winner:  # Winner blinks continuously once they have place #1
            if blink_cycle:
                bg_color = (50, 50, 50)  # Original gray background
                border_color = (255, 255, 255)  # White border
                border_width = 3
            else:
                bg_color = (0, 150, 0)  # Dark green
                border_color = (255, 255, 255)  # White border
                border_width = 3
        else:  # All other lanes stay gray
            bg_color = (50, 50, 50)  # Gray for everyone except winner
            border_color = None
            border_width = 0
            
        # Draw main background
        pygame.draw.rect(screen, bg_color, (x + 5, y, column_width - 10, SCREEN_HEIGHT - y - 10))
        
        # Draw blinking border for winner
        if result and result[1] == 1 and border_color:
            pygame.draw.rect(screen, border_color, (x + 5, y, column_width - 10, SCREEN_HEIGHT - y - 10), border_width)

        # *** STATUS DOT LOGIC ***
        dot_radius = 10
        dot_center_x = x + column_width // 2
        dot_center_y = y + dot_radius + 5
        
        if is_winner:  # Winner gets blinking green dot
            if blink_cycle:
                dot_color = (0, 255, 0)   # Bright green
                dot_radius_current = 12   # Slightly larger
            else:
                dot_color = (0, 200, 0)   # Slightly dimmer green
                dot_radius_current = 10
        elif is_any_dnf:  
            dot_color = (255, 0, 0)  # Red for DNF
            dot_radius_current = dot_radius
        elif result and result[1] is not None and result[1] > 1:  
            dot_color = (255, 165, 0)  # Orange for finished
            dot_radius_current = dot_radius
        elif result and result[2] is not None and result[1] is None:  
            dot_color = (255, 255, 0)  # Yellow for racing
            dot_radius_current = dot_radius
        else:  
            dot_color = (255, 255, 255)  # White for default
            dot_radius_current = dot_radius
            
        pygame.draw.circle(screen, dot_color, (dot_center_x, dot_center_y), dot_radius_current)

        y += dot_radius * 2 + 5

        # Lane label
        lane_label_surface = font.render(f"Lane {lane_number}", True, (255, 255, 255))
        lane_label_rect = lane_label_surface.get_rect(centerx=x + column_width // 2)
        lane_label_rect.y = y
        screen.blit(lane_label_surface, lane_label_rect)
        y += lane_label_surface.get_height() + row_spacing

        # Place number
        large_font = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 60)
        if is_any_dnf:
            place_text = "DNF"
            place_color = (255, 0, 0)
        elif result and result[1] is not None:
            place_text = str(result[1])
            if is_winner:
                place_color = (255, 255, 0) if blink_cycle else (255, 255, 255)
            else:
                place_color = (255, 255, 0)
        else:
            place_text = "---"
            place_color = (255, 255, 255)
            
        place_surface = large_font.render(place_text, True, place_color)
        place_rect = place_surface.get_rect(center=(x + column_width // 2, y + 30))
        screen.blit(place_surface, place_rect)
        y += place_surface.get_height() + row_spacing

        # Running time
        if is_any_dnf:
            time_surface = font.render("DNF", True, (255, 0, 0))
        elif result and result[2] is not None:
            if result[1] is not None:
                if is_winner:
                    time_color = (255, 255, 0) if blink_cycle else (0, 255, 0)
                    time_surface = font.render(f"WINNER: {result[2]:.3f}s", True, time_color)
                else:
                    time_surface = font.render(f"Final: {result[2]:.3f}s", True, (0, 255, 0))
            else:
                time_surface = font.render(f"Live: {result[2]:.3f}s", True, (255, 255, 0))
        else:
            time_surface = font.render("Time: ---", True, (255, 255, 255))

        time_rect = time_surface.get_rect(center=(x + column_width // 2, y + 15))
        screen.blit(time_surface, time_rect)
        y += time_surface.get_height() + row_spacing

        # Gap timing
        if is_any_dnf:
            gap_surface = small_font.render("DNF", True, (255, 0, 0))
            gap_rect = gap_surface.get_rect(center=(x + column_width // 2, y + 10))
            screen.blit(gap_surface, gap_rect)
            y += gap_surface.get_height() + row_spacing
        elif result and result[1] is not None and result[1] > 1 and result[2] is not None and winner_time is not None:
            gap_time = result[2] - winner_time
            gap_text = f"+{gap_time:.3f}s"
            gap_color = (255, 140, 0)
            gap_surface = small_font.render(gap_text, True, gap_color)
            gap_rect = gap_surface.get_rect(center=(x + column_width // 2, y + 10))
            screen.blit(gap_surface, gap_rect)
            y += gap_surface.get_height() + row_spacing
        elif is_winner:
            y += small_font.get_height() + row_spacing

        # Speed
        speed_font = pygame.font.Font("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        if is_any_dnf:
            speed_surface = speed_font.render("DNF", True, (255, 0, 0))
        elif result and result[3] is not None:
            if is_winner:
                speed_color = (255, 255, 0) if blink_cycle else (255, 255, 255)
            else:
                speed_color = (255, 255, 255)
            speed_surface = speed_font.render(f"Speed: {result[3]:.2f} mph", True, speed_color)
        else:
            speed_surface = speed_font.render("Speed: ---", True, (255, 255, 255))

        speed_rect = speed_surface.get_rect(center=(x + column_width // 2, y + 10))
        screen.blit(speed_surface, speed_rect)

    pygame.display.flip()

def calculate_speed(race_time_seconds):
    """Calculate the scale speed of a car based on race time"""
    if race_time_seconds is None or race_time_seconds <= 0:
        return 0.0
    
    # Assuming 1/64 scale for Hot Wheels
    scale_factor = 64
    real_world_track_length_inches = TRACK_LENGTH_INCHES * scale_factor
    
    # Convert track length to miles
    # 1 mile = 63360 inches (5280 feet * 12 inches/foot)
    real_world_track_length_miles = real_world_track_length_inches / 63360.0
    
    # Convert race time to hours
    time_hours = race_time_seconds / 3600.0
    
    # Speed = Distance / Time
    speed_mph = real_world_track_length_miles / time_hours
    return speed_mph

def send_component_status():
    """Send current component status to the central server if connected."""
    if not sio.connected:
        # logger.debug("Socket.IO not connected. Skipping component status send.")
        return

    logger.info("Preparing and sending component status to central server...")
    
    # Basic I2C and MUX status
    i2c_status = "OK" if i2c_bus_global else "Error"
    mux_status = "OK" if mux_global else "Error"
    
    # Sensor status (check if light_sensors dict is populated for expected lanes)
    # Assuming 6 lanes are expected for this example
    num_expected_sensors = 6 # Could be made dynamic from config or num_lanes
    num_active_sensors = len(light_sensors)
    sensor_overall_status = "OK"
    if num_active_sensors == 0:
        sensor_overall_status = "Critical Error - No Sensors"
    elif num_active_sensors < num_expected_sensors:
        sensor_overall_status = f"Warning - {num_active_sensors}/{num_expected_sensors} Sensors Active"
    
    sensor_details = {}
    for lane, sensor_obj in light_sensors.items():
        try:
            current_lux = sensor_obj.last_reading if sensor_obj.last_reading is not None else "N/A"
            baseline_avg = sensor_obj.stable_average if sensor_obj.is_ready and sensor_obj.stable_average is not None else "Not Ready"
            sensor_details[f"Lane_{lane}"] = f"Lux: {current_lux}, Baseline: {baseline_avg}"
        except Exception:
            sensor_details[f"Lane_{lane}"] = "Error reading status"


    

    components = {
        'I2C Bus': i2c_status,
        'Multiplexer (TCA9548A)': mux_status,
        'Light Sensors (BH1750)': sensor_overall_status,
        'Sensor Details': sensor_details,
        'Display (Pygame)': "OK" if screen else "Error"
    }
    
    data = {
        'timestamp': time.time(), # Using Unix timestamp
        'components': components,
        'gate_type': 'finish_gate' # Identifier for this gate instance
    }
    
    try:
        sio.emit('update_component_status', data)
        logger.info("Component status sent successfully.")
    except Exception as e:
        logger.error(f"Error sending component status via Socket.IO: {e}")


def start_race_action():
    """Action to take when a race starts."""
    global race_in_progress, start_time, finish_times, placement_counter, current_results
    current_results = {}
    placement_counter = 1
    
    if race_in_progress:
        logger.warning("Attempted to start a race, but a race is already in progress.")
        return

    logger.info("Starting a new race...")
    
    # Calibrate all active light sensors before starting
    logger.info("Calibrating light sensors...")
    calibration_all_ok = True
    if not light_sensors:
        logger.error("No light sensors available for calibration. Race cannot start accurately.")
        calibration_all_ok = False
    else:
        for lane, sensor_obj in light_sensors.items():
            logger.info(f"Calibrating sensor for Lane {lane}...")
            if not sensor_obj.calibrate(): # calibrate() now returns True/False
                logger.error(f"Failed to calibrate sensor for Lane {lane}.")
                calibration_all_ok = False
                # Consider if race should proceed with some uncalibrated sensors
    
    if not calibration_all_ok:
        logger.error("One or more sensors failed to calibrate. Race accuracy may be affected.")
        # Optionally, prevent race start:
        # send_race_state_to_server('Error - Calibration Failed')
        # return

    race_in_progress = True
    start_time = time.perf_counter() # High-precision timer
    # finish_times array is already initialized for 6 lanes
    for i in range(len(finish_times)):
        finish_times[i] = None # Reset all lane finish times

    # Display "Race in Progress" or clear previous results
    if screen and font:
        screen.fill((0,0,0))
        try:
            text_surface = font.render(f"Race {formatted_race if formatted_race else ''} Started!", True, (255, 255, 0)) # Yellow
            screen.blit(text_surface, (SCREEN_WIDTH // 2 - text_surface.get_width() // 2, SCREEN_HEIGHT // 2 - text_surface.get_height() // 2))
            pygame.display.flip()
        except Exception as e:
            logger.error(f"Error displaying race start message: {e}")

    
    
    logger.info(f"Race {formatted_race if formatted_race else ''} started at {start_time:.4f}. Monitoring lanes.")
    send_race_state_to_server('Racing')

def display_race_end_prompt():
    """Display a prompt to press 'R' to start a new race."""
    if not screen or not font:
        return
        
    # Check if we're running in offline mode
    offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv
    
    if offline_mode:
        prompt_text = "Press 'R' to start a new local race"
    else:
        prompt_text = "Press 'R' to reset, or wait for server commands"
    
    text_surface = font.render(prompt_text, True, (255, 255, 255))
    text_rect = text_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT - 30))
    screen.blit(text_surface, text_rect)
    pygame.display.flip()


def finish_race_action():
    """Action to take when a race finishes (all cars crossed or timeout)."""
    global race_in_progress, track_record
    
    if not race_in_progress:
        logger.warning("Attempted to finish a race, but no race was in progress.")
        return

    logger.info(f"Race {formatted_race if formatted_race else ''} is now finishing...")
    race_in_progress = False # Mark race as no longer active
    
    # Process results
    results_list = [] # List of tuples: (lane, place, elapsed_time, speed)
    
    # Filter out None times for sorting, keep original index (lane-1)
    valid_finish_entries = [] # Only cars that actually finished (not timed out)
    timeout_entries = [] # Cars that timed out
    
    for idx, ft in enumerate(finish_times):
        if ft is not None and start_time is not None:
            elapsed = ft - start_time
            if elapsed > 0:
                # Check if this is a timeout DNF (at or very close to max duration)
                if abs(elapsed - max_race_duration_config) < 0.01:  # Within 10ms of timeout
                    # This is a timeout DNF
                    timeout_entries.append({'lane': idx + 1, 'elapsed': elapsed})
                    logger.info(f"Lane {idx + 1} TIMEOUT DNF at {elapsed:.3f}s (max duration: {max_race_duration_config}s)")
                else:
                    # This is a real finish
                    valid_finish_entries.append({'time': elapsed, 'lane': idx + 1})

    # Sort real finishers by time to determine place
    sorted_finishers = sorted(valid_finish_entries, key=lambda x: x['time'])
    
    # Handle ties by grouping times that are very close together
    TIE_THRESHOLD = 0.001  # 1 millisecond tie threshold
    
    winning_lane_num = None
    
    # Process real finishers with proper place assignment
    if sorted_finishers:
        current_place = 1
        
        for i, finisher in enumerate(sorted_finishers):
            lane_num = finisher['lane']
            elapsed_time = finisher['time']
            speed = calculate_speed(elapsed_time)
            
            # Check if this is a tie with the previous finisher
            if i > 0:  # Not the first finisher
                prev_time = sorted_finishers[i-1]['time']
                if abs(elapsed_time - prev_time) <= TIE_THRESHOLD:
                    # This is a tie - use the same place as previous finisher
                    place = results_list[-1][1]  # Get place from previous result
                    logger.info(f"TIE DETECTED! Lane {lane_num} ties with Lane {results_list[-1][0]} at place {place}.")
                else:
                    # Not a tie - assign current place
                    place = current_place
            else:
                # First finisher always gets place 1
                place = 1
                winning_lane_num = lane_num
            
            results_list.append((lane_num, place, elapsed_time, speed))
            
            # Only increment current_place if this wasn't a tie
            if i == 0 or abs(elapsed_time - sorted_finishers[i-1]['time']) > TIE_THRESHOLD:
                current_place = len(results_list) + 1  # Next available place

    # Add timeout DNF entries (place = None to mark as DNF)
    for timeout_entry in timeout_entries:
        lane_num = timeout_entry['lane']
        elapsed_time = timeout_entry['elapsed']
        results_list.append((lane_num, None, elapsed_time, None))  # place=None, speed=None for DNF
        logger.info(f"Lane {lane_num} marked as TIMEOUT DNF")

    # Add true DNF entries for lanes that didn't finish at all
    all_lanes_in_race = range(1, len(finish_times) + 1)
    finished_lane_numbers = [r[0] for r in results_list]
    for lane_num in all_lanes_in_race:
        if lane_num not in finished_lane_numbers:
            results_list.append((lane_num, None, None, None))  # True DNF - never started/finished
            logger.info(f"Lane {lane_num} marked as TRUE DNF (never finished)")

    # Check for new track record
    track_record_updated = False
    for result in results_list:
        lane_num, place, elapsed_time, speed = result
        # Only consider finished racers (not DNF), valid times over 2 seconds
        if place is not None and elapsed_time is not None and elapsed_time >= 2.0:
            if track_record is None or elapsed_time < track_record:
                track_record = elapsed_time
                track_record_updated = True
                logger.info(f"New track record set: {track_record:.3f}s by Lane {lane_num}!")
    
    # Save if the track record was updated
    if track_record_updated:
        save_track_record()

    # Ensure results_list is sorted by lane for consistent display
    results_list.sort(key=lambda x: x[0])

    # Check if we're running in offline mode
    offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv
    
    # Store final results for continued display in main loop
    main_loop.last_race_results = results_list
    
    # Display results on screen (MUST happen before checking offline mode)
    display_on_screen(results_list, formatted_race, num_lanes_to_display=len(finish_times))
    
    # Add the prompt to restart the race
    display_race_end_prompt()
    
    logger.info("Race results processed:")
    for res in results_list:
        if res[1] is None:
            if res[2] is not None:
                logger.info(f"  Lane {res[0]}: TIMEOUT DNF at {res[2]:.3f}s")
            else:
                logger.info(f"  Lane {res[0]}: TRUE DNF (never finished)")
        else:
            logger.info(f"  Lane {res[0]}: Place {res[1]}, Time {res[2]:.3f}s")
    
    # Continue with offline/online mode handling...
    if offline_mode:
        logger.info("Local test race complete. Results displayed. Waiting for user to press 'R' to start a new race.")
    else:
        send_race_state_to_server('Placement', winning_lane=winning_lane_num, results=results_list)
        time.sleep(max(5, getattr(config, 'RESULTS_DISPLAY_TIME', 5)))
        send_race_state_to_server('Finished', winning_lane=winning_lane_num, results=results_list)
        save_race_results_to_server(start_time, results_list)
        logger.info(f"Race {formatted_race if formatted_race else ''} officially concluded.")
        display_race_end_prompt()

def check_finish_conditions(num_lanes_active=6):
    """Check if any cars have finished or if race should timeout."""
    global finish_times, race_in_progress, current_results
    
    if not race_in_progress or start_time is None:
        return

    current_event_time = time.perf_counter() # Use a consistent time for this check cycle
    
    # Initialize current_results if not already done
    if 'current_results' not in globals():
        global current_results
        current_results = {}
    
    # REMOVED: display_on_screen call from here - this was causing flickering
    
    # Mapped lanes to check (1 through num_lanes_active)
    lanes_to_monitor = range(1, num_lanes_active + 1)
    
    # Check Light Sensors
    for lane_num in lanes_to_monitor:
        if lane_num in light_sensors and finish_times[lane_num - 1] is None: # If not already finished
            sensor_obj = light_sensors[lane_num]
            try:
                current_lux = sensor_obj.sensor.lux
                sensor_obj.update(current_lux) # Update sensor's internal state/average
                
                if sensor_obj.is_triggered(current_lux):
                    finish_times[lane_num - 1] = current_event_time
                    
                    logger.info(f"Lane {lane_num} FINISHED (Light Sensor)! Time: {current_event_time - start_time:.4f}s")
                    global placement_counter
                    elapsed_time = current_event_time - start_time
                    speed = calculate_speed(elapsed_time)
                    
                    # Update current_results for this lane
                    current_results[lane_num] = (lane_num, placement_counter, elapsed_time, speed)
                    
                    placement_counter += 1
            except Exception as e:
                logger.error(f"Error reading or processing sensor for Lane {lane_num}: {e}")
    
    # Check for DNF by Timeout and if all lanes are done
    all_lanes_accounted_for = True
    num_finished_lanes = 0

    for lane_idx in range(num_lanes_active): # 0 to num_lanes_active-1
        lane_num_for_log = lane_idx + 1
        if finish_times[lane_idx] is None: # If this lane hasn't recorded a finish time
            if (current_event_time - start_time) > max_race_duration_config:
                finish_times[lane_idx] = start_time + max_race_duration_config
                logger.info(f"Lane {lane_num_for_log} DNF (Timeout: >{max_race_duration_config}s).")
                # Add DNF to current_results
                dnf_elapsed = max_race_duration_config
                dnf_speed = None
                current_results[lane_num_for_log] = (lane_num_for_log, None, dnf_elapsed, dnf_speed)
            else:
                all_lanes_accounted_for = False # Still waiting for this lane, and not timed out yet
        else: # Lane has a finish time (either actual or DNF marker)
            num_finished_lanes += 1
            
    # If all active lanes have finished (either by crossing or DNF by timeout)
    if all_lanes_accounted_for or num_finished_lanes == num_lanes_active :
        logger.info("All active lanes have finished or timed out.")
        finish_race_action()
    elif (current_event_time - start_time) > (max_race_duration_config + 2) and race_in_progress:
        # Safety net: if race is still marked as in_progress well after timeout (e.g. a logic glitch)
        logger.warning("Race appears to have exceeded timeout significantly but not all lanes marked. Forcing finish.")
        # Ensure all remaining None lanes are marked DNF before finishing
        for lane_idx in range(num_lanes_active):
            if finish_times[lane_idx] is None or finish_times[lane_idx] == float('inf'):
                finish_times[lane_idx] = start_time + max_race_duration_config  # Set to actual timeout moment
                logger.info(f"Lane {lane_idx + 1} DNF (Timeout). Time set to {max_race_duration_config:.3f}s.")
        finish_race_action()

def reset_race_state():
    """Reset the gate to a ready state for a new race."""
    global race_in_progress, start_time, finish_times, current_race_number, formatted_race
    
    logger.info("Resetting race state...")
    
    race_in_progress = False
    start_time = None
    # finish_times already dimensioned for 6 lanes, just nullify
    for i in range(len(finish_times)):
        finish_times[i] = None
        
    # current_race_number and formatted_race are typically set by server or external trigger
    # For a local reset, they could be cleared or set to a default "Ready" state.
    # current_race_number = None 
    # formatted_race = "Ready for Next Race"

    if screen:
        screen.fill((50, 50, 50)) # Dim gray background for ready state
        if font:
            try:
                ready_text = "FINISH GATE READY"
                if formatted_race:
                    ready_text = f"{formatted_race} - READY"

                text_surface = font.render(ready_text, True, (200, 200, 200))
                screen.blit(text_surface, (SCREEN_WIDTH // 2 - text_surface.get_width() // 2, SCREEN_HEIGHT // 2 - text_surface.get_height() // 2))
            except Exception as e:
                logger.error(f"Error rendering ready text: {e}")
        pygame.display.flip()
 
    logger.info("Finish gate reset and ready for the next race.")
    send_race_state_to_server('Ready') # Inform server gate is ready
    send_component_status() # Send updated status after reset




# --- Socket.IO Event Handlers ---

@sio.event
def connect():
    logger.info("Socket.IO: Successfully connected to central server.")
    sio.emit('register_gate', {'gate_type': 'finish_gate', 'gate_id': getattr(config, 'GATE_ID', 'FinishGate_Default')})
    send_component_status()
    
    # Request current track record from server after connecting
    request_track_record_from_server()


    
    # Request current track record from server
    offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv
    if not offline_mode:
        sio.emit('get_track_record')
        logger.info("Requested current track record from central server")
    # Request current race state from server upon connection, or wait for server commands
    # sio.emit('get_current_race_state') # If server supports this








@sio.event
def connect_error(data):
    logger.error(f"Socket.IO: Connection failed! Data: {data}")
    # Implement retry logic or fallback to offline mode if desired

@sio.event
def disconnect():
    logger.info("Socket.IO: Disconnected from central server.")
    # Handle state if connection is lost (e.g., pause operations, attempt reconnect)

@sio.on('track_record_update')
def on_track_record_update(data):
    """Receive track record updates from the central server"""
    global track_record
    if 'track_record' in data and data['track_record'] is not None:
        server_record = data['track_record']
        
        # Always update from server if we have no local record, or if server record is faster
        if track_record is None or server_record < track_record:
            track_record = server_record
            logger.info(f"Updated track record from server: {track_record:.3f}s")
            save_track_record()  # Save to local storage
        else:
            logger.info(f"Server track record ({server_record:.3f}s) is not faster than local record ({track_record:.3f}s)")
    else:
        logger.info("Received track record update with no valid record from server")

@sio.on('race_command') # Generic command handler from server
def on_race_command(data):
    global current_race_number, formatted_race # Allow modification by server commands
    logger.info(f"Socket.IO: Received race_command: {data}")
    command = data.get('command')
    
    # Update race identifiers if provided
    if 'race_number' in data:
        current_race_number = data['race_number']
    if 'formatted_race' in data:
        formatted_race = data['formatted_race']

    if command == 'start_race':
        logger.info(f"Server initiated START_RACE for race: {formatted_race or current_race_number or 'Unknown'}")
        start_race_action()
    elif command == 'reset_gate':
        logger.info("Server initiated RESET_GATE.")
        reset_race_state()
    elif command == 'request_status':
        logger.info("Server requested component status.")
        send_component_status()
    # Add more commands as needed: e.g., 'abort_race', 'set_num_lanes'
    else:
        logger.warning(f"Received unknown race command: {command}")

# --- Socket.IO Emitters ---
def send_race_state_to_server(status_str, winning_lane=None, results=None):
    """Send race state update to the central server."""
    if not sio.connected:
        # logger.debug("Socket.IO not connected. Skipping race state send.")
        return

    data = {
        'gate_id': getattr(config, 'GATE_ID', 'FinishGate_Default'),
        'status': status_str,
        'current_time_epoch': time.time(),
        'race_start_time_perf': start_time, # Perf counter time, relative to this machine
        'finish_times_perf_delta': [(ft - start_time if ft is not None and ft != float('inf') and start_time is not None else None) for ft in finish_times],
        'winning_lane': winning_lane,
        'race_number': current_race_number,
        'formatted_race': formatted_race,
        'results_summary': results # Optional: send full processed results with state
    }
    
    try:
        sio.emit('gate_race_state_update', data)
        logger.info(f"Sent race state '{status_str}' to server for race '{formatted_race}'.")
    except Exception as e:
        logger.error(f"Error sending race state update via Socket.IO: {e}")

def save_race_results_to_server(race_start_perf_time, processed_results_list):
    """Save processed race results to the central server."""
    if not sio.connected:
        # logger.debug("Socket.IO not connected. Skipping save_results.")
        return

    # Convert results for server (e.g., ensure serializable)
    # processed_results_list is like: [(lane, place, elapsed_time, speed), ...]
    # elapsed_time is already delta from start_time (perf_counter)
    
    results_for_server = []
    for res_item in processed_results_list:
        lane, place, elapsed, speed = res_item
        results_for_server.append({
            'lane': lane,
            'place': place, # None for DNF
            'time_seconds': elapsed, # None for DNF
            'speed_mph': speed # None for DNF
        })

    payload = {
        'gate_id': getattr(config, 'GATE_ID', 'FinishGate_Default'),
        'race_start_epoch': time.time() - (time.perf_counter() - race_start_perf_time if race_start_perf_time else 0), # Approximate epoch start
        'race_start_perf_counter': race_start_perf_time,
        'results': results_for_server,
        'race_number': current_race_number,
        'formatted_race': formatted_race
    }
    
    try:
        sio.emit('save_finish_gate_results', payload)
        logger.info(f"Sent race results for '{formatted_race}' to server for saving.")
    except Exception as e:
        logger.error(f"Error sending race results for saving via Socket.IO: {e}")


def main_loop(num_lanes_in_use=6):
    """Main event loop for the finish gate system."""
    global running_main_loop, formatted_race, current_race_number
    running_main_loop = True
    
    last_status_send_time = time.time()
    last_display_update_time = time.time()
    status_send_interval = 30  # Send component status every 30 seconds
    display_update_interval = 0.1  # Update screen 10 times per second for live timing
    
    # Check if we're running in offline mode
    offline_mode = getattr(config, 'OFFLINE_MODE', False) or '--offline_mode' in sys.argv

    logger.info(f"Finish Gate main loop started. Monitoring {num_lanes_in_use} lanes.")
    send_race_state_to_server('Ready') # Initial state

    while running_main_loop:
        try:
            current_loop_time = time.time()

            # Handle Pygame events (for UI interaction, e.g., quitting)
            if screen: # Only process pygame events if display is active
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        logger.info("Pygame QUIT event received. Shutting down.")
                        running_main_loop = False
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_ESCAPE:
                            logger.info("ESCAPE key pressed. Shutting down.")
                            running_main_loop = False
                        elif event.key == pygame.K_SPACE: # Example: Manual race start/reset via spacebar
                            # Only allow starting a local test race if in offline mode
                            if not race_in_progress and offline_mode:
                                logger.info("SPACE key: Initiating local race start.")
                                # Create a local race ID
                                formatted_race = f"Test_{int(time.time())}"
                                start_race_action()
                            elif not race_in_progress and not offline_mode:
                                logger.info("SPACE key: Cannot start local race in online mode. Wait for server commands.")
                                # Display a message on screen if available
                                if screen and font:
                                    screen.fill((50, 0, 0))  # Dark red background to indicate error
                                    message = "Cannot start local race in online mode"
                                    text_surface = font.render(message, True, (255, 255, 255))
                                    text_rect = text_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2))
                                    screen.blit(text_surface, text_rect)
                                    
                                    submessage = "Switch to offline mode or wait for server commands"
                                    sub_surface = font.render(submessage, True, (255, 255, 255))
                                    sub_rect = sub_surface.get_rect(center=(SCREEN_WIDTH // 2, SCREEN_HEIGHT // 2 + 40))
                                    screen.blit(sub_surface, sub_rect)
                                    pygame.display.flip()
                            else:
                                logger.info("SPACE key: Race in progress. To reset, send command or use ESC to quit.")
                        elif event.key == pygame.K_r: # Example: Manual reset via 'r' key
                            logger.info("R key: Initiating gate reset.")
                            reset_race_state()
                            if offline_mode:
                                formatted_race = f"Test_{int(time.time())}"
                                start_race_action()

            # Core race logic: check for finishes if a race is active
            if race_in_progress:
                # Process sensor readings
                check_finish_conditions(num_lanes_active=num_lanes_in_use)

            # *** FIXED: ALWAYS UPDATE DISPLAY WHEN CONDITIONS ARE MET ***
            # Update display at regular intervals (whether race is active or not)
            if screen and font and (current_loop_time - last_display_update_time >= display_update_interval):
                last_display_update_time = current_loop_time
                
                if race_in_progress and start_time:
                    # *** LIVE RACE DISPLAY - SHOW CURRENT TIMING FOR ALL LANES ***
                    current_perf = time.perf_counter()
                    live_results = []

                    for idx in range(num_lanes_in_use):
                        lane = idx + 1
                        if finish_times[idx] is not None:
                            # Lane has finished - show final time and place
                            elapsed = finish_times[idx] - start_time
                            place = calculate_current_place(lane, finish_times, start_time)
                            speed = calculate_speed(elapsed)
                        else:
                            # Lane hasn't finished - show LIVE elapsed time
                            elapsed = current_perf - start_time
                            place = None  # No place until finished
                            speed = None  # No speed until finished

                        live_results.append((lane, place, elapsed, speed))
                    
                    # *** ALWAYS UPDATE DISPLAY DURING RACE ***
                    display_on_screen(live_results, formatted_race, num_lanes_to_display=num_lanes_in_use)
                    
                elif not race_in_progress:
                    # Race finished - continue showing final results with winner blinking
                    if hasattr(main_loop, 'last_race_results') and main_loop.last_race_results:
                        display_on_screen(main_loop.last_race_results, formatted_race, num_lanes_to_display=num_lanes_in_use)
            
            # Periodic tasks
            if current_loop_time - last_status_send_time > status_send_interval:
                send_component_status()
                last_status_send_time = current_loop_time
            
            # Small delay to prevent high CPU usage
            time.sleep(0.02)  # 20ms delay for CPU relief

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt detected in main loop. Shutting down.")
            running_main_loop = False
        except Exception as e:
            logger.error(f"Unhandled error in main loop: {e}", exc_info=True)
            time.sleep(1) 
    
    logger.info("Main loop terminated.")



def calculate_current_place(lane_num, finish_times_array, race_start_time):
    """Calculate the current place for a lane that has finished based on finish order."""
    if not race_start_time:
        return None
        
    lane_finish_time = finish_times_array[lane_num - 1]
    if lane_finish_time is None:
        return None  # Lane hasn't finished yet
    
    # Count how many lanes finished before this one
    place = 1
    lane_elapsed = lane_finish_time - race_start_time
    
    for i, ft in enumerate(finish_times_array):
        if ft is not None and ft != lane_finish_time:
            other_elapsed = ft - race_start_time
            if other_elapsed < lane_elapsed:
                place += 1
    
    return place

def cleanup_resources():
    """Clean up resources before exiting."""
    logger.info("Cleaning up resources...")
    
    if sio.connected:
        try:
            send_race_state_to_server('Offline') # Inform server gate is going offline
            sio.disconnect()
            logger.info("Socket.IO disconnected.")
        except Exception as e:
            logger.error(f"Error during Socket.IO disconnection: {e}")

    if screen: # Pygame was initialized
        try:
            pygame.quit()
            logger.info("Pygame quit successfully.")
        except Exception as e:
            logger.error(f"Error quitting Pygame: {e}")

    # Any other specific cleanup (e.g., releasing I2C lock if held, though busio usually handles this)
    # if i2c_bus_global and i2c_bus_global.locked():
    #     i2c_bus_global.unlock()
    
    logger.info("Cleanup complete. Exiting application.")


# --- Application Entry Point ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hot Wheels Finish Gate System")
    parser.add_argument('--lanes', type=int, default=6, help='Number of lanes to operate (1-6). Default: 6.')
    parser.add_argument('--test_hw', action='store_true', help='Run hardware tests (e.g., from I2CSystemChecker) on startup.')
    parser.add_argument('--calibrate_sensors', action='store_true', help='Run interactive sensor calibration routine on startup.')
    parser.add_argument('--offline_mode', action='store_true', help='Run in offline mode without attempting server connection.')
    parser.add_argument('--debug', action='store_true', help='Enable DEBUG level logging.')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("DEBUG logging enabled.")
        if 'sio' in globals() and sio:
            sio.eio.logger = True
        else:
            logger.warning("Socket.IO client 'sio' not defined globally, cannot enable its engineio logger.")

    # Sync system time with NTP before any other initialization
    sync_system_time()

    # Load local track record first (before any other initialization)
    load_track_record()

    NUMBER_OF_LANES = min(max(1, args.lanes), 6)
    logger.info(f"Finish Gate System starting for {NUMBER_OF_LANES} lanes.")

    # --- Hardware Initialization Sequence ---

    # Step 1: Set up Blinka Environment using I2CSystemChecker
    logger.info("MAIN: Step 1 - Detecting connection type and setting Blinka environment...")
    connection_type = I2CSystemChecker.detect_connection_type()
    if not connection_type:
        logger.critical("MAIN: Failed to establish Blinka environment via I2CSystemChecker. Exiting.")
        sys.exit(1)
    logger.info(f"MAIN: Blinka environment set for connection type: {connection_type}")

    # Step 2: Run I2CSystemChecker's MUX/sensor detection
    logger.info("MAIN: Step 2 - Running I2CSystemChecker.detect_multiplexer_and_sensors() for diagnostics and to get MUX object...")
    _diagnostic_sensor_report_list, tca_object_from_checker, _diagnostic_mux_type_str = I2CSystemChecker.detect_multiplexer_and_sensors()

    # Add sensor check
    sensors_found = sum(1 for sensor_info in _diagnostic_sensor_report_list if sensor_info[1])
    if sensors_found < NUMBER_OF_LANES:
        logger.warning(f"MAIN: Only {sensors_found} out of {NUMBER_OF_LANES} required BH1750 sensors were detected by I2CSystemChecker.")
        if sensors_found == 0:
            logger.critical("MAIN: No BH1750 sensors detected! The finish gate requires BH1750 sensors for operation.")
    else:
        logger.info(f"MAIN: All {NUMBER_OF_LANES} required BH1750 sensors were detected by I2CSystemChecker.")
    
    if tca_object_from_checker:
        logger.info(f"MAIN: I2CSystemChecker's diagnostic run provided a MUX object (type: {_diagnostic_mux_type_str}). This will be passed to the main hardware initializer.")
    else:
        logger.warning("MAIN: I2CSystemChecker's diagnostic run did NOT provide a MUX object. The main hardware initializer will attempt manual setup.")

    # Step 3: Call main hardware initialization function
    logger.info("MAIN: Step 3 - Initializing application hardware using checker's MUX (if available) or attempting manual setup...")
    if not initialize_hardware(num_lanes=NUMBER_OF_LANES, tca_from_checker=tca_object_from_checker):
        logger.critical("MAIN: Application hardware initialization failed. The system may not function correctly or will exit.")
    else:
        logger.info("MAIN: Application hardware initialization successful.")
        if light_sensors:
             logger.info(f"MAIN: Active LightSensor objects for lanes: {list(light_sensors.keys())}")
        else:
             logger.warning("MAIN: Application hardware init reported success, but no LightSensor objects were created.")

    # (Optional) Run additional diagnostic methods if --test_hw flag is set
    if args.test_hw:
        logger.info("MAIN: Step 3b (Optional based on --test_hw) - Running additional I2C System Checker diagnostics...")
        I2CSystemChecker.check_libraries()
        I2CSystemChecker.detect_i2c_buses()
        logger.info("MAIN: Additional I2C diagnostics (from --test_hw) complete.")

    # Initialize display
    logger.info("MAIN: Initializing display...")
    if not initialize_display():
        logger.error("MAIN: Failed to initialize display.")

    # Optional: Run sensor calibration routine if commanded
    if args.calibrate_sensors:
        logger.info("MAIN: Sensor calibration mode activated from command line.")
        if not light_sensors:
            logger.error("MAIN: Cannot run calibration: No light sensors were initialized by initialize_hardware.")
        else:
            logger.info("--- Interactive Sensor Calibration ---")
            all_calibrated_successfully = True
            for lane_num, sensor_obj in sorted(light_sensors.items()):
                logger.info(f"\nCalibrating Lane {lane_num}:")
                if hasattr(sensor_obj, 'calibrate') and callable(sensor_obj.calibrate):
                    if not sensor_obj.calibrate():
                        all_calibrated_successfully = False
                        logger.error(f"MAIN: Calibration failed for Lane {lane_num}.")
                    else:
                        stable_avg_str = f"{sensor_obj.stable_average:.2f}" if hasattr(sensor_obj, 'stable_average') and sensor_obj.stable_average is not None else "N/A"
                        dyn_thresh_str = f"{sensor_obj.dynamic_threshold:.2f}" if hasattr(sensor_obj, 'dynamic_threshold') and sensor_obj.dynamic_threshold is not None else "N/A"
                        trig_perc_str = f"{sensor_obj.adaptive_trigger_percentage:.1f}" if hasattr(sensor_obj, 'adaptive_trigger_percentage') and sensor_obj.adaptive_trigger_percentage is not None else "N/A"
                        logger.info(f"  Initial state for Lane {lane_num}: StableAvg={stable_avg_str} Lux, DynThresh={dyn_thresh_str} Lux, Trig%={trig_perc_str}%")
                else:
                    logger.error(f"MAIN: Sensor object for Lane {lane_num} does not have a callable 'calibrate' method.")
                    all_calibrated_successfully = False
            
            if all_calibrated_successfully and light_sensors:
                logger.info("\n--- Live Monitoring Post-Calibration (Ctrl+C to exit calibration mode) ---")
                try:
                    while True:
                        print("-" * 30)
                        for lane_num, sensor_obj in sorted(light_sensors.items()):
                            try:
                                if hasattr(sensor_obj, 'sensor') and hasattr(sensor_obj.sensor, 'lux'):
                                    lux = sensor_obj.sensor.lux
                                    if hasattr(sensor_obj, 'update'):
                                        sensor_obj.update(lux)
                                    
                                    triggered_str = ""
                                    if hasattr(sensor_obj, 'is_triggered') and callable(sensor_obj.is_triggered):
                                        if sensor_obj.is_triggered(lux):
                                            triggered_str = ' <<<TRIGGERED>>>'
                                    
                                    s_avg = getattr(sensor_obj, 'stable_average', 0) or 0
                                    d_thr = getattr(sensor_obj, 'dynamic_threshold', 0) or 0
                                    a_trig_p = getattr(sensor_obj, 'adaptive_trigger_percentage', 0.0) or 0.0

                                    print(f"Lane {lane_num}: Lux={lux:7.2f}, Avg={s_avg:7.2f}, DynThr={d_thr:7.2f}, Trig%={a_trig_p:4.1f}{triggered_str}")
                                else:
                                    print(f"Lane {lane_num}: Sensor object or lux attribute missing.")
                            except Exception as e_read:
                                print(f"Lane {lane_num}: Error reading/processing sensor - {e_read}")
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    logger.info("MAIN: Exiting interactive calibration mode.")
            else:
                logger.error("MAIN: Calibration not fully successful or no sensors to monitor live.")

        logger.info("MAIN: Calibration routine finished.")

    # Connect to Socket.IO server (unless in offline mode)
    if not args.offline_mode:
        try:
            if 'CENTRAL_SERVER_URL' in globals() and CENTRAL_SERVER_URL:
                logger.info(f"MAIN: Attempting to connect to Socket.IO server at {CENTRAL_SERVER_URL}...")
                if 'sio' in globals() and sio:
                    sio.connect(CENTRAL_SERVER_URL, transports=['websocket'])
                    # Track record will be requested automatically in the connect() event handler
                    logger.info("MAIN: Connected to Socket.IO server. Track record will be requested automatically.")
                else:
                    logger.error("MAIN: Socket.IO client 'sio' is not defined. Cannot connect.")
            else:
                logger.error("MAIN: CENTRAL_SERVER_URL is not defined. Cannot connect to Socket.IO server.")
        except socketio.exceptions.ConnectionError as e:
            logger.error(f"MAIN: Socket.IO connection failed: {e}. Using local track record only.")
        except NameError:
            logger.error("MAIN: Socket.IO client 'sio' or 'CENTRAL_SERVER_URL' not defined. Cannot attempt connection.")
        except Exception as e_sio_connect:
            logger.error(f"MAIN: An unexpected error occurred during Socket.IO connection: {e_sio_connect}. Using local track record only.")
    else:
        logger.info("MAIN: Offline mode enabled. Using local track record only.")

    # Start the main application loop
    try:
        if 'main_loop' in globals() and callable(main_loop):
            logger.info("MAIN: Starting main application loop...")
            main_loop(num_lanes_in_use=NUMBER_OF_LANES)
        else:
            logger.critical("MAIN: main_loop function is not defined. Cannot start application.")
            sys.exit(1)
    except Exception as e_main_loop_start:
        logger.critical(f"MAIN: Error before or during start of main_loop: {e_main_loop_start}", exc_info=True)
    finally:
        if 'cleanup_resources' in globals() and callable(cleanup_resources):
            logger.info("MAIN: Initiating cleanup...")
            cleanup_resources()
        else:
            logger.warning("MAIN: cleanup_resources function not defined. Skipping cleanup.")
        logger.info("MAIN: Application has shut down.")
        sys.exit(0)
