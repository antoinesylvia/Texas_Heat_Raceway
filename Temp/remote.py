import asyncio
import os
import time
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError

# File to save the previously discovered remote address (so next run is faster)
ADDRESS_FILE = "remote_address.txt"

# LEGO 88010 Handset Bluetooth GATT service and characteristic UUIDs
SERVICE_UUID = "00001623-1212-efde-1623-785feabcd123"  # Service UUID (Fixed)
CHAR_UUID = "00001624-1212-efde-1623-785feabcd123"    # Characteristic UUID for communication

# Port numbers used to identify left and right button groups on the remote
PORT_LEFT = 0x00
PORT_RIGHT = 0x01

# Global variables
button_callback = None
last_button_states = {PORT_LEFT: None, PORT_RIGHT: None}
reconnect_flag = True  # Flag to control reconnection loop
connection_status = False  # Track if we're currently connected
bluetooth_already_reset = False

# Decode button signal values into human readable button events
def parse_button(port, value):
    if port == PORT_LEFT:
        side = "Left"
    elif port == PORT_RIGHT:
        side = "Right"
    else:
        side = "Unknown"

    # Button state decoding based on LEGO protocol (value byte meaning)
    if value == 0xFF:
        return f"{side} - (Minus)"
    elif value == 0x7F:
        return f"{side} (Center)"
    elif value == 0x01:
        return f"{side} + (Plus)"
    elif value == 0x00:
        return f"{side} Released"
    else:
        return f"{side} Unknown"

# Called whenever the remote sends a notification (button pressed, released, etc)
def notification_handler(sender, data):
    global last_button_states, button_callback

    # Always print raw packet for debug visibility
    print(f"Raw data: {list(data)}")

    # LEGO handset sends button packets like:
    # [ 0x05, 0x00, 0x45, <port>, <button_value> ]
    if len(data) != 5 or data[0] != 0x05 or data[2] != 0x45:
        return  # Not a valid button packet â ignore

    port = data[3]
    value = data[4]

    # If button state changed, print it
    if last_button_states.get(port) != value:
        button_desc = parse_button(port, value)
        print("Button event:", button_desc)
        last_button_states[port] = value
        
        # Call the callback if one is set
        if button_callback:
            button_callback(port, value)
    
    # Special handling for Left Center button - this ensures it works even with repeated presses
    if button_callback and port == PORT_LEFT and value == 0x7F:  # Left Center button
        button_callback(port, value)

# Send command to the LEGO handset telling it:
# "Send me notifications when button state changes on this port"
async def enable_port_notifications(client, port):
    print(f"Enabling notifications for port {port}...")

    # This is a "Port Input Format Setup (Single)" command â 0x41
    # It configures the remote to:
    # - Port: port (0x00 = Left, 0x01 = Right)
    # - Mode: 0x01 â "Simple Button Press Mode"
    # - Notifications Enabled: 0x01 â notify on changes
    setup = bytearray([
        0x0A,  # Length of packet
        0x00,  # Hub ID (not used here)
        0x41,  # Command: Port Input Format Setup (Single)
        port,  # Which port (Left or Right)
        0x01,  # Mode (simple button mode)
        0x01,  # Delta (change threshold, leave 1)
        0x00,  # Unit (ignored)
        0x00,  # Not used
        0x00,  # Not used
        0x01   # Enable notifications (1=on)
    ])
    await client.write_gatt_char(CHAR_UUID, setup)

# Checks if client is connected and responds
async def is_client_connected(client):
    try:
        # Try to read a characteristic as a connection test
        await client.get_services()
        return True
    except Exception:
        return False

