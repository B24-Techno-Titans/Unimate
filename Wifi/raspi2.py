# import socket
import asyncio
import threading
import time
import json
import random
import requests
import json
import time
import sys
from pathlib import Path
import os

from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any

PYPATH = Path(__file__).resolve().parent.parent / "LED"
sys.path.append(str(PYPATH))

# imported via unimate environment
from shared_utils import device_controls as dc, TempSensor as temp, LuxSensor as lux
import LED_Strip as led

RECONNECT_DELAY = 5 # connect again in?

#globle var for dta
latest_data: Dict[str, Any] = {"message": "Awaiting data from ESP32...", "timestamp": time.time()}


 #fetch data from esp32 server
#-----------------------------------------------------------
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

            return data; # Return dictionary with sensor data
            # return response.text

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

#fake function for test
# def read_esp32_data():
#    """???? ESP32 ????????????? ?????? ?????? ??????? ???? ???? ????."""
#    global latest_data
   
   
#    while True:
       
#        mock_temperature = round(random.uniform(10.0, 50.0), 2)
       
#        latest_data = {
#            "status": "OK",
#            "device": "ESP32_MOCK",
#            "temperature_c": mock_temperature,
#            "timestamp": time.time(),
#            "time_readable": time.ctime()
#        }
       
#        print(f"MOCK DATA Updated: {latest_data['temperature_c']} C")
       
#        time.sleep(2)

def read_esp32_data():
    """ connect to ESP32 server"""
    global latest_data
    decoded_data = {"heartrate": 0, "spO2": 0, "temperature": 0}
    print("Starting read_esp32_data !!!")
    
    while True:
        try:                     
            while True:
                decoded_data = {"r_temp": temp.get_temp(), "r_humidity": temp.get_humidity(), "lux": lux.get_lux()}
                decoded_data.update(fetch_sensor_data() or {})
                # decoded_data += f"'r_temp':{temp.get_temp()},'r_humidity':{temp.get_humidity()},'lux': {lux.get_lux()}"

                decoded_data = json.dumps(decoded_data)
                
               #update globle var
                latest_data = {
                    "message": decoded_data,
                    "timestamp": time.time()
                }
                
                print(f"Received: {decoded_data}")
                time.sleep(1) 

        # except socket.timeout:
        #     print("Connection timed out. Retrying...")
        except ConnectionRefusedError:
            print(f"Connection Refused. Ensure ESP32 is running and IP ({ESP_HOSTNAME}) is correct.")
            
        except Exception as e:
            print(f"An error occurred in client: {e}")
            
        finally:
            # client_socket.close()
            print(f"Waiting {RECONNECT_DELAY} seconds before retrying connection...")
            time.sleep(RECONNECT_DELAY)
#------------------------------------------------------------------------------------------------------------

# ==========================================================
# 3. FastAPI server configuration
# ==========================================================

app = FastAPI(title="ESP32 Data Bridge API")

# CORS Middleware 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins (for development)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """fastapi server start"""
    client_thread = threading.Thread(target=read_esp32_data, daemon=True)
    client_thread.start()
    print("ESP32 Client thread started successfully.")
    
    temp_loop = threading.Thread(target=temp.update_temp_loop, daemon=True)
    temp_loop.start()
    print("Temperature loop thread started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    led.set_color(0, 0, 0)
    
# API Endpoint 
@app.get("/data", response_model=Dict[str, Any], summary="Get Latest Data from ESP32")
async def get_latest_data():
    """json format data."""
    print(f"Sending : {latest_data}")
    return latest_data

@app.post("/set-color")
async def getcolor(req:Request):
    body=await req.json()
    print("Body: ", body)
    r = int(body.get("r"))
    g = int(body.get("g"))
    b = int(body.get("b"))
    print(r,g,b)

    if(r>255 or g>255 or b>255):
        # print("\nSetting RGB Flow")
        led.start_rgb_flow()
    else:
        led.set_color(r, g, b)

    return {"ok":True}

@app.post("/set-lights")
async def setLights(req:Request):
    body:dict = await req.json()
    print("\033[94m" + "Body: ", body, "\033[0m")

    new_auto = bool(body.get("autoLight", False))
    if(new_auto and not dc.auto_light_on):
        asyncio.create_task(dc.autoBrightness())
    elif(not new_auto and dc.auto_light_on):
        dc.stopAutoBrightness()
    
    dc.auto_light_on = new_auto
    
    dc.control_light(
        rgb = body.get('light', "ffffff"),
        brightness = int(body.get('brightness', 255)),
        )
        
    return {"ok":True}

@app.post("/set-fan")
async def setFan(req:Request):
    body=await req.json()
    print("\033[94m" + "Body: ", body, "\033[0m")
    dc.control_fan(int(body.get('fanSpeed', 0)))

@app.post("/set-humid")
async def setHumid(req:Request):
    body=await req.json()
    print("\033[94m" + "Body: ", body, "\033[0m")

# function to delete old files
def clean_old_files(directory_path,max_files=10):
    files = [os.path.join(directory_path, f) for f in os.listdir(directory_path) if os.path.isfile(os.path.join(directory_path, f))]
    files.sort(key=os.path.getmtime)

    if len(files) > max_files:
        files_to_delete = files[:-max_files]
        for file in files_to_delete:
            try:
                os.remove(file)
                print(f"Deleted old file: {file}")
            except Exception as e:
                print(f"Error deleting file {file}: {e}")
# ----------------------------


# saved directory
Directory="../saved/"
os.makedirs(Directory, exist_ok=True)
@app.post("/mcqs")
async def mcqs(req:Request):
    body=await req.json()
    print("\033[94m" + "Body: ", body, "\033[0m")

    pdf_name = body.get("name", "unknown.pdf")
    json_name = pdf_name.rsplit(".", 1)[0] + ".json"

    filepath = os.path.join(Directory, json_name)

    with open(filepath, "w",encoding="utf-8") as f:
        json.dump(body.get("mcqs"), f,ensure_ascii=False ,indent=4)
    clean_old_files(Directory,max_files=10)
    return {"ok":True}

# camera online status
@app.post("/online")
async def camonline(req: Request):
    body = await req.json() # This will now work perfectly!
    print("\033[94m" + "Body: ", body, "\033[0m")
    return {"ok": True}

DIRECTORY2 = "../questions/"
os.makedirs(DIRECTORY2, exist_ok=True)
@app.post("/get-questions")
async def get_questions(req: Request):
    body = await req.json()

    pdf_name = body.get("name", "unknown.pdf")
    json_name = pdf_name.rsplit(".", 1)[0] + ".json"

    filepath = os.path.join(DIRECTORY2, json_name)

    with open(filepath, "w",encoding="utf-8") as f:
        json.dump(body.get("questions"), f,ensure_ascii=False ,indent=4)
    clean_old_files(DIRECTORY2,max_files=10)
    return {"ok":True}
