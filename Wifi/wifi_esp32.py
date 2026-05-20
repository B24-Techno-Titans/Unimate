import requests
import json
import time

# The mDNS hostname set in the ESP32 code
ESP_HOSTNAME = "http://unimate-esp.local"
DATA_ENDPOINT = "/data"

def fetch_sensor_data():
    """Fetches and prints sensor data from the ESP32 via mDNS."""
    url = ESP_HOSTNAME + DATA_ENDPOINT
    
    print(f"Attempting to fetch data from: {url}")
    
    try:
        # Use a timeout to prevent the script from hanging forever
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            # Parse the JSON response
            data = response.json()
            
            # Print the data
            # print("-" * 30)
            # print(f"Received Data at: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            # # print(f"Received JSON String -> {response.text}")
            # print(f"HR = {data['heartRate']}\tSpO2 = {data['spO2']}\tTemp = {data['temperature']}")
            # print("-" * 30)
           
            # return data; # Return dictionary with sensor data
            return response.text

        else:
            print(f"ERROR: Failed to get data. Status Code: {response.status_code}")
            
    except requests.exceptions.Timeout:
        print("ERROR: Request timed out. Check network connection.")
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Connection error. Is the ESP32 at {ESP_HOSTNAME} running?")
    except json.JSONDecodeError:
        print("ERROR: Failed to decode JSON response from ESP32.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

# If run Directly (not imported)
if __name__ == "__main__":
    print("Raspberry Pi Sensor Client Started. Press Ctrl+C to stop.")
    while True:
        fetch_sensor_data()
        # Wait for 5 seconds before polling again
        time.sleep(5)