# Main connection + listen logic with reconnect capability
async def connect_and_listen(address):
    global reconnect_flag, connection_status
    reconnect_flag = True
    connection_status = False
    
    # Start the reconnection loop
    while reconnect_flag:
        try:
            print(f"Connecting to remote [{address}]...")
            async with BleakClient(address, address_type="random", timeout=10.0) as client:
                # Print connection timestamp
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                print(f"â CONNECTED at {timestamp} - Remote is ready! [{address}]")
                connection_status = True

                # Confirm and print discovered GATT services and characteristics
                services = await client.get_services()
                print(f"Using UUID: {CHAR_UUID}")
                for service in services:
                    print(f"Service: {service.uuid}")
                    for char in service.characteristics:
                        print(f"  Characteristic: {char.uuid}")

                # Enable notifications for both Left and Right ports â so remote sends button state changes
                await enable_port_notifications(client, PORT_LEFT)
                await enable_port_notifications(client, PORT_RIGHT)

                # Start listening to notifications from the remote
                await client.start_notify(CHAR_UUID, notification_handler)

                print("Listening for button presses. Press Ctrl+C to exit.")
                
                # Keep checking connection status
                while await is_client_connected(client):
                    await asyncio.sleep(1)
                
                # Connection lost - print disconnection timestamp
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                print(f"â DISCONNECTED at {timestamp} - Remote turned off or out of range")
                connection_status = False

        except (BleakError, asyncio.TimeoutError) as e:
            if connection_status:
                # Only print disconnect message if we were previously connected
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                print(f"â DISCONNECTED at {timestamp} - Connection error: {e}")
                connection_status = False
            else:
                print(f"Connection error: {e}")
            
        except KeyboardInterrupt:
            print("User interrupted. Exiting...")
            reconnect_flag = False
            return
            
        if reconnect_flag:
            # Wait before trying to reconnect
            print(f"Will try to reconnect in 5 seconds. Press Ctrl+C to exit.")
            try:
                await asyncio.sleep(5)
            except KeyboardInterrupt:
                print("User interrupted. Exiting...")
                reconnect_flag = False

# Bluetooth scanning logic to find the LEGO remote
async def scan_for_remote():
    print("Scanning for LEGO 88010 Remote...")
    devices = await BleakScanner.discover(timeout=10.0)

    for d in devices:
        if d.name and ("Handset" in d.name or "LEGO" in d.name):
            print(f"Found remote: {d.name} [{d.address}]")
            with open(ADDRESS_FILE, "w") as f:
                f.write(d.address)
            return d.address

    print("Remote not found.")
    return None

# Program entry point
async def main():
    global reconnect_flag, bluetooth_already_reset
    address = None
    
    # Only reset once at the very beginning
    if not bluetooth_already_reset:
        print("Initial Bluetooth reset to clear any zombie connections...")
        try:
            import subprocess
            subprocess.run(["sudo", "systemctl", "restart", "bluetooth.service"], 
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
            await asyncio.sleep(2)
            bluetooth_already_reset = True
            print("Bluetooth reset complete")
        except Exception as e:
            print(f"Warning: Could not reset Bluetooth: {e}")
    
    # Try loading saved address (from previous run)
    if os.path.exists(ADDRESS_FILE):
        with open(ADDRESS_FILE, "r") as f:
            address = f.read().strip()
        print(f"Trying saved address: {address}")

        try:
            await connect_and_listen(address)
            return
        except Exception as e:
            print(f"Failed to connect with saved address: {e}")
            
            # Try scanning instead
            print("Trying to scan for the remote...")

    # Scan for remote
    address = await scan_for_remote()

    if address:
        await connect_and_listen(address)
    else:
        print("Unable to find remote. Please turn it on and try again.")
        
        # If we didn't find it, start a loop that periodically scans until we find it
        while reconnect_flag:
            try:
                print("Will try scanning again in 5 seconds. Press Ctrl+C to exit.")
                await asyncio.sleep(5)
                address = await scan_for_remote()
                if address:
                    await connect_and_listen(address)
                    break
            except KeyboardInterrupt:
                print("User interrupted. Exiting...")
                break

def set_button_callback(callback):
    """Set a callback function to handle button events"""
    global button_callback
    button_callback = callback

# Function to check if currently connected
def is_connected():
    global connection_status
    return connection_status

# Function to stop reconnection attempts (can be called from outside)
def stop_reconnecting():
    global reconnect_flag
    reconnect_flag = False

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program terminated by user")
