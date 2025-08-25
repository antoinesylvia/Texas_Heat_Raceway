from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import sqlite3
import logging
from threading import Lock
import config


import datetime
import time
import sys
import importlib


# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
DB_NAME = config.DB_NAME
NUM_LANES = config.NUM_LANES
DEFAULT_CAR_NAMES = config.DEFAULT_CAR_NAMES
HOST = config.HOST
PORT = config.PORT
TEST_MODE = config.TEST_MODE
MAX_RETRIES = config.MAX_RETRIES
RETRY_DELAY = config.RETRY_DELAY
INITIAL_RACE_NUMBER = 1

INITIAL_RACE_STATUS = 'Initialization'  # Initial state of the race when the system starts

VALID_RACE_STATUSES = [  # List of all possible race states
    'Initialization',  # Initial setup
    'Ready',           # Ready to start
    'Countdown',       # Countdown before race starts
    'Racing',          # Race in progress
    'Placement',       # Determining final positions
    'Finished',        # Race completed
    'Intermission',    # Break between races
    'Reset'            # Resetting for next race
]

# 1. Define valid state transitions
VALID_TRANSITIONS = {
    'Initialization': ['Ready'],
    'Ready': ['Countdown'],
    'Countdown': ['Racing'],
    'Racing': ['Placement'],
    'Placement': ['Finished'],
    'Finished': ['Intermission'],
    'Intermission': ['Reset'],
    'Reset': ['Initialization']
}

STATE_TIMEOUTS = {
    'Initialization': 10,  
    'Ready': 10,          
    'Countdown': 10,       # 10 seconds
    'Racing': 10,          
    'Placement': 10,       
    'Finished': 10,        
    'Intermission': 10,   
    'Reset': 10            
}

app = Flask(__name__)
socketio = SocketIO(app)

# Initialize the SQLite database connection and lock
db_lock = Lock()



