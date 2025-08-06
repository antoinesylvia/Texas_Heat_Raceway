#!/usr/bin/env python3
"""
Raspberry Pi Build HAT Swing Gate Controller
Controls a LEGO motor to operate a swing gate from 0 to 90 degrees
with automatic port detection and disconnect handling
"""


import asyncio
import atexit
from buildhat import Motor, Hat, Matrix, ColorSensor, ColorDistanceSensor, DistanceSensor, ForceSensor
from buildhat.exc import DeviceError
import ntplib
import os
import pygame
import random
import remote  # Add this import for the LEGO remote control
import sys
import threading
import time
from time import ctime
import yaml
import socketio
import logging
import argparse  # Add this line with your other imports

GATE_ID = 'StartGate_Default' 

current_race_number = None
formatted_race = None
logger = logging.getLogger(__name__) 
# Global motor reference for remote control
global_motor = None

# Parse command line arguments
parser = argparse.ArgumentParser(description='Raspberry Pi BuildHAT Swing Gate Controller')
parser.add_argument('--demo-mode', action='store_true', help='Run demo mode testing race stages')  # ← ADD THIS
args = parser.parse_args()

# Runtime variables (not from config)
DEMO_RUNNING = False

# Configuration variables (will be loaded from config file)
BUTTON_DEBOUNCE_TIME = None
TARGET_OPEN_TRAVEL = None
GATE_TRANSITION = None
OPEN_SPEED = None
CLOSE_SPEED = None
OPEN_RAMP_TIME = None
CLOSE_RAMP_TIME = None
GATE_OPEN_WAIT_TIME = None
HOLD_POWER = None
CLOSED_HOLD_POWER = None
DEFAULT_SPEED = None
DEMO_CYCLES = None

selectcar_audio_played = []  # Tracks all played selectcar files in the current cycle
ready_audio_played = []  # Tracks all played ready files in the current cycle
crowd_audio_played = []  # Tracks all played crowd files in the current cycle
welcome_audio_played = []  # Tracks all played welcome files in the current cycle


matrix_display = None # Global variable to store the Matrix object when available
equalizer_running = False  # Flag to control the equalizer animation


# Initialize pygame mixer for sound playback
try:
    pygame.mixer.init()
    print("Sound system initialized")
except Exception as e:
    print(f"Warning: Could not initialize sound system: {e}")


race_state_from_server = {
    'status': 'Unknown',
    'race_number': None,
    'formatted_race': None,
    'car_names': [],
    'countdown_duration': 5,
    'start_time': None
}

sio = socketio.Client(logger=True, engineio_logger=True)

CENTRAL_SERVER_URL = "http://192.168.1.132:5000" 

def sync_time_with_ntp():
    """
    Synchronize system time with NTP server to ensure accurate timestamps.
    This doesn't actually change system time, but reports offset for logging purposes.
    """
    try:
        
        
        print("Synchronizing with NTP time server...")
        
        # Create NTP client
        client = ntplib.NTPClient()
        
        # Query several NTP servers for redundancy
        ntp_servers = [
            'pool.ntp.org',
            'time.google.com',
            'time.windows.com',
            'time.apple.com'
        ]
        
        for server in ntp_servers:
            try:
                # Request time from server with short timeout
                response = client.request(server, timeout=1)
                
                # Get the offset between system time and NTP time
                offset = response.offset
                
                # Log the time synchronization results
                print(f"✓ Time synchronized with {server}")
                print(f"  System time: {ctime()}")
                print(f"  NTP time:    {ctime(response.tx_time)}")
                print(f"  Offset:      {offset*1000:.2f} ms")
                
                if abs(offset) > 0.5:  # If more than 500ms off
                    print(f"⚠️ WARNING: System clock is off by {offset:.2f} seconds")
                    print("  Timestamps may not be fully accurate")
                    print("  Consider running 'sudo ntpdate pool.ntp.org' to sync system clock")
                else:
                    print(f"✓ System clock accuracy is within {abs(offset)*1000:.1f}ms")
                
                return True
                
            except Exception as e:
                print(f"Failed to sync with {server}: {e}")
                continue
        
        print("⚠️ WARNING: Could not synchronize with any NTP server")
        return False
        
    except ImportError:
        print("⚠️ ntplib module not installed. Run 'pip install ntplib' for accurate time sync")
        print("  Continuing with system time only")
        return False
    except Exception as e:
        print(f"⚠️ Error during time synchronization: {e}")
        print("  Continuing with system time only")
        return False


def format_time_with_ms():
    """Get current time with milliseconds precision."""
    current = time.time()
    # Get milliseconds part
    milliseconds = int((current % 1) * 1000)
    # Format time with standard strftime plus milliseconds
    return f"{time.strftime('%H:%M:%S', time.localtime(current))}.{milliseconds:03d}"


# Configuration

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config_start.yaml")

def load_config():
    """Load configuration from YAML file"""
    try:
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Config file not found at {CONFIG_PATH}, using defaults")
        return {}
    except Exception as e:
        print(f"Error loading config: {e}, using defaults")
        return {}

def refresh_config():
    """Refresh global variables from config file"""
    global GATE_OPEN_ANGLE, GATE_CLOSED_ANGLE, TARGET_OPEN_TRAVEL
    
    cfg = load_config()
    
    
    # Update globals with config values (with defaults if key missing)
    globals().update({
        "BUTTON_DEBOUNCE_TIME": cfg.get("button_debounce_time", 30.0),  # Default from config
        "TARGET_OPEN_TRAVEL": cfg.get("target_open_travel", -165),      # Default from config
        "GATE_TRANSITION": cfg.get("gate_transition", 0.27),            # Default from config
        "OPEN_SPEED": cfg.get("open_speed", 100),                       # Default from config
        "CLOSE_SPEED": cfg.get("close_speed", 10),                      # Default from config
        "OPEN_RAMP_TIME": cfg.get("open_ramp_time", 1.0),              # Default from config
        "CLOSE_RAMP_TIME": cfg.get("close_ramp_time", 15.0),           # Default from config
        "GATE_OPEN_WAIT_TIME": cfg.get("gate_open_wait_time", 5.0),    # Default from config
        "HOLD_POWER": cfg.get("hold_power", 100),                       # Default from config
        "CLOSED_HOLD_POWER": cfg.get("closed_hold_power", 100),         # Default from config
        "DEFAULT_SPEED": cfg.get("default_speed", 40),                  # Default from config
        "DEMO_CYCLES": cfg.get("demo_cycles", 1),                       # Default from config
    })
    
    # IMPORTANT: Recalculate gate open angle based on the new target_open_travel
    # Only do this if GATE_CLOSED_ANGLE is already defined
    if 'GATE_CLOSED_ANGLE' in globals() and GATE_CLOSED_ANGLE is not None:
        # Calculate the new open angle based on the current closed angle and the new target travel
        GATE_OPEN_ANGLE = GATE_CLOSED_ANGLE + TARGET_OPEN_TRAVEL
        print(f"Recalculated GATE_OPEN_ANGLE to {GATE_OPEN_ANGLE} (GATE_CLOSED_ANGLE {GATE_CLOSED_ANGLE} + TARGET_OPEN_TRAVEL {TARGET_OPEN_TRAVEL})")
    
    print("Configuration reloaded from file")

# Load config once at startup
refresh_config()

# Runtime variables (not from config)

LAST_BUTTON_PRESS = time.time()
position_monitor_active = False

# Dynamic gate position variables (calculated at runtime)
GATE_CLOSED_ANGLE = None
GATE_OPEN_ANGLE = None

#track the last played prelaunch audio
last_ready_audio = None

def clear_screen():
   """Clear the terminal screen."""
   os.system('clear')


def check_buildhat_connection():
   """Check if the BuildHAT is connected and get its status."""
   try:
       # Initialize the Hat class
       hat = Hat()
      
       # Get the input voltage
       voltage = hat.get_vin()
       print(f"BuildHAT detected! Input voltage: {voltage:.2f}V")
      
       # Check if voltage is in a good range (7.5V-9V is ideal)
       if voltage < 7.0:
           print(f"â ï¸ WARNING: Low input voltage ({voltage:.2f}V). Recommended: 7.5V-9V")
       elif voltage > 9.5:
           print(f"â ï¸ WARNING: High input voltage ({voltage:.2f}V). Recommended: 7.5V-9V")
      
       # Set LEDs based on voltage
       hat.set_leds(color='voltage')
      
       # Get connected devices overview
       devices = hat.get()
       if devices:
           print("Currently connected devices:")
           for port, device in devices.items():
               if device:  # If not None, device is connected
                   print(f"  Port {port}: {device}")
      
       return True
   except Exception as e:
       print(f"Error detecting BuildHAT: {e}")
       print("Make sure the BuildHAT is properly connected to your Raspberry Pi.")
       return False


