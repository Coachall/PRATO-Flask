from datetime import datetime, timezone
import time
from flask import Flask, jsonify, request, current_app
import os
import base64
import pandas
from db.session import Session
from db.users import User
from io import BytesIO
import requests
from datetime import datetime
import urllib3
from threading import Thread

urllib3.disable_warnings()

app = Flask(__name__)


# create a function to decode the base64 encoded file
def decode_file(file):
    return base64.b64decode(file)


# create a requests session
api_session = requests.Session()


# create a function to refresh the token
def refresh_token(request):
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    grant_type = "refresh_token"
    session = Session()
    token = request.request.headers.get("User")

    # get user from db
    user = session.query(User).filter_by(user_id=token).first()

    payload = {
        "refresh_token": user.refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": grant_type,
    }
    try:
        print(payload)
        # get new token
        r = requests.post(
            "https://focus.teamleader.eu/oauth2/access_token", data=payload
        )
        r.raise_for_status()  # Raise an exception for any HTTP error

        # update user with new tokens
        user.refresh_token = r.json().get("refresh_token")
        user.access_token = r.json().get("access_token")

        # commit changes
        session.commit()
    except requests.exceptions.RequestException as err:
        print(err)

    session.close()

    return r.json().get("access_token")


# create a function to catch invalid tokens
def catch_invalid_token(r, *args, **kwargs):
    if r.status_code == 401:
        print("Fetching new token as the previous token expired")
        token = refresh_token(r)
        print(args, kwargs)
        api_session.headers.update({"Authorization": f"Bearer {token}"})
        r.request.headers["Authorization"] = api_session.headers["Authorization"]
        return api_session.send(r.request, verify=False)


def catch_rate_limit(r, *args, **kwargs):
    if r.status_code == 429:
        print("Handling rate limit")
        # get X-RateLimit-Reset header
        reset_time_str = r.headers.get("X-RateLimit-Reset")

        try:
            # parse the ISO 8601 datetime string to a datetime object
            reset_time = datetime.fromisoformat(reset_time_str).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            # Handle the case where the header value is not a valid ISO 8601 datetime
            print(f"Invalid X-RateLimit-Reset header value: {reset_time_str}")
            return None

        # get current time
        now = datetime.now(timezone.utc)
        # calculate the time difference
        difference = reset_time - now
        # convert to seconds
        difference_seconds = difference.total_seconds()

        if difference_seconds > 0:
            print(f"Waiting for {difference_seconds} seconds")
            # wait for the specified time
            time.sleep(60)
            # send the request again
            return api_session.send(r.request, verify=False)
        else:
            # The reset time is in the past, so no need to wait
            print(
                "X-RateLimit-Reset time is in the past. Sending the request immediately."
            )
            return api_session.send(r.request, verify=False)


# add the function to the list of hooks
api_session.hooks["response"].append(catch_invalid_token)
api_session.hooks["response"].append(catch_rate_limit)


