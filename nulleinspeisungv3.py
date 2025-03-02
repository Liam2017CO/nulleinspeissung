#!/usr/bin/env python3
import requests, time, sys, logging, argparse, sqlite3, datetime
from requests.auth import HTTPBasicAuth

# ------------------------------------------------------------------------------
# Configuration (Update these as needed)
# ------------------------------------------------------------------------------
# Inverter 1 configuration
serial = "116492226387"         # Serial number of the Hoymiles inverter
maximum_wr = 2000               # Maximum inverter output (W) for inverter 1
minimum_wr = 200                # Minimum inverter output (W) for inverter 1

# Inverter 2 configuration
enable_second_inverter = True   # Enable/disable second inverter support
serial2 = "1164a00b64e3"         # Serial number for inverter 2 (if enabled)
maximum_wr2 = 1500              # Maximum output (W) for inverter 2
minimum_wr2 = 200               # Minimum output (W) for inverter 2
default_altes_limit2 = 200      # Fallback current limit for inverter 2 if DTU data is not available

# OpenDTU and Shelly connection configuration
dtu_ip = '192.168.179.152'      # IP address of OpenDTU
dtu_nutzer = 'admin'            # OpenDTU username
dtu_passwort = 'openDTU42'      # OpenDTU password
shelly_ip = '192.168.179.112'    # IP address of Shelly 3EM

# API Endpoints
dtu_status_url = f'http://{dtu_ip}/api/livedata/status/inverters'
dtu_config_url = f'http://{dtu_ip}/api/limit/config'
shelly_status_url = f'http://{shelly_ip}/rpc/EM.GetStatus?id=0'

# SQLite database file
db_file = "power_data.db"