def detect_special_devices():
   """Check for special devices like Matrix, ColorSensor before motor detection."""
   ports = ['A', 'B', 'C', 'D']
   special_devices = {}
  
   print("")
   print("Checking for special devices...")
  
   for port in ports:
       print(f"\nPort {port}:")
       try:
           # Try to detect a Matrix
           try:
               print("  Checking for Matrix...", end=" ", flush=True)
               matrix = Matrix(port)
               time.sleep(0.3)
               description = matrix.description
               print(f"Found! LED Matrix ({description})")
               special_devices[port] = ("Matrix", description)  # Store description, not object
               # Release the device properly
               matrix.clear()  # Clear display
               del matrix  # Release object
               continue  # If Matrix found, continue to next port
           except Exception as e:  # noqa: F841
               print("Not found")
          
           # Try to detect a ColorSensor
           try:
               print("  Checking for ColorSensor...", end=" ", flush=True)
               color_sensor = ColorSensor(port)
               time.sleep(0.3)
               description = color_sensor.description
               print(f"Found! Color Sensor ({description})")
               special_devices[port] = ("ColorSensor", description)  # Store description, not object
               # Properly release the device
               del color_sensor
               continue  # If ColorSensor found, continue to next port
           except Exception as e:  # noqa: F841
               print("Not found")
              
           # Try to detect a ColorDistanceSensor
           try:
               print("  Checking for ColorDistanceSensor...", end=" ", flush=True)
               color_distance = ColorDistanceSensor(port)
               time.sleep(0.3)
               description = color_distance.description
               print(f"Found! Color Distance Sensor ({description})")
               special_devices[port] = ("ColorDistanceSensor", description)  # Store description, not object
               # Properly release the device
               del color_distance
               continue  # If ColorDistanceSensor found, continue to next port
           except Exception as e:  # noqa: F841
               print("Not found")
          
           # Try to detect a DistanceSensor
           try:
               print("  Checking for DistanceSensor...", end=" ", flush=True)
               distance = DistanceSensor(port)
               time.sleep(0.3)
               description = distance.description
               print(f"Found! Distance Sensor ({description})")
               special_devices[port] = ("DistanceSensor", description)  # Store description, not object
               # Properly release the device
               del distance
               continue  # If DistanceSensor found, continue to next port
           except Exception as e:  # noqa: F841
               print("Not found")
          
           # Try to detect a ForceSensor
           try:
               print("  Checking for ForceSensor...", end=" ", flush=True)
               force = ForceSensor(port)
               time.sleep(0.3)
               description = force.description
               print(f"Found! Force Sensor ({description})")
               special_devices[port] = ("ForceSensor", description)  # Store description, not object
               # Properly release the device
               del force
               continue  # If ForceSensor found, continue to next port
           except Exception as e:  # noqa: F841
               print("Not found")
              
           print("  No special device detected on this port")
          
       except Exception as e:
           print(f"  Error checking port {port}: {e}")
  
   # No need to clean up devices here since we're immediately releasing them after detection
  
   print("\n")  # Add extra blank line before motor scanning
   return special_devices

def detect_motors():
   """Detect motors connected to ports A through D."""
   ports = ['A', 'B', 'C', 'D']
   connected_ports = []
  
   print("Scanning for connected motors...")
  
   for port in ports:
       try:
           # Attempt to connect to a motor on each port
           print(f"Checking port {port}...", end="", flush=True)
           motor = Motor(port)
          
           # Wait a moment for the motor to initialize
           time.sleep(0.5)
          
           # Get basic info to confirm it's connected
           type_id = motor.typeid
           description = motor.description
          
           print(f" Found: {description} (ID: {type_id})")
           connected_ports.append((port, description, type_id))
          
           # Release the motor to avoid conflicts
           try:
               motor.stop()  # First try to stop it safely
           except Exception:
               pass  # Ignore errors during cleanup
          
           # Explicitly delete the motor object
           del motor
          
       except Exception as e:  # noqa: F841
           print(" No motor detected")
  
   return connected_ports


def select_port(connected_ports):
   """Allow user to select a port from the available ones."""
   if not connected_ports:
       print("\nNo motors detected on any port!")
       print("Options:")
       print("1. Retry detection")
       print("2. Manually select a port")
       print("3. Exit")
      
       choice = input("Choice: ").strip()
       if choice == '1':
           return select_port(detect_motors())
       elif choice == '2':
           pass  # Continue to manual selection below
       else:
           sys.exit(0)
   elif len(connected_ports) == 1:
       # Automatically select the only detected motor
       port, desc, type_id = connected_ports[0]
       print("\nAutomatically selected the only detected motor:")
       print(f"Port {port}: {desc} (ID: {type_id})")
       return port
   else:
       print("\nDetected motors:")
       for i, (port, desc, type_id) in enumerate(connected_ports, 1):
           print(f"{i}. Port {port}: {desc} (ID: {type_id})")
       print(f"{len(connected_ports) + 1}. Manually select a different port")
       print(f"{len(connected_ports) + 2}. Exit")
      
       choice = input("Select motor: ").strip()
       try:
           choice_num = int(choice)
           if 1 <= choice_num <= len(connected_ports):
               return connected_ports[choice_num - 1][0]
           elif choice_num == len(connected_ports) + 1:
               pass  # Continue to manual selection
           else:
               sys.exit(0)
       except ValueError:
           pass  # Continue to manual selection if input wasn't a number
  
   # Manual port selection
   print("\nManual port selection:")
   print("A. Port A")
   print("B. Port B")
   print("C. Port C")
   print("D. Port D")
   print("Q. Exit")
  
   while True:
       choice = input("Select port: ").strip().upper()
       if choice in ['A', 'B', 'C', 'D']:
           return choice
       elif choice == 'Q':
           sys.exit(0)
       else:
           print("Invalid selection. Please choose A, B, C, D, or Q.")


def connect_motor(port):
   """Connect to the motor and handle potential errors."""
   try:
       print(f"Connecting to LEGO motor on port {port}...")
       motor = Motor(port)
       print(f"Motor connected. Type ID: {motor.typeid}")
       print(f"Description: {motor.description}")
      
       # Get current position - this will also verify motor is responsive
       try:
           position = motor.get_position()
           print(f"Current position: {position}")
       except Exception as e:
           print(f"Warning: Could not read position ({e}), but continuing...")
          
       return motor
   except Exception as e:
       print(f"Error connecting to motor: {e}")
       print("Make sure the BuildHAT is properly connected and the motor is plugged into the correct port.")
       return None


def is_motor_connected(motor):
   """Check if the motor is still connected."""
   try:
       if motor is None:
           return False
          
       # Try to read the position as a connection test
       position = motor.get_position()  # noqa: F841
       return True
   except DeviceError:
       return False
   except Exception:
       return False


def safe_stop_motor(motor):
   """Safely stop a motor, handling disconnection errors."""
   if motor is None:
       return
      
   try:
       motor.stop()
   except DeviceError:
       print("Motor disconnected - cannot stop.")
   except Exception as e:
       print(f"Error stopping motor: {e}")


def position_monitor_thread(motor):
   """Thread function to continuously display motor position."""
   global position_monitor_active
  
   print("\nPosition monitor started.")
  
   try:
       last_position = None  # Track the last position we printed
       last_print_time = 0   # Track the last time we printed
      
       while position_monitor_active:
           current_time = time.time()
          
           if is_motor_connected(motor):
               try:
                   position = motor.get_position()
                  
                   # Only print when position changes (and print at least every 5 seconds)
                   if position != last_position or (current_time - last_print_time) > 5:
                       # Only print if this is a new position
                       if position != last_position:
                           print(f"\n[POSITION] Current position: {position} degrees", flush=True)
                           last_position = position
                           last_print_time = current_time
                      
               except Exception:
                   if last_position != "error" or (current_time - last_print_time) > 5:
                       print("\n[POSITION] Error reading position", flush=True)
                       last_position = "error"
                       last_print_time = current_time
           else:
               if last_position != "disconnected" or (current_time - last_print_time) > 5:
                   print("\n[POSITION] Motor disconnected", flush=True)
                   last_position = "disconnected"
                   last_print_time = current_time
                  
           time.sleep(1)
   except Exception as e:
       print(f"\n[POSITION] Monitor error: {e}", flush=True)


def start_position_monitor(motor):
   """Start the position monitoring thread."""
   global position_monitor_active
  
   if not is_motor_connected(motor):
       print("Cannot start position monitor - motor disconnected.")
       return False
  
   position_monitor_active = True
   monitor_thread = threading.Thread(target=position_monitor_thread, args=(motor,))
   monitor_thread.daemon = True  # Set as daemon so it exits when main program exits
   monitor_thread.start()
   return True


def stop_position_monitor():
   """Stop the position monitoring thread."""
   global position_monitor_active
   position_monitor_active = False
   time.sleep(1.1)  # Wait slightly longer than monitor update interval
   print("\nPosition monitor stopped.")


