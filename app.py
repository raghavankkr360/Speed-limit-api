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
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/nearest_speed_limit",
        headers=headers,
        json={
            "lat_input": lat,
            "lon_input": lon
        }
    )

    data = response.json()

    if not data:
        return jsonify({"error": "No speed limit found"}), 404

    result = data[0]

    return jsonify({
        "speed_limit": result["speed_limit"],
        "nearest_x": result["x"],
        "nearest_y": result["y"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)