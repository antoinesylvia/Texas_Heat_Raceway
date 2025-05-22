import os
os.environ['BLINKA_MCP2221'] = '1'

import argparse

from collections import deque

import digitalio
import logging
import numpy as np # Typically aliased as np

import pygame
import socketio # Or from socketio import Client if you only use Client directly
import subprocess
import sys
import time

import config # Local application import

from PIL import Image, ImageDraw, ImageFont

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
                        print(f"MCP2221A detected via HID library")
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
            from adafruit_blinka.microcontroller.mcp2221 import pin
            # This import should be at the top of your file, not inside the function
            # import adafruit_tca9548a # Moved for clarity, though Python allows local import

            # Create I2C bus
            i2c = busio.I2C(pin.SCL, pin.SDA)# This is where Blinka talks to the hardware
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
        if current_light_level is None: return

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

def initialize_hardware(num_lanes=6, tca_from_checker=None): # Added tca_from_checker parameter
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
                while not channel_i2c_bus.try_lock(): time.sleep(0.01)
                try: channel_scan_devices = channel_i2c_bus.scan()
                finally: channel_i2c_bus.unlock()

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
        
        if sensors_on_mux_count > 0:
            logger.info(f"AppHW: Successfully initialized {sensors_on_mux_count} LightSensors using checker's MUX.")
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
                while not app_level_i2c_bus.try_lock(): time.sleep(0.01)
                try: devices = app_level_i2c_bus.scan()
                finally: app_level_i2c_bus.unlock()

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
            logger.error("AppHW: Multiple lanes configured, but no MUX object was provided by checker, and cannot proceed.")
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
    logger.info(f"Initializing display...")
    
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
    global screen, font
    if not screen or not font:
        logger.warning("Display not available, cannot show results on screen.")
        return

    screen.fill((0, 0, 0))  # Black background

    # Display Race ID at the top center
    if current_formatted_race_id:
        try:
            text_surface = font.render(f"Race: {current_formatted_race_id}", True, (255, 255, 255))
            screen.blit(text_surface, (SCREEN_WIDTH // 2 - text_surface.get_width() // 2, 5))
        except Exception as e:
            logger.error(f"Error rendering race ID: {e}")

    # Calculate layout
    column_width = SCREEN_WIDTH // num_lanes_to_display
    top_offset = 40
    row_spacing = 5

    for i in range(num_lanes_to_display):
        lane_number = i + 1
        result = next((r for r in race_results_list if r[0] == lane_number), None)
        x = i * column_width
        y = top_offset

        # Background color
        bg_color = (0, 100, 0) if result and result[1] == 1 else (50, 50, 50)
        pygame.draw.rect(screen, bg_color, (x + 5, y, column_width - 10, SCREEN_HEIGHT - y - 10))

        # Text color
        text_color = (255, 255, 255)

        lines = [
            f"Lane {lane_number}",
            f"Place: {result[1] if result and result[1] else 'DNF'}",
            f"Time: {result[2]:.3f}s" if result and result[2] is not None else "Time: ---",
            f"Speed: {result[3]:.2f} mph" if result and result[3] is not None else "Speed: ---"
        ]

        for line in lines:
            try:
                text_surface = font.render(line, True, text_color)
                screen.blit(text_surface, (x + 15, y))
                y += text_surface.get_height() + row_spacing
            except Exception as e:
                logger.error(f"Error rendering line for lane {lane_number}: {e}")

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
    global race_in_progress, start_time, finish_times
    
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


def finish_race_action():
    """Action to take when a race finishes (all cars crossed or timeout)."""
    global race_in_progress
    
    if not race_in_progress:
        logger.warning("Attempted to finish a race, but no race was in progress.")
        return

    logger.info(f"Race {formatted_race if formatted_race else ''} is now finishing...")
    race_in_progress = False # Mark race as no longer active
    
    # Process results
    results_list = [] # List of tuples: (lane, place, elapsed_time, speed)
    
    # Filter out None times for sorting, keep original index (lane-1)
    valid_finish_entries = [] # (time, original_lane_index)
    for idx, ft in enumerate(finish_times):
        if ft is not None and start_time is not None: # Ensure start_time is also valid
             # Check for reasonable finish times (e.g. not before start, not excessively long if not DNF by timeout)
            elapsed = ft - start_time
            if elapsed > 0: # Must be a positive elapsed time
                valid_finish_entries.append({'time': elapsed, 'lane': idx + 1})

    # Sort by time to determine place
    sorted_finishers = sorted(valid_finish_entries, key=lambda x: x['time'])
    
    winning_lane_num = None
    
    # Assign places and calculate speeds
    current_place = 1
    for finisher_entry in sorted_finishers:
        lane_num = finisher_entry['lane']
        elapsed_time = finisher_entry['time']
        speed = calculate_speed(elapsed_time)
        results_list.append((lane_num, current_place, elapsed_time, speed))
        if current_place == 1:
            winning_lane_num = lane_num
        current_place += 1

    # Add DNF entries for lanes that didn't finish or had invalid times
    all_lanes_in_race = range(1, len(finish_times) + 1) # Assumes finish_times represents all possible lanes
    finished_lane_numbers = [r[0] for r in results_list]
    for lane_num in all_lanes_in_race:
        if lane_num not in finished_lane_numbers:
            results_list.append((lane_num, None, None, None)) # DNF

    # Ensure results_list is sorted by lane for consistent display if needed, though display might re-sort or handle order.
    results_list.sort(key=lambda x: x[0])


    # Display results on screen
    display_on_screen(results_list, formatted_race, num_lanes_to_display=len(finish_times))
    
    logger.info("Race results processed:")
    for res in results_list:
        logger.info(f"  Lane {res[0]}: Place {res[1] if res[1] else 'DNF'}, Time {res[2]:.3f}s" if res[2] is not None else f"  Lane {res[0]}: DNF")

    # Send 'Placement' state (results available) and then 'Finished' state
    send_race_state_to_server('Placement', winning_lane=winning_lane_num, results=results_list)
    
    # Optional: delay before sending final "Finished" state to allow viewing of placement
    time.sleep(max(5, getattr(config, 'RESULTS_DISPLAY_TIME', 5))) # Display results for at least 5s

    send_race_state_to_server('Finished', winning_lane=winning_lane_num, results=results_list)
    save_race_results_to_server(start_time, results_list) # Save the processed results

    logger.info(f"Race {formatted_race if formatted_race else ''} officially concluded.")


def check_finish_conditions(num_lanes_active=6):
    """Check if any cars have finished or if race should timeout."""
    global finish_times, race_in_progress
    
    if not race_in_progress or start_time is None:
        return

    current_event_time = time.perf_counter() # Use a consistent time for this check cycle
    
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
                # Turn on LED to indicate DNF or some other signal? Optional.
                # if lane_num_for_log in leds: leds[lane_num_for_log].value = True # Example: also light up DNF lanes
            else:
                all_lanes_accounted_for = False # Still waiting for this lane, and not timed out yet
        else: # Lane has a finish time (either actual or DNF marker)
            num_finished_lanes +=1
            
    # If all active lanes have finished (either by crossing or DNF by timeout)
    if all_lanes_accounted_for or num_finished_lanes == num_lanes_active :
        logger.info("All active lanes have finished or timed out.")
        finish_race_action()
    elif (current_event_time - start_time) > (max_race_duration_config + 2) and race_in_progress:
        # Safety net: if race is still marked as in_progress well after timeout (e.g. a logic glitch)
        logger.warning(f"Race appears to have exceeded timeout significantly but not all lanes marked. Forcing finish.")
        # Ensure all remaining None lanes are marked DNF before finishing
        for lane_idx in range(num_lanes_active):
            if finish_times[lane_idx] is None:
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
                if formatted_race: ready_text = f"{formatted_race} - READY"

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
    global running_main_loop, formatted_race, current_race_number  # Add these to the globals
    running_main_loop = True
    
    last_status_send_time = time.time()
    status_send_interval = 30 # Send component status every 30 seconds

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
                            if not race_in_progress:
                                logger.info("SPACE key: Initiating race start.")
                                # Potentially set a dummy race ID if not from server
                                if not formatted_race: formatted_race = f"LocalTest_{int(time.time())}"
                                start_race_action()
                            else:
                                logger.info("SPACE key: Race in progress. To reset, send command or use ESC to quit.")
                        elif event.key == pygame.K_r: # Example: Manual reset via 'r' key
                             logger.info("R key: Initiating gate reset.")
                             reset_race_state()


            # Core race logic: check for finishes if a race is active
            if race_in_progress:
                check_finish_conditions(num_lanes_active=num_lanes_in_use)
            else:
                # When no race is in progress, sensors might still be updated for ambient tracking
                # This is handled within LightSensor.update() if called periodically
                # For now, sensor updates are mainly driven by check_finish_conditions or calibration
                pass # Idle state for sensors unless specific monitoring is needed

            
                # Draw live race progress (with current elapsed times)
            if screen and font and start_time:
                current_perf = time.perf_counter()
                live_results = []

                for idx in range(NUMBER_OF_LANES):
                    lane = idx + 1
                    if finish_times[idx] is not None:
                        elapsed = finish_times[idx] - start_time
                        place = None  # Will be filled in after race ends
                        speed = calculate_speed(elapsed)
                    else:
                        elapsed = current_perf - start_time
                        place = None
                        speed = None

                    live_results.append((lane, place, elapsed, speed))

                display_on_screen(live_results, formatted_race, num_lanes_to_display=NUMBER_OF_LANES)

            
            # Periodic tasks
            if current_loop_time - last_status_send_time > status_send_interval:
                send_component_status()
                last_status_send_time = current_loop_time
            
            # Small delay to prevent high CPU usage, also allows Socket.IO client to process
            # sio.sleep is non-blocking for the Socket.IO thread if background tasks are used
            if sio.connected:
                sio.sleep(0.02) # Let Socket.IO do its thing
            else:
                time.sleep(0.02) # Regular sleep if not connected

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt detected in main loop. Shutting down.")
            running_main_loop = False
        except Exception as e:
            logger.error(f"Unhandled error in main loop: {e}", exc_info=True)
            # Potentially add a short sleep to prevent rapid error loops if error is persistent
            time.sleep(1) 
    
    logger.info("Main loop terminated.")


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

    # Ensure logger and sio are configured and accessible globally before this point
    # Example:
    # logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    # logger = logging.getLogger(__name__)
    # sio = socketio.Client(logger=True, engineio_logger=True)
    # CENTRAL_SERVER_URL = config.CENTRAL_SERVER_URL # Ensure this is loaded

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        for handler in logging.getLogger().handlers:
            handler.setLevel(logging.DEBUG)
        logger.info("DEBUG logging enabled.")
        if 'sio' in globals() and sio: # Check if sio is defined
            sio.eio.logger = True
        else:
            logger.warning("Socket.IO client 'sio' not defined globally, cannot enable its engineio logger.")


    NUMBER_OF_LANES = min(max(1, args.lanes), 6) # Clamp lanes between 1 and 6
    logger.info(f"Finish Gate System starting for {NUMBER_OF_LANES} lanes.")

    # --- Hardware Initialization Sequence ---

    # Step 1: Set up Blinka Environment using I2CSystemChecker
    # This is crucial for 'board' and 'busio' imports to work correctly later.
    logger.info("MAIN: Step 1 - Detecting connection type and setting Blinka environment...")
    connection_type = I2CSystemChecker.detect_connection_type() # Assumes I2CSystemChecker is defined
    if not connection_type:
        logger.critical("MAIN: Failed to establish Blinka environment via I2CSystemChecker. Exiting.")
        sys.exit(1) # Essential to exit if this fails for reliable hardware access
    logger.info(f"MAIN: Blinka environment set for connection type: {connection_type}")

    # Step 2: Run I2CSystemChecker's MUX/sensor detection.
    # This is primarily for its diagnostic output and to attempt to get a working TCA MUX object
    # that its "better written" internal logic might have successfully initialized.
    logger.info("MAIN: Step 2 - Running I2CSystemChecker.detect_multiplexer_and_sensors() for diagnostics and to get MUX object...")
    # The I2CSystemChecker.detect_multiplexer_and_sensors() method, as per your class structure,
    # returns: (diagnostic_sensor_status_list, tca_object_it_created, mux_type_string)
    _diagnostic_sensor_report_list, tca_object_from_checker, _diagnostic_mux_type_str = I2CSystemChecker.detect_multiplexer_and_sensors()

    if tca_object_from_checker:
        logger.info(f"MAIN: I2CSystemChecker's diagnostic run provided a MUX object (type: {_diagnostic_mux_type_str}). This will be passed to the main hardware initializer.")
    else:
        logger.warning("MAIN: I2CSystemChecker's diagnostic run did NOT provide a MUX object (it was not found or an error occurred during its internal initialization). The main hardware initializer will attempt manual setup.")

    # Step 3: Call your main hardware initialization function.
    # It should be modified to accept 'tca_from_checker' as an argument.
    # (Ensure 'initialize_hardware' function is defined in your script as discussed previously,
    #  capable of using a passed TCA object or doing its own full setup).
    logger.info("MAIN: Step 3 - Initializing application hardware using checker's MUX (if available) or attempting manual setup...")
    # The `initialize_hardware` function needs to be the modified one that accepts `tca_from_checker`.
    if not initialize_hardware(num_lanes=NUMBER_OF_LANES, tca_from_checker=tca_object_from_checker):
        logger.critical("MAIN: Application hardware initialization failed. The system may not function correctly or will exit.")
        # Depending on severity, you might want to exit here.
        # For now, allowing to proceed to see if other parts can be tested, as per original comment.
        # sys.exit(1)
    else:
        logger.info("MAIN: Application hardware initialization successful.")
        if light_sensors: # Check if light_sensors got populated
             logger.info(f"MAIN: Active LightSensor objects for lanes: {list(light_sensors.keys())}")
        else:
             logger.warning("MAIN: Application hardware init reported success, but no LightSensor objects were created.")


    # (Optional) Run other purely diagnostic methods from I2CSystemChecker if the --test_hw flag is set
    if args.test_hw:
        logger.info("MAIN: Step 3b (Optional based on --test_hw) - Running additional I2C System Checker diagnostics...")
        I2CSystemChecker.check_libraries() # Assumes this is a static method or callable
        I2CSystemChecker.detect_i2c_buses() # This uses command line i2cdetect
        # Note: detect_multiplexer_and_sensors was already called, but calling again would repeat its specific diagnostics.
        logger.info("MAIN: Additional I2C diagnostics (from --test_hw) complete.")


    # Initialize display
    # Ensure initialize_display function is defined in your script
    logger.info("MAIN: Initializing display...")
    if not initialize_display(): # Assuming initialize_display returns True/False
        logger.error("MAIN: Failed to initialize display.")
        # Decide if this is critical enough to exit

    # Optional: Run sensor calibration routine if commanded
    if args.calibrate_sensors:
        logger.info("MAIN: Sensor calibration mode activated from command line.")
        if not light_sensors: # Check if sensors were actually initialized
            logger.error("MAIN: Cannot run calibration: No light sensors were initialized by initialize_hardware.")
        else:
            logger.info("--- Interactive Sensor Calibration ---")
            all_calibrated_successfully = True
            for lane_num, sensor_obj in sorted(light_sensors.items()):
                logger.info(f"\nCalibrating Lane {lane_num}:")
                if hasattr(sensor_obj, 'calibrate') and callable(sensor_obj.calibrate):
                    if not sensor_obj.calibrate(): # Assuming calibrate returns True/False
                        all_calibrated_successfully = False
                        logger.error(f"MAIN: Calibration failed for Lane {lane_num}.")
                    else:
                        # Ensure these attributes exist before trying to format them
                        stable_avg_str = f"{sensor_obj.stable_average:.2f}" if hasattr(sensor_obj, 'stable_average') and sensor_obj.stable_average is not None else "N/A"
                        dyn_thresh_str = f"{sensor_obj.dynamic_threshold:.2f}" if hasattr(sensor_obj, 'dynamic_threshold') and sensor_obj.dynamic_threshold is not None else "N/A"
                        trig_perc_str = f"{sensor_obj.adaptive_trigger_percentage:.1f}" if hasattr(sensor_obj, 'adaptive_trigger_percentage') and sensor_obj.adaptive_trigger_percentage is not None else "N/A"
                        logger.info(f"  Initial state for Lane {lane_num}: StableAvg={stable_avg_str} Lux, DynThresh={dyn_thresh_str} Lux, Trig%={trig_perc_str}%")
                else:
                    logger.error(f"MAIN: Sensor object for Lane {lane_num} does not have a callable 'calibrate' method.")
                    all_calibrated_successfully = False
            
            if all_calibrated_successfully and light_sensors: # Check light_sensors again
                logger.info("\n--- Live Monitoring Post-Calibration (Ctrl+C to exit calibration mode) ---")
                try:
                    while True:
                        print("-" * 30) # Adjusted width
                        for lane_num, sensor_obj in sorted(light_sensors.items()):
                            try:
                                if hasattr(sensor_obj, 'sensor') and hasattr(sensor_obj.sensor, 'lux'):
                                    lux = sensor_obj.sensor.lux
                                    if hasattr(sensor_obj, 'update'): sensor_obj.update(lux) # Update internal states
                                    
                                    triggered_str = ""
                                    if hasattr(sensor_obj, 'is_triggered') and callable(sensor_obj.is_triggered):
                                        if sensor_obj.is_triggered(lux):
                                            triggered_str = ' <<<TRIGGERED>>>'
                                    
                                    # Safe attribute access for printing
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
        # sys.exit(0) # Optionally exit after calibration if it's a dedicated mode

    # Connect to Socket.IO server (unless in offline mode)
    if not args.offline_mode:
        try:
            # Ensure CENTRAL_SERVER_URL is defined
            if 'CENTRAL_SERVER_URL' in globals() and CENTRAL_SERVER_URL:
                logger.info(f"MAIN: Attempting to connect to Socket.IO server at {CENTRAL_SERVER_URL}...")
                if 'sio' in globals() and sio: # Check if sio is defined
                    sio.connect(CENTRAL_SERVER_URL, transports=['websocket'])
                else:
                    logger.error("MAIN: Socket.IO client 'sio' is not defined. Cannot connect.")
            else:
                logger.error("MAIN: CENTRAL_SERVER_URL is not defined. Cannot connect to Socket.IO server.")
        except socketio.exceptions.ConnectionError as e:
            logger.error(f"MAIN: Socket.IO connection failed: {e}. Running in OFFLINE mode if applicable, or check server.")
        except NameError: # Handles if sio or CENTRAL_SERVER_URL were not defined
            logger.error("MAIN: Socket.IO client 'sio' or 'CENTRAL_SERVER_URL' not defined. Cannot attempt connection.")
        except Exception as e_sio_connect: # Catch other potential errors during connect
            logger.error(f"MAIN: An unexpected error occurred during Socket.IO connection: {e_sio_connect}")
    else:
        logger.info("MAIN: Offline mode enabled. Skipping Socket.IO server connection.")


    # Start the main application loop
    # Ensure main_loop and cleanup_resources functions are defined in your script
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
        sys.exit(0) # Ensure a clean exit
