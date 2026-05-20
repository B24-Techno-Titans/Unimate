from bleak import BleakClient
from bleak import BleakScanner
import asyncio
import struct

ESP32_MAC = "08:92:72:85:AE:8A"
CHAR_UUID = "84487d20-c5fc-484e-a7d9-91b5bb395ae2"

def notify_handler(source, data):
    val = struct.unpack("f", data)[0]
    print(f"{val} recieved from {source}")

async def notify_listen():
    device = await BleakScanner.find_device_by_name("ESP32-Notifier", timeout=10.0)
    if not device:
        print("Device not found")
        return

    async with BleakClient(ESP32_MAC, adapter="hci0", address_type="random") as client:
        print(f"Client ==> {client}")
        if(client.is_connected):
            print(f"Connected to {client}")
        else:
            print("Not Connected")
            return
        
        await asyncio.sleep(1.0)
        
        # For Debugging
        services = client.services()
        for service in services:
            print(service)
            for char in service.characteristics:
                print(f" {char}")

        await client.start_notify(CHAR_UUID, notify_handler)

        while(client.is_connected):
            await asyncio.sleep(2)

        await client.stop_notify(CHAR_UUID)

asyncio.run(notify_listen())
