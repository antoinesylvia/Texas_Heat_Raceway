#!/usr/bin/env python3
"""
Gate 2 Checkpoint System
ESP32-based checkpoint gate for pinewood derby racing
Provides intermediate timing data between start and finish lines
"""

import os
os.environ['BLINKA_MCP2221'] = '1'

import argparse
import logging
import socketio
import subprocess
import sys
import time
from datetime import datetime
from collections import deque
import config

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants from config
LIGHT_SENSOR_THRESHOLD = config.LIGHT_SENSOR_THRESHOLD
TRACK_LENGTH_INCHES = config.TRACK_LENGTH_INCHES
MAX_RACE_DURATION = config.MAX_RACE_DURATION
TIMEOUT_DURATION = getattr(config, 'TIMEOUT_DURATION', 10)
CRASH_WARNING_TIME = getattr(config, 'CRASH_WARNING_TIME', 7)
CRASH_DETECTION_ENABLED = getattr(config, 'CRASH_DETECTION_ENABLED', True)
CENTRAL_SERVER_URL = config.CENTRAL_SERVER_URL
USE_ADAPTIVE_THRESHOLD = config.USE_ADAPTIVE_THRESHOLD
USE_DYNAMIC_THRESHOLD = config.USE_DYNAMIC_THRESHOLD
LIGHT_REDUCTION_PERCENTAGE = config.LIGHT_REDUCTION_PERCENTAGE
BASELINE_SAMPLES = config.BASELINE_SAMPLES

# Sensor calibration constants - now from config file
ROLLING_WINDOW_SIZE = getattr(config, 'ROLLING_WINDOW_SIZE', 10)
MIN_ABSOLUTE_CHANGE = getattr(config, 'MIN_ABSOLUTE_CHANGE', 5.0)
MIN_PERCENT_CHANGE = getattr(config, 'MIN_PERCENT_CHANGE', 20)
NOISE_THRESHOLD = getattr(config, 'NOISE_THRESHOLD', 2.0)

# Checkpoint-specific constants
GATE_ID = 'checkpoint_gate_1'
CHECKPOINT_POSITION = 'midpoint'  # Position description for logging

# Initialize Socket.IO client
sio = socketio.Client(logger=True, engineio_logger=True)

# Global hardware and state variables
race_in_progress = False
start_time = None
checkpoint_times = [None] * 6  # For 6 lanes
current_race_number = None
formatted_race = None
light_sensors = {}  # Dictionary to hold LightSensor objects, keyed by lane number
max_race_duration_config = MAX_RACE_DURATION
i2c_bus_global = None
mux_global = None

race_state_from_server = {
    'status': 'Unknown',
    'race_number': None,
    'formatted_race': None,
    'car_names': [],
    'countdown_duration': 5,
    'start_time': None
}

def parse_arguments():
    parser = argparse.ArgumentParser(description='Checkpoint Gate System for Pinewood Derby')
    parser.add_argument('--test_hw', action='store_true', help='Run hardware tests on startup.')
    parser.add_argument('--calibrate_sensors', action='store_true', help='Run interactive sensor calibration routine on startup.')
    parser.add_argument('--demo_mode', action='store_true', help='Run in demo mode without attempting server connection.')
    parser.add_argument('--debug', action='store_true', help='Enable DEBUG level logging.')
    return parser.parse_args()

def print_header(message):
    print("\n" + "=" * 50)
    print(message)
    print("=" * 50)

