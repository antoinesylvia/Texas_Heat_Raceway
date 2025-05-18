#!/usr/bin/env python3
"""
Advanced I2C Sensor Test Script for Raspbian
Auto-detects connection type (Raspberry Pi HAT or MCP2221A), multiplexer type, and sensors

Usage:
    python sensaor_calibration_done.py       # Run full automated test
    python sensor_calibration_done.py -m    # Run in manual/interactive mode
"""
import time
import sys
import subprocess
import os
import argparse

# Add argument parsing
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

def run_manual_menu():
    """Display an interactive menu for manual testing"""
    while True:
        print_header("MANUAL MODE - I2C Sensor Test Menu")
        print("Select a test to run:")
        print("1. Connection Type Detection")
        print("2. I2C Bus Detection")
        print("3. Library Detection")
        print("4. Multiplexer and Sensor Detection")
        print("5. Light Sensitivity Test (requires working sensors)")
        print("6. Run Complete Test Suite (automated mode)")
        print("0. Exit")
        
        choice = input("\nEnter choice (0-6): ").strip()
        
        if choice == '0':
            print("Exiting program.")
            return
        elif choice == '1':
            detect_connection_type()
        elif choice == '2':
            detect_i2c_buses()
        elif choice == '3':
            check_libraries()
        elif choice == '4':
            detect_multiplexer_and_sensors()
        elif choice == '5':
            run_light_sensitivity_test()
        elif choice == '6':
            run_full_automated_test()
        else:
            print("Invalid choice. Please try again.")
        
        input("\nPress Enter to return to menu...")

# Break down the existing code into functions that can be called independently

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
sensor_results = []
tca = None
mux_type = None

def detect_multiplexer_and_sensors():
    global sensor_results, tca, mux_type
    print_header("Multiplexer and Sensor Detection")
    
    try:
        import board
        import busio
        import adafruit_tca9548a
        
        # Create I2C bus
        i2c = busio.I2C(board.SCL, board.SDA)
        print("✓ Successfully created I2C object")
        
        # Scan for I2C devices
        print("\nScanning for I2C devices directly...")
        devices = []
        
        while not i2c.try_lock():
            pass
        try:
            devices = i2c.scan()
        finally:
            i2c.unlock()
        
        if devices:
            print(f"Found {len(devices)} I2C devices:")
            for device in devices:
                print(f"  Device at address: 0x{device:02X}")
            
            # Check for multiplexer at default address 0x70
            mux_found = False
            
            if 0x70 in devices:
                print("Found a multiplexer at address 0x70")
                print("Attempting to identify multiplexer type...")
                
                # Try to initialize as TCA9548A
                try:
                    import adafruit_tca9548a
                    tca = adafruit_tca9548a.TCA9548A(i2c)
                    print("✓ Successfully initialized as TCA9548A")
                    mux_found = True
                    mux_type = "TCA9548A"
                except Exception as e:
                    print(f"Failed to initialize as TCA9548A: {e}")
                    
                    # Try to initialize as PCA9548A
                    try:
                        # PCA9548A should work with the same library but might have different behavior
                        print("Attempting to initialize as PCA9548A...")
                        tca = adafruit_tca9548a.TCA9548A(i2c)
                        
                        # Test if we can access a channel - this would confirm it's working
                        test_channel = tca[0]
                        test_channel_devices = []
                        while not test_channel.try_lock():
                            pass
                        try:
                            test_channel_devices = test_channel.scan()
                        finally:
                            test_channel.unlock()
                        
                        print("✓ Successfully initialized as PCA9548A")
                        mux_found = True
                        mux_type = "PCA9548A"
                    except Exception as e:
                        print(f"Failed to initialize as PCA9548A: {e}")
                        print("Unable to identify multiplexer type")
                
                # If multiplexer was found and initialized
                if mux_found and tca:
                    print(f"✓ Using {mux_type} multiplexer at address 0x70")
                    
                    # Store results for final summary
                    sensor_results = []
                    
                    # Check each channel for BH1750 sensors
                    for channel in range(6):  # Check 6 channels for 6 lanes
                        print(f"\nTesting channel {channel}...")
                        
                        # Get I2C bus for this channel
                        try:
                            channel_bus = tca[channel]
                            print(f"✓ Channel {channel} accessible")
                            
                            # Scan for devices on this channel
                            channel_devices = []
                            
                            while not channel_bus.try_lock():
                                pass
                            try:
                                channel_devices = channel_bus.scan()
                            finally:
                                channel_bus.unlock()
                            
                            if channel_devices:
                                print(f"Found {len(channel_devices)} devices on channel {channel}:")
                                for device in channel_devices:
                                    print(f"  Device at address: 0x{device:02X}")
                                
                                # Check for BH1750 sensor (typically at address 0x23)
                                if 0x23 in channel_devices:
                                    try:
                                        import adafruit_bh1750
                                        sensor = adafruit_bh1750.BH1750(channel_bus)
                                        lux = sensor.lux
                                        print(f"✓ BH1750 sensor found on channel {channel}")
                                        print(f"  Light reading: {lux:.2f} lux")
                                        sensor_results.append((channel, True, lux))
                                    except Exception as e:
                                        print(f"✗ Error reading from BH1750 on channel {channel}: {e}")
                                        sensor_results.append((channel, False, 0))
                                else:
                                    print(f"✗ No BH1750 sensor found at address 0x23 on channel {channel}")
                                    sensor_results.append((channel, False, 0))
                            else:
                                print(f"No devices found on channel {channel}")
                                sensor_results.append((channel, False, 0))
                        except Exception as e:
                            print(f"✗ Error accessing channel {channel}: {e}")
                            sensor_results.append((channel, False, 0))
                    
                    # Print a summary at the end
                    print_header("Sensor Test Summary")
                    working_count = sum(1 for _, working, _ in sensor_results if working)
                    print(f"Found {working_count} working BH1750 sensors out of 6 channels using {mux_type} multiplexer")
                    
                    print("\nChannel Status:")
                    for channel, working, lux in sensor_results:
                        status = "✓ WORKING" if working else "✗ NOT FOUND"
                        lux_str = f"{lux:.2f} lux" if working else "N/A"
                        print(f"  Channel {channel}: {status} - Current reading: {lux_str}")
                    
                    if working_count < 6:
                        print("\nSuggestions for missing sensors:")
                        print("1. Check the wiring connections to the multiplexer")
                        print("2. Verify the sensor address is 0x23 (default for BH1750)")
                        print("3. Try moving a working sensor to the problematic channel to test")
                        print("4. Ensure all sensors have proper power (3.3V and GND)")
                else:
                    print("✗ Could not initialize multiplexer at address 0x70")
            else:
                print("✗ No multiplexer found at address 0x70")
                print("Check connections and verify the multiplexer is properly connected to the Qwiic HAT")
        else:
            print("No I2C devices found")
            print("Check that I2C is enabled on your Raspberry Pi and that the Qwiic HAT is properly connected")
    
    except Exception as e:
        print(f"Error during I2C testing: {e}")
    
    return sensor_results, tca, mux_type

