#!/usr/bin/env python3
"""
Start Gate UI Dashboard - 1024x600 Display
Monitoring interface - gets all data from central server
"""

import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import time
import requests
from datetime import datetime
import queue
import logging
import socketio
import psutil

# Configuration - Get everything from central server
CENTRAL_SERVER_URL = "http://192.168.1.132:5000"
REFRESH_INTERVAL = 1000  # milliseconds
UI_TITLE = "Start Gate Monitor Dashboard"
GATE_TYPE = "start_gate"  # Filter by gate type instead of specific gate ID

class StartGateUI:
    def __init__(self):
        self.root = tk.Tk()
        self.setup_window()
        
        # Data queues for thread-safe updates
        self.log_queue = queue.Queue()
        self.status_queue = queue.Queue()
        
        # Current state variables
        self.current_mode = "RACING"
        self.race_state = "Unknown"
        self.race_number = 0
        self.formatted_race = "Unknown"
        self.component_status = {}
        self.config_data = {}
        self.server_connected = False
        
        # Setup Socket.IO to monitor same server as gate
        self.sio = socketio.Client()
        self.setup_socketio_listeners()
        
        # Setup UI components
        self.setup_ui()
        
        # Start background tasks
        self.start_background_tasks()
        
        # Start UI update loop
        self.update_ui()
    
    def setup_socketio_listeners(self):
        """Setup Socket.IO to listen to same events as the gate"""
        
        @self.sio.event
        def connect():
            self.log_queue.put("📡 Connected to central server (monitoring)")
            self.status_queue.put(('server_connected', True))
        
        @self.sio.event
        def disconnect():
            self.log_queue.put("📡 Disconnected from central server")
            self.status_queue.put(('server_connected', False))
        
        @self.sio.on('race_state_update')
        def on_race_state_update(data):
            """Monitor the same race state updates the gate receives"""
            current_status = data.get('status')
            race_number = data.get('race_number')
            formatted_race = data.get('formatted_race')
            
            self.status_queue.put(('race_state', current_status))
            self.status_queue.put(('race_info', {
                'race_number': race_number,
                'formatted_race': formatted_race
            }))
            
            self.log_queue.put(f"🏁 Race state: {current_status} (Race: {formatted_race})")
        
        @self.sio.on('config_updated')
        def on_config_updated(data):
            """Monitor config updates the gate receives"""
            self.status_queue.put(('config', data))
            self.log_queue.put(f"⚙️ Config updated: {list(data.keys())} settings changed")
        
        @self.sio.on('component_status_update')
        def on_component_status_update(data):
            """Monitor component status updates from gates"""
            gate_type = data.get('gate_type')
            if gate_type == GATE_TYPE:  # Only monitor start gate type
                self.status_queue.put(('component_status', data))
                self.log_queue.put(f"🔧 Component status update from {gate_type}")
        
        @self.sio.on('gate_timing_event')
        def on_gate_timing_event(data):
            """Monitor gate timing events"""
            gate_type = data.get('gate_type')
            event_type = data.get('event_type')
            if gate_type == GATE_TYPE:
                formatted_time = data.get('formatted_time', 'Unknown')
                self.log_queue.put(f"⏱️ {event_type}: {formatted_time}")
        
        @self.sio.on('gate_status_update')
        def on_gate_status_update(data):
            """Monitor gate status updates"""
            gate_type = data.get('gate_type')
            if gate_type == GATE_TYPE:
                status = data.get('status')
                self.log_queue.put(f"🚪 Start gate status: {status}")
        
        @self.sio.on('race_started')
        def on_race_started(data):
            """Monitor when races start"""
            start_time = data.get('formatted_time', 'Unknown')
            race_id = data.get('race_id', 'Unknown')
            self.log_queue.put(f"🏁 Race {race_id} started at {start_time}")
    
    def setup_window(self):
        """Configure the main window"""
        self.root.title(UI_TITLE)
        self.root.geometry("1024x600")
        self.root.configure(bg='#1e1e1e')  # Dark theme
        
        # Configure grid weights
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)
    
    def setup_ui(self):
        """Setup the complete UI layout"""
        # Status bar at top
        self.create_status_bar()
        
        # Main dashboard area
        self.create_main_dashboard()
        
        # Emergency controls at bottom
        self.create_emergency_controls()
    
    def create_status_bar(self):
        """Create top status bar"""
        status_frame = tk.Frame(self.root, bg='#2d2d2d', height=80)
        status_frame.grid(row=0, column=0, sticky='ew', padx=5, pady=5)
        status_frame.grid_propagate(False)
        
        # Left side - Gate info
        self.gate_info_label = tk.Label(
            status_frame, 
            text="🎯 START GATE MONITOR | Mode: RACING | Time: 00:00:00.000 | Race: #0_000000_20251225",
            bg='#2d2d2d', fg='white', font=('Arial', 12, 'bold')
        )
        self.gate_info_label.pack(side='left', padx=10, pady=20)
        
        # Right side - Connection status
        self.connection_status = tk.Label(
            status_frame,
            text="🔴 DISCONNECTED",
            bg='#2d2d2d', fg='red', font=('Arial', 12, 'bold')
        )
        self.connection_status.pack(side='right', padx=10, pady=20)
    
    def create_main_dashboard(self):
        """Create main 4-panel dashboard"""
        main_frame = tk.Frame(self.root, bg='#1e1e1e')
        main_frame.grid(row=1, column=0, sticky='nsew', padx=5, pady=5)
        
        # Configure grid weights for 2x2 layout
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        main_frame.grid_columnconfigure(1, weight=1)
        
        # Top Left - Race State Panel
        self.create_race_state_panel(main_frame, 0, 0)
        
        # Top Right - Component Status Panel
        self.create_component_panel(main_frame, 0, 1)
        
        # Bottom Left - Configuration Panel
        self.create_config_panel(main_frame, 1, 0)
        
        # Bottom Right - Activity Log Panel
        self.create_activity_panel(main_frame, 1, 1)
    
    def create_race_state_panel(self, parent, row, col):
        """Create race state monitoring panel"""
        frame = tk.LabelFrame(parent, text="RACE STATE (FROM CENTRAL SERVER)", bg='#2d2d2d', fg='white', 
                             font=('Arial', 10, 'bold'), padx=10, pady=10)
        frame.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
        
        # Current state display
        self.race_state_label = tk.Label(
            frame, text="Current State: UNKNOWN", 
            bg='#2d2d2d', fg='yellow', font=('Arial', 14, 'bold')
        )
        self.race_state_label.pack(pady=10)
        
        # Progress bar
        self.race_progress = ttk.Progressbar(
            frame, length=300, mode='determinate'
        )
        self.race_progress.pack(pady=10)
        
        # State details
        self.state_details = tk.Text(
            frame, height=8, width=40, bg='#1a1a1a', fg='white',
            font=('Courier', 10), wrap=tk.WORD
        )
        self.state_details.pack(pady=10, fill='both', expand=True)
        
        # Gate operation status
        self.gate_operation_status = tk.Label(
            frame, text="🚪 Gate: Monitoring...", 
            bg='#2d2d2d', fg='cyan', font=('Arial', 10)
        )
        self.gate_operation_status.pack(pady=5)
    
    def create_component_panel(self, parent, row, col):
        """Create component status panel"""
        frame = tk.LabelFrame(parent, text="START GATE COMPONENTS", bg='#2d2d2d', fg='white',
                             font=('Arial', 10, 'bold'), padx=10, pady=10)
        frame.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
        
        # Component status list
        self.component_tree = ttk.Treeview(frame, columns=('Status', 'Details'), show='tree headings')
        self.component_tree.heading('#0', text='Component')
        self.component_tree.heading('Status', text='Status')
        self.component_tree.heading('Details', text='Details')
        
        self.component_tree.column('#0', width=120)
        self.component_tree.column('Status', width=80)
        self.component_tree.column('Details', width=150)
        
        self.component_tree.pack(fill='both', expand=True, pady=10)
        
        # Overall status
        self.overall_status = tk.Label(
            frame, text="Status: WAITING FOR DATA...", 
            bg='#2d2d2d', fg='orange', font=('Arial', 12, 'bold')
        )
        self.overall_status.pack(pady=10)
        
        # Last update time
        self.last_update = tk.Label(
            frame, text="Last Update: Never", 
            bg='#2d2d2d', fg='gray', font=('Arial', 9)
        )
        self.last_update.pack()
    
    def create_config_panel(self, parent, row, col):
        """Create configuration display panel"""
        frame = tk.LabelFrame(parent, text="GATE CONFIGURATION", bg='#2d2d2d', fg='white',
                             font=('Arial', 10, 'bold'), padx=10, pady=10)
        frame.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
        
        # Config source indicator
        self.config_source = tk.Label(
            frame, text="Source: 📡 Central Server", 
            bg='#2d2d2d', fg='cyan', font=('Arial', 11, 'bold')
        )
        self.config_source.pack(pady=5)
        
        # Config values in scrollable frame
        self.config_text = scrolledtext.ScrolledText(
            frame, height=10, width=50, 
            bg='#1a1a1a', fg='white', font=('Courier', 9),
            wrap=tk.WORD
        )
        self.config_text.pack(fill='both', expand=True, pady=10)
        
        # Config status
        self.config_status = tk.Label(
            frame, text="Waiting for configuration data...", 
            bg='#2d2d2d', fg='gray', font=('Arial', 9)
        )
        self.config_status.pack(pady=5)
    
    def create_activity_panel(self, parent, row, col):
        """Create activity log panel"""
        frame = tk.LabelFrame(parent, text="START GATE ACTIVITY", bg='#2d2d2d', fg='white',
                             font=('Arial', 10, 'bold'), padx=10, pady=10)
        frame.grid(row=row, column=col, sticky='nsew', padx=5, pady=5)
        
        # Activity log with scrollbar
        self.activity_log = scrolledtext.ScrolledText(
            frame, height=15, width=50, 
            bg='#0a0a0a', fg='lime', font=('Courier', 9),
            wrap=tk.WORD, state='disabled'
        )
        self.activity_log.pack(fill='both', expand=True, pady=10)
        
        # Clear log button
        self.clear_log_btn = tk.Button(
            frame, text="🗑️ CLEAR LOG", 
            command=self.clear_activity_log,
            bg='#4a4a4a', fg='white', font=('Arial', 9)
        )
        self.clear_log_btn.pack(pady=5)
    
    def create_emergency_controls(self):
        """Create monitoring info panel at bottom"""
        emergency_frame = tk.Frame(self.root, bg='#2d2d2d', height=80)
        emergency_frame.grid(row=2, column=0, sticky='ew', padx=5, pady=5)
        emergency_frame.grid_propagate(False)
        
        # Info about UI purpose
        info_label = tk.Label(
            emergency_frame, 
            text="📊 MONITORING INTERFACE - Displays start gate data from central server. Gate Type: " + GATE_TYPE,
            bg='#2d2d2d', fg='orange', font=('Arial', 12, 'bold'),
            wraplength=800
        )
        info_label.pack(side='left', padx=10, pady=20)
        
        # Performance metrics (right side)
        metrics_frame = tk.Frame(emergency_frame, bg='#2d2d2d')
        metrics_frame.pack(side='right', fill='y', padx=10)
        
        self.performance_label = tk.Label(
            metrics_frame, 
            text="Monitor: Active | Server: Connecting | UI Memory: 0MB",
            bg='#2d2d2d', fg='cyan', font=('Arial', 10)
        )
        self.performance_label.pack(pady=25)
    
    def start_background_tasks(self):
        """Start background monitoring threads"""
        # Connect to central server
        threading.Thread(target=self.connect_to_server, daemon=True).start()
        
        # Periodically fetch component status from server
        threading.Thread(target=self.fetch_component_status, daemon=True).start()
        
        # Periodically fetch configuration from server
        threading.Thread(target=self.fetch_configuration, daemon=True).start()
        
        # Monitor UI performance
        threading.Thread(target=self.monitor_performance, daemon=True).start()
    
    def connect_to_server(self):
        """Connect to the central server with retry logic"""
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                self.log_queue.put(f"📡 Connecting to central server... (Attempt {attempt + 1}/{max_retries})")
                self.sio.connect(CENTRAL_SERVER_URL, transports=['websocket'])
                self.log_queue.put("📡 Successfully connected to central server")
                return
            except Exception as e:
                self.log_queue.put(f"❌ Connection attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    self.log_queue.put(f"🔄 Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    self.log_queue.put("🚨 FAILED TO CONNECT - All retry attempts exhausted")
                    self.status_queue.put(('connection_failed', True))
    
    def fetch_component_status(self):
        """Fetch component status from central server"""
        consecutive_failures = 0
        max_failures = 3
        
        while True:
            try:
                if self.server_connected:
                    response = requests.get(f"{CENTRAL_SERVER_URL}/get_component_status?gate_type={GATE_TYPE}", timeout=3)
                    if response.status_code == 200:
                        component_data = response.json()
                        consecutive_failures = 0  # Reset failure counter
                        
                        # Filter for our gate type
                        our_gate_data = None
                        for component in component_data:
                            if component.get('gate_type') == GATE_TYPE:
                                our_gate_data = component
                                break
                        
                        if our_gate_data:
                            self.status_queue.put(('component_status', our_gate_data))
                        else:
                            self.log_queue.put(f"⚠️ No data found for gate type: {GATE_TYPE}")
                    else:
                        self.log_queue.put(f"⚠️ Server returned status {response.status_code}")
                else:
                    # Not connected to server
                    if consecutive_failures == 0:  # Only log once
                        self.log_queue.put("⚠️ Not connected to server - waiting for connection...")
                    consecutive_failures += 1
                    
            except requests.exceptions.Timeout:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    self.log_queue.put(f"🚨 Server requests timing out ({consecutive_failures} failures)")
            except requests.exceptions.ConnectionError:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    self.log_queue.put(f"🚨 Cannot reach server ({consecutive_failures} connection errors)")
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    self.log_queue.put(f"🚨 Error fetching component status: {e}")
            
            time.sleep(5)
    
    def fetch_configuration(self):
        """Fetch configuration from central server"""
        while True:
            try:
                if self.server_connected:
                    response = requests.get(f"{CENTRAL_SERVER_URL}/get_config", timeout=3)
                    if response.status_code == 200:
                        config_data = response.json()
                        self.status_queue.put(('config', config_data))
                
            except Exception as e:
                self.log_queue.put(f"Error fetching configuration: {e}")
            
            time.sleep(10)  # Check every 10 seconds
    
    def monitor_performance(self):
        """Monitor UI performance"""
        while True:
            try:
                memory_mb = psutil.Process().memory_info().rss // (1024 * 1024)
                
                performance_data = {
                    'ui_memory': memory_mb,
                    'server_connected': self.server_connected,
                    'monitor_active': True
                }
                
                self.status_queue.put(('ui_performance', performance_data))
                
            except Exception as e:
                self.log_queue.put(f"Performance monitoring error: {e}")
            
            time.sleep(2)
    
    def update_ui(self):
        """Main UI update loop"""
        # Process status queue
        while not self.status_queue.empty():
            try:
                status_type, data = self.status_queue.get_nowait()
                self.process_status_update(status_type, data)
            except queue.Empty:
                break
        
        # Process log queue
        while not self.log_queue.empty():
            try:
                log_message = self.log_queue.get_nowait()
                self.add_log_entry(log_message)
            except queue.Empty:
                break
        
        # Update time display
        current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        race_info = f"🎯 START GATE MONITOR | Mode: {self.current_mode} | Time: {current_time} | Race: {self.formatted_race}"
        self.gate_info_label.config(text=race_info)
        
        # Schedule next update
        self.root.after(REFRESH_INTERVAL, self.update_ui)
    
    def process_status_update(self, status_type, data):
        """Process different types of status updates"""
        if status_type == 'server_connected':
            self.server_connected = data
            if data:
                self.connection_status.config(text="🟢 MONITORING", fg='lime')
            else:
                self.connection_status.config(text="🔴 DISCONNECTED", fg='red')
        
        elif status_type == 'connection_failed':
            # Show prominent connection failure
            self.connection_status.config(text="🚨 CONNECTION FAILED", fg='red')
            self.overall_status.config(text="❌ CANNOT REACH CENTRAL SERVER", fg='red')
        
        elif status_type == 'race_state':
            self.race_state = data
            self.update_race_state_display(data)
        
        elif status_type == 'race_info':
            self.race_number = data.get('race_number', 0)
            self.formatted_race = data.get('formatted_race', 'Unknown')
        
        elif status_type == 'component_status':
            self.update_component_display(data)
        
        elif status_type == 'config':
            self.update_config_display(data)
        
        elif status_type == 'ui_performance':
            self.update_performance_display(data)
    
    def update_race_state_display(self, state):
        """Update race state panel"""
        # State color mapping
        state_colors = {
            'Initialization': 'orange',
            'Ready': 'yellow', 
            'Countdown': 'red',
            'Racing': 'lime',
            'Placement': 'cyan',
            'Finished': 'white',
            'Intermission': 'purple',
            'Reset': 'gray'
        }
        
        color = state_colors.get(state, 'white')
        self.race_state_label.config(text=f"State: {state}", fg=color)
        
        # Update progress bar based on state
        progress_values = {
            'Initialization': 10,
            'Ready': 25,
            'Countdown': 50,
            'Racing': 75,
            'Placement': 90,
            'Finished': 100,
            'Intermission': 0,
            'Reset': 0
        }
        
        self.race_progress['value'] = progress_values.get(state, 0)
        
        # Update state details
        details = self.get_state_details(state)
        self.state_details.delete(1.0, tk.END)
        self.state_details.insert(1.0, details)
        
        # Update gate operation status
        gate_status_map = {
            'Initialization': "🚪 Gate: Initializing",
            'Ready': "🚪 Gate: Ready, closed", 
            'Countdown': "🚪 Gate: About to open",
            'Racing': "🚪 Gate: OPEN - Racing!",
            'Placement': "🚪 Gate: Open, finishing",
            'Finished': "🚪 Gate: Closing",
            'Intermission': "🚪 Gate: Closed",
            'Reset': "🚪 Gate: Resetting"
        }
        
        gate_status = gate_status_map.get(state, "🚪 Gate: Unknown")
        self.gate_operation_status.config(text=gate_status)
    
    def get_state_details(self, state):
        """Get detailed information for current state"""
        details = {
            'Initialization': """▪ Start gate initializing
▪ Checking motor connection
▪ Testing LED matrix
▪ Verifying audio system
▪ Connecting to central server""",
            
            'Ready': """▪ Start gate ready for race
▪ All components operational
▪ Gate secured in closed position
▪ Awaiting race setup
▪ Ready for countdown""",
            
            'Countdown': """▪ Race countdown active
▪ Audio/visual countdown playing
▪ Gate preparing to open
▪ Final systems check
▪ Cars ready to launch""",
            
            'Racing': """▪ GATE OPEN - RACE ACTIVE!
▪ Cars have been released
▪ Race timing in progress
▪ Monitoring race progress
▪ Waiting for finish results""",
            
            'Placement': """▪ Race finishing
▪ Cars crossing finish line
▪ Calculating final positions
▪ Processing timing data
▪ Determining winner""",
            
            'Finished': """▪ Race completed
▪ Final results calculated
▪ Gate closing for next race
▪ Cleaning up race data
▪ Preparing for intermission""",
            
            'Intermission': """▪ Between races
▪ Gate closed and secured
▪ Playing intermission content
▪ System in standby
▪ Awaiting next race""",
            
            'Reset': """▪ Resetting for next race
▪ Clearing previous data
▪ Repositioning components
▪ Refreshing configurations
▪ Preparing initialization"""
        }
        
        return details.get(state, "Unknown state")
    
    def update_component_display(self, data):
        """Update component status from central server data"""
        # Clear existing items
        for item in self.component_tree.get_children():
            self.component_tree.delete(item)
        
        # Extract component info from server data
        components_info = data.get('components', {})
        status = data.get('status', 'Unknown')
        timestamp = data.get('timestamp', 0)
        
        # Default components to show
        component_names = ['Motor', 'LED Matrix', 'Audio', 'BuildHAT', 'Central Server']
        
        all_ok = True
        for component in component_names:
            comp_status = components_info.get(component.lower().replace(' ', '_'), 'Unknown')
            
            # Status icon
            if comp_status == 'OK' or comp_status == 'Connected':
                icon = '✅'
                status_text = 'OK'
            else:
                icon = '❌'
                status_text = comp_status
                all_ok = False
            
            # Details based on component type
            details = 'Active'
            if 'motor' in component.lower():
                details = 'LEGO WeDo Motor'
            elif 'matrix' in component.lower():
                details = '3x3 LED Display'
            elif 'audio' in component.lower():
                details = 'pygame mixer'
            elif 'buildhat' in component.lower():
                details = 'Raspberry Pi HAT'
            elif 'server' in component.lower():
                details = 'Socket.IO connection'
            
            self.component_tree.insert('', 'end', text=f"{icon} {component}", 
                                     values=(status_text, details))
        
        # Update overall status
        if all_ok:
            self.overall_status.config(text="Status: ALL SYSTEMS OK", fg='lime')
        else:
            self.overall_status.config(text="Status: ISSUES DETECTED", fg='red')
        
        # Update timestamp
        if timestamp:
            update_time = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            self.last_update.config(text=f"Last Update: {update_time}")
    
    def update_config_display(self, config_data):
        """Update configuration display"""
        self.config_text.delete(1.0, tk.END)
        
        config_text = "Start Gate Configuration:\n"
        config_text += "=" * 30 + "\n\n"
        
        # Sort and display config
        for key, value in sorted(config_data.items()):
            config_text += f"{key}: {value}\n"
        
        self.config_text.insert(1.0, config_text)
        self.config_status.config(text=f"Config updated: {datetime.now().strftime('%H:%M:%S')}")
    
    def update_performance_display(self, perf_data):
        """Update performance metrics"""
        connected_status = "Connected" if perf_data['server_connected'] else "Disconnected"
        monitor_status = "Active" if perf_data['monitor_active'] else "Inactive"
        
        text = f"Monitor: {monitor_status} | Server: {connected_status} | UI Memory: {perf_data['ui_memory']}MB"
        self.performance_label.config(text=text)
    
    def add_log_entry(self, message):
        """Add entry to activity log"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"{timestamp} {message}\n"
        
        self.activity_log.config(state='normal')
        self.activity_log.insert(tk.END, log_entry)
        self.activity_log.see(tk.END)  # Auto-scroll to bottom
        self.activity_log.config(state='disabled')
    
    def clear_activity_log(self):
        """Clear the activity log display"""
        self.activity_log.config(state='normal')
        self.activity_log.delete(1.0, tk.END)
        self.activity_log.config(state='disabled')
        self.add_log_entry("🗑️ Activity log cleared")
    
    def run(self):
        """Start the UI application"""
        self.add_log_entry("🚀 Start Gate Monitor UI initialized")
        self.add_log_entry(f"👁️ Monitoring gate type: {GATE_TYPE}")
        
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.add_log_entry("👋 Monitor UI shutting down...")

def main():
    """Main entry point"""
    logging.basicConfig(level=logging.INFO)
    ui = StartGateUI()
    ui.run()

if __name__ == "__main__":
    main()