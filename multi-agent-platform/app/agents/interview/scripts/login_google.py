import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    print("==================================================")
    print("Google Meet Bot Authentication Setup (Playwright)")
    print("==================================================")
    print("Starting Chromium browser with the bot's profile...")
    
    # Path to the profile directory
    base_dir = Path(__file__).parent.parent.parent.parent.parent
    profile_path = os.path.abspath(os.path.join(base_dir, "chrome_profile"))
    
    print(f"Profile path: {profile_path}")
    os.makedirs(profile_path, exist_ok=True)
    
    with sync_playwright() as p:
        # We need a headed browser so the user can actually type their password
        # Disable headless mode for this specific script
        browser = p.chromium.launch_persistent_context(
            user_data_dir=profile_path,
            headless=False,
            channel="chromium",
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        page = browser.pages[0] if browser.pages else browser.new_page()
        
        # Mask webdriver
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            })
        """)
        
        print("\nNavigating to Google Login...")
        page.goto('https://accounts.google.com/signin')
        
        print("\n---> ACTION REQUIRED <---")
        print("Please log into the Google account you want the bot to use in the browser window.")
        print("Once you are fully logged in and see your account dashboard/avatar,")
        print("you can simply close the browser window or press Ctrl+C here in the terminal.")
        print("The session will be saved automatically to the chrome_profile folder.")
        print("\nWaiting for you to login... (Close the browser window when done)")
        
        try:
            # Wait for the browser to be closed by the user
            page.wait_for_event("close", timeout=0)
        except KeyboardInterrupt:
            print("\nInterrupt received. Closing browser...")
        except Exception as e:
            # If the user closes the whole context or there's an error
            pass
        finally:
            try:
                browser.close()
            except:
                pass
            print("Setup complete! Your bot will now use this logged-in session.")

if __name__ == "__main__":
    main()
