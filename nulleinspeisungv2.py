#!/usr/bin/env python3
import requests, time, sys, logging, argparse
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
maximum_wr2 = 1700              # Maximum output (W) for inverter 2
minimum_wr2 = 200               # Minimum output (W) for inverter 2
# Note: Inverter2 is now always updated so its load is controlled
default_altes_limit2 = 100      # Fallback current limit for inverter 2 if DTU data is not available

# OpenDTU and Shelly connection configuration
dtu_ip = '192.168.179.152'      # IP address of OpenDTU
dtu_nutzer = 'admin'            # OpenDTU username
dtu_passwort = 'openDTU42'      # OpenDTU password
shelly_ip = '192.168.179.112'    # IP address of Shelly 3EM

# API Endpoints
dtu_status_url = f'http://{dtu_ip}/api/livedata/status/inverters'
dtu_config_url = f'http://{dtu_ip}/api/limit/config'
shelly_status_url = f'http://{shelly_ip}/rpc/EM.GetStatus?id=0'

# ------------------------------------------------------------------------------
# Custom Color Formatter for logging with emojis
# ------------------------------------------------------------------------------
class ColorFormatter(logging.Formatter):
    # ANSI escape codes for colors
    COLORS = {
        "DEBUG": "\033[34m",    # Blue
        "INFO": "\033[32m",     # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",    # Red
        "CRITICAL": "\033[1;31m"  # Bold Red
    }
    RESET = "\033[0m"

    # Emojis per level
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
# DTU status fetching
# ------------------------------------------------------------------------------
def fetch_dtu_status():
    """
    Fetch the complete DTU status JSON, which contains both inverters and total production.
    """
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
    """Fetch and parse data from the Shelly 3EM API."""
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
    """
    Extracts relevant data from an inverter JSON dict.
    Returns: (reachable, producing, limit_absolute, power, name)
    """
    reachable = inverter.get('reachable', False)
    # Convert 'producing' to int (if boolean, True->1, False->0)
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
    """Send a new inverter limit to OpenDTU for a given inverter serial."""
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
    """Test connectivity to a given URL using a GET request."""
    try:
        response = requests.get(url, headers=headers, auth=auth, timeout=timeout)
        response.raise_for_status()
        logging.info(f"✅ Connection test successful for {url}")
        return True
    except Exception as e:
        logging.error(f"❌ Connection test failed for {url}: {e}")
        return False

def test_api_endpoints():
    """Test connectivity for DTU status, Shelly status, and DTU configuration endpoints."""
    all_ok = True

    if not test_connection(dtu_status_url):
        all_ok = False
    if not test_connection(shelly_status_url, headers={'Content-Type': 'application/json'}):
        all_ok = False

    # Test configuration endpoint for inverter 1
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

    # Test configuration endpoint for inverter 2 if enabled
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
        # Fetch DTU status once
        dtu_status = fetch_dtu_status()
        if dtu_status is None:
            logging.warning("⚠️ Skipping iteration due to DTU errors.")
            time.sleep(10)
            continue

        # Extract total inverter production from DTU data
        total_power = dtu_status.get('total', {}).get('Power', {}).get('v', 0)
        inverters = dtu_status.get('inverters', [])
        if len(inverters) < 1:
            logging.error("❌ No inverter data available in DTU response.")
            time.sleep(10)
            continue

        # Extract inverter 1 data
        inverter1 = inverters[0]
        reachable1, producing1, altes_limit1, power1, name1 = extract_inverter_data(inverter1, "Inverter 1")

        # Extract inverter 2 data (if available and enabled)
        if enable_second_inverter and len(inverters) >= 2:
            inverter2 = inverters[1]
            reachable2, producing2, altes_limit2, power2, name2 = extract_inverter_data(inverter2, "Inverter 2")
        else:
            logging.warning("⚠️ Inverter 2 data not available; using fallback values.")
            altes_limit2 = default_altes_limit2
            name2 = "Inverter 2"

        # Fetch Shelly grid data
        grid_sum = fetch_shelly_data()
        if grid_sum is None:
            logging.warning("⚠️ Skipping iteration due to Shelly errors.")
            time.sleep(10)
            continue

        # Log the current status using total production from DTU
        logging.info(f"⚡ Grid Power: {round(grid_sum, 0)} W | 🔋 {name1} AC Power: {round(power1, 0)} W | 🏭 Total Production: {round(total_power, 0)} W")

        # Process inverter 1
        if reachable1:
            setpoint1 = grid_sum + altes_limit1 - 5
            if setpoint1 > maximum_wr:
                setpoint1 = maximum_wr
                logging.info(f"🚀 {name1} setpoint capped at maximum: {maximum_wr} W")
            elif setpoint1 < minimum_wr:
                setpoint1 = minimum_wr
                logging.info(f"🔋 {name1} setpoint raised to minimum: {minimum_wr} W")
            else:
                logging.info(f"💡 {name1} setpoint calculated: {setpoint1} W")

            if round(setpoint1 / 50, 0) != round(altes_limit1 / 50, 0):
                logging.info(f"🔄 Updating {name1} limit from {altes_limit1} W to {setpoint1} W")
                update_inverter_limit(serial, setpoint1)
            else:
                logging.info("👌 No significant change in inverter 1 setpoint; no update necessary.")
        else:
            logging.warning(f"⚠️ {name1} DTU not reachable; skipping update.")

        # Process inverter 2 if enabled
        if enable_second_inverter:
            # Determine shortfall: if inverter 1 is not saturated, shortfall is zero.
            if setpoint1 < maximum_wr:
                shortfall = 0
                logging.info(f"😊 {name1} is not saturated; no shortfall detected.")
            else:
                shortfall = max(0, grid_sum - maximum_wr)
                logging.info(f"⚠️ {name1} is saturated; shortfall = {shortfall} W")

            # Calculate setpoint for inverter 2 using its own limit (from DTU data if available) plus the shortfall.
            setpoint2 = altes_limit2 + shortfall - 5
            if setpoint2 > maximum_wr2:
                setpoint2 = maximum_wr2
                logging.info(f"🚀 {name2} setpoint capped at maximum: {maximum_wr2} W")
            elif setpoint2 < minimum_wr2:
                setpoint2 = minimum_wr2
                logging.info(f"🔋 {name2} setpoint raised to minimum: {minimum_wr2} W")
            else:
                logging.info(f"💡 {name2} setpoint calculated: {setpoint2} W")

            logging.info(f"🔄 Updating {name2} limit to {setpoint2} W")
            update_inverter_limit(serial2, setpoint2)

        sys.stdout.flush()
        time.sleep(10)

# ------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    logging.info("🚀 Starting nulleinspeisung script with enhanced logging, connection tests, and dual inverter support")
    if not test_api_endpoints():
        logging.error("❌ One or more API endpoints are not reachable. Exiting.")
        sys.exit(1)
    else:
        logging.info("✅ All API endpoints are reachable. Entering main loop.")
    main_loop()

