from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

SUPABASE_URL = "https://qwrlfojltqfkgyjjhwky.supabase.co"
SUPABASE_KEY = "PASTE_YOUR_PUBLISHABLE_KEY_HERE"

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

    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)

    data = response.json()

    print("DATA:", data)

    if not isinstance(data, list) or len(data) == 0:
        return jsonify({
            "error": "No data returned from Supabase",
            "response": data
        }), 500

    nearest = None
    min_distance = float("inf")

    for row in data:
        distance = (
            (float(row["X"]) - lon) ** 2 +
            (float(row["Y"]) - lat) ** 2
        )

        if distance < min_distance:
            min_distance = distance
            nearest = row

    if nearest is None:
        return jsonify({
            "error": "No nearest point found"
        }), 500

    return jsonify({
        "speed_limit": nearest["Speed_Limit"],
        "nearest_x": nearest["X"],
        "nearest_y": nearest["Y"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)