def my_task(request_data):
    with app.app_context():
        session = Session()
        record = request_data

        sent_to = record.get("To")
        sent_from = record.get("From")
        # parse the email address to get everything before the @ and remove the ""
        sent_to = sent_to.split("@")[0].replace('"', "")
        user = session.query(User).filter_by(user_id=sent_to).first()

        print(user)
        if user:
            api_session.headers.update({"Authorization": f"Bearer {user.access_token}"})
            api_session.headers.update({"User": f"{user.user_id}"})
            # send an email with Postmark to notify the sender that the email has been received and is being processed
            requests.post(
                "https://api.postmarkapp.com/email",
                json={
                    "From": "noreply@coachall.be",
                    "To": sent_from,
                    "Subject": "Opdracht ontvangen",
                    "TextBody": "We hebben de importopdracht ontvangen en verwerken nu jouw aanvraag. Je ontvangt een nieuw bericht zodra de import gelukt is",
                },
                headers={
                    "X-Postmark-Server-Token": os.getenv("POSTMARK_SERVER_TOKEN"),
                    "X-PM-Message-Stream": "outbound",
                },
            )
            # get attachments

            attachments = record.get("Attachments")
            # get sender email

            # filter all attachments that are excel files
            excel_files = [
                attachment
                for attachment in attachments
                if attachment.get("Name").endswith(".xlsx")
            ]
            decoded_excel = decode_file(excel_files[0].get("Content"))
            df = pandas.read_excel(BytesIO(decoded_excel))

            template_df = pandas.DataFrame(columns=df.columns)

            # Iterate through the rows of the DataFrame
            transformed_data = {}

            # convert all column headers to lowercase
            df.columns = df.columns.str.lower()

            print(df.columns)

            for index, row in df.iterrows():
                customer_info = {
                    "KlantID": row["klantid"],
                    "Kl_Naam": row["kl_naam"],
                    "Kl_Voornaam": row["kl_voornaam"],
                    "KL_Email": row["kl_email"],
                    "KL_GSM": row["kl_gsm"],
                    "Straat": row["straat"],
                    "Postcode": row["postcode"],
                    "GemeenteNaam": row["gemeentenaam"],
                }

                timeframe = {"Van": row["van"], "Tot": row["tot"]}

                # Check if the KlantID already exists in the transformed_data dictionary
                if row["klantid"] in transformed_data:
                    transformed_data[row["klantid"]]["Timeframes"].append(timeframe)
                else:
                    transformed_data[row["klantid"]] = {
                        "CustomerInfo": customer_info,
                        "Timeframes": [timeframe],
                    }

            # Convert the dictionary values to a list
            transformed_list = list(transformed_data.values())

            # print(transformed_list)

            rows_with_errors = []

            for row in transformed_list:
                try:
                    customer_info = row.get("CustomerInfo")
                    id = str(customer_info.get("KlantID"))
                    naam = customer_info.get("Kl_Naam")
                    voornaam = customer_info.get("Kl_Voornaam")
                    email = customer_info.get("KL_Email")
                    gsm = str(customer_info.get("KL_GSM"))
                    straat = customer_info.get("Straat")
                    postcode = customer_info.get("Postcode")
                    gemeente = customer_info.get("GemeenteNaam")

                    custom_field = user.custom_field_id
                    # check if there are spaces in gsm and remove them
                    if " " in gsm:
                        gsm = gsm.replace(" ", "")

                    if "/" in gsm:
                        gsm = gsm.replace("/", "")

                    # Filter non-numeric characters
                    if gsm is not None:
                        gsm = "".join(filter(str.isdigit, gsm))

                    # Remaining logic
                    if gsm[:2] == "32":
                        if gsm[:3] == "324":
                            gsm = "0" + gsm[2:]
                        else:
                            gsm = "04" + gsm[2:]

                    if gsm[:2] == "31":
                        gsm = "00" + gsm

                    if gsm is None:
                        gsm = False

                    # check if gsm length is 10
                    # if len(gsm) != 10:
                    #     rows_with_errors.append(row)
                    #     continue

                    # check if the customer already exists
                    if email == "geen@schoonmaakzorg.be" and gsm != None:
                        print(gsm)
                        customer_by_phone = api_session.post(
                            "https://api.focus.teamleader.eu/contacts.list",
                            json={"filter": {"term": gsm}},
                        ).json()
                        if customer_by_phone.get("data"):
                            customer = {
                                "data": {
                                    "id": customer_by_phone.get("data")[0].get("id")
                                }
                            }
                        else:
                            customer = api_session.post(
                                "https://api.focus.teamleader.eu/contacts.add",
                                json={
                                    "first_name": voornaam,
                                    "last_name": naam,
                                    "emails": [{"type": "primary", "email": email}],
                                    "telephones": [{"type": "mobile", "number": gsm}]
                                    if gsm != None
                                    else None,
                                    "addresses": [
                                        {
                                            "type": "primary",
                                            "address": {
                                                "line_1": straat,
                                                "postal_code": postcode,
                                                "city": gemeente,
                                                "country": "BE",
                                            },
                                        }
                                    ],
                                    "custom_fields": [
                                        {"id": user.custom_field_id, "value": id}
                                    ],
                                },
                            ).json()
                    elif email != None:
                        customer_by_email = api_session.post(
                            "https://api.focus.teamleader.eu/contacts.list",
                            json={
                                "filter": {"email": {"type": "primary", "email": email}}
                            },
                        ).json()

                        if customer_by_email.get("data"):
                            customer = {
                                "data": {
                                    "id": customer_by_email.get("data")[0].get("id")
                                }
                            }
                        elif gsm != None:
                            customer = api_session.post(
                                "https://api.focus.teamleader.eu/contacts.add",
                                json={
                                    "first_name": voornaam,
                                    "last_name": naam,
                                    "emails": [{"type": "primary", "email": email}],
                                    "telephones": [{"type": "mobile", "number": gsm}],
                                    "addresses": [
                                        {
                                            "type": "primary",
                                            "address": {
                                                "line_1": straat,
                                                "postal_code": postcode,
                                                "city": gemeente,
                                                "country": "BE",
                                            },
                                        }
                                    ],
                                    "custom_fields": [
                                        {"id": user.custom_field_id, "value": id}
                                    ],
                                },
                            ).json()
                        else:
                            customer = api_session.post(
                                "https://api.focus.teamleader.eu/contacts.add",
                                json={
                                    "first_name": voornaam,
                                    "last_name": naam,
                                    "emails": [{"type": "primary", "email": email}],
                                    "addresses": [
                                        {
                                            "type": "primary",
                                            "address": {
                                                "line_1": straat,
                                                "postal_code": postcode,
                                                "city": gemeente,
                                                "country": "BE",
                                            },
                                        }
                                    ],
                                    "custom_fields": [
                                        {"id": user.custom_field_id, "value": id}
                                    ],
                                },
                            ).json()
                    print(customer)
                    # add timetracking to customer
                    for timeframe in row.get("Timeframes"):
                        van = timeframe.get("Van")
                        tot = timeframe.get("Tot")
                        # check if timetracking already exists
                        timetracking = api_session.post(
                            "https://api.focus.teamleader.eu/timeTracking.list",
                            json={
                                "filter": {
                                    "started_after": van.strftime(
                                        "%Y-%m-%dT%H:%M:%S+01:00"
                                    ),
                                    "ended_before": tot.strftime(
                                        "%Y-%m-%dT%H:%M:%S+01:00"
                                    ),
                                    "subject": {
                                        "type": "contact",
                                        "id": customer.get("data").get("id"),
                                    },
                                }
                            },
                        ).json()
                        if len(timetracking.get("data")) > 0:
                            print(van.strftime("%Y-%m-%dT%H:%M:%S+01:00"))
                            print("timetracking already exists")
                            continue
                        else:
                            api_session.post(
                                "https://api.focus.teamleader.eu/timeTracking.add",
                                json={
                                    "started_at": van.strftime(
                                        "%Y-%m-%dT%H:%M:%S+01:00"
                                    ),
                                    "ended_at": tot.strftime("%Y-%m-%dT%H:%M:%S+01:00"),
                                    "subject": {
                                        "type": "contact",
                                        "id": customer.get("data").get("id"),
                                    },
                                    "work_type_id": user.work_type_id,
                                },
                            )

                except Exception as e:
                    # Handle the exception and log the error
                    print(f"Error processing row: {e}")

            session.close()
            print("rows with errors:")
            print(rows_with_errors)

            rows = []

            # Iterate through the transformed_list and create rows
            for entry in rows_with_errors:
                customer_info = entry["CustomerInfo"]
                timeframes = entry["Timeframes"]

                # Iterate through timeframes for each customer
                for timeframe in timeframes:
                    # Create a row by combining customer info and timeframe
                    row = {
                        "KlantID": customer_info["KlantID"],
                        "Kl_Naam": customer_info["Kl_Naam"],
                        "Kl_Voornaam": customer_info["Kl_Voornaam"],
                        "KL_Email": customer_info["KL_Email"],
                        "KL_GSM": customer_info["KL_GSM"],
                        "Straat": customer_info["Straat"],
                        "Postcode": customer_info["Postcode"],
                        "GemeenteNaam": customer_info["GemeenteNaam"],
                        "Van": timeframe["Van"],
                        "Tot": timeframe["Tot"],
                    }

                    rows.append(row)

            # Create a DataFrame from the list of rows
            reversed_df = pandas.DataFrame(rows)

            df = pandas.concat([template_df, reversed_df], ignore_index=True)

            df.to_excel("errors.xlsx", index=False)
            with open("errors.xlsx", "rb") as f:
                encoded_errors = base64.b64encode(f.read()).decode("utf-8")

            # send an email with Postmark to notify the sender that the import has ended and send the errors as an attachment
            requests.post(
                "https://api.postmarkapp.com/email",
                json={
                    "From": "noreply@coachall.be",
                    "To": sent_from,
                    "Subject": "Importopdracht verwerkt",
                    "TextBody": "De importopdracht is verwerkt. Je vindt eventuele mislukte imports in de bijlage. Deze moeten manueel geimporteerd worden.",
                    "Attachments": [
                        {
                            "Content": encoded_errors,
                            "Name": "errors.xlsx",
                            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        }
                    ],
                },
                headers={
                    "X-Postmark-Server-Token": os.getenv("POSTMARK_SERVER_TOKEN"),
                    "X-PM-Message-Stream": "outbound",
                },
            )

        else:
            print("User not found")
            session.close()
            return "User not found", 404

        # return status code 200
        return "Success", 200


@app.route("/", methods=["POST"])
def index():
    request_data = request.get_json()
    response = jsonify(message="Request received and is being processed")
    response.status_code = 200
    # return status code 200
    Thread(target=lambda: my_task(request_data)).start()
    return response


# create a route for the initial authorization with Teamleader
@app.route("/authorize", methods=["GET"])
def authorize():
    code = request.args.get("code")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    grant_type = "authorization_code"
    redirect_uri = os.getenv("REDIRECT_URI")

    user_id = request.args.get("state")
    session = Session()
    user = session.query(User).filter_by(user_id=user_id).first()

    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": grant_type,
        "redirect_uri": redirect_uri,
    }

    r = requests.post("https://focus.teamleader.eu/oauth2/access_token", data=payload)
    # get data object from response
    tk_response = r.json()
    # update user with new tokens
    if user:
        user.access_token = tk_response.get("access_token")
        user.refresh_token = tk_response.get("refresh_token")
        session.commit()
        session.close()

    return jsonify(r.json())


if __name__ == "__main__":
    app.run(debug=True, port=os.getenv("PORT", default=5000))
