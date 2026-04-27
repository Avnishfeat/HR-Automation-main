import os
import time
import undetected_chromedriver as uc
from pathlib import Path

def main():
    print("==================================================")
    print("Google Meet Bot Authentication Setup")
    print("==================================================")
    print("Starting Chrome browser with the bot's profile...")
    
    # Path to the same profile directory used by the meet_controller
    base_dir = Path(__file__).parent.parent.parent.parent.parent
    profile_path = os.path.abspath(os.path.join(base_dir, "chrome_profile"))
    
    print(f"Profile path: {profile_path}")
    os.makedirs(profile_path, exist_ok=True)
    
    options = uc.ChromeOptions()
    options.add_argument(f'--user-data-dir={profile_path}')
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-plugins-discovery')
    
    # Needs to match installed Chrome version based on previous errors
    driver = uc.Chrome(options=options, version_main=146)
    
    print("\nNavigating to Google Login...")
    driver.get('https://accounts.google.com/signin')
    
    print("\n---> ACTION REQUIRED <---")
    print("Please log into the Google account you want the bot to use.")
    print("Once you are fully logged in and see your account dashboard/avatar,")
    print("you can simply close this terminal window or press Ctrl+C.")
    print("The session will be saved automatically to the chrome_profile folder.")
    print("\nWaiting for you to login... (Press Ctrl+C when done)")
    
    try:
        # Keep the browser open indefinitely until the user manually closes it or hits Ctrl+C
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nClosing browser and saving session...")
    finally:
        driver.quit()
        print("Setup complete! Your bot will now use this logged-in session.")

if __name__ == "__main__":
    main()