def initialize_motor(motor):
   """Initialize the motor by setting it to the closed position."""
   global GATE_CLOSED_ANGLE, GATE_OPEN_ANGLE
  
   if motor is None:
       print("No motor connected.")
       return False
      
   try:
       print("Initializing motor...")
       safe_stop_motor(motor)
       time.sleep(0.5)
      
       # Check if motor is still connected
       if not is_motor_connected(motor):
           print("Motor was disconnected during initialization.")
           return False
          
       # Set motor parameters
       motor.set_default_speed(DEFAULT_SPEED)
       print(f"Motor speed set to {DEFAULT_SPEED}%")
      
       # Run at a slow speed until resistance is felt to find home position
       print("Finding home position...")
       motor.run_for_seconds(2, -10)
      
       # Check if motor is still connected
       if not is_motor_connected(motor):
           print("Motor was disconnected during initialization.")
           return False
          
       safe_stop_motor(motor)
      
       # Reset position to 0
       print("Moving to closed position (0 degrees)...")
       motor.run_to_position(0, DEFAULT_SPEED, blocking=True)
       time.sleep(0.5)  # Give time to settle
      
       # Check how close we are to 0
       current_pos = motor.get_position()
       print(f"Initial position after setup: {current_pos} degrees")
      
       # Fine-tune to exactly 0 degrees if needed
       # Using a wider tolerance of Â±3 degrees as requested
       calibrated_home_position = current_pos  # Start with current position as default
      
       if abs(current_pos - 0) > 3:  # If we're more than 3 degrees off
           print("Fine-tuning home position to within ±3 degrees of zero...")
          
           # Use a gentle approach with lower speed for precision
           calibration_speed = 30  # Low speed for precise positioning
          
           # Try with gentle approach
           motor.run_to_position(0, calibration_speed, blocking=True)
           time.sleep(0.5)  # Give time to settle
          
           # Check final position
           final_pos = motor.get_position()
           calibrated_home_position = final_pos  # Update to calibrated position
          
           # If still off by more than Â±3 degrees, try one more time with higher power
           if abs(final_pos - 0) > 3:
               print(f"More precise calibration needed (currently at {final_pos})...")
               motor.run_to_position(0, 50, blocking=True)
               time.sleep(0.5)
               final_pos = motor.get_position()
               calibrated_home_position = final_pos  # Update to final calibrated position
          
           if abs(final_pos) <= 3:
               print(f"Successfully calibrated to home position: {final_pos} degrees (within Â±3Â° tolerance)")
           else:
               print(f"Note: Could not reach exact zero position. Current: {final_pos} degrees")
       else:
           print(f"Motor already at acceptable home position: {current_pos} degrees (within Â±3Â° tolerance)")
      
       # ===== NEW CODE: Set dynamic gate angles based on calibrated home position =====
       # Update the global gate angle settings based on the calibrated home position
       GATE_CLOSED_ANGLE = calibrated_home_position
      
       # Calculate open angle relative to the calibrated home position
       # If the original GATE_OPEN_ANGLE was -140, make it relative to the calibrated home
       target_open_travel = TARGET_OPEN_TRAVEL  # The desired angular travel from closed to open
       GATE_OPEN_ANGLE = GATE_CLOSED_ANGLE + target_open_travel
      
       print("Dynamic gate angles set based on calibration:")
       print(f"  - Closed position: {GATE_CLOSED_ANGLE} degrees")
       print(f"  - Open position: {GATE_OPEN_ANGLE} degrees")
       # ===== END NEW CODE =====
      
       # Apply holding power to maintain closed position
       if CLOSED_HOLD_POWER > 0:
           print(f"Applying closed holding power ({CLOSED_HOLD_POWER}%) to prevent movement...")
           # Direction may need adjustment based on your setup
           hold_direction = 1  # Try -1 if this doesn't work
           motor.start(CLOSED_HOLD_POWER * hold_direction)
           time.sleep(0.2)  # Brief pause to ensure power is applied
           print("1")
          
           print("Gate secured in closed position.")
      
       print("Motor initialized to closed position (within Â±3Â° of 0 degrees)")
       return True
   except DeviceError:
       print("Motor disconnected during initialization.")
       return False
   except Exception as e:
       print(f"Error initializing motor: {e}")
       return False


def ramp_speed(motor, target_speed, ramp_time=1.0):
   """Gradually ramp up motor speed to avoid current spikes."""
   if not is_motor_connected(motor):
       print("Motor disconnected - cannot ramp speed.")
       return False
      
   try:
       current_speed = 0
       steps = 10
       step_time = ramp_time / steps
       step_speed = target_speed / steps
      
       for i in range(steps):
           current_speed += step_speed
           motor.start(current_speed)
           time.sleep(step_time)
          
           # Check connection after each step
           if not is_motor_connected(motor):
               print("Motor disconnected during speed ramping.")
               return False
              
       return True
   except Exception as e:
       print(f"Error during speed ramping: {e}")
       return False


def open_gate(motor):
    """Open the gate to GATE_OPEN_ANGLE degrees."""
    global HOLD_POWER
    
    if not is_motor_connected(motor):
        print("Motor disconnected - cannot open gate.")
        return False
    
    try:
        print(f"Opening gate to {GATE_OPEN_ANGLE} degrees...")
        
        # Completely stop any holding power that might be applied
        print("Releasing holding power before opening...")
        motor.stop()
        time.sleep(GATE_TRANSITION)  # Use configured transition time
        
        # BOOST POWER SETTINGS FOR OPENING
        motor.plimit(1.0)            # Set power limit to 100%
        motor.pwmparams(0.05, 0.01)  # Aggressive power thresholds for maximum torque
        
        # Set motor speed and open to target angle
        motor.set_default_speed(OPEN_SPEED)
        motor.run_to_position(GATE_OPEN_ANGLE, OPEN_SPEED, blocking=True)
        
        # Get current time for timestamp
        current_time = time.strftime("%H:%M:%S", time.localtime())
        
        # Verify position reached
        if is_motor_connected(motor):
            current_pos = motor.get_position()
            if abs(current_pos - GATE_OPEN_ANGLE) > -125:
                print(f"Warning: Gate stopped at {current_pos}, target was {GATE_OPEN_ANGLE}")
        
        # IMPORTANT: Apply holding power to keep gate open
        if HOLD_POWER > 0:
            print(f"Applying holding power ({HOLD_POWER}%) to maintain position...")
            # For negative angles (like -90), use negative holding power
            hold_direction = -1 if GATE_OPEN_ANGLE < 0 else 1
            motor.start(HOLD_POWER * hold_direction)
            
        # Reset power settings to defaults AFTER applying holding power
        motor.plimit(0.9)            # Reset to default power limit (90%)
        motor.pwmparams(0.15, 0.1)   # Reset to default PWM thresholds
        
        # Print gate opened message with timestamp
        print(f"Gate opened at {current_time}!")
        return True
    except DeviceError:
        print("Motor disconnected while opening gate.")
        return False
    except Exception as e:
        print(f"Error opening gate: {e}")
        return False



def close_gate(motor):
    """Close the gate to GATE_CLOSED_ANGLE degrees with verification."""
    global CLOSED_HOLD_POWER
  
    if not is_motor_connected(motor):
        print("Motor disconnected - cannot close gate.")
        return False
      
    try:
        print(f"Closing gate to {GATE_CLOSED_ANGLE} degrees...")
      
        # Important: Force direct method that worked previously
        motor.set_default_speed(CLOSE_SPEED)
      
        # Direct approach without ramping logic
        motor.run_to_position(GATE_CLOSED_ANGLE, CLOSE_SPEED, blocking=True)
      
        # Get the actual position after movement
        time.sleep(0.4)  # Brief pause to let motor settle
        current_pos = motor.get_position()
      
        # Get current time for timestamp
        current_time = time.strftime("%H:%M:%S", time.localtime())
      
        # Verify we reached the closed position
        if abs(current_pos - GATE_CLOSED_ANGLE) > 3:  # If we're more than 3 degrees off
            print(f"Gate didn't fully close (at {current_pos}). Retrying...")
          
            # Try again with more power
            motor.run_to_position(GATE_CLOSED_ANGLE, CLOSE_SPEED + 20, blocking=True)
            time.sleep(0.2)
          
            # Check position again and update timestamp
            current_pos = motor.get_position()
            current_time = time.strftime("%H:%M:%S", time.localtime())  # Update timestamp after retry
          
            if abs(current_pos - GATE_CLOSED_ANGLE) > 3:
                print(f"Warning: Gate closed to {current_pos}, target was {GATE_CLOSED_ANGLE}")
            else:
                print(f"Gate fully closed to {current_pos} degrees")
        else:
            print(f"Gate fully closed to {current_pos} degrees")
      
        # Check if still connected
        if not is_motor_connected(motor):
            print("Motor disconnected while closing gate.")
            return False
      
        # Apply holding power to keep gate closed against pressure from cars
        if CLOSED_HOLD_POWER > 0:
            # Direction depends on your setup - adjust sign as needed
            # Positive value provides clockwise resistance
            # Negative value provides counter-clockwise resistance
            hold_direction = 1  # Default direction (may need to be -1 depending on setup)  # noqa: F841
          
            print(f"Applying closed holding power ({CLOSED_HOLD_POWER}%) to maintain position...")
            #motor.start(CLOSED_HOLD_POWER * hold_direction)  # Apply continuous power
            #print("2")
      
        # Print gate closed message with timestamp
        print(f"Gate closed at {current_time}!")
        return True
    except DeviceError:
        print("Motor disconnected while closing gate.")
        return False
    except Exception as e:
        print(f"Error closing gate: {e}")
        return False




def test_matrix(matrix_port):
   """Test and demonstrate LED Matrix capabilities."""
   try:
       print("\n--- Testing LED Matrix on port " + matrix_port + " ---")
      
       # Initialize Matrix
       matrix = Matrix(matrix_port)
      
       # First clear the matrix and pause briefly
       print("Clearing matrix...")
       matrix.clear()
       time.sleep(0.5)
      
       # Display a welcome message
       print("Displaying welcome pattern...")
      
       
      
       # Demo color range with transition effects
       print("Demonstrating color transition effects...")
      
       # Set transition mode to fade
       print("Setting transition mode to fade...")
       matrix.set_transition(2)  # Mode 2: Fade
      
       # Display different colors one after another
       colors = ["red", "orange", "yellow", "green", 
                "cyan", "blue", "pink", "white"]
      
       print("Cycling through colors...")
       for color in colors:
           print(f"Setting all pixels to {color}...")
           matrix.clear((color, 10))
           time.sleep(1)
      
       # Reset transition mode
       matrix.set_transition(0)
      
       # Finish with a custom pattern
       print("Final custom pattern...")
       matrix.clear()
       custom_pattern = [
           [(0, 0), ("red", 8)],
           [(0, 1), ("orange", 8)],
           [(0, 2), ("yellow", 8)],
           [(1, 0), ("green", 8)],
           [(1, 1), ("blue", 8)],
           [(1, 2), ("lilac", 8)],
           [(2, 0), ("pink", 8)],
           [(2, 1), ("cyan", 8)],
           [(2, 2), ("white", 8)]
       ]
       for coord, pixel in custom_pattern:
           matrix.set_pixel(coord, pixel)
          
       time.sleep(2)
      
       # Clear the matrix before finishing
       print("Test complete. Clearing matrix...")
       matrix.clear()
      
       return True
      
   except Exception as e:
       print(f"Error testing Matrix: {e}")
       return False





def initialize_matrix(port):
   """Initialize the Matrix LED display on the specified port."""
   global matrix_display
  
   try:
       matrix_display = Matrix(port)
       matrix_display.clear()
       print(f"Matrix display initialized on port {port}")
       return True
   except Exception as e:
       print(f"Could not initialize Matrix display: {e}")
       matrix_display = None
       return False



