#!/usr/bin/python3
import subprocess
import os
import tempfile
from PIL import Image

def get_sway_resolution():
    """Query the current screen resolution from Sway."""
    try:
        # Use swaymsg to get the output resolution
        result = subprocess.run(
            ["swaymsg", "-t", "get_outputs"],
            capture_output=True,
            text=True,
            check=True
        )
        # Parse the JSON output to extract resolution
        # This is a simplified approach; you may need to adjust based on your swaymsg output
        output = result.stdout.strip()
        if "rect" in output:
            # Extract width and height from the rect field
            import json
            data = json.loads(output)
            for output_data in data:
                if "rect" in output_data:
                    rect = output_data["rect"]
                    width = rect["width"]
                    height = rect["height"]
                    return width, height
    except Exception as e:
        print(f"Error getting resolution from Sway: {e}")
    # Fallback resolution if swaymsg fails
    return 1920, 1080

def generate_wallpaper(width, height, linen_path, logo_path):
    """Generate the wallpaper by tiling the linen image and overlaying the logo."""
    # Create a temporary directory for the wallpaper
    temp_dir = tempfile.gettempdir()
    wallpaper_path = os.path.join(temp_dir, "sway_wallpaper.png")

    # Open the linen image
    linen_img = Image.open(linen_path)
    linen_width, linen_height = linen_img.size

    # Create a new image with the target resolution
    wallpaper = Image.new("RGBA", (width, height))

    # Tile the linen image
    for x in range(0, width, linen_width):
        for y in range(0, height, linen_height):
            wallpaper.paste(linen_img, (x, y))

    # Open the logo image
    logo_img = Image.open(logo_path)
    logo_width, logo_height = logo_img.size

    # Calculate the position to center the logo
    logo_x = (width - logo_width) // 2
    logo_y = (height - logo_height) // 2

    # Overlay the logo
    wallpaper.paste(logo_img, (logo_x, logo_y), logo_img)

    # Save the wallpaper
    wallpaper.save(wallpaper_path)
    return wallpaper_path

def set_sway_wallpaper(wallpaper_path):
    """Set the generated wallpaper as the Sway background."""
    try:
        subprocess.run(
            ["swaymsg", "output", "*", "bg", wallpaper_path, "fill"],
            check=True
        )
    except Exception as e:
        print(f"Error setting wallpaper in Sway: {e}")

def main():
    # Paths to the input images
    linen_path = "/usr/share/backgrounds/sway/desktop-linen.png"
    logo_path = "/usr/share/backgrounds/sway/logo.png"

    # Ensure the input files exist
    if not os.path.exists(linen_path):
        print(f"Error: {linen_path} does not exist.")
        return
    if not os.path.exists(logo_path):
        print(f"Error: {logo_path} does not exist.")
        return

    # Get the screen resolution from Sway
    width, height = get_sway_resolution()
    print(f"Detected resolution: {width}x{height}")

    # Generate the wallpaper
    wallpaper_path = generate_wallpaper(width, height, linen_path, logo_path)
    print(f"Wallpaper generated at: {wallpaper_path}")

    # Set the wallpaper in Sway
    set_sway_wallpaper(wallpaper_path)
    print("Wallpaper set in Sway.")

if __name__ == "__main__":
    main()