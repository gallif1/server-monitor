import os
from dotenv import load_dotenv
load_dotenv()

ALERT_EMAIL_TO = "gal.lifshiz1212@gmail.com"

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
