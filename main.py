from flask import Flask, jsonify, request
import os
import base64
import pandas
from db.session import Session
from db.users import User
from io import BytesIO
import requests

app = Flask(__name__)
def decode_file(file):
    return base64.b64decode(file)

api_session = requests.Session()

def refresh_token(request):
    
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    grant_type = "refresh_token"
    session = Session()
    print(request.request.headers.get('Authorization'))
    # remove Bearer from the token
    token = request.request.headers.get('User')
    user = session.query(User).filter_by(user_id=token).first()

    payload = {
        "refresh_token": user.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": grant_type
    }

    r = requests.post("https://focus.teamleader.eu/oauth2/access_token", data=payload)
    user.refresh_token = r.json().get('refresh_token')
    user.access_token = r.json().get('access_token')
    session.commit()

    session.close() 

    return r.json().get('access_token')

def catch_invalid_token(r, *args, **kwargs):
    if r.status_code == 401:
        print("Fetching new token as the previous token expired")
        token = refresh_token(r)
        print(args, kwargs)
        api_session.headers.update({"Authorization": f"Bearer {token}"})
        r.request.headers["Authorization"] = api_session.headers["Authorization"]
        return api_session.send(r.request, verify=False)

api_session.hooks['response'].append(catch_invalid_token)

@app.route('/', methods=['POST'])
def index():
    session = Session()
    record = request.get_json()

    sent_to = record.get('To')
    # parse the email address to get everything before the @ and remove the ""
    sent_to = sent_to.split('@')[0].replace('"', '')
    user = session.query(User).filter_by(user_id=sent_to).first()

    if user:
        print(user)
        api_session.headers.update({"Authorization": f"Bearer {user.access_token}"})
        api_session.headers.update({"User": f"{user.user_id}"})
        company_info = api_session.get("https://api.focus.teamleader.eu/departments.list").json()

        print(company_info)

        attachments = record.get('Attachments')
        # get sender email

        # filter all attachments that are excel files
        excel_files = [attachment for attachment in attachments if attachment.get('Name').endswith('.xlsx')]
        decoded_excel = decode_file(excel_files[0].get('Content'))
        excel = pandas.read_excel(BytesIO(decoded_excel))

        excel_dict = excel.to_dict(orient='records')
        print(excel_dict) 

        session.close()

        return jsonify({"Status": "Oke"})

    else:
        session.close()
        return jsonify({"404": "Not found"})

@app.route('/authorize', methods=['GET'])
def authorize():
    code = request.args.get('code')
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    grant_type = "authorization_code"
    redirect_uri = "https://fcf954e69fbcaf.lhr.life/authorize"

    user_id = request.args.get('state')
    session = Session()
    user = session.query(User).filter_by(user_id=user_id).first()

    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": grant_type,
        "redirect_uri": redirect_uri
    }

    r = requests.post("https://focus.teamleader.eu/oauth2/access_token", data=payload)
    # get data object from response
    tk_response = r.json()
    # update user with new tokens
    if user:
        
        user.access_token = tk_response.get('access_token')
        user.refresh_token = tk_response.get('refresh_token')
        session.commit()
        session.close() 


    return jsonify(r.json())



if __name__ == '__main__':
    app.run(debug=True, port=os.getenv("PORT", default=5000))