def display_equalizer_on_matrix(duration=None):
    """
    Display an audio equalizer animation on the matrix.
    If duration is specified, it will auto-stop after that many seconds.
    Otherwise, it runs until stop_equalizer() is called.
    """
    global matrix_display, equalizer_running
    
    if not matrix_display:
        print("Matrix display not available")
        return
    
    # Set the flag that indicates the equalizer is running
    equalizer_running = True
    
    if duration:
        print(f"Displaying equalizer animation for {duration} seconds...")
    else:
        print("Starting equalizer animation (will run until stopped)...")
    
    start_time = time.time()
    
    # Define our colors for the different levels (lowest to highest)
    colors = ["green", "yellow", "orange", "red"]
    
    try:
        # Run animation until stopped or duration expires
        while equalizer_running:
            # Check if duration has expired (if specified)
            if duration and (time.time() - start_time > duration):
                break
                
            # Clear the matrix first
            matrix_display.clear()
            
            # Generate a random pattern for the three columns
            for column in range(3):
                # Randomly determine the height of this column (0-3)
                height = random.randint(0, 3)
                
                # Draw the column from bottom to top
                for row in range(height):
                    # Bottom row is 2, middle is 1, top is 0
                    y = 2 - row
                    
                    # Pick a color based on height
                    color = colors[min(row, len(colors)-1)]
                    
                    # Higher rows get higher brightness
                    brightness = 5 + row * 2
                    
                    # Set the pixel
                    matrix_display.set_pixel((column, y), (color, brightness))
            
            # Wait a short time before next frame
            time.sleep(0.15)
        
        # Clear the matrix when done
        matrix_display.clear()
        print("Equalizer animation stopped")
        
    except Exception as e:
        print(f"Error during equalizer animation: {e}")
        matrix_display.clear()  # Make sure to clear on error
    finally:
        # Always reset the flag when done
        equalizer_running = False

def stop_equalizer():
    """Stop the equalizer animation."""
    global equalizer_running
    equalizer_running = False
    print("Stopping equalizer animation...")

#sound
def play_random_ready_audio():
    """Play a random audio file from the ready folder, cycling through all files before repeating."""
    global last_ready_audio, ready_audio_played, equalizer_running
    
    ready_folder = "Audio/Ready"
    
    if not os.path.exists(ready_folder):
        print(f"ready folder not found: {ready_folder}")
        return
    
    # Get all mp3 files in the ready folder
    ready_files = [f for f in os.listdir(ready_folder) 
                     if f.endswith(('.mp3', '.wav'))]
    
    if not ready_files:
        print("No mp3 or wav files found in ready folder")
        return
    
    # If we've played all files, reset the tracking list
    if len(ready_audio_played) >= len(ready_files):
        print("All audio files have been played, resetting cycle")
        ready_audio_played = []
    
    # Remove all previously played files from the selection pool
    available_files = [f for f in ready_files if f not in ready_audio_played]
    
    # Randomly select a file
    selected_file = random.choice(available_files)
    
    # Update tracking
    last_ready_audio = selected_file
    ready_audio_played.append(selected_file)
    
    # Set the equalizer running flag before playing audio
    equalizer_running = True
    
    # Play the selected file
    audio_path = os.path.join(ready_folder, selected_file)
    try:
        sound = pygame.mixer.Sound(audio_path)
        sound.play()
        
        # Keep the original message about which file is playing
        print(f"Playing ready audio: {selected_file} ({len(ready_audio_played)}/{len(ready_files)} in cycle)")
        
        # Run the equalizer animation directly (non-threaded) while audio plays
        start_time = time.time()  # noqa: F841
        
        # Define our colors for the different levels (lowest to highest)
        colors = ["green", "yellow", "orange", "red"]
        
        # Run animation until audio finishes
        while pygame.mixer.get_busy() and equalizer_running:
            # Generate a random pattern for the three columns
            if matrix_display:
                # Clear the matrix first
                matrix_display.clear()
                
                # Generate a random pattern for the three columns
                for column in range(3):
                    # Randomly determine the height of this column (0-3)
                    height = random.randint(0, 3)
                    
                    # Draw the column from bottom to top
                    for row in range(height):
                        # Bottom row is 2, middle is 1, top is 0
                        y = 2 - row
                        
                        # Pick a color based on height
                        color = colors[min(row, len(colors)-1)]
                        
                        # Higher rows get higher brightness
                        brightness = 5 + row * 2
                        
                        # Set the pixel
                        matrix_display.set_pixel((column, y), (color, brightness))
                
                # Wait a short time before next frame
                time.sleep(0.15)
            else:
                # No matrix display, just wait for audio to complete
                time.sleep(0.1)
        
        # Clear the matrix when audio finishes
        if matrix_display:
            matrix_display.clear()
            
    except Exception as e:
        print(f"Error playing ready audio: {e}")
    finally:
        # Make sure equalizer is stopped and matrix is cleared
        equalizer_running = False
        if matrix_display:
            try:
                matrix_display.clear()
            except:  # noqa: E722
                pass
        print("Audio playback complete")

def play_prelaunch_sound(seconds):
    """Play the appropriate prelaunch sound."""
    audio_files = {
        0: "Audio/Prelaunch/launch_decision.wav"
    }
    
    if seconds in audio_files and os.path.exists(audio_files[seconds]):
        try:
            pygame.mixer.Sound(audio_files[seconds]).play()
        except Exception as e:
            print(f"Error playing prelaunch sound: {e}")



def play_countdown_sound(seconds):
    """Play the appropriate countdown sound."""
    audio_files = {
        3: "Audio/Countdown/z3.mp3",
        2: "Audio/Countdown/z2.mp3",
        1: "Audio/Countdown/z1.mp3",
        0: "Audio/Countdown/zGO.mp3"
    }
    
    if seconds in audio_files and os.path.exists(audio_files[seconds]):
        try:
            pygame.mixer.Sound(audio_files[seconds]).play()
        except Exception as e:
            print(f"Error playing countdown sound: {e}")


def play_selectcar_sound():
    """Play a random audio file from the selectcar folder, cycling through all files before repeating."""
    global selectcar_audio_played
    
    selectcar_folder = "Audio/SelectCar"
    
    if not os.path.exists(selectcar_folder):
        print(f"selectcar folder not found: {selectcar_folder}")
        return
    
    # Get all mp3 and wav files in the selectcar folder
    selectcar_files = [f for f in os.listdir(selectcar_folder) 
                   if f.endswith(('.mp3', '.wav'))]
    
    if not selectcar_files:
        print("No mp3 or wav files found in selectcar folder")
        return
    
    # If we've played all files, reset the tracking list
    if len(selectcar_audio_played) >= len(selectcar_files):
        print("All selectcar audio files have been played, resetting cycle")
        selectcar_audio_played = []
    
    # Remove all previously played files from the selection pool
    available_files = [f for f in selectcar_files if f not in selectcar_audio_played]
    
    # Randomly select a file
    selected_file = random.choice(available_files)
    
    # Update tracking
    selectcar_audio_played.append(selected_file)
    
    # Play the selected file
    audio_path = os.path.join(selectcar_folder, selected_file)
    try:
        pygame.mixer.Sound(audio_path).play()
        print(f"Playing selectcar audio: {selected_file} ({len(selectcar_audio_played)}/{len(selectcar_files)} in cycle)")
    except Exception as e:
        print(f"Error playing selectcar sound: {e}")

def play_crowd_sound():
    """Play a random audio file from the crowd folder, cycling through all files before repeating."""
    global crowd_audio_played
    
    crowd_folder = "Audio/Crowd"
    
    if not os.path.exists(crowd_folder):
        print(f"Crowd folder not found: {crowd_folder}")
        return
    
    # Get all mp3 and wav files in the crowd folder
    crowd_files = [f for f in os.listdir(crowd_folder) 
                   if f.endswith(('.mp3', '.wav'))]
    
    if not crowd_files:
        print("No mp3 or wav files found in crowd folder")
        return
    
    # If we've played all files, reset the tracking list
    if len(crowd_audio_played) >= len(crowd_files):
        print("All crowd audio files have been played, resetting cycle")
        crowd_audio_played = []
    
    # Remove all previously played files from the selection pool
    available_files = [f for f in crowd_files if f not in crowd_audio_played]
    
    # Randomly select a file
    selected_file = random.choice(available_files)
    
    # Update tracking
    crowd_audio_played.append(selected_file)
    
    # Play the selected file
    audio_path = os.path.join(crowd_folder, selected_file)
    try:
        pygame.mixer.Sound(audio_path).play()
        print(f"Playing crowd audio: {selected_file} ({len(crowd_audio_played)}/{len(crowd_files)} in cycle)")
    except Exception as e:
        print(f"Error playing crowd sound: {e}")

def play_welcome():
    """Play a random audio file from the welcome folder, cycling through all files before repeating."""
    global welcome_audio_played
    
    welcome_folder = "Audio/Welcome"
    
    if not os.path.exists(welcome_folder):
        print(f"Welcome folder not found: {welcome_folder}")
        return
    
    # Get all mp3 and wav files in the welcome folder
    welcome_files = [f for f in os.listdir(welcome_folder) 
                     if f.endswith(('.mp3', '.wav'))]
    
    if not welcome_files:
        print("No mp3 or wav files found in welcome folder")
        return
    
    # If we've played all files, reset the tracking list
    if len(welcome_audio_played) >= len(welcome_files):
        print("All welcome audio files have been played, resetting cycle")
        welcome_audio_played = []
    
    # Remove all previously played files from the selection pool
    available_files = [f for f in welcome_files if f not in welcome_audio_played]
    
    # Randomly select a file
    selected_file = random.choice(available_files)
    
    # Update tracking
    welcome_audio_played.append(selected_file)
    
    # Play the selected file
    audio_path = os.path.join(welcome_folder, selected_file)
    try:
        pygame.mixer.Sound(audio_path).play()
        print(f"Playing welcome audio: {selected_file} ({len(welcome_audio_played)}/{len(welcome_files)} in cycle)")
    except Exception as e:
        print(f"Error playing welcome sound: {e}")

