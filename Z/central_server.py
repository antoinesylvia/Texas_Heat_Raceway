from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import logging
from threading import Lock
import config
import datetime
import time
import sys
import importlib
from central_server_database import RaceDatabase

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

app = Flask(__name__, static_folder='templates', static_url_path='')
socketio = SocketIO(app)

# Initialize database
db = RaceDatabase(DB_NAME)

current_race_number = INITIAL_RACE_NUMBER

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
            db.save_race_state({
                'status': race_state['status'],
                'start_time': race_state['start_time'],
                'finish_times': race_state['finish_times'],
                'timestamp': time.time()
            })
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
    
    return True

@app.route('/')
def index():
    logging.info("Serving main.html as static file.")
    return app.send_static_file('main.html')

@app.route('/race_editor')
def race_editor():
    logging.info("Serving race_editor.html as static file.")
    return app.send_static_file('race_editor.html')

@app.route('/config')
def config_page():
    logging.info("Serving config.html as static file.")
    return app.send_static_file('config.html')

def validate_transition(current_state, new_state):
    return new_state in VALID_TRANSITIONS.get(current_state, [])

def init_config_db(overwrite=False):
    """Initialize configuration from config.py file"""
    try:
        config_module = importlib.import_module('config')
        db.init_config_from_file(config_module, overwrite)
        logging.info(f"Configuration {'overwritten' if overwrite else 'initialized'} in database.")
    except Exception as e:
        logging.error(f"Error {'overwriting' if overwrite else 'initializing'} configuration in database: {e}")

def check_for_new_config_keys():
    """Check for new configuration keys and add them"""
    try:
        config_module = importlib.import_module('config')
        db.init_config_from_file(config_module, overwrite=False)
        logging.info("Checked and added any new configuration keys.")
    except Exception as e:
        logging.error(f"Error checking for new configuration keys: {e}")

def get_track_record_from_database():
    """Retrieve the current track record from the database"""
    try:
        return db.get_track_record()
    except Exception as e:
        logging.error(f"Error retrieving track record: {e}")
        return None

@app.route('/get_config', methods=['GET'])
def get_config():
    """Get configuration from database"""
    try:
        config_data = db.get_config()
        return jsonify(config_data)
    except Exception as e:
        logging.error(f"Error retrieving configuration: {e}")
        return jsonify({'error': 'Failed to retrieve configuration'}), 500

