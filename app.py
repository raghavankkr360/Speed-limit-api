
from flask import Flask, request, jsonify, render_template
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


# DATABASE CONNECTION
def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=15,
        sslmode="require"
    )


# HOME PAGE - DASHBOARD
@app.route("/")
def home():
    return render_template("index.html")


# HEALTH CHECK
@app.route("/health")
def health():
    return "Speed Limit API Running - Neon PostgreSQL Connected"


# GET ROAD SPEED LIMIT
@app.route("/speedlimit", methods=["GET"])
def speedlimit():
    try:
        lat = float(request.args.get("lat"))
        lon = float(request.args.get("lon"))

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

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
                                    ST_MakePoint(%s, %s), 4326
                                )::geography
                            )::numeric,
                            2
                        ) AS distance_metres
                    FROM public.road_points
                    ORDER BY
                        geom <-> ST_SetSRID(
                            ST_MakePoint(%s, %s), 4326
                        )::geography
                    LIMIT 1;
                """, (lon, lat, lon, lat))

                result = cur.fetchone()

            if not result:
                return jsonify({
                    "error": "No nearby road found"
                }), 404

            return jsonify(dict(result)), 200

        finally:
            conn.close()

    except (TypeError, ValueError):
        return jsonify({
            "error": "Valid lat and lon are required"
        }), 400

    except Exception:
        app.logger.exception("Speed limit lookup failed")
        return jsonify({
            "error": "Speed limit lookup failed"
        }), 500


# STORE TRAFFIC VIOLATION
@app.route("/violation", methods=["POST"])
def violation():
    data = request.get_json(silent=True) or {}

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed = float(data["speed"])
        limit = int(data["speed_limit"])

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

        if speed < 0 or limit <= 0:
            return jsonify({"error": "Invalid speed values"}), 400

        fine_amount = 200

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.violations
                    (
                        latitude,
                        longitude,
                        vehicle_speed,
                        speed_limit,
                        fine_amount,
                        violation_time,
                        geom
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, NOW(),
                        ST_SetSRID(
                            ST_MakePoint(%s, %s), 4326
                        )::geography
                    );
                """, (
                    lat,
                    lon,
                    speed,
                    limit,
                    fine_amount,
                    lon,
                    lat
                ))

            conn.commit()

        finally:
            conn.close()

        return jsonify({
            "status": "success",
            "fine_amount": fine_amount,
            "message": "Violation stored"
        }), 201

    except (KeyError, TypeError, ValueError):
        return jsonify({
            "error": "Invalid violation data"
        }), 400

    except Exception:
        app.logger.exception("Violation storage failed")
        return jsonify({
            "error": "Violation storage failed"
        }), 500


# RECEIVE LIVE ESP32 GPS TELEMETRY
@app.route("/telemetry", methods=["POST"])
def telemetry():
    data = request.get_json(silent=True) or {}

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed = float(data["speed"])
        limit = int(data["speed_limit"])

        vehicle_id = str(
            data.get("vehicle_id", "Skoda Slavia")
        )

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({
                "error": "Invalid coordinates"
            }), 400

        if speed < 0 or limit <= 0:
            return jsonify({
                "error": "Invalid speed values"
            }), 400

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO public.vehicle_status
                    (
                        vehicle_id,
                        latitude,
                        longitude,
                        vehicle_speed,
                        speed_limit,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, NOW())

                    ON CONFLICT (vehicle_id)
                    DO UPDATE SET
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        vehicle_speed = EXCLUDED.vehicle_speed,
                        speed_limit = EXCLUDED.speed_limit,
                        updated_at = NOW();
                """, (
                    vehicle_id,
                    lat,
                    lon,
                    speed,
                    limit
                ))

            conn.commit()

        finally:
            conn.close()

        return jsonify({
            "status": "success"
        }), 200

    except (KeyError, TypeError, ValueError):
        return jsonify({
            "error": "Invalid telemetry data"
        }), 400

    except Exception:
        app.logger.exception("Telemetry update failed")
        return jsonify({
            "error": "Telemetry update failed"
        }), 500


# SEND DATA TO LIVE DASHBOARD
@app.route("/api/dashboard", methods=["GET"])
def dashboard_data():
    conn = None

    try:
        conn = get_db_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Latest vehicle information
            cur.execute("""
                SELECT
                    vehicle_id,
                    latitude,
                    longitude,
                    vehicle_speed,
                    speed_limit,
                    updated_at,
                    (
                        updated_at >=
                        NOW() - INTERVAL '15 seconds'
                    ) AS online
                FROM public.vehicle_status
                ORDER BY updated_at DESC
                LIMIT 1;
            """)

            vehicle = cur.fetchone()

            # Total violations
            cur.execute("""
                SELECT COUNT(*) AS total
                FROM public.violations;
            """)

            total_violations = cur.fetchone()["total"]

            # Recent violations
            cur.execute("""
                SELECT
                    latitude,
                    longitude,
                    vehicle_speed,
                    speed_limit,
                    fine_amount,
                    violation_time
                FROM public.violations
                ORDER BY violation_time DESC
                LIMIT 10;
            """)

            recent_violations = cur.fetchall()

        if vehicle:
            vehicle = dict(vehicle)

            vehicle["updated_at"] = (
                vehicle["updated_at"].isoformat()
                if vehicle["updated_at"]
                else None
            )

        violations = []

        for item in recent_violations:
            item = dict(item)

            item["violation_time"] = (
                item["violation_time"].isoformat()
                if item["violation_time"]
                else None
            )

            violations.append(item)

        return jsonify({
            "vehicle": vehicle,
            "total_violations": total_violations,
            "recent_violations": violations
        }), 200

    except Exception:
        app.logger.exception(
            "Dashboard data request failed"
        )

        return jsonify({
            "error": "Could not load dashboard data"
        }), 500

    finally:
        if conn:
            conn.close()


# START FLASK SERVER
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
