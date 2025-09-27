# database.py
import sqlite3
import logging
import json
import time
from threading import Lock
from contextlib import contextmanager

class RaceDatabase:
    def __init__(self, db_name):
        self.db_name = db_name
        self.lock = Lock()
        self.init_tables()
        
        # Initialize with default values (will be overridden by config loading)
        self.TRACK_LENGTH = 24.0  # Total track length in feet
        self.INCLINE_HEIGHT = 4.0  # Height of incline in feet
        self.CHECKPOINT_DISTANCE = 18.0  # Distance from start to checkpoint in feet
        self.GRAVITY = 9.81  # m/s² (standard gravity)
        self.AIR_DENSITY = 1.195  # kg/m³ (adjusted for Irving, TX altitude ~518 ft and typical conditions)
        
        # Load configuration from database (will override defaults)
        self._load_config_values()
    
    def _load_config_values(self):
        """Load track configuration values from database config table."""
        # Try to load TRACK_LENGTH_INCHES from config and convert to feet
        track_length_inches = self.get_config('TRACK_LENGTH_INCHES')
        if track_length_inches is not None:
            try:
                self.TRACK_LENGTH = float(track_length_inches) / 12.0  # Convert inches to feet
            except (ValueError, TypeError):
                pass  # Keep default value
        
        # Try to load other physical constants from database config
        config_mapping = {
            'INCLINE_HEIGHT_FEET': 'INCLINE_HEIGHT', 
            'CHECKPOINT_DISTANCE_FEET': 'CHECKPOINT_DISTANCE',
            'GRAVITY_MS2': 'GRAVITY',
            'AIR_DENSITY_KG_M3': 'AIR_DENSITY'
        }
        
        for config_key, attr_name in config_mapping.items():
            try:
                value = self.get_config(config_key)
                if value is not None:
                    setattr(self, attr_name, float(value))
            except (ValueError, TypeError):
                # Keep default value if config value is invalid
                pass
        
        # If we loaded track length but no checkpoint distance, set a sensible default (75% of track)
        if not hasattr(self, '_checkpoint_distance_set'):
            checkpoint_distance = self.get_config('CHECKPOINT_DISTANCE_FEET')
            if checkpoint_distance is None:
                self.CHECKPOINT_DISTANCE = self.TRACK_LENGTH * 0.75  # 75% of track length
                self._checkpoint_distance_set = True
    
    def calculate_dynamic_air_density(self, temperature_k, pressure_pa, humidity_percent):
        """
        Calculate real-time air density using the moist air formula from Google's recommendation.
        
        Formula: ρ = (P_d / R_d * T) + (P_v / R_v * T)
        Where:
        - ρ = Air density (kg/m³)
        - P_d = Partial pressure of dry air (Pa)
        - P_v = Partial pressure of water vapor (Pa)
        - R_d = Specific gas constant for dry air = 287.058 J/(kg·K)
        - R_v = Specific gas constant for water vapor = 461.495 J/(kg·K)
        - T = Temperature (K)
        
        Args:
            temperature_k: Temperature in Kelvin
            pressure_pa: Atmospheric pressure in Pascals
            humidity_percent: Relative humidity as percentage (0-100)
            
        Returns:
            Air density in kg/m³
        """
        try:
            # Gas constants
            R_d = 287.058  # Specific gas constant for dry air (J/(kg·K))
            R_v = 461.495  # Specific gas constant for water vapor (J/(kg·K))
            
            # Calculate saturation vapor pressure using Magnus formula
            # Valid for -45°C to +60°C
            temp_celsius = temperature_k - 273.15
            saturation_vapor_pressure = 611.2 * (10 ** ((7.5 * temp_celsius) / (237.7 + temp_celsius)))
            
            # Calculate actual vapor pressure from relative humidity
            P_v = (humidity_percent / 100.0) * saturation_vapor_pressure
            
            # Calculate partial pressure of dry air
            P_d = pressure_pa - P_v
            
            # Calculate air density using moist air formula
            air_density = (P_d / (R_d * temperature_k)) + (P_v / (R_v * temperature_k))
            
            logging.info(f"Dynamic air density calculated: {air_density:.4f} kg/m³ "
                        f"(T={temp_celsius:.1f}°C, P={pressure_pa:.0f}Pa, H={humidity_percent:.1f}%)")
            
            return air_density
            
        except Exception as e:
            logging.error(f"Error calculating dynamic air density: {e}")
            return self.AIR_DENSITY  # Fall back to static value
    
    def get_current_air_density(self):
        """
        Get current air density - either dynamic from weather API or static value.
        Implements caching to avoid excessive API calls.
        
        Returns:
            Current air density in kg/m³
        """
        import time
        import requests
        
        # Check if dynamic air density is enabled
        use_dynamic = self.get_config('USE_DYNAMIC_AIR_DENSITY')
        if use_dynamic != 'True':
            return self.AIR_DENSITY
        
        # Check cache timestamp
        current_time = time.time()
        last_update = self.get_config('last_air_density_update')
        update_interval = float(self.get_config('AIR_DENSITY_UPDATE_INTERVAL') or 300)
        
        if last_update:
            time_since_update = current_time - float(last_update)
            if time_since_update < update_interval:
                # Use cached value
                cached_density = self.get_config('cached_air_density')
                if cached_density:
                    return float(cached_density)
        
        # Fetch current weather data from OpenWeatherMap
        try:
            weather_api_key = self.get_config('WEATHER_API_KEY')
            lat = self.get_config('IRVING_LAT') or 32.8140
            lon = self.get_config('IRVING_LON') or -96.9489
            
            if not weather_api_key:
                logging.warning("No weather API key configured, using static air density")
                return self.AIR_DENSITY
            
            # One Call API 3.0 endpoint (current weather only)
            url = "https://api.openweathermap.org/data/3.0/onecall"
            params = {
                'lat': lat,
                'lon': lon,
                'exclude': 'minutely,hourly,daily,alerts',  # Only get current data
                'units': 'metric',  # Use metric units for easier calculation
                'appid': weather_api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            weather_data = response.json()
            current = weather_data.get('current', {})
            
            # Extract required values
            temperature_k = current.get('temp', 20) + 273.15  # Convert Celsius to Kelvin
            pressure_hpa = current.get('pressure', 1013.25)  # Atmospheric pressure in hPa
            pressure_pa = pressure_hpa * 100  # Convert hPa to Pascals
            humidity = current.get('humidity', 60)  # Relative humidity percentage
            
            # Calculate dynamic air density
            dynamic_air_density = self.calculate_dynamic_air_density(
                temperature_k, pressure_pa, humidity
            )
            
            # Cache the result
            self.update_config({
                'cached_air_density': dynamic_air_density,
                'last_air_density_update': current_time,
                'last_weather_temp_c': current.get('temp'),
                'last_weather_pressure_hpa': pressure_hpa,
                'last_weather_humidity': humidity
            })
            
            logging.info(f"Updated air density from weather API: {dynamic_air_density:.4f} kg/m³")
            return dynamic_air_density
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Weather API request failed: {e}")
        except Exception as e:
            logging.error(f"Error fetching dynamic air density: {e}")
        
        # Fall back to static value if API fails
        logging.info(f"Using fallback static air density: {self.AIR_DENSITY} kg/m³")
        return self.AIR_DENSITY
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections with proper error handling"""
        conn = None
        try:
            with self.lock:
                conn = sqlite3.connect(self.db_name, check_same_thread=False, timeout=30.0)
                conn.row_factory = sqlite3.Row  # Enable column access by name
                yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logging.error(f"Database error: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    def init_tables(self):
        """Initialize all database tables"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Existing tables (keep your current structure)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS race_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_number INTEGER,
                    lane INTEGER,
                    time REAL,
                    placement INTEGER,
                    timestamp TEXT,
                    additional_data TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS component_status (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    component TEXT,
                    status TEXT,
                    gate_type TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS race_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    state TEXT,
                    race_number INTEGER,
                    additional_data TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS races (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_number INTEGER UNIQUE,
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT,
                    metadata TEXT
                )
            ''')
            
            # New tables for advanced analytics
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS checkpoint_times (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id INTEGER,
                    lane INTEGER,
                    checkpoint_position REAL,
                    checkpoint_time REAL,
                    speed_at_checkpoint REAL,
                    timestamp TEXT,
                    FOREIGN KEY (race_id) REFERENCES races (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS car_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id INTEGER,
                    lane INTEGER,
                    weight_grams REAL,
                    additional_data TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (race_id) REFERENCES races (id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS advanced_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id INTEGER,
                    lane INTEGER,
                    
                    -- Part 1: Basic measurements
                    start_to_checkpoint_speed REAL,
                    checkpoint_to_finish_speed REAL,
                    average_speed REAL,
                    distance_traveled REAL,
                    
                    -- Part 2: Acceleration data
                    acceleration_mps2 REAL,
                    gravitational_acceleration REAL,
                    measured_acceleration REAL,
                    friction_loss_acceleration REAL,
                    drag_loss_acceleration REAL,
                    effective_gravity REAL,
                    standard_gravity REAL,
                    
                    -- Part 3: Force and energy
                    force_newtons REAL,
                    potential_energy_joules REAL,
                    kinetic_energy_checkpoint REAL,
                    kinetic_energy_finish REAL,
                    work_done_joules REAL,
                    power_watts REAL,
                    g_force REAL,
                    
                    -- Part 4: Advanced calculations
                    energy_loss_rolling REAL,
                    energy_loss_total REAL,
                    coefficient_restitution REAL,
                    impulse_ns REAL,
                    jerk_mps3 REAL,
                    terminal_velocity REAL,
                    
                    -- Part 5: Efficiency metrics
                    mechanical_efficiency REAL,
                    energy_transfer_efficiency REAL,
                    coefficient_friction REAL,
                    energy_conversion_efficiency REAL,
                    momentum_change REAL,
                    momentum_kgms REAL,
                    
                    -- Part 6: Enhanced gravitational analysis
                    theoretical_gravity_component REAL,
                    gravity_efficiency_ratio REAL,
                    total_loss_acceleration REAL,
                    
                    -- Part 7: Environmental conditions
                    air_density_used REAL,
                    
                    timestamp TEXT,
                    FOREIGN KEY (race_id) REFERENCES races (id)
                )
            ''')
            
            conn.commit()
            logging.info("Database tables initialized successfully")

    # =============================================================================
    # CONFIG METHODS
    # =============================================================================
    
    def get_config(self, key=None):
        """Get configuration value(s)"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if key:
                cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
                result = cursor.fetchone()
                return result['value'] if result else None
            else:
                cursor.execute('SELECT key, value FROM config')
                return {row['key']: row['value'] for row in cursor.fetchall()}
    
    def update_config(self, config_dict):
        """Update multiple config values"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for key, value in config_dict.items():
                cursor.execute('INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)', 
                             (key, str(value)))
                
                # Update internal constants if they change
                if key == 'TRACK_LENGTH_INCHES':
                    self.TRACK_LENGTH = float(value) / 12.0  # Convert inches to feet
                elif key == 'TRACK_LENGTH':
                    self.TRACK_LENGTH = float(value)
                elif key == 'INCLINE_HEIGHT':
                    self.INCLINE_HEIGHT = float(value)
                elif key == 'CHECKPOINT_DISTANCE':
                    self.CHECKPOINT_DISTANCE = float(value)
                elif key == 'AIR_DENSITY':
                    self.AIR_DENSITY = float(value)
            
            conn.commit()
            logging.info(f"Configuration updated: {config_dict}")
    
    def init_config_from_file(self, config_module, overwrite=False):
        """Initialize config from Python config module"""
        config_dict = {}
        
        for attr in dir(config_module):
            if not attr.startswith('_'):
                value = getattr(config_module, attr)
                if isinstance(value, (str, int, float, bool)):
                    config_dict[attr] = value
        
        if overwrite:
            # Clear existing config and replace with new values
            self.update_config(config_dict)
        else:
            # Only add new keys that don't exist
            existing_config = self.get_config()
            new_config = {}
            for key, value in config_dict.items():
                if key not in existing_config:
                    new_config[key] = value
            if new_config:
                self.update_config(new_config)
        
        return config_dict

    # =============================================================================
    # RACE DATA METHODS
    # =============================================================================
    
    def save_race_results(self, race_data):
        """Save complete race results"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            race_number = race_data.get('race_number')
            timestamp = race_data.get('timestamp', time.time())
            
            # Save individual lane results
            for lane_data in race_data.get('results', []):
                cursor.execute('''
                    INSERT INTO race_results 
                    (race_number, lane, time, placement, timestamp, additional_data)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    race_number,
                    lane_data.get('lane'),
                    lane_data.get('time'),
                    lane_data.get('placement'),
                    timestamp,
                    json.dumps(lane_data.get('additional_data', {}))
                ))
            
            # Save race metadata
            cursor.execute('''
                INSERT OR REPLACE INTO races 
                (race_number, start_time, end_time, status, metadata)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                race_number,
                race_data.get('start_time'),
                race_data.get('end_time'),
                race_data.get('status', 'completed'),
                json.dumps(race_data.get('metadata', {}))
            ))
            
            conn.commit()
            logging.info(f"Race {race_number} results saved to database")
    
    def get_race_results(self, race_id=None):
        """Get race results"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if race_id:
                cursor.execute('''
                    SELECT * FROM race_results 
                    WHERE race_number = ? 
                    ORDER BY placement
                ''', (race_id,))
            else:
                cursor.execute('SELECT * FROM race_results ORDER BY race_number DESC, placement')
            
            return [dict(row) for row in cursor.fetchall()]
    
    def save_checkpoint_data(self, checkpoint_data):
        """Save checkpoint gate timing data"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT INTO checkpoint_times 
                (race_id, lane, checkpoint_position, checkpoint_time, speed_at_checkpoint, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                checkpoint_data['race_id'],
                checkpoint_data['lane'],
                checkpoint_data.get('checkpoint_position', self.CHECKPOINT_DISTANCE),
                checkpoint_data['checkpoint_time'],
                checkpoint_data.get('speed_at_checkpoint'),
                checkpoint_data.get('timestamp', time.time())
            ))
            
            conn.commit()
            logging.info(f"Checkpoint data saved for race {checkpoint_data['race_id']}, lane {checkpoint_data['lane']}")
    
    def save_car_weights(self, race_id, car_weights):
        """Save car weight data for a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for lane, weight in car_weights.items():
                cursor.execute('''
                    INSERT OR REPLACE INTO car_data 
                    (race_id, lane, weight_grams, timestamp)
                    VALUES (?, ?, ?, ?)
                ''', (race_id, lane, weight, time.time()))
            
            conn.commit()
            logging.info(f"Car weights saved for race {race_id}")

    

    def save_race_start_time(self, race_id, timestamp, timing_data):
        """Save precise race start time"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Update the race record with start time
            cursor.execute('''
                UPDATE races 
                SET start_time = ?, metadata = ?
                WHERE race_number = ?
            ''', (timestamp, json.dumps(timing_data), race_id))
            
            # Also save in a dedicated timing events table (create if needed)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS timing_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    race_id INTEGER,
                    event_type TEXT,
                    gate_type TEXT,
                    gate_id TEXT,
                    timestamp REAL,
                    formatted_time TEXT,
                    raw_data TEXT,
                    created_at REAL
                )
            ''')
            
            cursor.execute('''
                INSERT INTO timing_events 
                (race_id, event_type, gate_type, gate_id, timestamp, formatted_time, raw_data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                race_id,
                timing_data.get('event_type'),
                timing_data.get('gate_type'),
                timing_data.get('gate_id'),
                timestamp,
                timing_data.get('formatted_time'),
                json.dumps(timing_data),
                time.time()
            ))
            
            conn.commit()
            logging.info(f"Race start time and timing event saved for race {race_id}")

    # =============================================================================
    # COMPONENT STATUS METHODS
    # =============================================================================
    
    def update_component_status(self, data):
        """Update gate component status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            timestamp = data['timestamp']
            components = data['components']
            gate_type = data.get('gate_type', 'unknown')
            
            for component, status in components.items():
                cursor.execute('''
                    INSERT INTO component_status (timestamp, component, status, gate_type) 
                    VALUES (?, ?, ?, ?)
                ''', (timestamp, component, status, gate_type))
            
            conn.commit()
            logging.info(f"Component status updated for {gate_type}")
    
    def get_component_status(self, gate_type=None):
        """Get latest component status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if gate_type:
                cursor.execute('''
                    SELECT * FROM component_status 
                    WHERE gate_type = ? 
                    ORDER BY timestamp DESC LIMIT 10
                ''', (gate_type,))
            else:
                cursor.execute('''
                    SELECT * FROM component_status 
                    ORDER BY timestamp DESC LIMIT 50
                ''')
            
            return [dict(row) for row in cursor.fetchall()]

    # =============================================================================
    # PHYSICS CALCULATIONS (Based on formulas.md)
    # =============================================================================
    
    def calculate_advanced_stats(self, race_id, car_weights=None):
        """
        Calculate all advanced physics-based statistics from formulas.md
        Uses: Start gate → Checkpoint gate → Finish gate timing + Car weights
        """
        try:
            # Get all timing data for this race
            start_times = self._get_race_start_times(race_id)
            checkpoint_times = self._get_checkpoint_times(race_id)
            finish_times = self._get_finish_times(race_id)
            
            if not start_times or not finish_times:
                logging.warning(f"Insufficient timing data for race {race_id}")
                return False
            
            # Get car weights if available
            if car_weights is None:
                car_weights = self._get_car_weights(race_id)
            
            # Get current air density (dynamic if enabled, static if not)
            current_air_density = self.get_current_air_density()
            logging.info(f"Using air density for race {race_id}: {current_air_density:.4f} kg/m³")
            
            for lane in range(1, 7):  # For each lane
                if lane not in start_times or lane not in finish_times:
                    continue
                
                # =============================================================================
                # PART 1: Basic Speed and Distance Calculations
                # =============================================================================
                
                # Calculate segment velocities (v = d / t)
                if lane in checkpoint_times:
                    # With checkpoint data
                    start_to_checkpoint_time = checkpoint_times[lane] - start_times[lane]
                    checkpoint_to_finish_time = finish_times[lane] - checkpoint_times[lane]
                    
                    start_to_checkpoint_speed = self.CHECKPOINT_DISTANCE / start_to_checkpoint_time if start_to_checkpoint_time > 0 else 0
                    checkpoint_to_finish_speed = (self.TRACK_LENGTH - self.CHECKPOINT_DISTANCE) / checkpoint_to_finish_time if checkpoint_to_finish_time > 0 else 0
                else:
                    # Without checkpoint data
                    total_time = finish_times[lane] - start_times[lane]
                    start_to_checkpoint_speed = 0
                    checkpoint_to_finish_speed = self.TRACK_LENGTH / total_time if total_time > 0 else 0
                
                # Average speed (v = d / t)
                total_time = finish_times[lane] - start_times[lane]
                average_speed = self.TRACK_LENGTH / total_time if total_time > 0 else 0
                
                # Distance traveled (already known: self.TRACK_LENGTH)
                distance_traveled = self.TRACK_LENGTH
                
                # =============================================================================
                # PART 2: Acceleration Calculations
                # =============================================================================
                
                # Acceleration (a = (v_final - v_initial) / t)
                if lane in checkpoint_times and checkpoint_to_finish_time > 0:
                    acceleration = (checkpoint_to_finish_speed - start_to_checkpoint_speed) / checkpoint_to_finish_time
                else:
                    acceleration = 0
                
                # Gravitational acceleration component (will be enhanced below)
                gravitational_acceleration = self.GRAVITY  # Standard gravity (temporary)
                
                # =============================================================================
                # PART 3: Force and Energy Calculations
                # =============================================================================
                
                # Get car weight for energy calculations
                weight_kg = 0
                force_newtons = 0
                potential_energy = 0
                kinetic_energy_checkpoint = 0
                kinetic_energy_finish = 0
                work_done = 0
                power_watts = 0
                momentum_finish = 0
                
                if car_weights and lane in car_weights:
                    weight_kg = car_weights[lane] / 1000  # Convert grams to kg
                    
                    # Force (F = m * a)
                    force_newtons = weight_kg * acceleration
                    
                    # Potential Energy (PE = m * g * h)
                    potential_energy = weight_kg * self.GRAVITY * self.INCLINE_HEIGHT
                    
                    # Kinetic Energy at checkpoint (KE = 1/2 * m * v²)
                    kinetic_energy_checkpoint = 0.5 * weight_kg * (start_to_checkpoint_speed ** 2)
                    
                    # Kinetic Energy at finish (KE = 1/2 * m * v²)
                    kinetic_energy_finish = 0.5 * weight_kg * (checkpoint_to_finish_speed ** 2)
                    
                    # Work Done (W = F * d)
                    work_done = force_newtons * distance_traveled
                    
                    # Power (P = W / t)
                    power_watts = work_done / total_time if total_time > 0 else 0
                    
                    # Momentum (p = m * v)
                    momentum_finish = weight_kg * checkpoint_to_finish_speed
                
                # G-Force (G = a / g)
                g_force = acceleration / self.GRAVITY if self.GRAVITY > 0 else 0
                
                # =============================================================================
                # PART 4: Advanced Calculations
                # =============================================================================
                
                # Energy Loss - Rolling Resistance (E_loss = KE_start - KE_end)
                energy_loss_rolling = kinetic_energy_checkpoint - kinetic_energy_finish if kinetic_energy_checkpoint > kinetic_energy_finish else 0
                
                # Total Energy Loss (E_loss = PE_top - KE_end)
                energy_loss_total = potential_energy - kinetic_energy_finish if potential_energy > kinetic_energy_finish else 0
                
                # Coefficient of Restitution (simplified, e = v_final / v_initial)
                coefficient_restitution = checkpoint_to_finish_speed / start_to_checkpoint_speed if start_to_checkpoint_speed > 0 else 0
                
                # Impulse (J = F * Δt)
                impulse = force_newtons * total_time
                
                # Jerk (Jerk = Δa / Δt) - simplified calculation
                jerk = acceleration / total_time if total_time > 0 else 0
                
                # Terminal Velocity (approximation based on final speed)
                terminal_velocity = checkpoint_to_finish_speed  # Simplified
                
                # =============================================================================
                # PART 5: Efficiency Calculations
                # =============================================================================
                
                # Mechanical Efficiency (η = Work_output / Work_input * 100%)
                mechanical_efficiency = (kinetic_energy_finish / potential_energy * 100) if potential_energy > 0 else 0
                
                # Energy Transfer Efficiency (η = KE_end / PE_top * 100%)
                energy_transfer_efficiency = (kinetic_energy_finish / potential_energy * 100) if potential_energy > 0 else 0
                
                # Coefficient of Friction (μ = F_friction / N) - simplified
                normal_force = weight_kg * self.GRAVITY
                friction_force = energy_loss_total / distance_traveled if distance_traveled > 0 else 0
                coefficient_friction = friction_force / normal_force if normal_force > 0 else 0
                
                # Energy Conversion Efficiency (same as energy transfer efficiency)
                energy_conversion_efficiency = energy_transfer_efficiency
                
                # Momentum Change (Δp = m * Δv)
                momentum_change = weight_kg * (checkpoint_to_finish_speed - start_to_checkpoint_speed) if weight_kg > 0 else 0
                
                # =============================================================================
                # ENHANCED GRAVITATIONAL ACCELERATION CALCULATIONS
                # =============================================================================
                
                import math
                
                # Standard gravity component
                standard_gravity = self.GRAVITY
                
                # Calculate track angle from height and length (convert to radians)
                track_angle_rad = math.atan(self.INCLINE_HEIGHT / self.TRACK_LENGTH)
                
                # Theoretical gravitational component along incline: g·sin(θ)
                theoretical_gravity_component = self.GRAVITY * math.sin(track_angle_rad)
                
                # Calculate effective gravity by comparing measured vs theoretical
                # This captures ALL losses (friction, air resistance, etc.) without needing car-specific constants
                if acceleration > 0 and theoretical_gravity_component > 0:
                    # Ratio of measured to theoretical gives us overall efficiency
                    gravity_efficiency_ratio = acceleration / theoretical_gravity_component
                    effective_gravity = acceleration  # The actual effective gravity IS the measured acceleration
                    total_loss_acceleration = theoretical_gravity_component - acceleration
                else:
                    gravity_efficiency_ratio = 0
                    effective_gravity = 0
                    total_loss_acceleration = 0
                
                # Update gravitational acceleration with effective value
                gravitational_acceleration = effective_gravity
                
                # Store individual components for analysis
                measured_acceleration = acceleration
                friction_loss_acceleration = 0  # Cannot determine without car-specific data
                drag_loss_acceleration = 0  # Cannot determine without car-specific data
                
                # =============================================================================
                # STORE ALL CALCULATED VALUES
                # =============================================================================
                
                self._save_advanced_stats(race_id, lane, {
                    'start_to_checkpoint_speed': start_to_checkpoint_speed,
                    'checkpoint_to_finish_speed': checkpoint_to_finish_speed,
                    'average_speed': average_speed,
                    'distance_traveled': distance_traveled,
                    'acceleration_mps2': acceleration,
                    'gravitational_acceleration': gravitational_acceleration,
                    'measured_acceleration': measured_acceleration,
                    'friction_loss_acceleration': friction_loss_acceleration,
                    'drag_loss_acceleration': drag_loss_acceleration,
                    'effective_gravity': effective_gravity,
                    'standard_gravity': standard_gravity,
                    'force_newtons': force_newtons,
                    'potential_energy_joules': potential_energy,
                    'kinetic_energy_checkpoint': kinetic_energy_checkpoint,
                    'kinetic_energy_finish': kinetic_energy_finish,
                    'work_done_joules': work_done,
                    'power_watts': power_watts,
                    'g_force': g_force,
                    'energy_loss_rolling': energy_loss_rolling,
                    'energy_loss_total': energy_loss_total,
                    'coefficient_restitution': coefficient_restitution,
                    'impulse_ns': impulse,
                    'jerk_mps3': jerk,
                    'terminal_velocity': terminal_velocity,
                    'mechanical_efficiency': mechanical_efficiency,
                    'energy_transfer_efficiency': energy_transfer_efficiency,
                    'coefficient_friction': coefficient_friction,
                    'energy_conversion_efficiency': energy_conversion_efficiency,
                    'momentum_change': momentum_change,
                    'momentum_kgms': momentum_finish,
                    # Additional gravitational analysis fields
                    'theoretical_gravity_component': theoretical_gravity_component,
                    'gravity_efficiency_ratio': gravity_efficiency_ratio,
                    'total_loss_acceleration': total_loss_acceleration,
                    # Environmental conditions used in calculations
                    'air_density_used': current_air_density
                })
            
            logging.info(f"Advanced stats calculated for race {race_id}")
            return True
            
        except Exception as e:
            logging.error(f"Error calculating advanced stats for race {race_id}: {e}")
            return False
    
    def _save_advanced_stats(self, race_id, lane, stats):
        """Save calculated advanced statistics to database"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO advanced_stats (
                    race_id, lane, start_to_checkpoint_speed, checkpoint_to_finish_speed,
                    average_speed, distance_traveled, acceleration_mps2, gravitational_acceleration,
                    measured_acceleration, friction_loss_acceleration, drag_loss_acceleration,
                    effective_gravity, standard_gravity,
                    force_newtons, potential_energy_joules, kinetic_energy_checkpoint, kinetic_energy_finish,
                    work_done_joules, power_watts, g_force, energy_loss_rolling, energy_loss_total,
                    coefficient_restitution, impulse_ns, jerk_mps3, terminal_velocity,
                    mechanical_efficiency, energy_transfer_efficiency, coefficient_friction,
                    energy_conversion_efficiency, momentum_change, momentum_kgms,
                    theoretical_gravity_component, gravity_efficiency_ratio, total_loss_acceleration, air_density_used, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                race_id, lane, stats['start_to_checkpoint_speed'], stats['checkpoint_to_finish_speed'],
                stats['average_speed'], stats['distance_traveled'], stats['acceleration_mps2'], stats['gravitational_acceleration'],
                stats['measured_acceleration'], stats['friction_loss_acceleration'], stats['drag_loss_acceleration'],
                stats['effective_gravity'], stats['standard_gravity'],
                stats['force_newtons'], stats['potential_energy_joules'], stats['kinetic_energy_checkpoint'], stats['kinetic_energy_finish'],
                stats['work_done_joules'], stats['power_watts'], stats['g_force'], stats['energy_loss_rolling'], stats['energy_loss_total'],
                stats['coefficient_restitution'], stats['impulse_ns'], stats['jerk_mps3'], stats['terminal_velocity'],
                stats['mechanical_efficiency'], stats['energy_transfer_efficiency'], stats['coefficient_friction'],
                stats['energy_conversion_efficiency'], stats['momentum_change'], stats['momentum_kgms'],
                stats['theoretical_gravity_component'], stats['gravity_efficiency_ratio'], stats['total_loss_acceleration'], stats['air_density_used'], time.time()
            ))
            
            conn.commit()
    
    def get_advanced_stats(self, race_id, lane=None):
        """Get calculated advanced statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if lane:
                cursor.execute('SELECT * FROM advanced_stats WHERE race_id = ? AND lane = ?', (race_id, lane))
            else:
                cursor.execute('SELECT * FROM advanced_stats WHERE race_id = ? ORDER BY lane', (race_id,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    # =============================================================================
    # HELPER METHODS
    # =============================================================================
    
    def _get_race_start_times(self, race_id):
        """Get start times for all lanes in a race"""
        # This would be implemented based on how you store start gate timing data
        # For now, returning empty dict - you'll implement based on your actual data structure
        return {}
    
    def _get_checkpoint_times(self, race_id):
        """Get checkpoint times for all lanes in a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT lane, checkpoint_time FROM checkpoint_times WHERE race_id = ?', (race_id,))
            return {row['lane']: row['checkpoint_time'] for row in cursor.fetchall()}
    
    def _get_finish_times(self, race_id):
        """Get finish times for all lanes in a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT lane, time FROM race_results WHERE race_number = ?', (race_id,))
            return {row['lane']: row['time'] for row in cursor.fetchall()}
    
    def _get_car_weights(self, race_id):
        """Get car weights for all lanes in a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT lane, weight_grams FROM car_data WHERE race_id = ?', (race_id,))
            return {row['lane']: row['weight_grams'] for row in cursor.fetchall()}

    def get_track_record(self):
        """Get the fastest time (track record) from all races"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Get the fastest time from all races (must be >= 2.0 seconds to be valid)
                cursor.execute('''
                    SELECT MIN(time) as track_record
                    FROM race_results 
                    WHERE time IS NOT NULL AND time >= 2.0
                ''')
                
                result = cursor.fetchone()
                if result and result['track_record']:
                    return float(result['track_record'])
                else:
                    return None
                    
        except Exception as e:
            logging.error(f"Error getting track record: {e}")
            return None

    def get_advanced_leaderboards(self):
        """Generate advanced leaderboards based on calculated physics stats"""
        leaderboards = {
            # Basic Performance
            'fastest_time': [],
            'fastest_speed': [],
            'checkpoint_speed': [],
            'finish_speed': [],
            
            # Force & Acceleration
            'best_acceleration': [],
            'max_force': [],
            'best_gforce': [],
            'terminal_velocity': [],
            
            # Energy Analysis
            'highest_potential_energy': [],
            'highest_kinetic_energy': [],
            'most_work_done': [],
            'most_power': [],
            
            # Efficiency Metrics
            'highest_efficiency': [],
            'mechanical_efficiency': [],
            'energy_conversion': [],
            'lowest_friction': [],
            
            # Advanced Physics
            'momentum_masters': [],
            'momentum_change': [],
            'impulse_champions': [],
            'jerk_analysis': [],
            'coefficient_restitution': [],
            
            # Energy Loss Analysis
            'lowest_energy_loss': [],
            'rolling_resistance': [],
            
            # Enhanced Gravitational Analysis
            'gravitational_efficiency': [],
            'friction_analysis': [],
            'aerodynamic_performance': [],
            'effective_gravity': [],
            'gravity_utilization': []
        }
        
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                
                # Fastest Time Leaderboard (from race_results)
                cursor.execute('''
                    SELECT rr.*, r.start_time, r.end_time, rr.additional_data
                    FROM race_results rr
                    LEFT JOIN races r ON rr.race_number = r.race_number
                    ORDER BY rr.time ASC
                    LIMIT 10
                ''')
                fastest_times = cursor.fetchall()
                for row in fastest_times:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['fastest_time'].append({
                            'car_name': car_name,
                            'value': f"{row['time']:.3f}",
                            'unit': 'seconds',
                            'race_number': row['race_number'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing fastest time row: {e}")
                        continue

                # Fastest Speed Leaderboard (from race_results)  
                cursor.execute('''
                    SELECT rr.*, r.start_time, r.end_time, rr.additional_data
                    FROM race_results rr
                    LEFT JOIN races r ON rr.race_number = r.race_number
                    WHERE rr.additional_data IS NOT NULL
                    ORDER BY 
                        CAST(json_extract(rr.additional_data, '$.speed') AS REAL) DESC
                    LIMIT 10
                ''')
                fastest_speeds = cursor.fetchall()
                for row in fastest_speeds:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        speed = additional_data.get('speed')
                        if speed is not None:
                            car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                            race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                            
                            leaderboards['fastest_speed'].append({
                                'car_name': car_name,
                                'value': f"{speed:.2f}",
                                'unit': 'mph',
                                'race_number': row['race_number'],
                                'date': race_date
                            })
                    except Exception as e:
                        logging.error(f"Error processing fastest speed row: {e}")
                        continue

                # Best Acceleration Leaderboard (from advanced_stats)
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.acceleration_mps2 IS NOT NULL AND s.acceleration_mps2 > 0
                    ORDER BY s.acceleration_mps2 DESC
                    LIMIT 10
                ''')
                best_acceleration = cursor.fetchall()
                for row in best_acceleration:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['best_acceleration'].append({
                            'car_name': car_name,
                            'value': f"{row['acceleration_mps2']:.2f}",
                            'unit': 'm/s²',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing acceleration row: {e}")
                        continue

                # Highest Energy Efficiency Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.energy_transfer_efficiency IS NOT NULL AND s.energy_transfer_efficiency > 0
                    ORDER BY s.energy_transfer_efficiency DESC
                    LIMIT 10
                ''')
                highest_efficiency = cursor.fetchall()
                for row in highest_efficiency:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['highest_efficiency'].append({
                            'car_name': car_name,
                            'value': f"{row['energy_transfer_efficiency']:.1f}",
                            'unit': '%',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing efficiency row: {e}")
                        continue

                # Most Power Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.power_watts IS NOT NULL AND s.power_watts > 0
                    ORDER BY s.power_watts DESC
                    LIMIT 10
                ''')
                most_power = cursor.fetchall()
                for row in most_power:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['most_power'].append({
                            'car_name': car_name,
                            'value': f"{row['power_watts']:.2f}",
                            'unit': 'watts',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing power row: {e}")
                        continue

                # Best G-Force Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.g_force IS NOT NULL AND s.g_force > 0
                    ORDER BY s.g_force DESC
                    LIMIT 10
                ''')
                best_gforce = cursor.fetchall()
                for row in best_gforce:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['best_gforce'].append({
                            'car_name': car_name,
                            'value': f"{row['g_force']:.2f}",
                            'unit': 'G',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing g-force row: {e}")
                        continue

                # Momentum Masters Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.momentum_kgms IS NOT NULL AND s.momentum_kgms > 0
                    ORDER BY s.momentum_kgms DESC
                    LIMIT 10
                ''')
                momentum_masters = cursor.fetchall()
                for row in momentum_masters:
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        
                        leaderboards['momentum_masters'].append({
                            'car_name': car_name,
                            'value': f"{row['momentum_kgms']:.4f}",
                            'unit': 'kg⋅m/s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        logging.error(f"Error processing momentum row: {e}")
                        continue

                # ==============================================================================
                # ADDITIONAL ADVANCED LEADERBOARDS
                # ==============================================================================

                # Checkpoint Speed Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.start_to_checkpoint_speed IS NOT NULL AND s.start_to_checkpoint_speed > 0
                    ORDER BY s.start_to_checkpoint_speed DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['checkpoint_speed'].append({
                            'car_name': car_name,
                            'value': f"{row['start_to_checkpoint_speed']:.2f}",
                            'unit': 'ft/s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Finish Speed Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.checkpoint_to_finish_speed IS NOT NULL AND s.checkpoint_to_finish_speed > 0
                    ORDER BY s.checkpoint_to_finish_speed DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['finish_speed'].append({
                            'car_name': car_name,
                            'value': f"{row['checkpoint_to_finish_speed']:.2f}",
                            'unit': 'ft/s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Maximum Force Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.force_newtons IS NOT NULL AND s.force_newtons > 0
                    ORDER BY s.force_newtons DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['max_force'].append({
                            'car_name': car_name,
                            'value': f"{row['force_newtons']:.3f}",
                            'unit': 'N',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Terminal Velocity Leaderboard
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.terminal_velocity IS NOT NULL AND s.terminal_velocity > 0
                    ORDER BY s.terminal_velocity DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['terminal_velocity'].append({
                            'car_name': car_name,
                            'value': f"{row['terminal_velocity']:.2f}",
                            'unit': 'ft/s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Highest Potential Energy
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.potential_energy_joules IS NOT NULL AND s.potential_energy_joules > 0
                    ORDER BY s.potential_energy_joules DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['highest_potential_energy'].append({
                            'car_name': car_name,
                            'value': f"{row['potential_energy_joules']:.4f}",
                            'unit': 'J',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Highest Kinetic Energy
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.kinetic_energy_finish IS NOT NULL AND s.kinetic_energy_finish > 0
                    ORDER BY s.kinetic_energy_finish DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['highest_kinetic_energy'].append({
                            'car_name': car_name,
                            'value': f"{row['kinetic_energy_finish']:.4f}",
                            'unit': 'J',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Most Work Done
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.work_done_joules IS NOT NULL AND s.work_done_joules > 0
                    ORDER BY s.work_done_joules DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['most_work_done'].append({
                            'car_name': car_name,
                            'value': f"{row['work_done_joules']:.4f}",
                            'unit': 'J',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Mechanical Efficiency
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.mechanical_efficiency IS NOT NULL AND s.mechanical_efficiency > 0
                    ORDER BY s.mechanical_efficiency DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['mechanical_efficiency'].append({
                            'car_name': car_name,
                            'value': f"{row['mechanical_efficiency']:.1f}",
                            'unit': '%',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Energy Conversion Efficiency
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.energy_conversion_efficiency IS NOT NULL AND s.energy_conversion_efficiency > 0
                    ORDER BY s.energy_conversion_efficiency DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['energy_conversion'].append({
                            'car_name': car_name,
                            'value': f"{row['energy_conversion_efficiency']:.1f}",
                            'unit': '%',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Lowest Friction Coefficient
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.coefficient_friction IS NOT NULL AND s.coefficient_friction > 0
                    ORDER BY s.coefficient_friction ASC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['lowest_friction'].append({
                            'car_name': car_name,
                            'value': f"{row['coefficient_friction']:.4f}",
                            'unit': 'μ',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Momentum Change
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.momentum_change IS NOT NULL AND s.momentum_change > 0
                    ORDER BY s.momentum_change DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['momentum_change'].append({
                            'car_name': car_name,
                            'value': f"{row['momentum_change']:.4f}",
                            'unit': 'kg⋅m/s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Impulse Champions
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.impulse_ns IS NOT NULL AND s.impulse_ns > 0
                    ORDER BY s.impulse_ns DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['impulse_champions'].append({
                            'car_name': car_name,
                            'value': f"{row['impulse_ns']:.4f}",
                            'unit': 'N⋅s',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Jerk Analysis (highest jerk)
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.jerk_mps3 IS NOT NULL AND s.jerk_mps3 > 0
                    ORDER BY s.jerk_mps3 DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['jerk_analysis'].append({
                            'car_name': car_name,
                            'value': f"{row['jerk_mps3']:.3f}",
                            'unit': 'm/s³',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Coefficient of Restitution
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.coefficient_restitution IS NOT NULL AND s.coefficient_restitution > 0
                    ORDER BY s.coefficient_restitution DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['coefficient_restitution'].append({
                            'car_name': car_name,
                            'value': f"{row['coefficient_restitution']:.3f}",
                            'unit': 'e',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Lowest Energy Loss
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.energy_loss_total IS NOT NULL AND s.energy_loss_total > 0
                    ORDER BY s.energy_loss_total ASC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['lowest_energy_loss'].append({
                            'car_name': car_name,
                            'value': f"{row['energy_loss_total']:.4f}",
                            'unit': 'J',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Rolling Resistance
                cursor.execute('''
                    SELECT s.*, r.start_time, r.end_time, rr.additional_data
                    FROM advanced_stats s
                    LEFT JOIN races r ON s.race_id = r.race_number
                    LEFT JOIN race_results rr ON s.race_id = rr.race_number AND s.lane = rr.lane
                    WHERE s.energy_loss_rolling IS NOT NULL AND s.energy_loss_rolling > 0
                    ORDER BY s.energy_loss_rolling ASC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['rolling_resistance'].append({
                            'car_name': car_name,
                            'value': f"{row['energy_loss_rolling']:.4f}",
                            'unit': 'J',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # =================================================================
                # ENHANCED GRAVITATIONAL ANALYSIS LEADERBOARDS  
                # =================================================================

                # Gravitational Efficiency (gravity_efficiency_ratio)
                cursor.execute('''
                    SELECT astats.*, rr.additional_data, r.end_time
                    FROM advanced_stats astats
                    LEFT JOIN race_results rr ON astats.race_id = rr.race_number AND astats.lane = rr.lane
                    LEFT JOIN races r ON astats.race_id = r.race_number
                    WHERE astats.gravity_efficiency_ratio IS NOT NULL AND astats.gravity_efficiency_ratio > 0
                    ORDER BY astats.gravity_efficiency_ratio DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        efficiency_percent = row['gravity_efficiency_ratio'] * 100
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['gravitational_efficiency'].append({
                            'car_name': car_name,
                            'value': f"{efficiency_percent:.2f}",
                            'unit': '%',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Total Loss Analysis (lowest total_loss_acceleration)
                cursor.execute('''
                    SELECT astats.*, rr.additional_data, r.end_time
                    FROM advanced_stats astats
                    LEFT JOIN race_results rr ON astats.race_id = rr.race_number AND astats.lane = rr.lane
                    LEFT JOIN races r ON astats.race_id = r.race_number
                    WHERE astats.total_loss_acceleration IS NOT NULL
                    ORDER BY astats.total_loss_acceleration ASC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['friction_analysis'].append({
                            'car_name': car_name,
                            'value': f"{row['total_loss_acceleration']:.4f}",
                            'unit': 'm/s²',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Effective Performance (highest effective_gravity)
                cursor.execute('''
                    SELECT astats.*, rr.additional_data, r.end_time
                    FROM advanced_stats astats
                    LEFT JOIN race_results rr ON astats.race_id = rr.race_number AND astats.lane = rr.lane
                    LEFT JOIN races r ON astats.race_id = r.race_number
                    WHERE astats.effective_gravity IS NOT NULL
                    ORDER BY astats.effective_gravity DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['aerodynamic_performance'].append({
                            'car_name': car_name,
                            'value': f"{row['effective_gravity']:.4f}",
                            'unit': 'm/s²',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Effective Gravity (same as above, different category)
                cursor.execute('''
                    SELECT astats.*, rr.additional_data, r.end_time
                    FROM advanced_stats astats
                    LEFT JOIN race_results rr ON astats.race_id = rr.race_number AND astats.lane = rr.lane
                    LEFT JOIN races r ON astats.race_id = r.race_number
                    WHERE astats.effective_gravity IS NOT NULL
                    ORDER BY astats.effective_gravity DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['effective_gravity'].append({
                            'car_name': car_name,
                            'value': f"{row['effective_gravity']:.4f}",
                            'unit': 'm/s²',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                # Gravity Utilization (same as gravitational efficiency)
                cursor.execute('''
                    SELECT astats.*, rr.additional_data, r.end_time
                    FROM advanced_stats astats
                    LEFT JOIN race_results rr ON astats.race_id = rr.race_number AND astats.lane = rr.lane
                    LEFT JOIN races r ON astats.race_id = r.race_number
                    WHERE astats.gravity_efficiency_ratio IS NOT NULL AND astats.gravity_efficiency_ratio > 0
                    ORDER BY astats.gravity_efficiency_ratio DESC
                    LIMIT 10
                ''')
                for row in cursor.fetchall():
                    try:
                        utilization = row['gravity_efficiency_ratio'] * 100
                        additional_data = json.loads(row['additional_data'] or '{}')
                        car_name = additional_data.get('car_name', f'Car Lane {row["lane"]}')
                        race_date = row['end_time'][:10] if row['end_time'] else 'Unknown'
                        leaderboards['gravity_utilization'].append({
                            'car_name': car_name,
                            'value': f"{utilization:.2f}",
                            'unit': '%',
                            'race_number': row['race_id'],
                            'date': race_date
                        })
                    except Exception as e:
                        continue

                logging.info("Advanced leaderboards generated successfully")
                return leaderboards
                
        except Exception as e:
            logging.error(f"Error generating advanced leaderboards: {e}")
            return leaderboards  # Return empty structure on error

    # =============================================================================
    # GRANULAR RACE EDITING METHODS
    # =============================================================================
    
    def get_race_metadata(self, race_id):
        """Get race metadata for a specific race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM races WHERE race_number = ?', (race_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def update_race_metadata(self, race_id, metadata):
        """Update race metadata"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE races 
                SET metadata = ?, end_time = COALESCE(end_time, ?)
                WHERE race_number = ?
            ''', (json.dumps(metadata), time.time(), race_id))
            conn.commit()
            return cursor.rowcount > 0
    
    def update_race_results(self, race_id, results_data):
        """Update race results for a specific race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Update each lane's result
            for result in results_data:
                cursor.execute('''
                    UPDATE race_results 
                    SET time = ?, placement = ?, additional_data = ?
                    WHERE race_number = ? AND lane = ?
                ''', (
                    result.get('time'),
                    result.get('placement'),
                    json.dumps(result.get('additional_data', {})),
                    race_id,
                    result.get('lane')
                ))
            
            conn.commit()
            return True
    
    def update_checkpoint_data(self, race_id, checkpoint_data):
        """Update checkpoint timing data for a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for lane_data in checkpoint_data:
                cursor.execute('''
                    INSERT OR REPLACE INTO checkpoint_times 
                    (race_id, lane, checkpoint_position, checkpoint_time, speed_at_checkpoint, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    race_id,
                    lane_data.get('lane'),
                    lane_data.get('checkpoint_position', self.CHECKPOINT_DISTANCE),
                    lane_data.get('checkpoint_time'),
                    lane_data.get('speed_at_checkpoint'),
                    time.time()
                ))
            
            conn.commit()
            return True
    
    def update_advanced_stats(self, race_id, stats_data):
        """Update advanced statistics for a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            for lane_stats in stats_data:
                lane = lane_stats.get('lane')
                
                # Build the update query dynamically based on provided fields
                update_fields = []
                update_values = []
                
                for field, value in lane_stats.items():
                    if field != 'lane' and value is not None:
                        update_fields.append(f"{field} = ?")
                        update_values.append(value)
                
                if update_fields:
                    update_values.extend([race_id, lane])
                    cursor.execute(f'''
                        UPDATE advanced_stats 
                        SET {', '.join(update_fields)}, timestamp = ?
                        WHERE race_id = ? AND lane = ?
                    ''', update_values + [time.time()])
            
            conn.commit()
            return True
    
    def get_checkpoint_data(self, race_id):
        """Get checkpoint timing data for a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM checkpoint_times 
                WHERE race_id = ? 
                ORDER BY lane
            ''', (race_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_car_weights(self, race_id):
        """Get car weight data for a race"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT lane, weight_grams FROM car_data 
                WHERE race_id = ?
            ''', (race_id,))
            return {row['lane']: row['weight_grams'] for row in cursor.fetchall()}
    
    def get_all_races_summary(self, page=1, per_page=20):
        """Get paginated summary of all races"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            offset = (page - 1) * per_page
            
            cursor.execute('''
                SELECT 
                    r.race_number,
                    r.start_time,
                    r.end_time,
                    r.status,
                    r.metadata,
                    MIN(rr.time) as fastest_time,
                    COUNT(rr.lane) as total_lanes,
                    COUNT(CASE WHEN rr.placement = 1 THEN 1 END) as winners,
                    GROUP_CONCAT(
                        CASE WHEN rr.placement = 1 
                        THEN json_extract(rr.additional_data, '$.car_name') 
                        END, ', '
                    ) as winner_names,
                    COUNT(DISTINCT as1.lane) as has_advanced_stats
                FROM races r
                LEFT JOIN race_results rr ON r.race_number = rr.race_number
                LEFT JOIN advanced_stats as1 ON r.race_number = as1.race_id
                GROUP BY r.race_number, r.start_time, r.end_time, r.status, r.metadata
                ORDER BY r.race_number DESC
                LIMIT ? OFFSET ?
            ''', (per_page, offset))
            
            races = []
            for row in cursor.fetchall():
                race_dict = dict(row)
                try:
                    race_dict['metadata'] = json.loads(race_dict['metadata'] or '{}')
                except Exception:
                    race_dict['metadata'] = {}
                races.append(race_dict)
            
            return races
    
    def get_total_race_count(self):
        """Get total number of races in database"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(DISTINCT race_number) FROM races')
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def search_races(self, search_term='', date_from=None, date_to=None, has_advanced_stats=None):
        """Search races by various criteria"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build dynamic query
            where_conditions = []
            params = []
            
            if search_term:
                where_conditions.append('''
                    (r.metadata LIKE ? OR 
                     EXISTS (SELECT 1 FROM race_results rr2 
                             WHERE rr2.race_number = r.race_number 
                             AND rr2.additional_data LIKE ?))
                ''')
                params.extend([f'%{search_term}%', f'%{search_term}%'])
            
            if date_from:
                where_conditions.append('DATE(r.start_time) >= ?')
                params.append(date_from)
            
            if date_to:
                where_conditions.append('DATE(r.start_time) <= ?')
                params.append(date_to)
            
            if has_advanced_stats is not None:
                if has_advanced_stats.lower() == 'true':
                    where_conditions.append('EXISTS (SELECT 1 FROM advanced_stats as1 WHERE as1.race_id = r.race_number)')
                else:
                    where_conditions.append('NOT EXISTS (SELECT 1 FROM advanced_stats as1 WHERE as1.race_id = r.race_number)')
            
            where_clause = 'WHERE ' + ' AND '.join(where_conditions) if where_conditions else ''
            
            query = f'''
                SELECT 
                    r.race_number,
                    r.start_time,
                    r.end_time,
                    r.status,
                    r.metadata,
                    MIN(rr.time) as fastest_time,
                    COUNT(rr.lane) as total_lanes,
                    COUNT(CASE WHEN rr.placement = 1 THEN 1 END) as winners,
                    GROUP_CONCAT(
                        CASE WHEN rr.placement = 1 
                        THEN json_extract(rr.additional_data, '$.car_name') 
                        END, ', '
                    ) as winner_names,
                    COUNT(DISTINCT as1.lane) as has_advanced_stats
                FROM races r
                LEFT JOIN race_results rr ON r.race_number = rr.race_number
                LEFT JOIN advanced_stats as1 ON r.race_number = as1.race_id
                {where_clause}
                GROUP BY r.race_number, r.start_time, r.end_time, r.status, r.metadata
                ORDER BY r.race_number DESC
                LIMIT 50
            '''
            
            cursor.execute(query, params)
            
            races = []
            for row in cursor.fetchall():
                race_dict = dict(row)
                try:
                    race_dict['metadata'] = json.loads(race_dict['metadata'] or '{}')
                except Exception:
                    race_dict['metadata'] = {}
                races.append(race_dict)
            
            return races