@app.route('/update_config', methods=['POST'])
def update_config():
    """Update configuration in database"""
    new_config = request.json
    try:
        db.update_config(new_config)
        
        # Broadcast config changes to all connected gates
        socketio.emit('config_updated', new_config)
        logging.info(f"Configuration updated and broadcasted: {new_config}")
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logging.error(f"Error updating configuration: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/reset_config', methods=['POST'])
def reset_config():
    """Reset configuration to defaults"""
    try:
        # Reinitialize config from config.py with overwrite=True
        init_config_db(overwrite=True)
        
        # Get the reset configuration
        config_data = db.get_config()
        
        # Broadcast config reset to all connected clients
        socketio.emit('config_reset', config_data)
        logging.info("Configuration reset to defaults")
        
        return jsonify({'status': 'success', 'config': config_data})
    except Exception as e:
        logging.error(f"Error resetting configuration: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/get_state', methods=['GET'])
def get_state():
    """Get current race state"""
    if TEST_MODE:
        logging.info(f"Test mode: Retrieved race state: {race_state}")
        return jsonify(race_state)
    
    try:
        # Update race state from database
        db_state = db.get_latest_race_state()
        if db_state:
            race_state.update(db_state)
        
        if race_state['status'] not in VALID_RACE_STATUSES:
            race_state['status'] = INITIAL_RACE_STATUS
            
        logging.info(f"Retrieved race state: {race_state}")
        return jsonify(race_state)
    except Exception as e:
        logging.error(f"Error retrieving race state: {e}")
        return jsonify({'error': 'Failed to retrieve race state'}), 500

@app.route('/save_results', methods=['POST'])
def save_results():
    """Save race results to database"""
    global current_race_number
    if TEST_MODE:
        logging.info("Test mode: Race results not saved to database.")
        return jsonify({'status': 'success'})
    
    results_data = request.json
    formatted_race = generate_formatted_race_number()
    
    # Prepare race data for database
    race_data = {
        'race_number': current_race_number,
        'formatted_race': formatted_race,
        'timestamp': results_data['timestamp'],
        'results': []
    }
    
    # Convert results to database format
    for result in results_data['results']:
        race_data['results'].append({
            'lane': result['lane'],
            'time': result['time'],
            'speed': result['speed'],
            'weight': result.get('weight'),
            'kinetic_energy': result.get('kinetic_energy'),
            'momentum': result.get('momentum'),
            'car_name': race_state['car_names'][result['lane'] - 1],
            'placement': None  # Will be calculated
        })
    
    try:
        success = db.save_race_results(race_data)
        if success:
            current_race_number += 1
            logging.info("Race results saved to the database.")
            
            # Get placements and check for records
            placements = db.calculate_placements(race_data['results'])
            new_record = db.check_for_new_record(race_data['results'])
            
            return jsonify({
                'status': 'success', 
                'new_record': new_record, 
                'placements': placements, 
                'formatted_race': formatted_race
            })
        else:
            return jsonify({'error': 'Failed to save race results'}), 500
    except Exception as e:
        logging.error(f"Error saving race results: {e}")
        return jsonify({'error': 'Failed to save race results'}), 500

@app.route('/update_weight_and_ke', methods=['POST'])
def update_weight_and_ke():
    """Update weight and kinetic energy for a specific result"""
    data = request.json
    try:
        success = db.update_race_result_physics(
            timestamp=data['timestamp'],
            lane=data['lane'],
            weight=data.get('weight'),
            kinetic_energy=data.get('kinetic_energy'),
            momentum=data.get('momentum')
        )
        
        if success:
            logging.info(f"Weight, KE, and Momentum updated for lane {data['lane']}")
            return jsonify({'status': 'success'})
        else:
            return jsonify({'error': 'Failed to update weight, KE, and Momentum'}), 500
    except Exception as e:
        logging.error(f"Error updating weight, KE, and Momentum: {e}")
        return jsonify({'error': 'Failed to update weight, KE, and Momentum'}), 500

@app.route('/get_records', methods=['GET'])
def get_records():
    """Get all race records"""
    if TEST_MODE:
        logging.info("Test mode: No records retrieved from database.")
        return jsonify([])
    
    try:
        records = db.get_race_results()
        logging.info("Retrieved race records.")
        return jsonify(records)
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
    
    if not TEST_MODE:
        try:
            result = db.update_component_status(data)
            
            # Check component readiness
            all_ready = db.check_components_ready()
            race_state['components_ready'] = all_ready
            
            if all_ready:
                logging.info("All components OK for both gates. Ready for user to start initialization.")
                socketio.emit('components_ready', {'ready': True, 'message': 'All systems ready - click START RACE to begin'})
            else:
                logging.info("Components not ready yet.")
                socketio.emit('components_ready', {'ready': False, 'message': 'Waiting for all components...'})
            
            logging.info("Component status updated and committed to the database.")
            return result
        except Exception as e:
            logging.error(f"Error updating component status: {e}")
            return {'error': 'Failed to update component status'}
    else:
        # Test mode logic
        if 'components' in data and data['components']:
            all_ok = all(status == 'OK' for status in data['components'].values())
            race_state['components_ready'] = all_ok
            if all_ok:
                socketio.emit('components_ready', {'ready': True, 'message': 'All systems ready - click START RACE to begin'})
            else:
                socketio.emit('components_ready', {'ready': False, 'message': 'Waiting for all components...'})
        else:
            # No component data provided, maintain current state
            logging.debug("No component data provided in test mode")

    return {'status': 'success', 'race_state': race_state['status'], 'components_ready': race_state.get('components_ready', False)}

@app.route('/get_component_status', methods=['GET'])
def get_component_status():
    """Get latest component status"""
    if TEST_MODE:
        logging.info("Test mode: No component status retrieved from database.")
        return jsonify({'error': 'No component status found'}), 404
    
    try:
        status = db.get_component_status()
        if status:
            logging.info(f"Retrieved component status: {status}")
            return jsonify(status[-1])  # Return most recent
        else:
            return jsonify({'error': 'No component status found'}), 404
    except Exception as e:
        logging.error(f"Error retrieving component status: {e}")
        return jsonify({'error': 'Failed to retrieve component status'}), 500

@app.route('/reset', methods=['POST'])
def reset():
    """Reset race state"""
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
        if update_race_state('Reset'):  # ✅ CHANGED: Skip directly to Reset
            logging.info("User action: Skipped intermission, moving directly to Reset state.")
            return {'status': 'success', 'new_state': 'Reset', 'message': 'Intermission skipped - ready for next race!'}
        else:
            return {'status': 'error', 'message': 'Failed to skip intermission'}
    
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
    """Get weather configuration"""
    return jsonify({
        'api_key': config.WEATHER_API_KEY,
        'city_id': config.WEATHER_CITY_ID
    })

# =============================================================================
# ADVANCED STATISTICS ENDPOINTS
# =============================================================================

@app.route('/calculate_stats/<int:race_id>', methods=['GET', 'POST'])
def calculate_race_stats(race_id):
    """Endpoint to calculate advanced stats for a completed race"""
    try:
        # Optional: Get car weights from request
        car_weights = None
        if request.method == 'POST' and request.json:
            car_weights = request.json.get('car_weights')
        
        success = db.calculate_advanced_stats(race_id, car_weights)
        if success:
            stats = db.get_advanced_stats(race_id)
            return jsonify({'status': 'success', 'stats': stats})
        else:
            return jsonify({'status': 'error', 'message': 'Failed to calculate stats'}), 500
    except Exception as e:
        logging.error(f"Error calculating stats for race {race_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/get_stats/<int:race_id>')
def get_race_stats(race_id):
    """Get calculated advanced statistics for a race"""
    try:
        stats = db.get_advanced_stats(race_id)
        return jsonify(stats)
    except Exception as e:
        logging.error(f"Error retrieving stats for race {race_id}: {e}")
        return jsonify({'error': 'Failed to retrieve stats'}), 500

@app.route('/save_checkpoint_data', methods=['POST'])
def save_checkpoint_data():
    """Save checkpoint gate timing data"""
    try:
        checkpoint_data = request.json
        db.save_checkpoint_data(checkpoint_data)
        logging.info(f"Checkpoint data saved for race {checkpoint_data['race_id']}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logging.error(f"Error saving checkpoint data: {e}")
        return jsonify({'error': 'Failed to save checkpoint data'}), 500

@app.route('/save_car_weights/<int:race_id>', methods=['POST'])
def save_car_weights(race_id):
    """Save car weight data for a race"""
    try:
        car_weights = request.json.get('car_weights', {})
        db.save_car_weights(race_id, car_weights)
        logging.info(f"Car weights saved for race {race_id}")
        return jsonify({'status': 'success'})
    except Exception as e:
        logging.error(f"Error saving car weights: {e}")
        return jsonify({'error': 'Failed to save car weights'}), 500

@app.route('/get_advanced_leaderboards', methods=['GET'])
def get_advanced_leaderboards():
    """Get advanced leaderboards based on calculated physics stats"""
    try:
        leaderboards = db.get_advanced_leaderboards()
        logging.info("Retrieved advanced leaderboards")
        return jsonify(leaderboards)
    except Exception as e:
        logging.error(f"Error retrieving advanced leaderboards: {e}")
        return jsonify({'error': 'Failed to retrieve advanced leaderboards'}), 500

# =============================================================================
# GRANULAR RACE EDITING ENDPOINTS
# =============================================================================

@app.route('/get_race/<int:race_id>', methods=['GET'])
def get_race(race_id):
    """Get detailed race data for a specific race ID"""
    try:
        # Get basic race results
        race_results = db.get_race_results(race_id)
        
        # Get advanced stats if available
        advanced_stats = db.get_advanced_stats(race_id)
        
        # Get race metadata
        race_metadata = db.get_race_metadata(race_id)
        
        # Get checkpoint data if available
        checkpoint_data = db.get_checkpoint_data(race_id)
        
        # Get car weights if available
        car_weights = db.get_car_weights(race_id)
        
        race_data = {
            'race_id': race_id,
            'results': race_results,
            'advanced_stats': advanced_stats,
            'metadata': race_metadata,
            'checkpoint_data': checkpoint_data,
            'car_weights': car_weights
        }
        
        logging.info(f"Retrieved complete race data for race {race_id}")
        return jsonify(race_data)
    except Exception as e:
        logging.error(f"Error retrieving race {race_id}: {e}")
        return jsonify({'error': f'Failed to retrieve race {race_id}'}), 500

@app.route('/update_race/<int:race_id>', methods=['PUT', 'POST'])
def update_race(race_id):
    """Update race data for a specific race ID"""
    try:
        update_data = request.json
        
        # Update different components based on what's provided
        success_count = 0
        
        # Update basic race results if provided
        if 'results' in update_data:
            success = db.update_race_results(race_id, update_data['results'])
            if success:
                success_count += 1
                
        # Update metadata if provided
        if 'metadata' in update_data:
            success = db.update_race_metadata(race_id, update_data['metadata'])
            if success:
                success_count += 1
                
        # Update car weights if provided
        if 'car_weights' in update_data:
            success = db.save_car_weights(race_id, update_data['car_weights'])
            if success:
                success_count += 1
                
        # Update checkpoint data if provided
        if 'checkpoint_data' in update_data:
            success = db.update_checkpoint_data(race_id, update_data['checkpoint_data'])
            if success:
                success_count += 1
        
        logging.info(f"Updated race {race_id} - {success_count} components updated")
        return jsonify({
            'status': 'success',
            'race_id': race_id,
            'components_updated': success_count,
            'message': f'Race {race_id} updated successfully'
        })
        
    except Exception as e:
        logging.error(f"Error updating race {race_id}: {e}")
        return jsonify({'error': f'Failed to update race {race_id}'}), 500

@app.route('/update_advanced_stats/<int:race_id>', methods=['PUT', 'POST'])
def update_advanced_stats(race_id):
    """Update advanced statistics for a specific race ID"""
    try:
        stats_data = request.json
        
        # Validate that we have stats data
        if not stats_data or 'stats' not in stats_data:
            return jsonify({'error': 'No stats data provided'}), 400
            
        success = db.update_advanced_stats(race_id, stats_data['stats'])
        
        if success:
            logging.info(f"Updated advanced stats for race {race_id}")
            return jsonify({
                'status': 'success',
                'race_id': race_id,
                'message': f'Advanced stats for race {race_id} updated successfully'
            })
        else:
            return jsonify({'error': f'Failed to update advanced stats for race {race_id}'}), 500
            
    except Exception as e:
        logging.error(f"Error updating advanced stats for race {race_id}: {e}")
        return jsonify({'error': f'Failed to update advanced stats for race {race_id}'}), 500

@app.route('/get_all_races', methods=['GET'])
def get_all_races():
    """Get summary of all races for race browser/selector"""
    try:
        # Get pagination parameters
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))
        
        races = db.get_all_races_summary(page=page, per_page=per_page)
        total_races = db.get_total_race_count()
        
        return jsonify({
            'races': races,
            'pagination': {
                'current_page': page,
                'per_page': per_page,
                'total_races': total_races,
                'total_pages': (total_races + per_page - 1) // per_page
            }
        })
        
    except Exception as e:
        logging.error(f"Error retrieving all races: {e}")
        return jsonify({'error': 'Failed to retrieve races'}), 500

@app.route('/search_races', methods=['GET'])
def search_races():
    """Search races by various criteria"""
    try:
        # Get search parameters
        search_term = request.args.get('search', '')
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        has_advanced_stats = request.args.get('has_advanced_stats')
        
        races = db.search_races(
            search_term=search_term,
            date_from=date_from,
            date_to=date_to,
            has_advanced_stats=has_advanced_stats
        )
        
        return jsonify({
            'races': races,
            'search_criteria': {
                'search_term': search_term,
                'date_from': date_from,
                'date_to': date_to,
                'has_advanced_stats': has_advanced_stats
            }
        })
        
    except Exception as e:
        logging.error(f"Error searching races: {e}")
        return jsonify({'error': 'Failed to search races'}), 500

# =============================================================================
# SOCKET.IO EVENT HANDLERS
# =============================================================================

@socketio.on('connect')
def handle_connect():
    client_sid = request.sid
    logging.info(f"Client connected: {client_sid}")
    
    # Send current race state to the newly connected client
    socketio.emit('race_state_update', race_state, room=client_sid)
    
    # Send the current track record to the newly connected client
    track_record = get_track_record_from_database()
    if track_record:
        socketio.emit('track_record_update', {'track_record': track_record}, room=client_sid)
        logging.info(f"Sent track record ({track_record:.3f}s) to newly connected client {client_sid}")
    else:
        logging.info(f"No track record found to send to client {client_sid}")
        socketio.emit('track_record_update', {'track_record': None}, room=client_sid)

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

@socketio.on('component_status_update')
def handle_component_status_socket(data):
    """Handle component status updates via Socket.IO"""
    update_component_status(data)
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

@socketio.on('update_config')
def handle_update_config_socket(data):
    """Handle config updates via Socket.IO"""
    try:
        db.update_config(data)
        
        # Broadcast to ALL gates immediately
        socketio.emit('config_updated', data)
        logging.info(f"Configuration updated via Socket.IO: {data}")
    except Exception as e:
        logging.error(f"Error updating config via Socket.IO: {e}")



@socketio.on('gate_timing_event')
def handle_gate_timing_event(data):
    """Handle precise timing events from gates"""
    try:
        event_type = data.get('event_type')
        timestamp = data.get('timestamp')
        race_id = data.get('race_id')
        gate_type = data.get('gate_type')
        gate_id = data.get('gate_id')
        
        logging.info(f"Received timing event: {event_type} from {gate_type} ({gate_id}) for race {race_id}")
        
        if event_type == 'gate_opened' and gate_type == 'start_gate':
            # Store the official race start time
            logging.info(f"Race {race_id} officially started at {data.get('formatted_time')} (timestamp: {timestamp})")
            
            # Update race_state with the precise start time
            global race_state
            race_state['start_time'] = timestamp
            race_state['race_number'] = race_id
            race_state['formatted_race'] = data.get('formatted_race')
            
            # Save to database
            try:
                db.save_race_start_time(race_id, timestamp, data)
                logging.info(f"Race start time saved to database for race {race_id}")
            except Exception as db_error:
                logging.error(f"Error saving race start time to database: {db_error}")
            
            # Broadcast to all other components (finish gate, web UI, etc.)
            socketio.emit('race_started', {
                'race_id': race_id,
                'start_time': timestamp,
                'formatted_time': data.get('formatted_time'),
                'formatted_race': data.get('formatted_race'),
                'milliseconds': data.get('milliseconds')
            })
            
            logging.info(f"Broadcasted race_started event to all connected clients")
            
        elif event_type == 'car_finished' and gate_type == 'finish_gate':
            # Handle finish gate timing (if you add this later)
            lane = data.get('lane')
            finish_time = data.get('finish_time')
            logging.info(f"Car in lane {lane} finished at {finish_time} for race {race_id}")
            
            # You could add finish time handling here
            
        elif event_type == 'checkpoint_passed' and gate_type == 'checkpoint_gate':
            # Handle checkpoint gate timing (for future checkpoint gates)
            lane = data.get('lane')
            checkpoint_time = data.get('checkpoint_time')
            logging.info(f"Car in lane {lane} passed checkpoint at {checkpoint_time} for race {race_id}")
            
            # Save checkpoint data
            try:
                db.save_checkpoint_data({
                    'race_id': race_id,
                    'lane': lane,
                    'checkpoint_time': checkpoint_time,
                    'checkpoint_position': data.get('checkpoint_position'),
                    'speed_at_checkpoint': data.get('speed_at_checkpoint'),
                    'timestamp': timestamp
                })
                logging.info(f"Checkpoint data saved for race {race_id}, lane {lane}")
            except Exception as db_error:
                logging.error(f"Error saving checkpoint data: {db_error}")
        
        else:
            logging.warning(f"Unknown timing event: {event_type} from {gate_type}")
            
    except Exception as e:
        logging.error(f"Error handling gate timing event: {e}")
        logging.error(f"Data received: {data}")


# =============================================================================
# BACKGROUND TASKS AND TIMEOUT HANDLING
# =============================================================================

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
        try:
            placements = db.calculate_placements(race_results)
            race_state['placements'] = placements
            transition_to_state('Finished')
        except Exception as e:
            logging.error(f"Error calculating placements: {e}")

    elif current_state == 'Finished':
        transition_to_state('Intermission')

    elif current_state == 'Intermission':
        if time.time() - race_state['last_state_change'] > config.INTERMISSION_DURATION:
            transition_to_state('Reset')
        else:
            logging.info("Continuing Intermission")

    elif current_state == 'Reset':
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

# =============================================================================
# APPLICATION STARTUP
# =============================================================================

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