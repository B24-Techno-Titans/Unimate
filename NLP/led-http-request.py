# import requests

# LED_OFF_URL = "http://led-controller.local/set-colour?rgb=%2300ff00&brightness=0"

# # LED_OFF_URL = "http://fan-controller.local/set-speed?speed=3"

# requests.get(LED_OFF_URL, timeout=3)

humidifier_url = "http://humidifier.local/press"


import requests

BASE_URL = "http://led-controller.local/set-colour?rgb=%23123456&brightness=200"

FAN_URL = "http://smart-fan.local/set-speed?speed=2"

response = requests.get(BASE_URL,timeout=3)

print("Status:", response.status_code) 
print("Response:", response.text)