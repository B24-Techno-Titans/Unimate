import TempSensor as temp
import LED_Strip as led

def shift_color_by_temp(rgb, temp_c, strength=0.5):
    """
    Shifts a single RGB color towards Blue (Cold) or Orange (Hot).
    
    Args:
        rgb (tuple): The input color (R, G, B) integers 0-255.
        temp_c (float): The physical temperature in Celsius.
        strength (float): How much to tint the color (0.0 to 1.0).
                          0.1 is subtle, 1.0 replaces the color entirely.
    
    Returns:
        tuple: The adjusted (R, G, B).
    """
    r, g, b = rgb
    
    # Target Tints (Psychological mapping)
    # Cold Target = Deep Sky Blue
    COLD_COLOR = (0, 100, 255) 
    # Hot Target  = Orange Red
    WARM_COLOR = (255, 100, 0)
    
    # Define Neutral Temperature (e.g., 20°C)
    NEUTRAL_TEMP = 27.0
    
    # 1. Determine direction and blend factor
    delta = temp_c - NEUTRAL_TEMP
    
    # We clamp the "mix amount" between 0.0 and 1.0
    # We assume a 40 degree difference reaches max intensity
    factor = min(abs(delta) / 40.0, 1.0) * strength

    target_color = rgb # Default to no change

    if delta > 0:
        # Warmer than neutral -> Blend towards WARM_COLOR
        target_color = WARM_COLOR
    elif delta < 0:
        # Colder than neutral -> Blend towards COLD_COLOR
        target_color = COLD_COLOR
        
    # 2. Perform Linear Interpolation (Lerp)
    # Formula: result = current * (1 - factor) + target * factor
    new_r = r * (1 - factor) + target_color[0] * factor
    new_g = g * (1 - factor) + target_color[1] * factor
    new_b = b * (1 - factor) + target_color[2] * factor
    
    # 3. Return as integer tuple
    return (int(new_r), int(new_g), int(new_b))

# # --- Usage ---

# my_color = (200, 200, 200) # Light Gray

# # 1. Freezing (-10°C)
# cold_shifted = shift_color_by_temp(my_color, -10)
# print(f"Original: {my_color} -> Cold (-10°C): {cold_shifted}")
# # Expect: Higher Blue, Lower Red

# # 2. Neutral (20°C)
# neutral_shifted = shift_color_by_temp(my_color, 20)
# print(f"Original: {my_color} -> Neutral (20°C): {neutral_shifted}")
# # Expect: No change

# # 3. Hot (40°C)
# hot_shifted = shift_color_by_temp(my_color, 40)
# print(f"Original: {my_color} -> Hot (40°C): {hot_shifted}")
# # Expect: Higher Red, Lower Blue

try:
    while True:
        rgb = led.get_current_color()
except KeyboardInterrupt:
    print("Exiting...")

