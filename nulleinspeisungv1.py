#!/usr/bin/env python3
import requests, time, sys, logging, argparse
from requests.auth import HTTPBasicAuth

# ------------------------------------------------------------------------------
# Configuration (Update these as needed)
# ------------------------------------------------------------------------------
serial = "116492226387"         # Serial number of the Hoymiles inverter
maximum_wr = 2000               # Maximum inverter output (W)
minimum_wr = 200                # Minimum inverter output (W)

dtu_ip = '192.168.179.152'      # IP address of OpenDTU
dtu_nutzer = 'admin'            # OpenDTU username
dtu_passwort = 'openDTU42'      # OpenDTU password

shelly_ip = '192.168.179.112'    # IP address of Shelly 3EM

# API Endpoints
dtu_status_url = f'http://{dtu_ip}/api/livedata/status/inverters'
dtu_config_url = f'http://{dtu_ip}/api/limit/config'
shelly_status_url = f'http://{shelly_ip}/rpc/EM.GetStatus?id=0'

# ------------------------------------------------------------------------------
# Argument parsing for debug mode
# ------------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Script to communicate with Shelly 3EM Pro and OpenDTU")
parser.add_argument('--debug', action='store_true', help="Enable debug mode with detailed logging output")
args = parser.parse_args()

# ------------------------------------------------------------------------------
# Logging configuration based on debug flag
# ------------------------------------------------------------------------------
log_level = logging.DEBUG if args.debug else logging.INFO
logging.basicConfig(
    level=log_level,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ------------------------------------------------------------------------------
# Connection test functions
# ------------------------------------------------------------------------------
def test_connection(url, headers=None, auth=None, timeout=5):
    """Test connectivity to a given URL using a GET request."""
    try:
        response = requests.get(url, headers=headers, auth=auth, timeout=timeout)
        response.raise_for_status()
        logging.info(f"Connection test successful for {url}")
        return True
    except Exception as e:
        logging.error(f"Connection test failed for {url}: {e}")
        return False

def test_api_endpoints():
    """Test connectivity for DTU status, Shelly status, and DTU configuration endpoints."""
    all_ok = True

    if not test_connection(dtu_status_url):
        all_ok = False
    if not test_connection(shelly_status_url, headers={'Content-Type': 'application/json'}):
        all_ok = False

    # Test DTU configuration endpoint with a harmless payload (using the minimum value)
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
        logging.info(f"Configuration endpoint test successful for {dtu_config_url}")
    except Exception as e:
        logging.error(f"Configuration endpoint test failed for {dtu_config_url}: {e}")
        all_ok = False

    return all_ok

# ------------------------------------------------------------------------------
# Data fetching functions
# ------------------------------------------------------------------------------
def fetch_dtu_data():
    """Fetch and parse data from the OpenDTU API."""
    try:
        response = requests.get(dtu_status_url, timeout=5)
        response.raise_for_status()
        r = response.json()
        logging.debug(f"DTU response: {r}")
        inverter = r.get('inverters', [{}])[0]

        reachable   = inverter.get('reachable', False)
        producing   = int(inverter.get('producing', 0))
        altes_limit = int(inverter.get('limit_absolute', 0))
        power_dc    = inverter.get('AC', {}).get('0', {}).get('Power DC', {}).get('v', 0)
        power       = inverter.get('AC', {}).get('0', {}).get('Power', {}).get('v', 0)
        return reachable, producing, altes_limit, power_dc, power
    except Exception as e:
        logging.error("Error fetching DTU data: " + str(e), exc_info=True)
        return None

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
        logging.error("Error fetching Shelly data: " + str(e), exc_info=True)
        return None

# ------------------------------------------------------------------------------
# Update function for inverter limit
# ------------------------------------------------------------------------------
def update_inverter_limit(new_limit):
    """Send a new inverter limit to OpenDTU."""
    try:
        data_payload = f'data={{"serial":"{serial}", "limit_type":0, "limit_value":{new_limit}}}'
        logging.debug(f"Sending configuration payload: {data_payload}")
        response = requests.post(
            dtu_config_url,
            data=data_payload,
            auth=HTTPBasicAuth(dtu_nutzer, dtu_passwort),
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=5
        )
        response.raise_for_status()
        result = response.json()
        logging.info(f"Configuration sent successfully: {result.get('type', 'No type in response')}")
    except Exception as e:
        logging.error("Error updating inverter limit: " + str(e), exc_info=True)

# ------------------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------------------
def main_loop():
    while True:
        dtu_data = fetch_dtu_data()
        shelly_data = fetch_shelly_data()
        if dtu_data is None or shelly_data is None:
            logging.warning("Skipping iteration due to previous errors.")
            time.sleep(10)
            continue

        reachable, producing, altes_limit, power_dc, power = dtu_data
        grid_sum = shelly_data

        logging.info(f"Grid Power: {round(grid_sum, 0)} W, Inverter AC Power: {round(power, 0)} W, Combined: {round(grid_sum + power, 0)} W")
        if reachable:
            # Calculate new setpoint
            setpoint = grid_sum + altes_limit - 5
            logging.info(f"Calculated setpoint: {setpoint} W before applying limits")

            # Enforce maximum and minimum limits
            if setpoint > maximum_wr:
                setpoint = maximum_wr
                logging.info(f"Setpoint capped at maximum: {maximum_wr} W")
            elif setpoint < minimum_wr:
                setpoint = minimum_wr
                logging.info(f"Setpoint raised to minimum: {minimum_wr} W")
            else:
                logging.info(f"Setpoint within limits: {setpoint} W")

            # Check if there is a significant change (granularity step of 50 W)
            if round(setpoint / 50, 0) != round(altes_limit / 50, 0):
                logging.info(f"Updating inverter limit from {altes_limit} W to {setpoint} W")
                update_inverter_limit(setpoint)
            else:
                logging.info("No significant change in setpoint; no update necessary.")
        else:
            logging.warning("DTU not reachable; skipping update.")

        sys.stdout.flush()
        time.sleep(10)

# ------------------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    logging.info("Starting nulleinspeisung script with enhanced logging and connection tests")
    if not test_api_endpoints():
        logging.error("One or more API endpoints are not reachable. Exiting.")
        sys.exit(1)
    else:
        logging.info("All API endpoints are reachable. Entering main loop.")
    main_loop()