def run_light_sensitivity_test():
    global sensor_results, tca, mux_type

    if not sensor_results or not tca:
        print("You need to run the multiplexer and sensor detection first!")
        return

    print_header("Light Sensitivity Test")
    print("This test will monitor light levels using a rolling average.")
    print("Wave your hand or block the sensor to test. Press Ctrl+C to exit.\n")

    import adafruit_bh1750
    from collections import deque
    import time

    # Config values
    SAMPLE_SIZE = 5
    MIN_ABSOLUTE_CHANGE = 1.0     # in lux
    MIN_PERCENT_CHANGE = 15       # in %
    NOISE_THRESHOLD = 1.0         # below this, apply stricter filtering
    DEBOUNCE_TIME = 1.0           # seconds between reports per channel

    # Filter working sensors
    working_channels = [(channel, tca[channel]) for channel, working, _ in sensor_results if working]
    if not working_channels:
        print("No working sensors found for the light test")
        return

    sensors = []
    for channel, bus in working_channels:
        try:
            sensor = adafruit_bh1750.BH1750(bus)
            sensors.append((channel, sensor))
            print(f"Channel {channel} ready for testing")
        except Exception as e:
            print(f"Couldn't initialize sensor on channel {channel}: {e}")

    # Prep tracking data
    rolling_buffers = {channel: deque(maxlen=SAMPLE_SIZE) for channel, _ in sensors}
    stable_averages = {channel: 0.0 for channel, _ in sensors}
    last_report_time = {channel: 0 for channel, _ in sensors}

    try:
        print("\nMonitoring light levels. Press Ctrl+C to stop...")
        while True:
            now = time.time()

            for channel, sensor in sensors:
                try:
                    lux = sensor.lux
                    buffer = rolling_buffers[channel]
                    buffer.append(lux)
                    if len(buffer) < SAMPLE_SIZE:
                        continue  # Not enough samples yet

                    avg_lux = sum(buffer) / SAMPLE_SIZE
                    baseline = stable_averages[channel]
                    abs_change = avg_lux - baseline

                    # % change only if baseline > 0
                    if baseline > 0:
                        pct_change = (abs_change / baseline) * 100
                        pct_display = f"{pct_change:+.1f}%"
                    else:
                        pct_change = float('inf') if avg_lux > 0 else 0
                        pct_display = "FROM 0" if avg_lux > 0 else "0%"

                    # Debounce: skip if not enough time passed
                    if now - last_report_time[channel] < DEBOUNCE_TIME:
                        continue

                    # Check thresholds
                    should_display = False
                    if avg_lux < NOISE_THRESHOLD and baseline < NOISE_THRESHOLD:
                        should_display = abs(abs_change) > MIN_ABSOLUTE_CHANGE * 2
                    else:
                        should_display = (abs(abs_change) > MIN_ABSOLUTE_CHANGE or
                                          abs(pct_change) > MIN_PERCENT_CHANGE)

                    if should_display:
                        timestamp = time.strftime("%I:%M:%S", time.localtime(now))
                        millisec = int((now - int(now)) * 1000)
                        suffix = "am" if time.localtime(now).tm_hour < 12 else "pm"
                        full_time = f"{timestamp}:{millisec:03d}{suffix}"
                        print(f"Channel {channel}: {avg_lux:.2f} lux (Change: {abs_change:+.2f}, {pct_display}, {full_time})")

                        stable_averages[channel] = avg_lux
                        last_report_time[channel] = now

                except Exception as e:
                    print(f"Error reading channel {channel}: {e}")

            time.sleep(0.2)

    except KeyboardInterrupt:
        print("\nLight monitoring stopped by user")

def run_full_automated_test():
    """Run all tests in automated sequence"""
    detect_connection_type()
    detect_i2c_buses()
    if check_libraries():
        global sensor_results, tca, mux_type
        sensor_results, tca, mux_type = detect_multiplexer_and_sensors()
        if sensor_results and any(working for _, working, _ in sensor_results):
            run_light_sensitivity_test()
    print_header("Test Completed")

# Main code execution
if __name__ == "__main__":
    args = parse_arguments()
    
    if args.manual:
        print("Starting in manual/interactive mode...")
        run_manual_menu()
    else:
        print("Starting in automated mode...")
        run_full_automated_test()