def display_countdown_on_matrix(seconds):
    """Display countdown visualization on the Matrix LED and play audio."""
    global matrix_display
    
    if not matrix_display:
        return  # No matrix available
    
    try:
        if seconds > 3:
            # Pulse yellow while waiting
            matrix_display.clear(("yellow", 3))
            time.sleep(0.2)
            matrix_display.clear(("yellow", 6))
            time.sleep(0.2)
            matrix_display.clear(("yellow", 3))
            # Play prelaunch audio
            play_prelaunch_sound(0)
            
        
        elif seconds == 3:
            # Just the bottom row red
            matrix_display.clear()
            for x in range(3):
                matrix_display.set_pixel((x, 0), ("red", 8))
            play_countdown_sound(3)
        
        elif seconds == 2:
            # Bottom and middle rows red
            matrix_display.clear()
            for x in range(3):
                matrix_display.set_pixel((x, 1), ("red", 8))
                matrix_display.set_pixel((x, 0), ("red", 8))
            play_countdown_sound(2)
        
        elif seconds == 1:
            # All rows red
            matrix_display.clear(("red", 8))
            play_countdown_sound(1)
        
        elif seconds == 0:
            # All green for GO!
            matrix_display.clear(("green", 10))
            play_countdown_sound(0)
    
    except Exception as e:  # noqa: F841
        # Silently handle errors - we don't want Matrix issues to stop the gate demo
        pass

def display_gate_status_on_matrix(is_open):
   """Display the gate status on the Matrix LED."""
   global matrix_display
  
   if not matrix_display:
       return  # No matrix available
  
   try:
       if is_open:
           # Gate open indicator (green checkmark)
           matrix_display.clear()
           open_pattern = [
               [(0, 0), ("green", 8)],
               [(1, 0), ("green", 8)],
               [(2, 0), ("green", 8)],
               [(0, 1), ("green", 8)],
               [(2, 1), ("green", 8)],
               [(0, 2), ("green", 8)],
               [(1, 2), ("green", 8)],
               [(2, 2), ("green", 8)]
           ]
           for coord, pixel in open_pattern:
               matrix_display.set_pixel(coord, pixel)
       else:
           # Gate closed indicator (red X)
           matrix_display.clear()
           
           
           closed_pattern = [
            # Top row: Red Red Red
            [(0, 0), ("red", 8)],
            [(1, 0), ("red", 8)],
            [(2, 0), ("red", 8)],
            
            # Left column: Red
            [(0, 1), ("red", 8)],
            
            # Bottom row: Red Red Red
            [(0, 2), ("red", 8)],
            [(1, 2), ("red", 8)],
            [(2, 2), ("red", 8)]
        ]
           for coord, pixel in closed_pattern:
               matrix_display.set_pixel(coord, pixel)
  
   except Exception as e:  # noqa: F841
       # Silently handle errors
       pass

def test_components():
    """
    Dynamically check if all discovered components are still connected.
    Returns a dictionary with the status of each component.
    """
    global global_motor, matrix_display
    
    # Initialize results dictionary
    components = {}
    
    # Check motor connection if we have one
    if global_motor is not None:
        try:
            # Try to get position as a connection test
            position = global_motor.get_position()
            components['motor'] = {
                'status': 'OK',
                'port': global_motor.port,
                'type': global_motor.description if hasattr(global_motor, 'description') else 'Unknown',
                'position': position
            }
        except Exception as e:
            components['motor'] = {
                'status': 'DISCONNECTED',
                'port': global_motor.port if hasattr(global_motor, 'port') else 'Unknown',
                'error': str(e)
            }
    else:
        components['motor'] = {'status': 'NOT_INITIALIZED'}
    
    # Check Matrix display if we have one
    if matrix_display is not None:
        try:
            # Test matrix by quickly setting and clearing a pixel
            original_state = None  # noqa: F841
            try:
                # Get the state of the first pixel (difficult with buildhat API)
                pass
            except:  # noqa: E722
                pass
                
            # Set a test pixel
            matrix_display.set_pixel((0, 0), ("blue", 1))
            time.sleep(0.05)
            # Clear it immediately
            matrix_display.clear()
            
            # If we got here without errors, the matrix is working
            components['led_matrix'] = {
                'status': 'OK',
                'port': getattr(matrix_display, 'port', 'Unknown'),
                'type': getattr(matrix_display, 'description', '3x3 Color Light Matrix')
            }
        except Exception as e:
            components['led_matrix'] = {
                'status': 'DISCONNECTED',
                'port': getattr(matrix_display, 'port', 'Unknown'),
                'error': str(e)
            }
    else:
        components['led_matrix'] = {'status': 'NOT_INITIALIZED'}
        
    # Check all BuildHAT ports for any changes
    try:
        hat = Hat()
        devices = hat.get()
        components['buildhat'] = {
            'status': 'OK', 
            'voltage': hat.get_vin(),
            'connected_ports': []
        }
        
        # List all currently connected devices by port
        for port, device in devices.items():
            if device:  # If not None, device is connected
                components['buildhat']['connected_ports'].append({
                    'port': port,
                    'device': str(device)
                })
                
    except Exception as e:
        components['buildhat'] = {
            'status': 'ERROR',
            'error': str(e)
        }
    
    return components

def close_gate_enhanced(motor):
    """Enhanced gate closing with improved holding power management and position verification."""
    global CLOSED_HOLD_POWER, GATE_CLOSED_ANGLE
    
    if not is_motor_connected(motor):
        logger.error("Motor disconnected - cannot close gate.")
        return False
    
    try:
        # Stop the holding power before attempting to close
        logger.info("Releasing holding power before closing...")
        motor.stop()
        time.sleep(0.2)  # Brief pause after stopping
        
    except Exception as e:
        logger.error(f"Error during hold release: {e}")
        motor.stop()  # Make sure we stop the motor even on error
    
    logger.info("Closing gate now...")
    if not close_gate(motor):
        logger.error("Gate closing failed due to motor disconnection.")
        return False
    
    # Update matrix to show closed status
    display_gate_status_on_matrix(is_open=False)
        
    # Check if still connected before continuing
    if not is_motor_connected(motor):
        logger.error("Motor disconnected during gate closing.")
        return False

    # ===== IMPROVED HOLDING POWER MANAGEMENT =====
    # After closing, verify position but minimize adjustments
    
    current_pos = motor.get_position()
    logger.info(f"Verifying closed position (currently at {current_pos}°)...")
    
    # Only attempt calibration if position is significantly off 
    # This is a more aggressive threshold to avoid unnecessary adjustments
    if abs(current_pos - GATE_CLOSED_ANGLE) > 5:  # Only calibrate if more than 5 degrees off
        logger.warning(f"Position significantly off target! Needs adjustment from {current_pos}° to {GATE_CLOSED_ANGLE}°")
        
        # Temporarily stop holding power for accurate calibration
        logger.info("Releasing holding power for repositioning...")
        motor.stop()
        time.sleep(0.2)
        
        # Now run calibration with higher power for a decisive movement
        try:
            logger.info("Moving to correct closed position...")
            motor.run_to_position(GATE_CLOSED_ANGLE, 50, blocking=True)  # Use higher power right away
            time.sleep(0.3)  # Give time to settle
            
            # Check final position
            final_pos = motor.get_position()
            logger.info(f"Repositioning complete - now at {final_pos}° (target: {GATE_CLOSED_ANGLE}°)")
        
        except Exception as e:
            logger.error(f"Error during repositioning: {e}")
            # Make sure motor is stopped
            try:
                motor.stop()
            except:  # noqa: E722
                pass
        
        # Always reapply holding power after calibration with maximum strength
        logger.info(f"Applying strong holding power ({CLOSED_HOLD_POWER}%) to maintain position...")
        hold_direction = 1  # Default direction (may need to be -1 depending on setup)
        motor.start(CLOSED_HOLD_POWER * hold_direction)  # Apply continuous power
        time.sleep(0.2)  # Brief pause to ensure power is applied
        logger.debug("Strong holding power applied after repositioning")
    else:
        # Even if position is good, verify that holding power is still active
        # This extra check ensures holding power is maintained
        logger.info(f"Gate position within acceptable range ({current_pos}°)")
        
        # Strengthen holding power to ensure it doesn't drift
        logger.info(f"Reinforcing holding power ({CLOSED_HOLD_POWER}%) to prevent drift...")
        hold_direction = 1  # Default direction (may need to be -1 depending on setup)
        motor.start(CLOSED_HOLD_POWER * hold_direction)  # Apply continuous power
        time.sleep(0.1)  # Brief pause to ensure power is applied
        logger.debug("Holding power reinforced")

    logger.info("Enhanced gate closing sequence complete")
    time.sleep(0.5)  # Brief pause for stability
    # ===== END IMPROVED HOLDING POWER MANAGEMENT =====
    
    return True



#central

#send
def send_component_status_with_results(component_status, initialization_success):
    """Send start gate component status using pre-obtained test results"""
    if not sio.connected:
        return

    # Use the overall initialization result
    overall_status = "OK" if initialization_success else "Error"

    # Build component status data using the results we already have
    data = {
        # Current timestamp when status is being sent
        'timestamp': time.time(),
        
        # Component status dictionary - use pre-obtained results
        'components': {
            # Motor status from the test results we already ran
            'Motor (LEGO)': component_status.get('motor', {}).get('status', 'Error'),
            
            # LED Matrix status from test results
            'LED Matrix': component_status.get('led_matrix', {}).get('status', 'Not Available'),
            
            # BuildHAT hardware status from test results  
            'BuildHAT': component_status.get('buildhat', {}).get('status', 'Unknown'),
            
            # Audio system status - quick check without full testing
            'Audio System': "OK" if pygame.mixer.get_init() else "Error"
        },
        
        # Identifies this as a start gate (vs finish gate)
        'gate_type': 'start_gate',
        
        # Simple hardcoded gate ID
        'gate_id': GATE_ID,
        
        # Overall system status based on initialization success
        'overall_status': overall_status
    }
    
    try:
        sio.emit('update_component_status', data)
        logger.info(f"Start gate component status sent: {overall_status}")
    except Exception as e:
        logger.error(f"Error sending component status: {e}")


