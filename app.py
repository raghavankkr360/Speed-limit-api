
from flask import Flask, request, jsonify
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=15,
        sslmode="require"
    )


@app.route("/")
def home():
    return "Speed Limit API Running - Neon PostgreSQL Connected"


# -----------------------------------
# NEAREST SPEED LIMIT
# -----------------------------------

@app.route("/speedlimit", methods=["GET"])
def speedlimit():

    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid GPS coordinates"}), 400

        conn = get_db_connection()

        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:

                cur.execute("""
                    SELECT
                        highway,
                        speed_limit,
                        longitude AS nearest_x,
                        latitude AS nearest_y,
                        ROUND(
                            ST_Distance(
                                geom,
                                ST_SetSRID(
                                    ST_MakePoint(%s, %s),
                                    4326
                                )::geography
                            )::numeric,
                            2
                        ) AS distance_metres

                    FROM public.road_points

                    ORDER BY geom <-> ST_SetSRID(
                        ST_MakePoint(%s, %s),
                        4326
                    )::geography

                    LIMIT 1;
                """, (lon, lat, lon, lat))

                result = cur.fetchone()

                if not result:
                    return jsonify({
                        "error": "No speed limit found"
                    }), 404

                return jsonify({
                    "speed_limit": result["speed_limit"],
                    "nearest_x": result["nearest_x"],
                    "nearest_y": result["nearest_y"],
                    "highway": result["highway"],
                    "distance_metres": float(
                        result["distance_metres"]
                    )
                })

        finally:
            conn.close()

    except (TypeError, ValueError):
        return jsonify({"error": "Invalid or missing GPS coordinates"}), 400

    except Exception:
        app.logger.exception("Speed limit lookup failed")
        return jsonify({"error": "Database lookup failed"}), 500


# -----------------------------------
# STORE OVERSPEED VIOLATION
# -----------------------------------

@app.route("/violation", methods=["POST"])
def violation():

    data = request.get_json(silent=True) or {}

    required = ["lat", "lon", "speed", "speed_limit"]

    for field in required:
        if field not in data:
            return jsonify({
                "status": "error",
                "message": f"Missing field: {field}"
            }), 400

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed = float(data["speed"])
        speed_limit = int(data["speed_limit"])

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid GPS coordinates"}), 400

        if speed < 0 or speed_limit <= 0:
            return jsonify({"error": "Invalid speed values"}), 400

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO public.violations (
                        latitude,
                        longitude,
                        vehicle_speed,
                        speed_limit,
                        fine_amount,
                        geom
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        200,
                        ST_SetSRID(
                            ST_MakePoint(%s, %s),
                            4326
                        )::geography
                    );
                """, (
                    lat,
                    lon,
                    speed,
                    speed_limit,
                    lon,
                    lat
                ))

            conn.commit()

        finally:
            conn.close()

        return jsonify({
            "status": "success",
            "fine_amount": 200,
            "message": "Violation stored"
        }), 201

    except (TypeError, ValueError):
        return jsonify({
            "status": "error",
            "message": "Invalid input values"
        }), 400

    except Exception:
        app.logger.exception("Violation insertion failed")
        return jsonify({
            "status": "error",
            "message": "Could not store violation"
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