# ------------------------------------------------------------------------------
# Custom Color Formatter for logging with emojis
# ------------------------------------------------------------------------------
class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[34m",    # Blue
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[1;31m"  # Bold Red
    }
    RESET = "\033[0m"
    EMOJIS = {
        "DEBUG": "🔍",
        "INFO": "💡",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🛑"
    }
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{self.EMOJIS[levelname]} {levelname}{self.RESET}"
        return super().format(record)

# ------------------------------------------------------------------------------
# Argument parsing for debug mode
# ------------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Script to communicate with Shelly 3EM Pro and OpenDTU")
parser.add_argument('--debug', action='store_true', help="Enable debug mode with detailed logging output")
args = parser.parse_args()

# ------------------------------------------------------------------------------
# Logging configuration based on debug flag using our ColorFormatter
# ------------------------------------------------------------------------------
log_level = logging.DEBUG if args.debug else logging.INFO
handler = logging.StreamHandler(sys.stdout)
formatter = ColorFormatter(fmt='%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
handler.setFormatter(formatter)
logging.basicConfig(level=log_level, handlers=[handler])

# ------------------------------------------------------------------------------
# SQLite Database Initialization
# ------------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS power_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            grid_power REAL,
            inverter1_power REAL,
            inverter2_power REAL,
            total_production REAL,
            inverter1_setpoint REAL,
            inverter2_setpoint REAL,
            inverter1_reachable INTEGER,
            inverter2_reachable INTEGER,
            dtus_error INTEGER,
            shelly_error INTEGER
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("✅ SQLite database initialized.")

def store_data(grid_power, inverter1_power, inverter2_power, total_production,
               inverter1_setpoint, inverter2_setpoint,
               inverter1_reachable, inverter2_reachable,
               dtus_error, shelly_error):
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO power_data (
                grid_power, inverter1_power, inverter2_power, total_production,
                inverter1_setpoint, inverter2_setpoint,
                inverter1_reachable, inverter2_reachable,
                dtus_error, shelly_error
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ''', (grid_power, inverter1_power, inverter2_power, total_production,
              inverter1_setpoint, inverter2_setpoint,
              inverter1_reachable, inverter2_reachable,
              dtus_error, shelly_error))
        conn.commit()
        conn.close()
        logging.debug("Data stored in SQLite database.")
    except Exception as e:
        logging.error(f"❌ Error storing data in SQLite DB: {e}", exc_info=True)

# ------------------------------------------------------------------------------
# DTU status fetching
# ------------------------------------------------------------------------------
def fetch_dtu_status():
    try:
        response = requests.get(dtu_status_url, timeout=5)
        response.raise_for_status()
        r = response.json()
        logging.debug(f"DTU response: {r}")
        return r
    except Exception as e:
        logging.error("❌ Error fetching DTU status: " + str(e), exc_info=True)
        return None

# ------------------------------------------------------------------------------
# Shelly data fetching
# ------------------------------------------------------------------------------
def fetch_shelly_data():
    try:
        response = requests.get(shelly_status_url, headers={'Content-Type': 'application/json'}, timeout=5)
        response.raise_for_status()
        r = response.json()
        logging.debug(f"Shelly response: {r}")
        grid_sum = r.get('total_act_power', None)
        if grid_sum is None:
            raise ValueError("total_act_power not found in Shelly response")
        return grid_sum
    except Exception as e:
        logging.error("❌ Error fetching Shelly data: " + str(e), exc_info=True)
        return None

# ------------------------------------------------------------------------------
# Helper function to extract inverter data from DTU status
# ------------------------------------------------------------------------------
def extract_inverter_data(inverter, default_name):
    reachable = inverter.get('reachable', False)
    producing = 1 if inverter.get('producing', False) else 0
    limit_absolute = int(inverter.get('limit_absolute', 0))
    # Try to extract power data from AC; if absent, default to 0.
    if 'AC' in inverter:
        power = inverter.get('AC', {}).get('0', {}).get('Power', {}).get('v', 0)
    else:
        power = 0
    name = inverter.get('name', default_name)
    return reachable, producing, limit_absolute, power, name

# ------------------------------------------------------------------------------
# Update function for inverter limit
# ------------------------------------------------------------------------------
def update_inverter_limit(serial_param, new_limit):
    try:
        data_payload = f'data={{"serial":"{serial_param}", "limit_type":0, "limit_value":{new_limit}}}'
        logging.debug(f"Sending configuration payload for serial {serial_param}: {data_payload}")
        response = requests.post(
            dtu_config_url,
            data=data_payload,
            auth=HTTPBasicAuth(dtu_nutzer, dtu_passwort),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=5
        )
        response.raise_for_status()
        result = response.json()
        logging.info(f"✅ Updated inverter ({serial_param}) limit successfully: {result.get('type', 'No type in response')}")
    except Exception as e:
        logging.error(f"❌ Error updating inverter limit for serial {serial_param}: {e}", exc_info=True)

# ------------------------------------------------------------------------------
# Connection test functions
# ------------------------------------------------------------------------------
def test_connection(url, headers=None, auth=None, timeout=5):
    try:
        response = requests.get(url, headers=headers, auth=auth, timeout=timeout)
        response.raise_for_status()
        logging.info(f"✅ Connection test successful for {url}")
        return True
    except Exception as e:
        logging.error(f"❌ Connection test failed for {url}: {e}")
        return False

def test_api_endpoints():
    all_ok = True
    if not test_connection(dtu_status_url):
        all_ok = False
    if not test_connection(shelly_status_url, headers={'Content-Type': 'application/json'}):
        all_ok = False
    try:
        data_payload = f'data={{"serial":"{serial}", "limit_type":0, "limit_value":{minimum_wr}}}'
        response = requests.post(
            dtu_config_url,
            data=data_payload,
            auth=HTTPBasicAuth(dtu_nutzer, dtu_passwort),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=5
        )
        response.raise_for_status()
        logging.info(f"✅ Configuration endpoint test successful for inverter 1 at {dtu_config_url}")
    except Exception as e:
        logging.error(f"❌ Configuration endpoint test failed for inverter 1 at {dtu_config_url}: {e}")
        all_ok = False
    if enable_second_inverter:
        try:
            data_payload = f'data={{"serial":"{serial2}", "limit_type":0, "limit_value":{minimum_wr2}}}'
            response = requests.post(
                dtu_config_url,
                data=data_payload,
                auth=HTTPBasicAuth(dtu_nutzer, dtu_passwort),
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=5
            )
            response.raise_for_status()
            logging.info(f"✅ Configuration endpoint test successful for inverter 2 at {dtu_config_url}")
        except Exception as e:
            logging.error(f"❌ Configuration endpoint test failed for inverter 2 at {dtu_config_url}: {e}")
            all_ok = False
    return all_ok

# ------------------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------------------
def main_loop():
    while True:
        dtus_error = 0
        shelly_error = 0
        # Fetch DTU status
        dtu_status = fetch_dtu_status()
        if dtu_status is None:
            dtus_error = 1
            logging.warning("⚠️ DTU error encountered; DTU data will be stored as NULL.")
        # Fetch Shelly data
        grid_sum = fetch_shelly_data()
        if grid_sum is None:
            shelly_error = 1
            logging.warning("⚠️ Shelly error encountered; grid power will be stored as NULL.")

        # Initialize variables for DTU data
        inverter1_power = None
        inverter2_power = None
        total_production = None
        inverter1_setpoint = None
        inverter2_setpoint = None
        inverter1_reachable = 0
        inverter2_reachable = 0

        if dtu_status is not None:
            total_production = dtu_status.get('total', {}).get('Power', {}).get('v', 0)
            inverters = dtu_status.get('inverters', [])
            if len(inverters) < 1:
                logging.error("❌ No inverter data available in DTU response.")
            else:
                # Process inverter 1
                inverter1 = inverters[0]
                inverter1_data = extract_inverter_data(inverter1, "Inverter 1")
                inverter1_reachable = 1 if inverter1_data[0] else 0
                _, _, altes_limit1, inverter1_power, name1 = inverter1_data
                if inverter1_reachable:
                    inverter1_setpoint = (grid_sum + altes_limit1 - 5) if grid_sum is not None else None
                    if inverter1_setpoint is not None:
                        if inverter1_setpoint > maximum_wr:
                            inverter1_setpoint = maximum_wr
                            logging.info(f"🚀 {name1} setpoint capped at maximum: {maximum_wr} W")
                        elif inverter1_setpoint < minimum_wr:
                            inverter1_setpoint = minimum_wr
                            logging.info(f"🔋 {name1} setpoint raised to minimum: {minimum_wr} W")
                        else:
                            logging.info(f"💡 {name1} setpoint calculated: {inverter1_setpoint} W")
                        logging.info(f"🔄 Updating {name1} limit from {altes_limit1} W to {inverter1_setpoint} W")
                        update_inverter_limit(serial, inverter1_setpoint)
                else:
                    logging.warning(f"⚠️ {name1} DTU not reachable; skipping update.")

                # Process inverter 2 if enabled
                if enable_second_inverter:
                    if len(inverters) >= 2:
                        inverter2 = inverters[1]
                        inverter2_data = extract_inverter_data(inverter2, "Inverter 2")
                        inverter2_reachable = 1 if inverter2_data[0] else 0
                        _, _, altes_limit2, inverter2_power, name2 = inverter2_data
                    else:
                        logging.warning("⚠️ Inverter 2 data not available; using fallback values.")
                        altes_limit2 = default_altes_limit2
                        name2 = "Inverter 2"
                    # Determine shortfall for inverter 2:
                    if inverter1_setpoint is not None and inverter1_setpoint < maximum_wr:
                        shortfall = 0
                        logging.info(f"😊 {name1} is not saturated; no shortfall detected.")
                    else:
                        shortfall = max(0, grid_sum - maximum_wr) if grid_sum is not None else 0
                        logging.info(f"⚠️ {name1} is saturated; shortfall = {shortfall} W")
                    inverter2_setpoint = altes_limit2 + shortfall - 5
                    if inverter2_setpoint > maximum_wr2:
                        inverter2_setpoint = maximum_wr2
                        logging.info(f"🚀 {name2} setpoint capped at maximum: {maximum_wr2} W")
                    elif inverter2_setpoint < minimum_wr2:
                        inverter2_setpoint = minimum_wr2
                        logging.info(f"🔋 {name2} setpoint raised to minimum: {minimum_wr2} W")
                    else:
                        logging.info(f"💡 {name2} setpoint calculated: {inverter2_setpoint} W")
                    logging.info(f"🔄 Updating {name2} limit to {inverter2_setpoint} W")
                    update_inverter_limit(serial2, inverter2_setpoint)
        else:
            logging.warning("⚠️ DTU data is unavailable; DTU fields will be stored as NULL.")

        # Log overall status with total production
        logging.info(f"⚡ Grid Power: {round(grid_sum, 1) if grid_sum is not None else 'NULL'} W | "
                     f"🔋 Inverter 1 Power: {round(inverter1_power, 1) if inverter1_power is not None else 'NULL'} W | "
                     f"🏭 Total Production: {round(total_production, 1) if total_production is not None else 'NULL'} W")

        # Store data in SQLite (storing NULLs if data is missing)
        store_data(
            grid_power = grid_sum,
            inverter1_power = inverter1_power,
            inverter2_power = inverter2_power,
            total_production = total_production,
            inverter1_setpoint = inverter1_setpoint,
            inverter2_setpoint = inverter2_setpoint,
            inverter1_reachable = inverter1_reachable,
            inverter2_reachable = inverter2_reachable,
            dtus_error = dtus_error,
            shelly_error = shelly_error
        )
        sys.stdout.flush()
        time.sleep(10)

# ------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    logging.info("🚀 Starting nulleinspeisung script with enhanced logging, SQLite storage, and dual inverter support")
    if not test_api_endpoints():
        logging.error("❌ One or more API endpoints are not reachable. Exiting.")
        sys.exit(1)
    else:
        logging.info("✅ All API endpoints are reachable. Entering main loop.")
    main_loop()