def sync_system_time_checkpoint():
    """
    Synchronize system time with NTP server for precise timing.
    Uses same function as gate_1_start.py and gate_3_finish.py for consistency.
    """
    print_header("SYSTEM TIME SYNCHRONIZATION")
    
    try:
        # Check if the timedatectl service is available
        result = subprocess.run(['timedatectl', 'status'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("System time synchronization status:")
            for line in result.stdout.strip().split('\n'):
                if any(keyword in line.lower() for keyword in ['ntp', 'synchronized', 'time zone']):
                    logger.info(f"  {line.strip()}")
            
            # Enable NTP synchronization
            sync_result = subprocess.run(['sudo', 'timedatectl', 'set-ntp', 'true'], capture_output=True, text=True, timeout=15)
            if sync_result.returncode == 0:
                logger.info("✓ NTP synchronization enabled successfully")
                
                # Wait a moment for sync to take effect
                time.sleep(2)
                
                # Check sync status again
                final_result = subprocess.run(['timedatectl', 'show'], capture_output=True, text=True, timeout=10)
                if final_result.returncode == 0:
                    for line in final_result.stdout.strip().split('\n'):
                        if 'NTPSynchronized=' in line:
                            is_synced = 'yes' in line.lower()
                            status = "✓ SYNCHRONIZED" if is_synced else "⚠ SYNCING..."
                            logger.info(f"  NTP Status: {status}")
                            break
                
                current_time = datetime.now()
                logger.info(f"  Current system time: {current_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
                logger.info("✓ Checkpoint gate time synchronization complete")
                return True
            else:
                logger.warning(f"Failed to enable NTP sync: {sync_result.stderr}")
                return False
        else:
            logger.warning("timedatectl not available, skipping NTP sync")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Time synchronization timed out")
        return False
    except Exception as e:
        logger.error(f"Error during time synchronization: {e}")
        return False

def initialize_hardware_checkpoint(num_lanes=6):
    """
    Initialize checkpoint gate hardware components.
    ESP32-based system with BH1750 light sensors.
    """
    global light_sensors, i2c_bus_global, mux_global
    
    logger.info(f"Initializing checkpoint gate hardware for {num_lanes} lanes...")
    light_sensors.clear()
    
    try:
        # Import required libraries
        import board
        import busio
        import adafruit_pca9548a  # Different multiplexer for ESP32
        import adafruit_bh1750
        
        # Initialize I2C bus
        i2c_bus_global = busio.I2C(board.SCL, board.SDA)
        logger.info("✓ I2C bus initialized")
        
        # Initialize PCA9548A multiplexer (different from TCA9548A used in Pi 5)
        mux_global = adafruit_pca9548a.PCA9548A(i2c_bus_global)
        logger.info("✓ PCA9548A multiplexer initialized")
        
        # Initialize BH1750 sensors for each lane
        for lane in range(1, num_lanes + 1):
            try:
                mux_channel = lane - 1  # 0-indexed
                sensor = adafruit_bh1750.BH1750(mux_global[mux_channel])
                
                # Create LightSensor wrapper (using advanced sensor class)
                light_sensor = LightSensor(lane, sensor)
                light_sensors[lane] = light_sensor
                
                logger.info(f"✓ Lane {lane} sensor initialized (channel {mux_channel})")
                
            except Exception as e:
                logger.error(f"✗ Failed to initialize sensor for lane {lane}: {e}")
        
        logger.info(f"✓ Checkpoint gate hardware initialization complete - {len(light_sensors)} sensors active")
        return True
        
    except Exception as e:
        logger.error(f"✗ Hardware initialization failed: {e}")
        return False

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
        """Check if the current light value triggers a checkpoint detection."""
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
            logger.info(f"Lane {self.lane}: CHECKPOINT Detection TRIGGERED! Lux: {current_lux_value:.2f}, StableAvg: {self.stable_average:.2f}, DynThresh: {self.dynamic_threshold:.2f} (Target Reduc%: {self.adaptive_trigger_percentage:.1f}%, Actual Reduc%: {reduction_percentage:.1f}%)")
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

def reset_gate_state_checkpoint():
    """Reset checkpoint gate to ready state"""
    global race_in_progress, start_time, checkpoint_times
    
    logger.info("Resetting checkpoint gate state...")
    
    race_in_progress = False
    start_time = None
    
    # Reset all checkpoint times
    for i in range(len(checkpoint_times)):
        checkpoint_times[i] = None
    
    logger.info("✓ Checkpoint gate reset complete")

def race_action_inbound_to_checkpoint_gate():
    """Action to take when race starts at checkpoint gate"""
    global race_in_progress, start_time, checkpoint_times
    
    if race_in_progress:
        logger.warning("Attempted to start checkpoint monitoring, but already monitoring a race.")
        return
    
    logger.info("Starting checkpoint monitoring for new race...")
    
    race_in_progress = True
    start_time = time.perf_counter()  # High-precision timer
    
    # Reset all checkpoint times
    for i in range(len(checkpoint_times)):
        checkpoint_times[i] = None
    
    logger.info(f"Race {formatted_race if formatted_race else ''} checkpoint monitoring started at {start_time:.4f}")
    send_race_state_to_server_checkpoint('Racing')

def check_checkpoint_conditions(num_lanes_active=6):
    """Check if any cars have passed the checkpoint"""
    global checkpoint_times, race_in_progress
    
    if not race_in_progress or start_time is None:
        return
    
    current_event_time = time.perf_counter()
    
    # Check light sensors for cars passing checkpoint
    for lane_num in range(1, num_lanes_active + 1):
        if lane_num in light_sensors and checkpoint_times[lane_num - 1] is None:
            sensor_obj = light_sensors[lane_num]
            try:
                current_lux = sensor_obj.sensor.lux
                
                # Update sensor with new reading (important for adaptive thresholds)
                sensor_obj.update(current_lux)
                
                # Check if triggered using advanced detection logic
                if sensor_obj.is_triggered(current_lux):
                    # Capture precise checkpoint time
                    precise_checkpoint_time = current_event_time
                    checkpoint_times[lane_num - 1] = precise_checkpoint_time
                    
                    # Convert to epoch time for server
                    epoch_checkpoint_time = time.time() - (time.perf_counter() - precise_checkpoint_time)
                    epoch_race_start = time.time() - (time.perf_counter() - start_time)
                    
                    elapsed_time = current_event_time - start_time
                    logger.info(f"Lane {lane_num} CHECKPOINT! Time: {elapsed_time:.4f}s")
                    
                    # Send checkpoint timing to server
                    send_car_checkpoint_time(lane_num, epoch_checkpoint_time, epoch_race_start, elapsed_time)
                    
            except Exception as e:
                logger.error(f"Error reading checkpoint sensor for Lane {lane_num}: {e}")

def start_countdown_sequence_checkpoint_gate():
    """Prepare checkpoint gate for incoming race during countdown"""
    logger.info("Countdown sequence started - preparing checkpoint sensors")
    
    # Final sensor calibration before race
    calibration_all_ok = True
    if not light_sensors:
        logger.error("No checkpoint sensors available for calibration.")
        calibration_all_ok = False
    else:
        for lane, sensor_obj in light_sensors.items():
            logger.info(f"Calibrating checkpoint sensor for Lane {lane}...")
            if not sensor_obj.calibrate():  # Use advanced calibrate() method
                logger.error(f"Failed to calibrate checkpoint sensor for Lane {lane}.")
                calibration_all_ok = False
    
    if not calibration_all_ok:
        logger.error("One or more checkpoint sensors failed calibration.")
    else:
        logger.info("✓ All checkpoint sensors calibrated and ready")

def confirm_gate_ready_checkpoint():
    """Confirm checkpoint gate is ready for racing"""
    logger.info("Checkpoint gate confirming ready state")
    send_component_status_checkpoint()

def initialize_gate_for_new_race_checkpoint():
    """Initialize checkpoint gate for a new race"""
    global current_race_number, formatted_race
    
    logger.info(f"Initializing checkpoint gate for new race: {formatted_race}")
    reset_gate_state_checkpoint()
    
    # Calibrate sensors for new race
    for lane, sensor_obj in light_sensors.items():
        if not sensor_obj.calibrate():  # Use advanced calibrate() method
            logger.warning(f"Calibration warning for checkpoint Lane {lane}")

# --- Socket.IO Event Handlers ---

@sio.event
def connect():
    logger.info("✓ Checkpoint gate connected to central server")
    
    # Send initial status
    send_component_status_checkpoint()
    
    # Announce checkpoint gate is online
    sio.emit('gate_announcement', {
        'gate_type': 'checkpoint_gate',
        'gate_id': GATE_ID,
        'position': CHECKPOINT_POSITION,
        'status': 'online',
        'lanes_monitored': len(light_sensors),
        'timestamp': time.time()
    })

@sio.event
def connect_error(data):
    logger.error(f"Checkpoint gate connection failed: {data}")

@sio.event
def disconnect():
    logger.info("Checkpoint gate disconnected from central server")

@sio.on('race_command')
def on_race_command_checkpoint(data):
    global current_race_number, formatted_race
    logger.info(f"Checkpoint gate received race_command: {data}")
    command = data.get('command')
    
    # Update race identifiers if provided
    if 'race_number' in data:
        current_race_number = data['race_number']
    if 'formatted_race' in data:
        formatted_race = data['formatted_race']
    
    if command == 'start_race':
        logger.info(f"Server initiated START_RACE for checkpoint gate: {formatted_race or current_race_number}")
        race_action_inbound_to_checkpoint_gate()
    elif command == 'reset_gate':
        logger.info("Server initiated RESET_GATE for checkpoint.")
        reset_gate_state_checkpoint()
    elif command == 'request_status':
        logger.info("Server requested checkpoint status.")
        send_component_status_checkpoint()
    else:
        logger.warning(f"Checkpoint gate received unknown race command: {command}")

@sio.on('race_state_update')
def on_race_state_update_checkpoint(data):
    """Handle race state updates from central server"""
    global race_state_from_server, current_race_number, formatted_race
    
    logger.info(f"Checkpoint gate received race state update: {data}")
    race_state_from_server = data
    
    current_status = data.get('status')
    race_number = data.get('race_number')
    formatted_race_from_data = data.get('formatted_race')
    
    if current_status == 'Initialization':
        logger.info(f"Checkpoint gate - Server race state: INITIALIZATION for race {formatted_race_from_data}")
        current_race_number = race_number
        formatted_race = formatted_race_from_data
        initialize_gate_for_new_race_checkpoint()
        
    elif current_status == 'Ready':
        logger.info(f"Checkpoint gate - Server race state: READY for race {formatted_race_from_data}")
        confirm_gate_ready_checkpoint()
        
    elif current_status == 'Countdown':
        logger.info(f"Checkpoint gate - Server race state: COUNTDOWN for race {formatted_race_from_data}")
        start_countdown_sequence_checkpoint_gate()
        
    elif current_status == 'Racing':
        logger.info(f"Checkpoint gate - Server race state: RACING for race {formatted_race_from_data}")
        current_race_number = race_number
        formatted_race = formatted_race_from_data
        race_action_inbound_to_checkpoint_gate()
        
    elif current_status == 'Placement':
        logger.info("Checkpoint gate - Server race state: PLACEMENT")
        # Checkpoint gate just monitors, doesn't control placement display
        
    elif current_status == 'Finished':
        logger.info("Checkpoint gate - Server race state: FINISHED")
        # Race is complete
        
    elif current_status == 'Intermission':
        logger.info("Checkpoint gate - Server race state: INTERMISSION")
        
    elif current_status == 'Reset':
        logger.info("Checkpoint gate - Server race state: RESET")
        reset_gate_state_checkpoint()

@sio.on('get_checkpoint_times')
def on_get_checkpoint_times(data):
    """Handle request for checkpoint times from finish gate"""
    race_number = data.get('race_number')
    requesting_gate = data.get('gate_type', 'unknown')
    
    logger.info(f"Checkpoint times requested by {requesting_gate} for race {race_number}")
    
    # Convert checkpoint times to dictionary format
    checkpoint_data = {}
    for i, checkpoint_time in enumerate(checkpoint_times):
        lane_num = i + 1
        if checkpoint_time is not None:
            elapsed = checkpoint_time - start_time if start_time else None
            checkpoint_data[lane_num] = elapsed
        else:
            checkpoint_data[lane_num] = None
    
    # Send response
    sio.emit('checkpoint_times_response', {
        'race_number': race_number,
        'formatted_race': formatted_race,
        'checkpoint_times': checkpoint_data,
        'gate_type': 'checkpoint_gate',
        'position': CHECKPOINT_POSITION
    })
    
    logger.info(f"Sent checkpoint times: {checkpoint_data}")

# --- Socket.IO Emitters ---

def send_race_state_to_server_checkpoint(status_str, results=None):
    """Send checkpoint gate race state to central server"""
    if not sio.connected:
        logger.warning("Cannot send race state - not connected to server")
        return
    
    data = {
        'gate_type': 'checkpoint_gate',
        'gate_id': GATE_ID,
        'status': status_str,
        'race_number': current_race_number,
        'formatted_race': formatted_race,
        'position': CHECKPOINT_POSITION,
        'timestamp': time.time()
    }
    
    if results:
        data['results_summary'] = results
    
    try:
        sio.emit('gate_status_update', data)
        logger.info(f"Sent checkpoint race state to server: {status_str}")
    except Exception as e:
        logger.error(f"Error sending checkpoint race state: {e}")

def send_car_checkpoint_time(lane, checkpoint_time, race_start_time, elapsed_time):
    """Send precise car checkpoint timing to central server"""
    if not sio.connected:
        logger.warning(f"Cannot send checkpoint time for lane {lane} - not connected to server")
        return
    
    data = {
        'event_type': 'car_checkpoint',
        'gate_type': 'checkpoint_gate',
        'gate_id': GATE_ID,
        'lane': lane,
        'checkpoint_time': checkpoint_time,
        'race_start_time': race_start_time,
        'elapsed_time': elapsed_time,
        'race_number': current_race_number,
        'formatted_race': formatted_race,
        'position': CHECKPOINT_POSITION,
        'timestamp': time.time(),
        'milliseconds': int((checkpoint_time % 1) * 1000)  # Milliseconds for consistency
    }
    
    try:
        sio.emit('gate_timing_event', data)
        logger.info(f"Sent checkpoint timing for Lane {lane}: {elapsed_time:.4f}s")
    except Exception as e:
        logger.error(f"Error sending checkpoint timing for Lane {lane}: {e}")

def send_component_status_checkpoint():
    """Send checkpoint gate component status to central server"""
    if not sio.connected:
        return
    
    sensor_status = {}
    for lane, sensor_obj in light_sensors.items():
        try:
            current_lux = sensor_obj.sensor.lux
            sensor_status[f'lane_{lane}'] = {
                'status': 'operational',
                'current_lux': round(current_lux, 1),
                'stable_average': round(sensor_obj.stable_average, 1) if sensor_obj.stable_average else None,
                'dynamic_threshold': round(sensor_obj.dynamic_threshold, 1) if sensor_obj.dynamic_threshold else None,
                'adaptive_trigger_percentage': round(sensor_obj.adaptive_trigger_percentage, 1),
                'is_ready': sensor_obj.is_ready
            }
        except Exception as e:
            sensor_status[f'lane_{lane}'] = {
                'status': 'error',
                'error': str(e)
            }
    
    status_data = {
        'gate_type': 'checkpoint_gate',
        'gate_id': GATE_ID,
        'position': CHECKPOINT_POSITION,
        'race_in_progress': race_in_progress,
        'current_race': formatted_race,
        'sensors_active': len(light_sensors),
        'sensor_status': sensor_status,
        'timestamp': time.time()
    }
    
    try:
        sio.emit('component_status', status_data)
        logger.debug("Sent checkpoint component status to server")
    except Exception as e:
        logger.error(f"Error sending checkpoint component status: {e}")

def main_loop_checkpoint(num_lanes_in_use=6):
    """Main event loop for checkpoint gate - monitoring only"""
    global race_in_progress
    
    logger.info(f"Checkpoint gate main loop started. Monitoring {num_lanes_in_use} lanes.")
    send_race_state_to_server_checkpoint('Ready')
    
    last_status_send_time = time.time()
    status_send_interval = 30  # Send status every 30 seconds
    
    try:
        while True:
            current_loop_time = time.time()
            
            # Core checkpoint logic: monitor for cars passing
            if race_in_progress:
                check_checkpoint_conditions(num_lanes_active=num_lanes_in_use)
            
            # Periodic status updates
            if current_loop_time - last_status_send_time > status_send_interval:
                send_component_status_checkpoint()
                last_status_send_time = current_loop_time
            
            time.sleep(0.02)  # 20ms delay
            
    except KeyboardInterrupt:
        logger.info("Checkpoint gate shutting down...")
    except Exception as e:
        logger.error(f"Error in checkpoint main loop: {e}", exc_info=True)

def run_demo_checkpoint(num_lanes=6):
    """Demo mode for checkpoint gate testing"""
    print("\n" + "=" * 60)
    print("CHECKPOINT GATE DEMO MODE")
    print("=" * 60)
    print("Local testing mode for checkpoint gate:")
    print("• Monitors sensor readings")
    print("• Simulates checkpoint timing")
    print("• ESC key: Exit demo mode")
    print("=" * 60)
    
    logger.info(f"Checkpoint demo mode started. Monitoring {num_lanes} lanes.")
    
    demo_race_number = 1
    
    try:
        while True:
            print(f"\nDemo Race {demo_race_number} - Press ENTER to start monitoring or ESC to exit")
            
            # Simple demo loop
            print("Monitoring checkpoint sensors...")
            for i in range(10):  # 10 second demo
                if light_sensors:
                    for lane, sensor_obj in light_sensors.items():
                        try:
                            lux = sensor_obj.sensor.lux
                            # Show current reading and threshold info
                            if sensor_obj.is_ready:
                                status = f"{lux:.1f}lx (thresh: {sensor_obj.dynamic_threshold:.1f})"
                            else:
                                status = f"{lux:.1f}lx (calibrating...)"
                            print(f"Lane {lane}: {status}", end="  ")
                        except Exception:
                            print(f"Lane {lane}: ERROR", end="  ")
                    print()
                time.sleep(1)
            
            demo_race_number += 1
            
    except KeyboardInterrupt:
        print("\n" + "=" * 60)
        print("CHECKPOINT DEMO COMPLETED")
        print("=" * 60)
        logger.info("Checkpoint demo mode terminated.")

def cleanup_resources_checkpoint():
    """Clean up checkpoint gate resources"""
    global i2c_bus_global, mux_global, light_sensors
    
    logger.info("Cleaning up checkpoint gate resources...")
    
    # Clear sensors
    light_sensors.clear()
    
    # Close I2C resources
    if i2c_bus_global:
        try:
            i2c_bus_global.deinit()
        except Exception:
            pass
        i2c_bus_global = None
    
    mux_global = None
    
    logger.info("Checkpoint gate cleanup complete.")

# --- Application Entry Point ---
if __name__ == "__main__":
    args = parse_arguments()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("DEBUG logging enabled for checkpoint gate.")
    
    # Sync system time with NTP
    sync_system_time_checkpoint()
    
    print_header("CHECKPOINT GATE SYSTEM INITIALIZATION")
    
    # Use constant for all 6 lanes
    NUMBER_OF_LANES = 6
    logger.info(f"Checkpoint Gate System starting for all {NUMBER_OF_LANES} lanes.")
    
    # Initialize hardware
    if not initialize_hardware_checkpoint(num_lanes=NUMBER_OF_LANES):
        logger.critical("Checkpoint hardware initialization failed. Exiting.")
        sys.exit(1)
    
    # Check for demo mode
    demo_mode = args.demo_mode or getattr(config, 'DEMO_MODE', False)
    
    if demo_mode:
        logger.info("Checkpoint demo mode enabled - skipping server connection")
        print("\n🎯 STARTING CHECKPOINT GATE DEMO MODE")
        
        try:
            run_demo_checkpoint(num_lanes=NUMBER_OF_LANES)
        except Exception as e_demo:
            logger.critical(f"Error during checkpoint demo mode: {e_demo}", exc_info=True)
        finally:
            cleanup_resources_checkpoint()
            sys.exit(0)
    
    else:
        # Connect to server
        try:
            logger.info(f"Connecting checkpoint gate to server at {CENTRAL_SERVER_URL}...")
            sio.connect(CENTRAL_SERVER_URL, transports=['websocket'])
            logger.info("✓ Checkpoint gate connected to server")
        except Exception as e:
            logger.error(f"Checkpoint gate connection failed: {e}. Consider using --demo_mode")
            sys.exit(1)
        
        # Start main loop
        try:
            main_loop_checkpoint(num_lanes_in_use=NUMBER_OF_LANES)
        except Exception as e:
            logger.critical(f"Error in checkpoint main loop: {e}", exc_info=True)
        finally:
            cleanup_resources_checkpoint()
            sys.exit(0)
