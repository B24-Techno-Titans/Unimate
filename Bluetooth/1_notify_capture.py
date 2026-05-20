import asyncio
from bleak import BleakClient

ESP32_MAC = "08:92:72:85:AE:8A"   # Replace with your actual device MAC
CHAR_UUID = "84487d20-c5fc-484e-a7d9-91b5bb395ae2"

def notify_handler(sender, data):
    print(f"Notification from {sender}: {data}")

async def notify_listen():
    async with BleakClient(ESP32_MAC, adapter="hci0", timeout=20.0) as client:
        if not await client.is_connected():
            print("❌ Failed to connect.")
            return
        print("✅ Connected to ESP32.")
        await client.start_notify(CHAR_UUID, notify_handler)
        await asyncio.sleep(60)
        await client.stop_notify(CHAR_UUID)

asyncio.run(notify_listen())
