# Texas Heat Raceway - Automated Diecast Racetrack System

# Index
- [Project Overview](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#project-overview)
- [Project - Setup Instructions](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#project---setup-and-deployment)
- [Key Benefits](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#key-benefits)
- [System Integration and Architecture](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#system-integration-and-architecture)
- [Software](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#software)
- [Hardware](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#hardware)
- [Hardware Setup Instructions](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#hardware-setup-instructions)
- [Why We Chose the I2C / Stemma QT Ecosystem](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#why-we-chose-the-i2c--stemma-qt-ecosystem)
- [Network](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#network-1)
- [Network Setup Instructions](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#network-setup-instructions)
- [Error Handling and Logging](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#error-handling-and-logging)
- [Troubleshooting](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#troubleshooting)
- [Maintenance](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#maintenance)
- [Race Event Management and Timing System](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#race-event-management-and-timing-system)
- [API Endpoints (Central Server)](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#api-endpoints-central-server)
- [WebSocket Events](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#websocket-events)
- [Future Enhancements](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#future-enhancements)
- [License](https://github.com/antoinesylvia/Texas_Heat_Raceway/blob/main/README.md#license)


# Project Overview

![Texas Heat Raceway in Action](https://github.com/antoinesylvia/Texas_Heat_Raceway/raw/54fa975025f74245992fad0b8fe581977904259c/zPics/20240816_225830.jpg)

This project implements an automated 6 lane racetrack system for diecast vehicles 1/64 scale, featuring real-time race management, result tracking, audio-visual feedback and more. The track operates outdoors under a covered roof in Dallas, Texas. The system is comprised of:
- Automated start gate (using Lego motors which uses a Raspberry Pi Build HAT)
- Checkpoint gate (bottom of the initial launch incline, powered via a Raspberry Pi)
- Finish gate with light sensors (powered by a Tiny Lenovo ThinkCentre, but can be swapped out for a Pi)
- Checkpoint gate (optional) with light sensors (powered by a Raspberry Pi)
- Central server (serves as the brain of the operation, handles the coordination and race event state between the start gate and finish gate)
- Audio manager (plays various sounds based on race state) 
- Web control interface ran locally (main dash and configuration options)

The development of this project has a key secondary benefit: creating an engaging system that can teach children about science. The following phases will be integrated into our main dashboard as they are completed:

- Phase 1: Measurement of time, speed, and distance. [Currently Testing]
- Phase 2: Analysis of gravitational acceleration (incline drop) and linear acceleration (straightaway between checkpoint and finish gate). [Planned]
- Phase 3: Exploration of potential energy, work done, power, force, and g-force. [Planned]
- Phase 4: Investigation of energy efficiency, coefficient of restitution, heat generation, impulse and jerk, and terminal velocity. [Planned]
---------
Other Notables

Database Management:
- SQLite database for storing race results and component statuses
- Automatic creation of necessary tables on first run
- Queries for detecting new records and managing race history

Cross-Platform Compatibility:
- Use of os.path.join for file path management
- Pygame for cross-platform audio playback
- Web interface for platform-independent race monitoring and control

Temperature and Humidity Monitoring:
   - Weather information section that fetches and displays this data on our dashboard via a periodic OpenWeatherMap API call.

# Project - Setup Instructions
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure `config.py` for your environment
4. Run the central server: `python app.py`
5. Start the finish gate script: `python finish_gate.py`
6. Start the start gate script: `python start_gate.py`
7. Access the web interface at `http://localhost:5000` (or configured HOST:PORT)

-----------------------------
#### Order of Opening Programs
1. Central Server
2. Finish Gate
3. Start Gate
4. Checkpoint Gate

This order ensures that the central server is ready to receive connections from both gates.

# Key Benefits
![Texas Heat Raceway Setup](https://github.com/antoinesylvia/Texas_Heat_Raceway/raw/f776e179d2016afa6b6089f81d7a35401d6e4603/zPics/20240816_225454.jpg)
## System
1. Modular design with clear separation of concerns
2. Real-time updates and communication
3. Scalable architecture for future enhancements
4. Interactive web-based user interface
5. Robust race state management
6. Synchronized audio-visual feedback
7. Flexible testing and deployment options
8. Centralized timing to ensure consistent measurements across all lanes
9. Minimal latency for near real-time timing accuracy

## Network
- Minimized network latency for time-critical operations
- Isolated network for enhanced security and reliability
- Eliminates dependency on external network infrastructure

## Configuration 
- Centralized parameter management
- Reduced risk of cross-component inconsistencies
- Easy race setup and behavior adjustments
- Enabled test mode for component isolation
- Simplified multi-environment deployment

# System Integration and Architecture
- Central Server coordinates all components and maintains race state
- Finish Gate reports to and receives instructions from Central Server
- Start Gate manages race initiation and reports to Central Server
- Checkpoint Gate reports to Central Server
- Web Interface provides real-time updates and user interaction
- Audio Manager syncs with Central Server for state-appropriate audio cues

# Software

## System Components

### 1. Central Server (central_server.py)
- **Core Functionality**: Main controller for the entire system (all of the codebase flows through this) 
- **Key Features**:
  - Centralized race timing authority
  - Race state management using `VALID_RACE_STATUSES`
  - Database operations with `DB_NAME`
  - RESTful API endpoints
  - Real-time communication via Socket.IO (`HOST`, `PORT`)
  - Initialization with `INITIAL_RACE_STATUS`
  - Plays welcome sound on startup
  - Handles new record and tie detection
  - Manages component status updates from both gates
  - Ensures minimal latency and near real-time timing

### 2. Finish Gate (finish_gate.py)
- **Core Functionality**: Handles race finish detection and reporting
- **Key Features**:
	- Adaptive light sensor-based finish detection with multiple modes:
		- Static threshold (LIGHT_SENSOR_THRESHOLD)
		- Percentage-based light reduction (LIGHT_REDUCTION_PERCENTAGE)
	- Dynamic threshold using statistical analysis
	- Configurable detection method via USE_ADAPTIVE_THRESHOLD and USE_DYNAMIC_THRESHOLD
	- Continuous ambient light monitoring and baseline calibration
	- Result reporting to central server (CENTRAL_SERVER_URL)
	- LED and display management (SCREEN_WIDTH, SCREEN_HEIGHT, FULLSCREEN)
	- Speed calculations using TRACK_LENGTH_INCHES
	- Race timeout handling (TIMEOUT_DURATION)
	- Standalone testing mode (INITIAL_RACE_IN_PROGRESS)
	- Visual indication of winners and ties on Waveshare display
	- Precision finish detection to ensure accurate crossing detection
	- Time measured using thousandths of a second (milliseconds) precision
	- Photo finish capability using arcade buttons for close races
	- Automatic calibration before each race (BASELINE_SAMPLES)
	- Robust error handling and component status reporting
	- LED and button mapping tests for setup verification
	- Real-time updates and race state management
	- Flexible configuration options in config.py
	- Support for multi-lane racing (up to 6 lanes)
	- Integration with I2C multiplexer for multiple sensors and LEDs
	- Pygame-based graphical interface for result display
	- Socket.IO integration for real-time communication with the central server
		- Finish Gate Threshold Behavior:
			- If USE_ADAPTIVE_THRESHOLD is False: System uses the static LIGHT_SENSOR_THRESHOLD value.
			- If USE_ADAPTIVE_THRESHOLD is True and USE_DYNAMIC_THRESHOLD is False: #   System uses the percentage-based light reduction method (LIGHT_REDUCTION_PERCENTAGE).
			- If both USE_ADAPTIVE_THRESHOLD and USE_DYNAMIC_THRESHOLD are True: System uses a dynamic threshold calculation (mean - (sensitivity * standard deviation)).
			- BASELINE_SAMPLES determines how many recent light readings are used to calculate the baseline light level. Higher values make the system more stable but slower to adapt.
			- This sampling happens automatically and quickly before each race and between races.

### 3. Start Gate (start_gate.py)
- **Core Functionality**: Manages race start procedures and initial countdown
- **Key Features**:
  	- Control of start gate mechanism using Lego Technic Motor via Raspberry Pi Build HAT
  	- LED countdown sequence provides visual cues synchronized with audio countdown
  	- Countdown sequence management with LED feedback
  	- Communication with central server for race initiation and synchronization
  	- User input handling for race start and reset via arcade buttons
  	- Component status reporting to central server
  	- Configurable motor positions and speed for consistent start gate operation
  	- Synchronized start to ensure all lanes start timing simultaneously
  
### 4. Web Interface (main.html | config.html | tourney_bracketbuster.html | tourney_faceoff.html )
- **Core Functionality**: User interfaces for advanced race management and monitoring. Below is a list of **key features**:

---------------------

- **main.html**:
  	- Real-time race status and results display (`race_state_update socket` event)
  	- Component health monitoring with visual indicators (`components` state)
	- Interactive car name management for `NUM_LANES` with automatic server updates
	- Live weather data display using `weatherApiKey` and `weatherCityId`
	- Responsive dark/light mode toggle (`isDarkMode state`)
	- Dynamic calculation of kinetic energy and momentum based on car weight and speed
	- Real-time leaderboard updates with winner highlighting (`leaderboard` state)
	- Comprehensive race information display (`raceInfo` state: `raceNumber`, `trackState`, `componentStatus`)
	- Socket.IO connection to central server (`CENTRAL_SERVER_URL`) for instant updates
    
 
- **config.html**:
  	- Dynamic configuration management with real-time updates: Allows instant modification of system settings without page reload (`handleConfigChange` function)
  	- Comprehensive settings for Finish Gate: Manages crucial race parameters including track length and timeout duration (`TRACK_LENGTH_INCHES` and `TIMEOUT_DURATION`).
 	- Adaptive threshold configuration for light sensors: Provides flexible light detection options for varying race conditions (`USE_ADAPTIVE_THRESHOLD`, `USE_DYNAMIC_THRESHOLD`).
 	- Waveshare screen settings management: Controls display parameters for the race visualization screen (`SCREEN_WIDTH`, `SCREEN_HEIGHT`, `FULLSCREEN`).
	- Central server configuration options: Configures core server settings including database, lanes, and retry mechanisms (`DB_NAME`, `NUM_LANES`, `MAX_RETRIES`, `RETRY_DELAY`).
	- Weather API integration settings: Enables real-time weather data fetching for race conditions (`WEATHER_API_KEY`, `WEATHER_CITY_ID`).
  	- Responsive dark/light mode toggle: Offers user-preferred viewing experience with theme switching (`isDarkMode` state).
  	- Configuration reset functionality with confirmation: Allows reverting to default settings with user verification (`resetConfig` function).
  	- Persistent configuration storage with database integration: Ensures settings are saved and retrievable across sessions (`saveConfig` function).
      

- **tourney_bracketbuster.html**:
	- Dynamic tournament bracket generation based on `racerCount`: Supports 2, 4, or 8 racers with automatic matchup creation and progression through rounds.
	- Real-time score tracking and winner determination: Manages 3 heats per round with point-based scoring system (`handleResultChange`, `getWinner` functions).
	- Automatic advancement of winners to next rounds: Updates bracket and progresses winning racers in real-time (advanceWinner, `advanceToNextRound` functions).
	- Interactive racer naming system with real-time updates: Allows dynamic participant management throughout the tournament (`handleCarNameChange`, `RacerList` component).
	- Responsive design with dark/light mode toggle: Ensures optimal viewing experience across devices (`isDarkMode` state, `toggleTheme` function).
	- Detailed race statistics including highest score, average score, and total points: Provides comprehensive performance metrics for each racer (`getHighestScore`, `getAveragePoints`, `getTotalPoints` functions).
	- Visual highlighting of leading cars in race tables: Offers clear visual cues for current standings (`getLeadingCars` function).
	- Tournament bracket visualization with round progression: Displays real-time tournament status and matchups (`TournamentBracket` component).
	- Confetti celebration effect for tournament champion: Enhances the winning moment with visual celebration (`ReactConfetti` component).
        

- **tourney_faceoff.html**:
  	- Dynamic scoring system with real-time updates: Manages 3 heats per round for 2-6 racers, instantly calculating rankings based on finishing positions (`handleResultChange` function).
  	- Automatic tiebreaker detection and additional heat generation: Identifies point ties after 3 heats and initiates a 4th sudden death heat (`checkForTiebreaker` function).
  	- Flexible racer count management: Allows adjustment between 2, 4, or 6 participants with dynamic UI updates (`handleRacerCountChange` function).
  	- Live leaderboard with ordinal ranking: Displays real-time standings with 1st, 2nd, 3rd place designations (`getLeaderboard` and `getOrdinalRank` functions).
  	- Interactive data visualization using Chart.js: Presents a line chart showing each racer's point progression across heats (`updateChart` function).
  	- Comprehensive statistics including highest score, average score, and total points: Offers detailed performance metrics for each racer (`getHighestScore`, `getAveragePoints`, `getTotalPoints` functions).
  	- Undo/Redo functionality for all actions: Provides tournament management flexibility with action reversal and restoration (`undo`, `redo` functions with `history` state).
  	- Data persistence with local storage and import/export capabilities: Ensures tournament data can be saved, loaded, and transferred between sessions (`exportData`, `importData` functions).
  	- Responsive design with dark/light mode toggle: Adapts to various screen sizes and offers user-preferred viewing modes (`isDarkMode` state, `toggleDarkMode` function).

  -----------------------

### 5. Audio Manager (audio_manager.py)
- **Core Functionality**: Manages race-state specific audio playback
- **Key Features**:
  	- State-based audio selection from `VALID_RACE_STATUSES`
  	- Threaded audio playback
  	- Race state transition audio cues
  	- Handles special event sounds (new record, tie)
  	- Cross-platform compatibility for audio file paths
  	- Uses pygame for cross-platform audio playback
  	- Audio files are organized in state-specific folders for easy management
  	- Special events (new records, ties) have dedicated audio cues
  	- Welcome sound plays on Central Server startup

### 6. Configuration (config.py, leverage by config.html & SQLite database (Central Server))
- **Core Functionality**: Centralized system configuration
- **Key Features**:
  	- Defines all system-wide constants and settings
  		- Enables easy system behavior adjustments
  		- Facilitates test mode and deployment configurations
  		- Can be retrieved through an API endpoint once imported by the Central Server (on startup)
		- Dynamic Web Interface: A user-friendly web interface for viewing and modifying configuration settings in real-time, without the need to restart the application.
		- Database-Driven Configuration: All configuration values are stored in a SQLite database, allowing for persistent changes and easy retrieval across application restarts.
		- Dual-Source Configuration:
			- config.py serves as the initial template and fallback for default values if a "reset" is called. 
			- The database acts as the source of truth once the config.py file is imported, reflecting the most up-to-date configuration.
		- Flexible Initialization Options:
			- Automatic Database Initialization: On first run, the system automatically populates the database with default values from config.py, ensuring a smooth setup process.
			- Command-Line Reset: Option to reset the database to default values from config.py using a command-line argument (e.g., python central_server.py -config).
		- Adaptive Configuration Management:
			- Automatic detection and addition of new configuration keys from config.py on each application boot, ensuring backwards compatibility and easy integration of new features.
		- Real-Time Updates: Changes made through the web interface are immediately reflected in the running application, providing instant feedback and eliminating the need for manual restarts.

-----------------------------

#### Initialization Process (1st run and subsequent runs)
1. Central server starts and enters the 'Initialization' state.
2. Finish gate connects and reports its component status.
3. Start gate connects and reports its component status.
4. Once both gates have reported OK status, the central server transitions to the 'Ready' state.
5. The start gate then waits for user input (button press) to begin the race.

For subsequent runs, the reset button is used to return to the 'Initialization' state and begin this process again.

# Hardware 

## System Components

### Start Gate Setup (Setup 1 of 4)
- Main Controller: Raspberry Pi 5
- Motor Controller: Raspberry Pi Build HAT
- Microcontroller: Adafruit QT Py - SAMD21 Dev Board with STEMMA QT
- I2C Multiplexer: Adafruit PCA9548 8-Channel STEMMA QT / Qwiic Multiplexer
- User Input: Adafruit LED Arcade Button 1x4 - STEMMA QT I2C Breakout
- Visual Indicator: SparkFun Qwiic LED Stick APA102C (10 RGB LEDs)
- Motor: Lego Technic Motor for start gate mechanism

### Checkpoint Gate Setup (Setup 2 of 4)
- Main Controller: Raspberry Pi 5
- Microcontroller: SparkFun Qwiic / STEMMA QT HAT for Raspberry Pi
- I2C Multiplexer: Adafruit PCA9548 8-Channel STEMMA QT / Qwiic Multiplexer
- Light Sensors: 6x Adafruit BH1750 Light Sensors

### Finish Gate Setup (Setup 3 of 4)
- Main Controller: Lenovo ThinkCentre M920q Tiny
- Microcontroller: Adafruit QT Py - SAMD21 Dev Board with STEMMA QT
- I2C Multiplexer: Adafruit PCA9548 8-Channel STEMMA QT / Qwiic I2C multiplexer
- Light Sensors: 6x Adafruit BH1750 Light Sensors
- LED Strip: USB 5v LED strip (6000k cold white color)
- Display: Waveshare 11.9inch Capacitive Touch Screen LCD (320x1480)
- LED Indicators: Adafruit PCF8575 I2C 16 GPIO Expander Breakout

### Central Server (Setup 4 of 4)
- Hardware: Lenovo ThinkCentre M920q Tiny (shared with Finish Gate setup)

# Hardware Setup Instructions
1. Connect all I2C devices to their respective multiplexers
2. Ensure proper power supply to all components
3. Connect Ethernet cables from Finish Gate and Start Gate setups to each other (if you don't want to use a router and not using a checkpoint gate). If using a start gate, checkpoint gate and finish gate, connect all 3 to a router via an ethernet cord.  
4. Position light sensors and LED indicators at the finish line
5. Mount the Waveshare display for clear visibility
6. Install the start gate mechanism with the Lego Technic Motor

# Why We Chose the I2C / STEMMA QT Ecosystem
Our project leverages the I2C / STEMMA QT ecosystem for several key reasons:

- Modularity: Easily connect, disconnect, and swap components.
- Simplicity: Reduces wiring complexity and pin usage on main controllers.
- Expandability: I2C multiplexers allow connection of numerous devices.
- Consistency: Similar components across setups improve maintainability.
- Educational Value: Exposes users to industry-standard technologies.
- Plug-and-Play: STEMMA QT connectors enable quick, foolproof assembly.
- Scalability: Easily add or remove components as the project evolves.
- Reduced Errors: Standardized connections minimize wiring mistakes.
- Community Support: Wide adoption means extensive documentation and community resources.

This ecosystem provides a robust, flexible foundation for our racetrack system, supporting both current functionality and future expansions while facilitating hands-on STEM learning.

# Network

## Network Setup Instructions

### Direct Connection
- The Raspberry Pi (Start Gate) and Lenovo ThinkCentre (Central Server/Finish Gate) are connected via a regular Ethernet cable for low-latency, direct communication.
- Modern Ethernet ports support Auto-MDI/MDIX, which automatically detects and configures the connection type (straight-through or crossover) needed for the link.
- Static IP addresses are assigned to both devices to ensure consistent connectivity.

### Configuration
- **Raspberry Pi**: 192.168.1.2 (example IP)
- **Lenovo ThinkCentre**: 192.168.1.1 (example IP)
- **Subnet mask**: 255.255.255.0
- **No default gateway needed** for this direct connection

# Testing
- Set `INITIAL_RACE_IN_PROGRESS = True` in `config.py` for isolated finish gate testing
- Use `TEST_MODE = True` for full system testing without physical hardware
- Implement specific test modes for Start Gate mechanism and countdown sequence
- `sensor_calibration.py` calibration tool doubles as a testing utility for finish detection
	- Real-time display of light levels for all 6 sensors
  	- Simulates race finishes to test calibration accuracy
  	- Allows dynamic adjustment of `LIGHT_SENSOR_THRESHOLD`
  	- Percentage-based light reduction measure (LIGHT_REDUCTION_PERCENTAGE)
  	- Provides feedback on percent light coverage on car roll over. 
  	- Helps fine-tune sensor sensitivity for accurate finish detection
  	- Interactive threshold adjustment for optimal finish detection 	

# Error Handling and Logging
- Comprehensive error handling across all components
- Detailed logging for troubleshooting and system monitoring
- Component status updates are regularly sent to the Central Server

# Troubleshooting
- Check console outputs for error messages and logs
- Use the web interface to monitor system status and component health
- For audio issues, verify system volume and presence of audio files
- Run sensor calibration tool if finish detection becomes unreliable

# Maintenance
- Regularly check and clean light sensors for accurate detection
- Ensure all cable connections are secure
- Update firmware on microcontrollers as needed
- Periodically test and calibrate the start gate mechanism
- Run sensor calibration tool to maintain optimal `LIGHT_SENSOR_THRESHOLD`/ `LIGHT_REDUCTION_PERCENTAGE`

# Race Event Management and Timing System

## Race Timing System
1. Race Initiation: Start Gate lifts the lever and signals the Central Server
2. Timer Start: Central Server starts the race timer
3. Ongoing Race: Central Server continues timing
4. Finish Detection: Finish Gate detects cars crossing finish line
5. Finish Time Recording: Central Server records finish times via Finish Gate (using thousandths of a second (milliseconds) precision)
6. Race Completion: All cars finish or timeout is reached
7. Results Processing: Central Server calculates final times, positions, and speeds
8. Results Distribution: Web Interface displays results, database stores them

## Race State Management
- The system uses a state machine approach with defined valid transitions between states.
- States include: Initialization, Ready, Countdown, Racing, Placement, Finished, Intermission, and Reset.
- Each state transition triggers specific actions and audio cues.
- All races completed are captured and numbered sequentially in the database. 
- State transition edge cases: Timeout logic to ensure no state persists for too long.

## Race State Event List 
1. Initialization: Perform checks on all components to ensure readiness.
2. Ready: All systems are ready for the race to begin.
3. Countdown: Initiate the countdown sequence: 3, 2, 1.
4. Racing: The gate is activated, and cars are moving down the track.
5. Placement: Determine the order of finish from 1st to 6th; cars that don't finish within 3 seconds are marked as crashed or non-participating.
6. Finished: The race has concluded.
7. Intermission: Await reset to prepare for the next race.
8. Reset: Reset the track, cars, and system for the next race.

## API Endpoints (Central Server)

#### `/` (GET)
- **Description**: Renders the main HTML page for the web interface.
- **Function**: `index()`

#### `/get_config` (GET)
- **Description**: Returns the configuration values needed by the start gate.
- **Function**: `get_config()`

#### `/update_state` (POST)
- **Description**: Updates the race state and emits the new state to connected clients. If the state is 'Finished', it automatically transitions to 'Intermission'.
- **Function**: `update_state()`

#### `/get_state` (GET)
- **Description**: Retrieves the current race state from the database (or returns a mock state in test mode).
- **Function**: `get_state()`

#### `/save_results` (POST)
- **Description**: Saves race results to the SQLite database and checks for new records or ties, playing appropriate sounds.
- **Function**: `save_results()`

#### `/update_weight_and_ke` (POST)
- **Description**: Updates the weight and kinetic energy of a car for a given timestamp and lane in the race results.
- **Function**: `update_weight_and_ke()`

#### `/get_records` (GET)
- **Description**: Retrieves all race records from the SQLite database (or returns an empty list in test mode).
- **Function**: `get_records()`

#### `/update_car_names` (POST)
- **Description**: Updates the car names for the race.
- **Function**: `update_car_names()`

#### `/update_component_status` (POST)
- **Description**: Updates the status of race components (start and finish gates) and potentially transitions the race state if all components are OK.
- **Function**: `update_component_status()`

#### `/get_component_status` (GET)
- **Description**: Retrieves the latest component status from the database (or returns an error in test mode).
- **Function**: `get_component_status()`

#### `/reset` (POST)
- **Description**: Resets the race state to 'Reset', stops any playing audio, and notifies clients of the state change.
- **Function**: `reset()`

#### `/user_action` (POST)
- **Description**: Handles user actions to transition from 'Reset' to 'Initialization' or from 'Ready' to 'Countdown'.
- **Function**: `handle_user_action()`

#### `/get_weather_config` (GET)
- **Description**: Fetch weather configuration
- **Function**: `get_weather_config()`

#### `/update_config` (POST)
- **Description**: Updates configuration values in the database.
- **Function**: update_config()

#### `/reset_config` (POST)
- **Description**: Resets all configuration values to defaults from config.py.
- **Function**: reset_config()

# WebSocket Events

#### `button_press` (SocketIO event)
- **Description**: Handles button press actions to trigger user actions.
- **Function**: `handle_button_press()`

#### `connect` (SocketIO event)
- **Description**: Handles a new client connection and emits the current race state to the connected client.
- **Function**: `handle_connect()`

#### `disconnect` (SocketIO event)
- **Description**: Handles a client disconnection.
- **Function**: `handle_disconnect()`

# Future Enhancements

1. Improved Data Analytics: Enhance the existing analytics dashboard with historical trends, comparison tools, and visual data representations.

2. Data model integration: Integrate Google's image recognition API for automatic car identification and naming. We would also fine tune a model and use our local compute resources.

3. Text to Speech: TBD

4. Drone Coverage: Cover the race with a mini drone.

5. Implementation of formulas for phase 2, 3 and 4: Requires an additional checkpoint gate (at the end of an incline) then we'll be able to measure Gravitational Acceleration and (linear) Acceleration. This would open the doors to be able to calculate outputs for force, potential energy, work done, power, g-force., friction force, air resistance ,net force, deceleration and more. 

# License
This project is licensed under the MIT License - see the LICENSE.md file for details.

