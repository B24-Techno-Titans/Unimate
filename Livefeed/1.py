from live import toggle_live_feed
import time

# Start
toggle_live_feed("on")

# Wait 1 minute
time.sleep(60)

# Stop
toggle_live_feed("off")


# https://george-superprepared-discrepantly.ngrok-free.dev/cam/