def send_gate_status_update(status):
    """Send gate status update to central server"""
    if not sio.connected:
        return
    
    try:
        data = {
            'gate_type': 'start_gate',
            'gate_id': GATE_ID,
            'status': status,
            'timestamp': time.time()
        }
        sio.emit('gate_status_update', data)
        logger.info(f"Sent gate status to server: {status}")
    except Exception as e:
        logger.error(f"Error sending gate status: {e}")



def initialize_gate_for_new_race():
    #Stage 1: Initialization
    """Initialize start gate for a new race"""
    global global_motor
    
    logger.info("Initializing start gate for new race...")
    
    # Test all components once and get comprehensive status
    component_status = test_components()
    
    # Check if motor is working based on test results
    motor_status = component_status.get('motor', {})
    initialization_success = motor_status.get('status') == 'OK'
    
    if initialization_success:
        # Motor is connected and responsive, now ensure it's positioned correctly
        try:
            logger.info("Motor verified working - positioning to closed position...")
            
            # Display closed status on Matrix if available
            display_gate_status_on_matrix(is_open=False)
            
            # Check current position (using proven demo logic)
            current_pos = global_motor.get_position()
            if abs(current_pos - GATE_CLOSED_ANGLE) > 3:
                logger.info(f"Positioning gate to closed position (currently at {current_pos}°)...")
                
                # First stop any existing holding power
                global_motor.stop()
                time.sleep(0.1)
                
                # Move to closed position
                global_motor.run_to_position(GATE_CLOSED_ANGLE, CLOSE_SPEED, blocking=True)
                time.sleep(0.3)  # Brief pause
                
                # Immediately reapply holding power
                if CLOSED_HOLD_POWER > 0:
                    hold_direction = 1  # Default direction (may need to be -1 depending on setup)
                    logger.info(f"Applying closed holding power ({CLOSED_HOLD_POWER}%) to maintain position...")
                    global_motor.start(CLOSED_HOLD_POWER * hold_direction)  # Apply continuous power
                    time.sleep(0.1)  # Brief pause to ensure power is applied
            else:
                logger.info(f"Gate already in closed position ({current_pos}°)")
                
                # Even if position is good, ensure holding power is active
                if CLOSED_HOLD_POWER > 0:
                    hold_direction = 1
                    logger.info(f"Reinforcing holding power ({CLOSED_HOLD_POWER}%) to maintain position...")
                    global_motor.start(CLOSED_HOLD_POWER * hold_direction)
                    time.sleep(0.1)
            
            logger.info("✅ Start gate initialization successful")
            play_random_ready_audio()
            
        except Exception as e:
            logger.error(f"Error during gate positioning: {e}")
            initialization_success = False
    else:
        logger.error("❌ Start gate initialization failed - motor not responding")
    
    # Send component status using the results we already obtained
    send_component_status_with_results(component_status, initialization_success)
    
    return initialization_success



def confirm_gate_ready():
    #Stasge 2: Ready
    """Confirm gate is ready position with audio feedback"""
    logger.info("Start gate confirmed ready for race")
    
    # Play select car sound first
    play_selectcar_sound()
    
    # Wait for the selectcar sound to finish playing
    while pygame.mixer.get_busy():
        time.sleep(0.1)  # Check every 100ms
    
    
    

    #Notify server that gate is ready for countdown
    send_gate_status_update("Countdown")

def start_countdown_sequence():
    #Stage 3: Countdown
    """Begin countdown sequence with audio and visual feedback"""
    global global_motor
    
    logger.info("Starting countdown sequence...")
    
    # Use local configuration for countdown duration
    countdown_duration = GATE_OPEN_WAIT_TIME
    
    # Start countdown - gate will open in countdown_duration seconds
    logger.info(f"Starting countdown - gate will open in {countdown_duration} seconds...")
    
    # Wait for the specified countdown time with display
    wait_start = time.time()
    wait_end = wait_start + countdown_duration
    
    # Display yellow pulsing until 3 seconds remaining
    last_sound_time = 0  # Track when we last played the sound
    sound_interval = 3.0  # Only play sound every 3 seconds

    while time.time() < wait_end - 3:
        current_time = time.time()
        remaining = int(wait_end - time.time())
        logger.info(f"Gate opens in {remaining} seconds...")
        
        # Only play sound at certain intervals, not on every loop iteration
        if current_time - last_sound_time >= sound_interval:
            play_prelaunch_sound(0)
            last_sound_time = current_time
        
        # Yellow pulse on matrix
        if matrix_display:
            # Pulse between dim and bright yellow
            matrix_display.clear(("yellow", 3))
            time.sleep(0.2)
            matrix_display.clear(("yellow", 6))
            time.sleep(0.2)
    
    # 3 seconds remaining - top row red
    if time.time() < wait_end:
        remaining = 3
        logger.info(f"Gate opens in {remaining} seconds...")
        
        if matrix_display:
            play_countdown_sound(3)
            matrix_display.clear()  # Clear first
            
            for x in range(3):
                matrix_display.set_pixel((x, 0), ("red", 8))
        
        # Wait until 2 seconds remaining
        while time.time() < wait_end - 2:
            time.sleep(0.1)
    
    # 2 seconds remaining - top and middle row red
    if time.time() < wait_end:
        remaining = 2
        logger.info(f"Gate opens in {remaining} seconds...")
        
        if matrix_display:
            play_countdown_sound(2)
            matrix_display.clear()  # Clear first
            
            for x in range(3):
                matrix_display.set_pixel((x, 0), ("red", 8))
                matrix_display.set_pixel((x, 1), ("red", 8))
        
        # Wait until 1 second remaining
        while time.time() < wait_end - 1:
            time.sleep(0.1)
    
    # 1 second remaining - all rows red
    if time.time() < wait_end:
        remaining = 1
        logger.info(f"Gate opens in {remaining} second...")
        
        if matrix_display:
            play_countdown_sound(1)
            matrix_display.clear(("red", 8))  # All LEDs red
            
        # Wait until time to open
        while time.time() < wait_end:
            time.sleep(0.1)
    
    # Time to open - GO!
    play_countdown_sound(0)
    logger.info("Countdown complete - ready for gate opening!")
    
    if matrix_display:
        matrix_display.clear(("green", 10))  # All LEDs bright green
        
    time.sleep(0.5)  # Brief pause to show the GO signal
    
    logger.info("Countdown sequence completed")

    #Notify server that gate is ready for opening of gate
    send_gate_status_update("Racing")

def open_gate_for_race():
    #Stage 4: Racing
    """Open the gate when race officially starts"""
    global global_motor
    
    logger.info("Opening gate for race start!")
    
    try:
        # Play crowd sound as gate starts opening
        play_crowd_sound()
        
        # NOW open the gate
        if global_motor and is_motor_connected(global_motor):
            if open_gate(global_motor):
                logger.info("Gate opened successfully for race start")

                
                
                # Update matrix to show open status
                display_gate_status_on_matrix(is_open=True)
                
                # Apply holding power to resist gravity
                logger.info(f"Applying holding power ({HOLD_POWER}%) to maintain open position...")
                
                # Since gate opens to negative angle, use negative power to hold it
                try:
                    global_motor.start(-HOLD_POWER)  # Negative power for negative angles
                    logger.info("Holding power applied - gate ready for race")
                except Exception as e:
                    logger.error(f"Error applying holding power: {e}")
                    
            else:
                logger.error("Failed to open gate - motor connection issue")
        else:
            logger.error("Cannot open gate - motor not connected")
            
    except Exception as e:
        logger.error(f"Error during gate opening sequence: {e}")

def display_placement_results():
    #Stage 5: Placement
    """Display placement phase on start gate (if it has a display)"""
    print("challenge accepted")

def display_race_finished():
    #Stage 6: Finished
    """Display race finished state and close gate safely"""
    global global_motor
    
    logger.info("Race finished - closing gate for next race")
    
    try:
        # Close the gate using enhanced closing logic
        if global_motor and is_motor_connected(global_motor):
            if close_gate_enhanced(global_motor):
                logger.info("Gate successfully closed after race completion")
            else:
                logger.error("Failed to close gate after race")
        else:
            logger.warning("Cannot close gate - motor not connected")
            
    except Exception as e:
        logger.error(f"Error closing gate after race: {e}")
    
    logger.info("Race finished processing complete")
    
#handle sounds
def intermission_mode():
    """Handle intermission period between races"""
    logger.info("Intermission mode activated")
    
    # Display equalizer animation on matrix during intermission
    if matrix_display:
        logger.info("Starting continuous equalizer animation for intermission period")
        # Run equalizer indefinitely (no duration specified)
        display_equalizer_on_matrix()
    else:
        logger.info("No matrix display available for intermission animation")
        # If no matrix, just wait/idle during intermission
        while True:
            time.sleep(1)  # Keep the function alive until state changes
    
    logger.info("Intermission mode complete")   


def reset_gate_state():
    """Display reset state"""
    print("challenge accepted")

#handle sounds

