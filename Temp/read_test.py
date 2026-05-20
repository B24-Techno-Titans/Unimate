import json, time

with open("temp_data.json") as f:
    while True:
        line = f.readline()
        print("JSON = ", line)
        if len(line) > 0:
            data = json.loads(line)
            print(f"Temperature = {data['r_temp']}")
        else:
            print("No data yet")
        
        f.seek(0)
        time.sleep(2)
