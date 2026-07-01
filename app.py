from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

SUPABASE_URL = "https://qwrlfojltqfkgyjjhwky.supabase.co"
SUPABASE_KEY = "sb_publishable_wY6i_JE-2Msitn-vkCkJWA_SPoSpSUm"

@app.route("/")
def home():
    return "Speed Limit API Running"

@app.route("/speedlimit")
def speedlimit():

    lat = float(request.args.get("lat"))
    lon = float(request.args.get("lon"))

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    url = f"{SUPABASE_URL}/rest/v1/Speed%20limit?select=X,Y,Speed_Limit"

    response = requests.get(url, headers=headers)

    data = response.json()

    nearest = None
    min_distance = 999999999

    for row in data:
        distance = (
            (float(row["X"]) - lon) ** 2 +
            (float(row["Y"]) - lat) ** 2
        )

        if distance < min_distance:
            min_distance = distance
            nearest = row

    return jsonify({
        "speed_limit": nearest["Speed_Limit"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)