from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

SUPABASE_URL = "https://qwrlfojltqfkgyjjhwky.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF3cmxmb2psdHFma2d5ampod2t5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4MjkwNzEzNCwiZXhwIjoyMDk4NDgzMTM0fQ.J_CibEEtUZFialqKeDmJqu3hrLrDSAjSVNiJRn-Okwc"

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

@app.route("/violation", methods=["POST"])
def violation():

    data = request.get_json()

    lat = data.get("lat")
    lon = data.get("lon")
    speed = data.get("speed")
    speed_limit = data.get("speed_limit")

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    payload = {
        "latitude": lat,
        "longitude": lon,
        "speed": speed,
        "speed_limit": speed_limit,
        "fine_amount": 200,
        "violation_duration": 15
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/violations",
        headers=headers,
        json=payload
    )

    if response.status_code not in [200, 201]:
        return jsonify({
            "status": "error",
            "details": response.text
        }), 500

    return jsonify({
        "status": "success",
        "fine_amount": 200,
        "message": "Violation stored"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)