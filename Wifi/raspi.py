import socket
import threading
import time
import json
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, Any


ESP32_HOST = 'unimate-esp.local' #esp32 ip
ESP32_PORT = 80 #esp32 port
RECONNECT_DELAY = 5 # connect again in?

#globle var for dta
latest_esp32_data: Dict[str, Any] = {"message": "Awaiting data from ESP32...", "timestamp": time.time()}


 #fetch data from esp32 server
#-----------------------------------------------------------

#fake function for test
def read_esp32_data():
    """???? ESP32 ????????????? ?????? ?????? ??????? ???? ???? ????."""
    global latest_esp32_data
    
    
    while True:
        
        mock_temperature = round(random.uniform(10.0, 50.0), 2)
        
        latest_esp32_data = {
            "status": "OK",
            "device": "ESP32_MOCK",
            "temperature_c": mock_temperature,
            "timestamp": time.time(),
            "time_readable": time.ctime()
        }
        
        print(f"MOCK DATA Updated: {latest_esp32_data['temperature_c']} C")
        
        time.sleep(2)

# def read_esp32_data():
#     """ connect to ESP32 server"""
#     global latest_esp32_data
    
    # while True:
    #     try:
    #         # Socket 
    #         client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #         client_socket.settimeout(10) # 10s timeout
            
    #         print(f"Attempting to connect to ESP32 at {ESP32_HOST}:{ESP32_PORT}...")
    #         client_socket.connect((ESP32_HOST, ESP32_PORT))
    #         print("Successfully connected to ESP32.")
            
    #        
    #         while True:
    #             
    #             data = client_socket.recv(1024) 
    #             if not data:
    #                
    #                 print("ESP32 server closed the connection.")
    #                 break

    #             # decode data
    #             decoded_data = data.decode('utf-8').strip()
                
    #            #update globle var
    #             latest_esp32_data = {
    #                 "message": decoded_data,
    #                 "timestamp": time.time()
    #             }
                
    #             print(f"Received: {decoded_data}")
    #             time.sleep(1) 

    #     except socket.timeout:
    #         print("Connection timed out. Retrying...")
            
    #     except ConnectionRefusedError:
    #         print(f"Connection Refused. Ensure ESP32 is running and IP ({ESP32_HOST}) is correct.")
            
    #     except Exception as e:
    #         print(f"An error occurred in client: {e}")
            
    #     finally:
    #    
    #         client_socket.close()
    #         print(f"Waiting {RECONNECT_DELAY} seconds before retrying connection...")
    #         time.sleep(RECONNECT_DELAY)
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

# API Endpoint 
@app.get("/data", response_model=Dict[str, Any], summary="Get Latest Data from ESP32")
async def get_latest_data():
    """json format data."""
    return latest_esp32_data

#