current_race_number = INITIAL_RACE_NUMBER

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS race_states (
                id INTEGER PRIMARY KEY,
                status TEXT,
                start_time TEXT,
                finish_times TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS race_results (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                lane INTEGER,
                car_name TEXT,
                time REAL,
                speed REAL,
                weight REAL,
                kinetic_energy REAL,
                momentum REAL,
                race_number INTEGER,
                formatted_race TEXT,
                is_dnf INTEGER DEFAULT 0,
                is_track_record INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS races (
                id INTEGER PRIMARY KEY,
                race_number INTEGER,
                formatted_race TEXT,
                race_start_time TEXT,
                gate_id TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS component_status (
                id INTEGER PRIMARY KEY,
                timestamp TEXT,
                component TEXT,
                status TEXT,
                gate_type TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        logging.info("Database connection established and tables created if not exist.")
        return conn
    except sqlite3.Error as e:
        logging.error(f"Database error: {e}")
        return None

# Race states
race_state = {
    'status': INITIAL_RACE_STATUS,
    'start_time': None,
    'finish_times': [None] * NUM_LANES,
    'car_names': DEFAULT_CAR_NAMES.copy(),
    'last_state_change': time.time(),
    'retry_count': 0,
    'last_retry': None,
    'components_ready': False 
}

def generate_formatted_race_number():
    global current_race_number
    now = datetime.datetime.now()
    formatted_date = now.strftime("%H%M%S_%Y%m%d")
    formatted_race = f"Race_{current_race_number}_{formatted_date}"
    return formatted_race


def update_race_state(new_status, race_data=None, broadcast=True):
    """Update race state and optionally broadcast to all connected gates"""
    global race_state
    
    # Validate the state transition
    if not validate_transition(race_state['status'], new_status):
        error_msg = f"Invalid state transition from {race_state['status']} to {new_status}"
        logging.error(error_msg)
        return False
    
    # Update the server's race state
    old_status = race_state['status']
    race_state['status'] = new_status
    race_state['last_state_change'] = time.time()
    race_state['retry_count'] = 0
    race_state['last_retry'] = None
    
    # Update additional race data if provided
    if race_data:
        race_state.update(race_data)
    
    # Save to database if not in test mode
    if not TEST_MODE:
        try:
            with db_lock:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute('INSERT INTO race_states (status, start_time, finish_times) VALUES (?, ?, ?)',
                                 (race_state['status'], race_state['start_time'], str(race_state['finish_times'])))
                    conn.commit()
                    conn.close()
                    logging.info("Race state updated and committed to the database.")
        except Exception as e:
            logging.error(f"Error saving race state to database: {e}")
    
    # Broadcast the state change to all connected gates if requested
    if broadcast:
        broadcast_data = {
            'status': new_status,
            'race_number': race_state.get('race_number'),
            'formatted_race': race_state.get('formatted_race'),
            'timestamp': time.time(),
            'car_names': race_state.get('car_names', DEFAULT_CAR_NAMES),
            'countdown_duration': race_data.get('countdown_duration') if race_data else None,
            'start_time': race_state.get('start_time'),
            'finish_times': race_state.get('finish_times')
        }
        
        socketio.emit('race_state_update', broadcast_data)
        logging.info(f"Broadcasted race state change '{old_status}' -> '{new_status}' to all connected gates")
    
    







@app.route('/')
def index():
    logging.info("Rendering index.html.")
    return render_template('index.html')

def validate_transition(current_state, new_state):
    return new_state in VALID_TRANSITIONS.get(current_state, [])

def init_config_db(overwrite=False):
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                if overwrite:
                    cursor.execute('DELETE FROM config')
                
                config_module = importlib.import_module('config')
                for attr in dir(config_module):
                    if not attr.startswith("__") and not callable(getattr(config_module, attr)):
                        value = getattr(config_module, attr)
                        if overwrite:
                            cursor.execute('INSERT INTO config (key, value) VALUES (?, ?)', (attr, str(value)))
                        else:
                            cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (attr, str(value)))
                conn.commit()
                conn.close()
                logging.info(f"Configuration {'overwritten' if overwrite else 'initialized'} in database.")
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error {'overwriting' if overwrite else 'initializing'} configuration in database: {e}")

def check_for_new_config_keys():
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                config_module = importlib.import_module('config')
                for attr in dir(config_module):
                    if not attr.startswith("__") and not callable(getattr(config_module, attr)):
                        value = getattr(config_module, attr)
                        cursor.execute('INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)', (attr, str(value)))
                conn.commit()
                conn.close()
                logging.info("Checked and added any new configuration keys.")
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error checking for new configuration keys: {e}")


# Add after get_db_connection() and before the route handlers (around line 500)

def execute_query(query, params=None, fetch=False):
    """Execute a database query with optional parameters.
    
    Args:
        query (str): SQL query to execute
        params (tuple, optional): Parameters for the query
        fetch (bool, optional): Whether to fetch and return results
        
    Returns:
        list or None: Query results if fetch=True, None otherwise
    """
    conn = None
    cursor = None
    try:
        # Since your central server is using SQLite, modify the connection:
        conn = sqlite3.connect(DB_NAME, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute(query, params)
        
        result = None
        if fetch:
            result = cursor.fetchall()
        
        conn.commit()
        return result
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"Database error: {e}")
        raise
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def save_results_to_database(data):
    """Save race results data to the database.
    
    Args:
        data (dict): Race results data containing gate_id, race info, and results
    
    Returns:
        bool: Success status
    """
    try:
        # Extract data from the incoming payload
        gate_id = data.get('gate_id', 'unknown')
        race_start_epoch = data.get('race_start_epoch')
        race_number = data.get('race_number')
        formatted_race = data.get('formatted_race')
        results = data.get('results', [])
        
        # Log the incoming data
        logging.info(f"Saving results for race '{formatted_race}' from gate '{gate_id}'")
        
        # Create race record in races table
        with db_lock:
            conn = get_db_connection()
            if not conn:
                logging.error(f"Failed to establish database connection for race '{formatted_race}'")
                return False
                
            cursor = conn.cursor()
            
            # Insert race record
            race_query = """
                INSERT INTO races (race_number, formatted_race, race_start_time, gate_id)
                VALUES (?, ?, ?, ?)
            """
            race_params = (race_number, formatted_race, datetime.datetime.fromtimestamp(race_start_epoch), gate_id)
            cursor.execute(race_query, race_params)
            
            # Check for track record before inserting results
            current_record = get_track_record_from_database()
            
            # Insert each individual result
            for result in results:
                lane_num = result[0] if isinstance(result, (list, tuple)) else result.get('lane')
                place = result[1] if isinstance(result, (list, tuple)) else result.get('place')
                time_seconds = result[2] if isinstance(result, (list, tuple)) else result.get('time_seconds')
                speed_mph = result[3] if isinstance(result, (list, tuple)) else result.get('speed_mph')
                
                # Get car name from race_state
                car_name = race_state['car_names'][lane_num - 1] if lane_num <= len(race_state['car_names']) else f"Car {lane_num}"
                
                # Check if this is a new track record
                is_track_record = 0
                if place == 1 and time_seconds is not None and time_seconds >= 2.0:
                    if current_record is None or time_seconds < current_record:
                        is_track_record = 1
                        # Broadcast the new record
                        socketio.emit('track_record_update', {'track_record': time_seconds})
                        logging.info(f"New track record set: {time_seconds:.3f}s by Lane {lane_num}")
                
                # Insert into race_results - using your existing schema
                result_query = """
                    INSERT INTO race_results 
                    (timestamp, lane, car_name, time, speed, race_number, formatted_race, is_dnf, is_track_record)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                timestamp = datetime.datetime.now().isoformat()
                is_dnf = 1 if place is None else 0
                
                result_params = (
                    timestamp,
                    lane_num,
                    car_name,
                    time_seconds,
                    speed_mph,
                    race_number,
                    formatted_race,
                    is_dnf,
                    is_track_record
                )
                
                cursor.execute(result_query, result_params)
            
            conn.commit()
            conn.close()
            
        logging.info(f"Successfully saved all results for race '{formatted_race}'")
        return True
        
    except Exception as e:
        logging.error(f"Error saving race results to database: {e}", exc_info=True)
        return False

def get_track_record_from_database():
    """Retrieve the current track record from the database"""
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                # Query to find the fastest valid time (>= 2.0 seconds) across all races
                cursor.execute("SELECT MIN(time) FROM race_results WHERE time >= 2.0")
                result = cursor.fetchone()
                conn.close()
                return result[0] if result and result[0] else None
            else:
                logging.error("Failed to establish database connection")
                return None
    except Exception as e:
        logging.error(f"Error retrieving track record: {e}")
        return None







@app.route('/get_config', methods=['GET'])
def get_config():
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute('SELECT key, value FROM config')
                config_items = cursor.fetchall()
                conn.close()
                
                config_dict = {}
                for key, value in config_items:
                    if value.lower() == 'true':
                        config_dict[key] = True
                    elif value.lower() == 'false':
                        config_dict[key] = False
                    elif value.replace('.', '').isdigit():
                        config_dict[key] = float(value) if '.' in value else int(value)
                    else:
                        config_dict[key] = value
                
                return jsonify(config_dict)
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error retrieving configuration: {e}")
        return jsonify({'error': 'Failed to retrieve configuration'}), 500

@app.route('/update_config', methods=['POST'])
def update_config():
    new_config = request.json
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                for key, value in new_config.items():
                    cursor.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', (key, str(value)))
                conn.commit()
                conn.close()
                logging.info("Configuration updated successfully.")
                return jsonify({'status': 'success'})
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error updating configuration: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500



@app.route('/get_state', methods=['GET'])
def get_state():
    if TEST_MODE:
        logging.info(f"Test mode: Retrieved race state: {race_state}")
        return jsonify(race_state)
    
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM race_states ORDER BY id DESC LIMIT 1')
                state = cursor.fetchone()
                conn.close()
                if state:
                    race_state['status'], race_state['start_time'], finish_times = state[1], state[2], state[3]
                    race_state['finish_times'] = eval(finish_times)
                if race_state['status'] not in VALID_RACE_STATUSES:
                    race_state['status'] = INITIAL_RACE_STATUS
                logging.info(f"Retrieved race state: {race_state}")
                return jsonify(race_state)
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error retrieving race state: {e}")
        return jsonify({'error': 'Failed to retrieve race state'}), 500

def check_for_new_record(race_results):
    new_record = False
    with db_lock:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            for result in race_results:
                cursor.execute('SELECT MIN(time) FROM race_results WHERE lane = ?', (result['lane'],))
                best_time = cursor.fetchone()[0]
                if best_time is None or result['time'] < best_time:
                    new_record = True
                    break
            conn.close()
    return new_record

def calculate_placement(race_results):
    sorted_results = sorted(race_results, key=lambda x: x['time'])
    placements = []
    tied_lanes = []
    current_place = 1
    for i, result in enumerate(sorted_results):
        if i > 0 and result['time'] == sorted_results[i-1]['time']:
            tied_lanes.append(result['lane'])
        else:
            if tied_lanes:
                for lane in tied_lanes:
                    placements.append({'lane': lane, 'place': current_place, 'tied': True})
                tied_lanes = [result['lane']]
                current_place += len(placements)
            else:
                placements.append({'lane': result['lane'], 'place': current_place, 'tied': False})
                current_place += 1
    
    if tied_lanes:
        for lane in tied_lanes:
            placements.append({'lane': lane, 'place': current_place, 'tied': True})
    
    return placements, any(p['tied'] for p in placements)



@app.route('/save_results', methods=['POST'])
def save_results():
    global current_race_number
    if TEST_MODE:
        logging.info("Test mode: Race results not saved to database.")
        return jsonify({'status': 'success'})
    
    results = request.json
    timestamp = results['timestamp']
    race_results = results['results']
    logging.info(f"Saving race results: {race_results}")
    
    formatted_race = generate_formatted_race_number()
    
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                for result in race_results:
                    cursor.execute('''
                        INSERT INTO race_results 
                        (timestamp, lane, car_name, time, speed, weight, kinetic_energy, momentum, race_number, formatted_race) 
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        timestamp,
                        result['lane'],
                        race_state['car_names'][result['lane'] - 1],
                        result['time'],
                        result['speed'],
                        result.get('weight'),
                        result.get('kinetic_energy'),
                        result.get('momentum'),
                        current_race_number,
                        formatted_race
                    ))
                conn.commit()
                current_race_number += 1
                conn.close()
                logging.info("Race results saved to the database.")
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error saving race results: {e}")
        return jsonify({'error': 'Failed to save race results'}), 500
    
    new_record = check_for_new_record(race_results)
    placements, is_tie = calculate_placement(race_results)
    
    
    
    return jsonify({'status': 'success', 'new_record': new_record, 'placements': placements, 'is_tie': is_tie, 'formatted_race': formatted_race})

@app.route('/update_weight_and_ke', methods=['POST'])
def update_weight_and_ke():
    data = request.json
    timestamp = data['timestamp']
    lane = data['lane']
    weight = data.get('weight')
    kinetic_energy = data.get('kinetic_energy')
    momentum = data.get('momentum')

    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE race_results 
                    SET weight = ?, kinetic_energy = ?, momentum = ?
                    WHERE timestamp = ? AND lane = ?
                ''', (weight, kinetic_energy, momentum, timestamp, lane))
                conn.commit()
                conn.close()
                logging.info(f"Weight, KE, and Momentum updated for lane {lane}")
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error updating weight, KE, and Momentum: {e}")
        return jsonify({'error': 'Failed to update weight, KE, and Momentum'}), 500

    return jsonify({'status': 'success'})

@app.route('/get_records', methods=['GET'])
def get_records():
    if TEST_MODE:
        logging.info("Test mode: No records retrieved from database.")
        return jsonify([])
    
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM race_results')
                records = cursor.fetchall()
                conn.close()
                logging.info("Retrieved race records.")
                return jsonify(records)
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error retrieving race records: {e}")
        return jsonify({'error': 'Failed to retrieve race records'}), 500



def update_component_status(data=None):
    """Handle component status updates (called by both HTTP and Socket.IO)"""
    global race_state
    
    # Handle both Socket.IO data and HTTP request data
    if data is None:
        data = request.json if request else {}
    
    logging.info(f"Received component status update: {data}")
    timestamp = data['timestamp']
    components = data['components']
    gate_type = data.get('gate_type', 'unknown')
    
    if not TEST_MODE:
        try:
            with db_lock:
                conn = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    for component, status in components.items():
                        cursor.execute('INSERT INTO component_status (timestamp, component, status, gate_type) VALUES (?, ?, ?, ?)',
                                       (timestamp, component, status, gate_type))
                    conn.commit()
                    
                    cursor.execute('''
                        SELECT DISTINCT gate_type, component, status 
                        FROM component_status 
                        WHERE timestamp = (SELECT MAX(timestamp) FROM component_status)
                        GROUP BY gate_type, component
                    ''')
                    all_statuses = cursor.fetchall()
                    
                    start_gate_status = any(status[0] == 'start_gate' for status in all_statuses)
                    finish_gate_status = any(status[0] == 'finish_gate' for status in all_statuses)
                    all_ok = all(status[2] == 'OK' for status in all_statuses)
                    
                    # ✅ CHANGE: Don't auto-advance to Ready - wait for user action
                    # Store component readiness status but don't transition
                    race_state['components_ready'] = all_ok and start_gate_status and finish_gate_status
                    
                    if race_state['components_ready']:
                        logging.info("All components OK for both gates. Ready for user to start initialization.")
                        # Broadcast component readiness but stay in current state
                        socketio.emit('components_ready', {'ready': True, 'message': 'All systems ready - click START RACE to begin'})
                    else:
                        logging.info("Components not ready yet.")
                        socketio.emit('components_ready', {'ready': False, 'message': 'Waiting for all components...'})
                    
                    conn.close()
                    logging.info("Component status updated and committed to the database.")
                else:
                    raise Exception("Failed to establish database connection")
        except Exception as e:
            logging.error(f"Error updating component status: {e}")
            return {'error': 'Failed to update component status'}
    else:
        # Test mode logic - similar changes
        all_ok = all(status == 'OK' for status in components.values())
        race_state['components_ready'] = all_ok
        if all_ok:
            socketio.emit('components_ready', {'ready': True, 'message': 'All systems ready - click START RACE to begin'})
        else:
            socketio.emit('components_ready', {'ready': False, 'message': 'Waiting for all components...'})

    return {'status': 'success', 'race_state': race_state['status'], 'components_ready': race_state.get('components_ready', False)}

@app.route('/get_component_status', methods=['GET'])
def get_component_status():
    if TEST_MODE:
        logging.info("Test mode: No component status retrieved from database.")
        return jsonify({'error': 'No component status found'}), 404
    
    try:
        with db_lock:
            conn = get_db_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM component_status ORDER BY id DESC LIMIT 1')
                status = cursor.fetchone()
                conn.close()
                if status:
                    component_status = {
                        'timestamp': status[1],
                        'component': status[2],
                        'status': status[3],
                        'gate_type': status[4]
                    }
                    logging.info(f"Retrieved component status: {component_status}")
                    return jsonify(component_status)
                else:
                    return jsonify({'error': 'No component status found'}), 404
            else:
                raise Exception("Failed to establish database connection")
    except Exception as e:
        logging.error(f"Error retrieving component status: {e}")
        return jsonify({'error': 'Failed to retrieve component status'}), 500

@app.route('/reset', methods=['POST'])
def reset():
    global race_state
    
    
    
    race_state['status'] = 'Reset'
    race_state['last_state_change'] = time.time()
    race_state['retry_count'] = 0
    race_state['last_retry'] = None
    
    socketio.emit('race_state_update', race_state)
    
    
    
    logging.info("Race reset initiated. Waiting for user action to move to Initialization.")
    
    return jsonify({'status': 'success', 'message': 'Reset completed. Waiting for user action.'})

def handle_user_action(action_type=None):
    """Handle user actions (called by both HTTP and Socket.IO)"""
    global race_state
    if action_type is None:
        # For backward compatibility with any remaining HTTP calls
        action_type = request.json.get('action_type') if request else None
    
    current_state = race_state['status']
    
    # ✅ NEW: Start initialization when components are ready
    if action_type == 'start_race' and race_state.get('components_ready', False):
        if update_race_state('Initialization'):
            logging.info("User action: Started race initialization.")
            return {'status': 'success', 'new_state': 'Initialization', 'message': 'Race initialization started!'}
        else:
            return {'status': 'error', 'message': 'Failed to start initialization'}
    
    # ✅ CORRECTED: Skip intermission (goes directly to Reset, not Finished)
    elif action_type == 'skip_intermission' and current_state == 'Intermission':
        # Stop intermission audio
        
        if update_race_state('Reset'):  # ✅ CHANGED: Skip directly to Reset
            logging.info("User action: Skipped intermission, moving directly to Reset state.")
            return {'status': 'success', 'new_state': 'Reset', 'message': 'Intermission skipped - ready for next race!'}
        else:
            return {'status': 'error', 'message': 'Failed to skip intermission'}
    
    # ✅ REMOVED: No longer need reset_race action since skip_intermission goes directly to Reset
    # The natural flow is: Finished → Intermission → (skip or wait) → Reset
    
    # ✅ EXISTING: Reset to initialization (from Reset state)
    elif action_type == 'reset_to_init' and current_state == 'Reset':
        # Clear the components_ready flag so user needs to wait for components again
        race_state['components_ready'] = False
        
        if update_race_state('Initialization'):
            logging.info("User action: Transitioned from Reset to Initialization.")
            return {'status': 'success', 'new_state': 'Initialization', 'message': 'System initialized - waiting for components...'}
        else:
            return {'status': 'error', 'message': 'Failed to initialize'}
    
    # ✅ EXISTING: Start countdown (still needed for manual override)
    elif action_type == 'start_countdown' and current_state == 'Ready':
        if update_race_state('Countdown'):
            logging.info("User action: Started countdown.")
            return {'status': 'success', 'new_state': 'Countdown', 'message': 'Countdown started!'}
        else:
            return {'status': 'error', 'message': 'Failed to start countdown'}
    
    else:
        logging.warning(f"Invalid user action: {action_type} in state {current_state}")
        return {'status': 'error', 'message': f'Invalid action "{action_type}" for current state "{current_state}"'}

@app.route('/get_weather_config')
def get_weather_config():
    return jsonify({
        'api_key': config.WEATHER_API_KEY,
        'city_id': config.WEATHER_CITY_ID
    })

@socketio.on('connect')
def handle_connect(sid, environ):
    logging.info(f"Client connected: {sid}")
    
    # Send current race state to the newly connected client
    socketio.emit('race_state_update', race_state, room=sid)
    
    # Send the current track record to the newly connected client
    track_record = get_track_record_from_database()
    if track_record:
        socketio.emit('track_record_update', {'track_record': track_record}, room=sid)
        logging.info(f"Sent track record ({track_record:.3f}s) to newly connected client {sid}")
    else:
        logging.info(f"No track record found to send to client {sid}")
        socketio.emit('track_record_update', {'track_record': None}, room=sid)

@socketio.on('button_press')
def handle_button_press(data):
    action_type = data.get('action_type')
    return handle_user_action(action_type)



@socketio.on('disconnect')
def handle_disconnect():
    logging.info("Client disconnected")

@socketio.on('get_track_record')
def handle_get_track_record():
    """Handle request for current track record from a finish gate"""
    track_record = get_track_record_from_database()
    if track_record:
        logging.info(f"Sending track record: {track_record:.3f}s")
        socketio.emit('track_record_update', {'track_record': track_record}, room=request.sid)
    else:
        logging.info("No track record found")
        socketio.emit('track_record_update', {'track_record': None}, room=request.sid)

@socketio.on('gate_status_update')
def handle_gate_status_update(data):
    """Handle race state progression updates from gates"""
    global race_state, current_race_number
    
    gate_type = data.get('gate_type')
    gate_id = data.get('gate_id')
    new_status = data.get('status')
    current_state = race_state['status']
    
    logging.info(f"Gate status update: {gate_type} ({gate_id}) requesting {current_state} → {new_status}")
    
    # Define which gate can trigger which transitions
    allowed_transitions = {
        'start_gate': {
            'Ready': 'Countdown',
            'Countdown': 'Racing'
        },
        'finish_gate': {
            'Racing': 'Placement',
            'Placement': 'Finished', 
            'Finished': 'Intermission',
            'Intermission': 'Reset',
            'Reset': 'Initialization'
        }
    }
    
    # Check if this gate can make this transition
    if (gate_type in allowed_transitions and 
        current_state in allowed_transitions[gate_type] and
        allowed_transitions[gate_type][current_state] == new_status):
        
        # Special handling for Racing state (needs race info)
        race_data = {}
        if new_status == 'Racing':
            race_data = {
                'start_time': time.time(),
                'race_number': current_race_number,
                'formatted_race': generate_formatted_race_number()
            }
            current_race_number += 1
        
        # Update the race state using your existing function
        if update_race_state(new_status, race_data):
            logging.info(f"✅ State advanced: {current_state} → {new_status} (triggered by {gate_type})")
        else:
            logging.error(f"❌ Failed to advance: {current_state} → {new_status}")
    else:
        logging.warning(f"🚫 Invalid transition: {gate_type} cannot advance {current_state} → {new_status}")

# Add after line 800, after existing @socketio.on handlers:


@socketio.on('component_status_update')
def handle_component_status_socket(data):
    """Handle component status updates via Socket.IO"""
    update_component_status(data)  # ✅ Just call the function
    logging.info(f"Component status processed via Socket.IO from {data.get('gate_type', 'unknown')}")

@socketio.on('update_car_names')
def handle_update_car_names_socket(data):
    """Handle car names update via Socket.IO"""
    global race_state
    car_names = data['car_names']
    race_state['car_names'] = car_names
    
    # Broadcast to ALL clients immediately
    socketio.emit('car_names_updated', {'car_names': car_names})
    logging.info(f"Car names updated via Socket.IO: {car_names}")

@socketio.on('user_action')  
def handle_user_action_socket(data):
    """Handle user actions via Socket.IO"""
    action_type = data.get('action_type')
    result = handle_user_action(action_type)
    logging.info(f"User action '{action_type}' processed via Socket.IO")









def check_state_timeout():
    global race_state
    current_time = time.time()
    current_state = race_state['status']
    state_duration = current_time - race_state['last_state_change']
    
    if state_duration > STATE_TIMEOUTS[current_state]:
        if race_state['retry_count'] < MAX_RETRIES:
            if race_state['last_retry'] is None or (current_time - race_state['last_retry']) >= RETRY_DELAY:
                race_state['retry_count'] += 1
                race_state['last_retry'] = current_time
                logging.warning(f"State {current_state} timed out. Retry attempt {race_state['retry_count']} of {MAX_RETRIES}")
                
                retry_state(current_state)
        else:
            logging.error(f"State {current_state} timed out after {MAX_RETRIES} retry attempts. Forcing state transition.")
            
            next_state = {
                'Initialization': 'Ready',
                'Ready': 'Reset',
                'Countdown': 'Racing',
                'Racing': 'Placement',
                'Placement': 'Finished',
                'Finished': 'Intermission',
                'Intermission': 'Reset',
                'Reset': 'Initialization'
            }.get(current_state, 'Initialization')
            
            transition_to_state(next_state)

def retry_state(current_state):
    global race_state
    logging.info(f"Retrying state: {current_state}")

    if current_state == 'Initialization':
        update_component_status()
        if all(status == 'OK' for status in race_state.get('component_status', {}).values()):
            transition_to_state('Ready')
        else:
            logging.warning("Components still not ready after retry")

    elif current_state == 'Ready':
        update_component_status()
        if not all(status == 'OK' for status in race_state.get('component_status', {}).values()):
            transition_to_state('Reset')
        else:
            logging.info("Systems still ready, waiting for race start")

    elif current_state == 'Countdown':
        logging.info("Restarting countdown")
        

    elif current_state == 'Racing':
        finish_times = race_state['finish_times']
        if all(time is not None for time in finish_times):
            transition_to_state('Placement')
        else:
            logging.warning("Not all cars have finished, continuing Racing state")

    elif current_state == 'Placement':
        race_results = [{'lane': i+1, 'time': time} for i, time in enumerate(race_state['finish_times']) if time is not None]
        placements, _ = calculate_placement(race_results)
        race_state['placements'] = placements
        transition_to_state('Finished')

    elif current_state == 'Finished':
        save_results()
        transition_to_state('Intermission')

    elif current_state == 'Intermission':
        if time.time() - race_state['last_state_change'] > config.INTERMISSION_DURATION:
            transition_to_state('Reset')
        else:
            logging.info("Continuing Intermission")

    elif current_state == 'Reset':
        reset()
        transition_to_state('Initialization')

    else:
        logging.error(f"Unknown state in retry_state: {current_state}")



def transition_to_state(new_state):
    global race_state
    race_state['status'] = new_state
    race_state['last_state_change'] = time.time()
    race_state['retry_count'] = 0
    race_state['last_retry'] = None
    socketio.emit('race_state_update', race_state)
    logging.info(f"Transitioned to {new_state}")

def background_task():
    while True:
        socketio.sleep(1)
        check_state_timeout()

socketio.start_background_task(background_task)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '-config':
        init_config_db(overwrite=True)
        logging.info("Configuration reset to defaults from config.py.")
    else:
        init_config_db()
        check_for_new_config_keys()

    if TEST_MODE:
        logging.info("Starting Flask server in TEST MODE...")
    else:
        logging.info("Starting Flask server in NORMAL MODE...")
    try:
        socketio.run(app, host=HOST, port=PORT)
    except Exception as e:
        logging.error(f"Error starting Flask server: {e}")