def run_demo(motor):
    """
    Demo mode that tests the initial race stages for the start gate.
    Runs through: initialize → ready → countdown → open gate
    """
    global DEMO_RUNNING
    
    print("\n" + "=" * 60)
    print("🏁 START GATE DEMO MODE 🏁")
    print("=" * 60)
    print("Testing the initial race stages that the start gate anchors:")
    print("1. Initialize gate for new race")
    print("2. Confirm gate ready") 
    print("3. Start countdown sequence")
    print("4. Open gate for race")
    print("=" * 60)
    
    try:
        # Stage 1: Initialize gate for new race
        print("\n🔧 STAGE 1: Initializing gate for new race...")
        print("-" * 40)
        
        if not initialize_gate_for_new_race():
            print("❌ Demo failed at initialization stage")
            return False
        
        print("✅ Stage 1 complete: Gate initialization successful")
        while pygame.mixer.get_busy():
            time.sleep(0.1)
        
        # Stage 2: Confirm gate ready
        print("\n🎯 STAGE 2: Confirming gate ready...")
        print("-" * 40)
        while pygame.mixer.get_busy():
            time.sleep(0.1)
        
        confirm_gate_ready()
        print("✅ Stage 2 complete: Gate confirmed ready")
        
        # Wait for audio to complete before moving to next stage
        while pygame.mixer.get_busy():
            time.sleep(0.1)
        
        
        # Stage 3: Start countdown sequence
        print("\n⏱️ STAGE 3: Starting countdown sequence...")
        print("-" * 40)
        
        start_countdown_sequence()
        print("✅ Stage 3 complete: Countdown sequence finished")
        while pygame.mixer.get_busy():
            time.sleep(0.1)
        
        # Stage 4: Open gate for race
        print("\n🚪 STAGE 4: Opening gate for race...")
        print("-" * 40)
        
        open_gate_for_race()
        print("✅ Stage 4 complete: Gate opened for race")
        time.sleep(7)

        display_race_finished()
        print("✅ Final stage complete: Gate closed for race")
        
        # Demo completion
        print("\n" + "=" * 60)
        print("🎉 DEMO COMPLETED SUCCESSFULLY! 🎉")
        print("=" * 60)
        print("All start gate race stages tested successfully:")
        print("✅ Gate initialization")
        print("✅ Ready confirmation with audio")
        print("✅ Countdown sequence with visual/audio")
        print("✅ Gate opening for race start")
        print("=" * 60)
        
        # Wait a moment to let user see the completion message
        time.sleep(3)
        
        # Show restart instructions
        print("\n🔄 DEMO READY TO RESTART")
        print("-" * 30)
        print("Press the LEGO remote Left Center button to run demo again")
        print("Or select a different option from the main menu")
        print("-" * 30)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        print("Demo terminated due to unexpected error")
        return False
    
    finally:
        # Always reset the demo flag when finished
        DEMO_RUNNING = False
        print("DEBUG: Demo completed, DEMO_RUNNING flag reset to False")









#remote
# Then modify your handle_remote_button function:
def handle_remote_button(port, value):
    global global_motor, DEMO_RUNNING, LAST_BUTTON_PRESS
    
    # Get current time once for consistency
    current_time = time.time()
    
    # Use max() to ensure we never get a negative or huge number if LAST_BUTTON_PRESS wasn't set properly
    time_since_last = current_time - LAST_BUTTON_PRESS
    
    # Debug info for every button event
    print(f"DEBUG: Button event - port={port}, value=0x{value:02x}, time_since_last={time_since_last:.2f}s, DEMO_RUNNING={DEMO_RUNNING}")
    
    # Only handle relevant button press events
    #Launcher
    if port == remote.PORT_LEFT and value == 0x7F:  # Left Center button pressed
        print(f"Button event received: Left Center pressed, {time_since_last:.2f}s since last press")
        
        # Load fresh config for this button press
        refresh_config()
        
        # Super aggressive debouncing - ignore ALL presses within BUTTON_DEBOUNCE_TIME
        if time_since_last < BUTTON_DEBOUNCE_TIME:
            print(f"IGNORED: Button press too soon after previous press ({time_since_last:.2f}s < {BUTTON_DEBOUNCE_TIME}s)")
            
            # Even when ignoring, redisplay the menu to keep the UI consistent
            #display_main_menu()
            return
        
        # Check if a demo is already running
        if DEMO_RUNNING:
            print(f"IGNORED: Demo already running (flag={DEMO_RUNNING})")
            return
        
        # If we get here, it's a valid button press - update the timestamp immediately
        LAST_BUTTON_PRESS = current_time
        
        print("BUTTON PRESS ACCEPTED - Starting Demo!")
        
        if global_motor and is_motor_connected(global_motor):
            print("DEBUG: Setting DEMO_RUNNING=True")
            DEMO_RUNNING = True
            
            try:
                # Run the demo (will use the config we just loaded)
                run_demo(global_motor)
                
                # After the demo completes, force the menu to display again
                print("\n" + "-" * 50)
                print("Demo completed! Returning to main menu...")
                print("-" * 50)
                
                # Display settings and menu
                display_main_menu()
                
            finally:
                # Always make sure we reset the flag, even if there's an error
                print("DEBUG: Setting DEMO_RUNNING=False")
                DEMO_RUNNING = False
        else:
            print("Motor not available or disconnected!")
            # Display menu when there's an error too
            display_main_menu()
    
    elif port == remote.PORT_LEFT and value == 0x00:
        # Only log button releases, don't process them
        
        print("Button released (ignored)")


def start_remote_control_thread(loop):
    """Start the remote control in a separate thread."""
    asyncio.set_event_loop(loop)
    loop.run_until_complete(remote.main())



def display_main_menu():
    """Display current settings and main menu options."""
    # Clear several lines for better visibility
    print("\n\n" + "-" * 80)
    print("=" * 30 + " CURRENT SETTINGS " + "=" * 30)
    print("-" * 80)
    
    # Display settings in a structured format
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Button debounce time:", f"{BUTTON_DEBOUNCE_TIME}s",
        "Target open travel:", f"{TARGET_OPEN_TRAVEL}°"))
    
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Gate transition:", f"{GATE_TRANSITION}s",
        "Opening speed:", f"{OPEN_SPEED}%"))
        
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Closing speed:", f"{CLOSE_SPEED}%",
        "Opening ramp time:", f"{OPEN_RAMP_TIME}s"))
        
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Closing ramp time:", f"{CLOSE_RAMP_TIME}s",
        "Gate open wait time:", f"{GATE_OPEN_WAIT_TIME}s"))
        
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Holding power:", f"{HOLD_POWER}%",
        "Closed holding power:", f"{CLOSED_HOLD_POWER}%"))
        
    print("│ {:<25} {:>10} │ {:<25} {:>10} │".format(
        "Default speed:", f"{DEFAULT_SPEED}%",
        "Demo cycles:", f"{DEMO_CYCLES}"))
    
    #menu
    print("-" * 80)
    print("=" * 30 + " MAIN MENU " + "=" * 32)
    print("-" * 80)
    print("Position monitor is running in the background")
    print("Remote control is listening for LEGO 88010 remote button presses")
    print("Position updates will appear above this menu")
    print("-" * 80)
    print("\nSelect mode:")
    print("1. Run demo")
    print("2. Interactive control")
    print("3. Change port")
    print("4. Reset motor position to 0")
    print("5. Quit")
    print("Waiting for input...", flush=True)












# --- Socket.IO Event Handlers ---
#socket
@sio.event
def connect():
    """Handle connection to central server"""
    print("Connected to central server")
    
    # Test components and send status using the new function
    component_status = test_components()
    motor_status = component_status.get('motor', {})
    initialization_success = motor_status.get('status') == 'OK'
    
    # Send component status
    send_component_status_with_results(component_status, initialization_success)

@sio.event
def disconnect():
    """Handle disconnection from central server"""
    print("Disconnected from central server")

@sio.on('race_state_update')
def on_race_state_update(data):
    """Handle race state updates from the central server"""
    global race_state_from_server, current_race_number, formatted_race
    
    logger.info(f"Received race state update from server: {data}")
    race_state_from_server = data
    
    current_status = data.get('status')
    race_number = data.get('race_number')
    formatted_race_from_data = data.get('formatted_race')
    
    #elif
    # Handle different race states
    if current_status == 'Initialization':
        logger.info(f"Server race state: INITIALIZATION for race {formatted_race_from_data}")
        # Initialize start gate for new race
        current_race_number = race_number
        formatted_race = formatted_race_from_data
        initialize_gate_for_new_race()
        
    elif current_status == 'Ready':
        logger.info(f"Server race state: READY for race {formatted_race_from_data}")
        # Confirm gate is ready
        confirm_gate_ready()
        
    elif current_status == 'Countdown':
        logger.info(f"Server race state: COUNTDOWN for race {formatted_race_from_data}")
        # Begin countdown sequence and sounds
        start_countdown_sequence()
        
    elif current_status == 'Racing':
        logger.info(f"Server race state: RACING for race {formatted_race_from_data}")
        # Open the gate
        current_race_number = race_number
        formatted_race = formatted_race_from_data
        open_gate_for_race()
        
    
    elif current_status == 'Placement':
        logger.info(f"Server race state: PLACEMENT for race {formatted_race_from_data}")
        # Show placement/results on start gate display
        display_placement_results()
        
    elif current_status == 'Finished':
        logger.info(f"Server race state: FINISHED for race {formatted_race_from_data}")
        # Race complete, display final results
        display_race_finished()
        
    elif current_status == 'Intermission':
        logger.info("Server race state: INTERMISSION")
        # Break period between races
        intermission_mode() 
    #matrix equalizer
        
   
        
    elif current_status == 'Reset':
        logger.info("Server race state: RESET")
        # Reset to prepare for next race
        reset_gate_state()






