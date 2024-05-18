import board
import busio
import adafruit_mpr121
import time

# Initialize I2C bus
i2c = busio.I2C(board.SCL, board.SDA)

# Initialize MPR121 sensor
mpr121 = adafruit_mpr121.MPR121(i2c)

# Define the number of channels to test
num_channels = 6

# Set the touch and release thresholds for all channels
touch_threshold = 5
release_threshold = 2

for i in range(num_channels):
    mpr121[i].threshold = touch_threshold
    mpr121[i].release_threshold = release_threshold

# Define the minimum duration for a valid touch (in seconds)
min_touch_duration = 0.12

# Create variables to store the touch state and timestamp for each channel
touch_states = [False] * num_channels
touch_timestamps = [0] * num_channels

print("Ready to test touch detection on channels 0-5.")
print("Connect copper foil to each channel and touch the foil with the Hot Wheels car to trigger the detection.")
print("Press Ctrl+C to exit.")

try:
    while True:
        for i in range(num_channels):
            if mpr121[i].value:
                if not touch_states[i]:
                    # Touch detected, record the timestamp
                    touch_states[i] = True
                    touch_timestamps[i] = time.time()
            else:
                if touch_states[i]:
                    # Touch released, check the duration
                    touch_duration = time.time() - touch_timestamps[i]
                    if touch_duration >= min_touch_duration:
                        print(f"Valid touch confirmed on channel {i} (duration: {touch_duration:.2f}s)")
                    touch_states[i] = False
        
        time.sleep(0.1)  # Small delay to avoid excessive CPU usage
except KeyboardInterrupt:
    print("Test completed. Exiting.")