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
FULLSCREEN = True  # Whether to run the display in fullscreen mode

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

# Weather API configuration used by raceway html
WEATHER_API_KEY = '863892b569efb0c8c0402ce23a787e37'  # Replace with your actual API key
WEATHER_CITY_ID = '4699066'  # City ID for Irving, Texas

TEST_MODE = True

MAX_RACE_DURATION = 10