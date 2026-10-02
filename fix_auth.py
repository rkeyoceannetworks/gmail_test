import os
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

# Use the SAME scope you used before
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def manual_auth():
    # 1. Load your credentials file
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    
    # 2. Tell the flow we want to do this MANUALLY (Out-of-Band)
    # This specific redirect_uri is what tells Google "don't look for a local server"
    flow.redirect_uri = 'http://localhost' 
    
    auth_url, _ = flow.authorization_url(prompt='consent')
    
    print(f"\n1. Open this URL:\n{auth_url}\n")
    code = input("2. Paste the 'code' from the URL here: ").strip()
    
    # 3. Exchange the code for the real tokens
    flow.fetch_token(code=code)
    
    # 4. Save it immediately
    with open('token.json', 'w') as token:
        token.write(flow.credentials.to_json())
    
    print("\nSUCCESS! 'token.json' has been created.")

if __name__ == '__main__':
    manual_auth()
