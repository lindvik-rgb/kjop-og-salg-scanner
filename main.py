import os
import time
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
TO_EMAIL = os.getenv("TO_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")

def send_email(subject, html):
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "subject": subject,
        "html": html,
    }
    response = requests.post(url, headers=headers, json=payload)
    print(response.status_code, response.text)

def check_listings():
    subject = "Testvarsel fra kjøpe- og salg-scanner"
    html = """
    <h2>Testvarsel</h2>
    <p>Backend kjører nå i Railway.</p>
    <p>Neste steg er å koble til ekte annonsedata.</p>
    """
    send_email(subject, html)

if __name__ == "__main__":
    while True:
        check_listings()
        time.sleep(3600)
