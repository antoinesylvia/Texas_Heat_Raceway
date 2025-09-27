# =============================================================================
    # FINISH GATE CONFIGURATION CONSTANTS
# =============================================================================

# Finish Gate Thresholds 
LIGHT_SENSOR_THRESHOLD = 100  # Static threshold for light detection (used when adaptive threshold is off)
USE_ADAPTIVE_THRESHOLD = True  # Keep this True for outdoor environments
USE_DYNAMIC_THRESHOLD = False  # The new adaptive system replaces this
LIGHT_REDUCTION_PERCENTAGE = 20 # Starting value only - will be dynamically adjusted
BASELINE_SAMPLES = 50 # Good value for initial calibration

# Enhanced Sensor Calibration Constants
ROLLING_WINDOW_SIZE = 10  # Size of rolling window for continuous light level monitoring
MIN_ABSOLUTE_CHANGE = 5.0  # No longer directly used by the new adaptive system
MIN_PERCENT_CHANGE = 20    # No longer directly used by the new adaptive system  
NOISE_THRESHOLD = 2.0      # Still used for very low light conditions

# New Outdoor Environment Settings
RECALIBRATION_INTERVAL = 120  # Seconds between automatic recalibrations (2 minutes)
LIGHT_TREND_WINDOW = 30    # Number of readings to track light trends
SIGNIFICANT_CHANGE_THRESHOLD = 15  # Percentage change to trigger immediate recalibration

# Waveshare Screen 
SCREEN_WIDTH = 1480  # Width of the waveshare display screen in pixels
SCREEN_HEIGHT = 320  # Height of the waveshare display screen in pixels
FULLSCREEN = False  # Whether to run the display in fullscreen mode
PYGAME_DISPLAY_INDEX = 0

# Weather API configuration used by raceway html
WEATHER_API_KEY = 'xxxxx'  # Replace with your actual API key
WEATHER_CITY_ID = '4699066'  # City ID for Irving, Texas

# Irving, Texas coordinates for OpenWeatherMap One Call API 3.0
IRVING_LAT = 32.8140  # Latitude for Irving, TX
IRVING_LON = -96.9489  # Longitude for Irving, TX
IRVING_ALTITUDE_FEET = 518  # Altitude in feet above sea level
IRVING_ALTITUDE_METERS = 158  # Altitude in meters above sea level

# Dynamic air density calculation settings
USE_DYNAMIC_AIR_DENSITY = True  # Set to False to use static value
AIR_DENSITY_UPDATE_INTERVAL = 300  # Update every 5 minutes (300 seconds)
MAX_AIR_DENSITY_API_CALLS_PER_HOUR = 10  # Limit API calls to conserve quota

# =============================================================================
    # CENTRAL SERVER CONFIGURATION CONSTANTS
# =============================================================================

# Central Server settings
DB_NAME = 'central_race_results.db'  # Name of the SQLite database file
NUM_LANES = 6  # Number of lanes on the race track
DEFAULT_CAR_NAMES = ['Car 1', 'Car 2', 'Car 3', 'Car 4', 'Car 5', 'Car 6']  # Default names for cars in each lane. Date & time are appended.
MAX_RETRIES = 1 # retry if fail 
RETRY_DELAY = 5  # wait X seconds
HOST = '192.168.1.132'  # Server listens on all network interfaces
PORT = 5000  # Port number for the server to listen on
SERVER_HOSTNAME = '192.168.1.132'  # Hostname for clients to connect to (localhost)



# Shared settings
CENTRAL_SERVER_URL = f"http://{SERVER_HOSTNAME}:{PORT}"  # Full URL for connecting to the central server



TEST_MODE = True

TRACK_LENGTH_INCHES=180
TIMEOUT_DURATION=10                # Realistic crash detection: 10 seconds timeout
CRASH_WARNING_TIME=7               # Warning time at 7 seconds (cars taking too long)
CRASH_DETECTION_ENABLED=True       # Enable enhanced crash detection

MAX_RACE_DURATION = 12             # Maximum race duration set to 12 seconds

# =============================================================================
# TRACK PHYSICS CONSTANTS (for advanced calculations)
# =============================================================================

# Track physical dimensions
INCLINE_HEIGHT_FEET = 4.0          # Height of the incline in feet
CHECKPOINT_DISTANCE_FEET = 13.5    # Distance from start to checkpoint in feet (75% of 180"/12 = 15')

# Physics constants
GRAVITY_MS2 = 9.81                 # Standard gravity acceleration in m/s²

# Air density for Irving, Texas (altitude ~518 feet / 158 meters)
# Standard conditions: 20°C (68°F), 1013.25 hPa
# Adjusted for local altitude and typical Texas conditions
AIR_DENSITY_KG_M3 = 1.195          # Air density adjusted for Irving, TX altitude and typical conditions

# Alternative air density values for different conditions (reference)
# Hot summer day (35°C/95°F): ~1.15 kg/m³
# Cool winter day (5°C/41°F): ~1.25 kg/m³
# Standard sea level (15°C/59°F): 1.225 kg/m³
# Current setting represents typical moderate conditions for North Texas

# FUTURE ENHANCEMENT: Dynamic Air Density Calculation
# Could integrate with existing weather API to calculate real-time air density using:
# ρ = (P × M) / (R × T)
# Where: P = pressure (Pa), M = molar mass of air (0.02897 kg/mol), 
#        R = gas constant (8.314 J/(mol·K)), T = temperature (K)
# Using WEATHER_API_KEY and WEATHER_CITY_ID for current conditions

# =============================================================================
    # START GATE CONFIGURATION CONSTANTS
# =============================================================================

# Start Gate Configuration Section
BUTTON_DEBOUNCE_TIME = 30.0        # Button debounce time in seconds
GATE_TRANSITION = 0.27             # Seconds to wait when switching power states
GATE_OPEN_WAIT_TIME = 5.0          # Seconds before auto-closing

# Gate movement parameters  
TARGET_OPEN_TRAVEL = -165          # Degrees from closed to open
OPEN_RAMP_TIME = 1.0               # Ramp up time for opening
CLOSE_RAMP_TIME = 15.0             # Ramp down time for closing

# Motor speeds (0-100%)
OPEN_SPEED = 100                   # Speed when opening gate
CLOSE_SPEED = 10                   # Speed when closing gate  
DEFAULT_SPEED = 40                 # Default motor speed

# Motor power settings
MOTOR_POWER_LIMIT = 0.85           # Maximum power limit (0-1)
HOLD_POWER = 100                   # Holding power when gate is open
CLOSED_HOLD_POWER = 100            # Holding power when gate is closed

# Demo settings
DEMO_CYCLES = 1                    # Number of cycles per demo

