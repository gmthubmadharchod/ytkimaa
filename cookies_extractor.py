from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import pickle
import os

class YouTubeCookieExtractor:
    def __init__(self):
        self.driver = None
        self.two_factor_needed = False
        self.state = "email"  # email, password, 2fa, done
        
    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("--window-size=1920,1080")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 30)
        
    def login_with_email(self, email):
        try:
            self.driver.get("https://accounts.google.com/o/oauth2/auth/identifier?flowName=GlifWebSignIn&flowEntry=ServiceLogin")
            email_input = self.wait.until(EC.presence_of_element_located((By.ID, "identifierId")))
            email_input.send_keys(email)
            self.driver.find_element(By.ID, "identifierNext").click()
            time.sleep(2)
            self.state = "password"
            return {"status": "success", "next": "password"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
    
    def login_with_password(self, password):
        try:
            password_input = self.wait.until(EC.presence_of_element_located((By.NAME, "Passwd")))
            password_input.send_keys(password)
            self.driver.find_element(By.ID, "passwordNext").click()
            time.sleep(3)
            
            # Check for 2FA
            try:
                # Check if 2FA input appears
                two_factor_input = self.driver.find_element(By.ID, "totpPin")
                if two_factor_input:
                    self.two_factor_needed = True
                    self.state = "2fa"
                    return {"status": "2fa_required", "message": "2FA code required"}
            except:
                # No 2FA, proceed to YouTube
                self.driver.get("https://www.youtube.com")
                time.sleep(3)
                self.state = "done"
                cookies = self.extract_cookies()
                self.driver.quit()
                return {"status": "success", "cookies": cookies}
                
            return {"status": "2fa_required"}
        except Exception as e:
            self.driver.quit()
            return {"status": "error", "message": str(e)}
    
    def verify_2fa(self, code):
        try:
            # Try multiple 2FA input methods
            twofa_selectors = [
                (By.ID, "totpPin"),
                (By.NAME, "otc"),
                (By.ID, "idvPin"),
                (By.CSS_SELECTOR, "input[type='tel']")
            ]
            
            code_input = None
            for selector in twofa_selectors:
                try:
                    code_input = self.wait.until(EC.presence_of_element_located(selector))
                    if code_input:
                        break
                except:
                    continue
            
            if code_input:
                code_input.send_keys(code)
                # Click verify button
                verify_btn = self.driver.find_element(By.ID, "idvNext")
                verify_btn.click()
                time.sleep(3)
                
                # Navigate to YouTube
                self.driver.get("https://www.youtube.com")
                time.sleep(3)
                self.state = "done"
                cookies = self.extract_cookies()
                self.driver.quit()
                return {"status": "success", "cookies": cookies}
            else:
                self.driver.quit()
                return {"status": "error", "message": "2FA input not found"}
        except Exception as e:
            self.driver.quit()
            return {"status": "error", "message": str(e)}
    
    def extract_cookies(self):
        """Extract cookies in Netscape format"""
        cookies = self.driver.get_cookies()
        netscape = "# Netscape HTTP Cookie File\n"
        netscape += "# https://curl.se/docs/http-cookies.html\n"
        netscape += "# Extracted by YouTube Cookie Bot\n\n"
        
        for cookie in cookies:
            domain = cookie['domain']
            if not domain.startswith('.'):
                domain = f".{domain}"
            
            flag = 'TRUE'
            path = cookie.get('path', '/')
            secure = 'TRUE' if cookie.get('secure', False) else 'FALSE'
            expiry = int(cookie.get('expiry', 0)) if cookie.get('expiry') else 0
            name = cookie['name']
            value = cookie['value']
            
            netscape += f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n"
        
        return netscape

    def extract_from_session(self, email, password, two_factor_code=None):
        """Main method to extract cookies with 2FA support"""
        self.setup_driver()
        
        # Step 1: Email
        result = self.login_with_email(email)
        if result["status"] != "success":
            return result
        
        # Step 2: Password
        result = self.login_with_password(password)
        if result["status"] == "2fa_required":
            if two_factor_code:
                return self.verify_2fa(two_factor_code)
            return {"status": "2fa_required"}
        elif result["status"] == "success":
            return result
        else:
            return result