def main():
    """Main function to run the gate controller."""
    global global_motor  # Make motor available to remote control
    
    clear_screen()
    print("=== Raspberry Pi BuildHAT Swing Gate Controller ===\n")
    
    # Sync time with NTP server for accurate timestamps
    sync_time_with_ntp()
    
    # Play Welcome Sound
    play_welcome()
    
    # First check for special devices like Matrix, ColorSensors, etc.
    special_devices = detect_special_devices()
    
    # Test Matrix if found
    matrix_port = None
    for port, (device_type, _) in special_devices.items():
        if device_type == "Matrix":
            matrix_port = port
            break
    
    if matrix_port:
        print(f"\nLED Matrix found on port {matrix_port}!")
        print("Running LED Matrix initialization sequence...")
        
        # Run the matrix test automatically
        test_matrix(matrix_port)
        
        # Initialize the Matrix for use in the program 
        print("Initializing Matrix for use during gate operation...")
        initialize_matrix(matrix_port)
    
    # Detect motors and select port
    print("\n")  # Add a separation line
    
    # Detect motors and select port
    connected_ports = detect_motors()
    selected_port = select_port(connected_ports)
    
    print(f"\nUsing motor on port {selected_port}")
    
    # Connect to the motor on selected port
    motor = connect_motor(selected_port)
    global_motor = motor  # Save for remote access
    
    # Check if motor connection succeeded
    if motor is None:
        print("Failed to connect to motor. Please check connections and try again.")
        return
    
    # Initialize the motor
    if not initialize_motor(motor):
        print("Failed to initialize motor. Checking if motor is still connected...")
        if not is_motor_connected(motor):
            print("Motor appears to be disconnected.")
            print("Would you like to retry with a different port? (y/n)")
            choice = input().strip().lower()
            if choice == 'y':
                main()  # Restart the program
            return
    
    # Start position monitor
    start_position_monitor(motor)

    
    
    
    print("\nConnecting to central server...")
    try:
        sio.connect(CENTRAL_SERVER_URL, transports=['websocket'])
        print("Successfully connected to central server")
    except Exception as e:
        print(f"Failed to connect to central server: {e}")
        print("Continuing in standalone mode...")
    
    
    
    
    
    
    # Start remote control
    print("\nStarting remote control system...")
    # Set the callback for button events
    remote.set_button_callback(handle_remote_button)
    
    # Start the remote control in a separate thread
    import threading
    remote_loop = asyncio.new_event_loop()
    remote_thread = threading.Thread(target=start_remote_control_thread, args=(remote_loop,), daemon=True)
    remote_thread.start()
    print("Remote control ready. Press Left Center button to run demo.")

     # ✅ ADD THIS: Check for demo-mode CLI argument
    if args.demo_mode:
        print("\n🚀 AUTO-STARTING DEMO MODE (--demo-mode argument detected)")
        print("Please hit LEGO controller Left Center button to start demo...")
        print("Press Ctrl+C to exit demo mode and continue to main menu")
        
        try:
            # Wait for button press to start demo
            while True:
                time.sleep(0.1)  # Wait for remote button press
                # The remote button handler will automatically trigger run_demo() when pressed
        except KeyboardInterrupt:
            print("\n\nDemo mode interrupted by user")
            print("Continuing to main menu...")
            time.sleep(1)
    
    # Main program loop
    while True:
        refresh_config()
        # Check if motor is still connected before showing the menu
        if not is_motor_connected(motor):
            print("\nWARNING: Motor disconnected!")
            print("Options:")
            print("1. Reconnect current port")
            print("2. Select different port")
            print("3. Exit")
            
            choice = input("Choice: ").strip()
            if choice == '1':
                # Try to reconnect
                stop_position_monitor()
                motor = connect_motor(selected_port)
                global_motor = motor  # Update global reference
                if motor is None or not is_motor_connected(motor):
                    print("Failed to reconnect. Motor may be unplugged.")
                    continue  # Go back to the disconnection menu
                else:
                    start_position_monitor(motor)
            elif choice == '2':
                # Clean up and go to port selection
                try:
                    stop_position_monitor()
                    safe_stop_motor(motor)
                except:  # noqa: E722
                    pass
                
                connected_ports = detect_motors()
                selected_port = select_port(connected_ports)
                motor = connect_motor(selected_port)
                global_motor = motor  # Update global reference
                stop_position_monitor
                if motor is None:
                    print("Failed to connect to motor. Please check connections and try again.")
                    continue
                
                if not initialize_motor(motor):
                    print("Failed to initialize motor.")
                    continue
                
                # Restart position monitor
                start_position_monitor(motor)
            else:
                print("Exiting program...")
                stop_position_monitor()
                break
        
        # Display current settings
        print("\nCurrent settings:")
        print(f"  Button debounce time: {BUTTON_DEBOUNCE_TIME}s")
        print(f"  Target open travel: {TARGET_OPEN_TRAVEL}°")
        print(f"  Gate transition: {GATE_TRANSITION}s")
        print(f"  Opening speed: {OPEN_SPEED}%")
        print(f"  Closing speed: {CLOSE_SPEED}%")
        print(f"  Opening ramp time: {OPEN_RAMP_TIME}s")
        print(f"  Closing ramp time: {CLOSE_RAMP_TIME}s")
        print(f"  Gate open wait time: {GATE_OPEN_WAIT_TIME}s")
        print(f"  Holding power: {HOLD_POWER}%")
        print(f"  Closed holding power: {CLOSED_HOLD_POWER}%")
        print(f"  Default speed: {DEFAULT_SPEED}%")
        print(f"  Demo cycles: {DEMO_CYCLES}")
        
        # Main menu
        print("\n" + "-" * 50)
        print("Position monitor is running in the background")
        print("Remote control is listening for LEGO 88010 remote button presses")
        print("(Position updates will appear above this menu)")
        print("-" * 50 + "\n")

        mode = input("Select mode:\n1. Run demo\n2. Interactive control\n3. Change port\n4. Reset motor position to 0\n5. Quit\nChoice: ").strip()
        
        if mode == '1':
            # Set flag to indicate demo is running
            DEMO_RUNNING = True  # noqa: F841
            try:
                run_demo(motor)
            finally:
                # Always reset the flag when we're done
                print("DEBUG: Setting DEMO_RUNNING=False")
                #DEMO_RUNNING = False
        elif mode == '2':
            # Stop the global position monitor during interactive mode
            # since it will interfere with command input
            stop_position_monitor()
            interactive_mode(motor)
            # Restart position monitor after exiting interactive mode
            start_position_monitor(motor)
        elif mode == '3':
            # Clean up before changing port
            print("Stopping motor...")
            stop_position_monitor()
            safe_stop_motor(motor)
            
            # Re-detect and select port
            connected_ports = detect_motors()
            selected_port = select_port(connected_ports)
            print(f"\nUsing motor on port {selected_port}")
            motor = connect_motor(selected_port)
            global_motor = motor  # Update global reference
            
            # Check if the connection succeeded
            if motor is None:
                print("Failed to connect to motor on the selected port.")
                continue
                
            if not initialize_motor(motor):
                print("Failed to initialize motor.")
                continue
                
            # Restart position monitor
            start_position_monitor(motor)
        
        # Replace the reset position code block with this simpler approach:
        elif mode == '4':
            print("Resetting motor to position 0...")
            print("Press [Enter] to stop, or use arrow keys â¬ï¸â¡ï¸ to change direction.")

            if not is_motor_connected(motor):
                print("Motor disconnected - cannot move to 0.")
            else:
                try:
                    import threading
                    import sys
                    import tty
                    import termios

                    cancel_flag = {'stop': False}
                    direction_flag = {'reverse': True}  # Start in reverse (-360)

                    def key_listener():
                        fd = sys.stdin.fileno()
                        old_settings = termios.tcgetattr(fd)
                        tty.setcbreak(fd)
                        try:
                            while not cancel_flag['stop']:
                                key = sys.stdin.read(1)
                                if key == '\n':  # Enter key
                                    cancel_flag['stop'] = True
                                elif key == '\x1b':  # Arrow key prefix
                                    if sys.stdin.read(1) == '[':
                                        arrow = sys.stdin.read(1)
                                        if arrow in ['C', 'D']:  # Right or Left
                                            direction_flag['reverse'] = not direction_flag['reverse']
                                            print(f"\nâï¸ Direction toggled. Now turning: {'reverse' if direction_flag['reverse'] else 'forward'}")
                        finally:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

                    threading.Thread(target=key_listener, daemon=True).start()

                    current_pos = motor.get_position()
                    print(f"Starting position: {current_pos} degrees")

                    while abs(current_pos) > 100:
                        if cancel_flag['stop']:
                            print("Unwinding stopped by user.")
                            return

                        print(f"Unwinding... current: {current_pos}")
                        step = -360 if direction_flag['reverse'] else 360
                        motor.run_for_degrees(step, speed=80, blocking=True)
                        time.sleep(0.3)
                        current_pos = motor.get_position()

                    print("Fine-tuning to 0 degrees...")
                    motor.run_to_position(0, speed=50, blocking=True)
                    time.sleep(0.3)

                    final_pos = motor.get_position()
                    print(f"Final position before reset: {final_pos} degrees")

                    motor.set_degrees_counted(0)
                    print("Motor encoder has been reset to 0 degrees.")

                except Exception as e:
                    print(f"Error during motor reset: {e}")

        elif mode == '5':
            print("Exiting program...")
            stop_position_monitor()
            break
    
    # Clean up
    print("Stopping motor...")
    safe_stop_motor(motor)
    print("Goodbye!")

if __name__ == "__main__":
    def cleanup_remote():
        """Clean up remote controller connections when exiting"""
        try:
            print("Closing remote control connections...")
            remote.stop_reconnecting()
            
            # Add Socket.IO cleanup
            if sio.connected:
                sio.disconnect()
                print("Disconnected from central server")
            
            
            # Force disconnect the BLE client if it exists
            if hasattr(remote, 'client') and remote.client:
                try:
                    asyncio.run(remote.client.disconnect())
                except:  # noqa: E722
                    pass
            
            # Allow time for connections to close
            time.sleep(0.5)
        except:  # noqa: E722
            pass

    # Register the cleanup function to run at exit
    atexit.register(cleanup_remote)
    
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram interrupted!")
        stop_position_monitor()
        print("Program terminated.")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        stop_position_monitor()
        print("Program terminated.")
        sys.exit(1)


