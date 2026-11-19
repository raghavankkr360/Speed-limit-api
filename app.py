
from flask import Flask, request, jsonify, render_template
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")
DEFAULT_VEHICLE_ID = "Skoda Slavia"

# Maximum accepted interval between GPS samples for distance calculations.
MAX_SAMPLE_GAP_SECONDS = 15

# Reject implausible GPS jumps above this speed.
MAX_PLAUSIBLE_SPEED_KMH = 180


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is missing")

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=15,
        sslmode="require"
    )


# =========================================================
# HELPER: SERIALIZE DATABASE DATETIME VALUES
# =========================================================

def serialize_rows(rows):
    result = []

    for row in rows:
        item = dict(row)

        for key, value in item.items():
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()

        result.append(item)

    return result


# =========================================================
# HOME PAGE
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():
    try:
        conn = get_db_connection()
        conn.close()

        return jsonify({
            "status": "success",
            "message": "Speed Limit API Running - Neon Connected"
        }), 200

    except Exception:
        app.logger.exception("Health check failed")

        return jsonify({
            "status": "error",
            "message": "Database connection failed"
        }), 500


# =========================================================
# GET ROAD SPEED LIMIT
# =========================================================

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


# =========================================================
# STORE TRAFFIC VIOLATION
# =========================================================

@app.route("/violation", methods=["POST"])
def violation():

    data = request.get_json(silent=True) or {}

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed = float(data["speed"])
        limit = int(data["speed_limit"])

        vehicle_id = str(
            data.get("vehicle_id", DEFAULT_VEHICLE_ID)
        ).strip()

        if not vehicle_id:
            return jsonify({"error": "Vehicle ID is required"}), 400

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

        if speed < 0 or limit <= 0:
            return jsonify({"error": "Invalid speed values"}), 400

        if speed <= limit:
            return jsonify({
                "error": "Vehicle speed is not above the speed limit"
            }), 400

        fine_amount = 200

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:

                cur.execute("""
                    INSERT INTO public.violations
                    (
                        vehicle_id,
                        latitude,
                        longitude,
                        vehicle_speed,
                        speed_limit,
                        fine_amount,
                        violation_time,
                        geom
                    )

                    VALUES (
                        %s, %s, %s, %s, %s, %s, NOW(),
                        ST_SetSRID(
                            ST_MakePoint(%s, %s), 4326
                        )::geography
                    );
                """, (
                    vehicle_id,
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
            "vehicle_id": vehicle_id,
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


# =========================================================
# RECEIVE AND STORE LIVE ESP32 TELEMETRY
# =========================================================

@app.route("/telemetry", methods=["POST"])
def telemetry():

    data = request.get_json(silent=True) or {}

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
        speed = float(data["speed"])
        limit = int(data["speed_limit"])

        vehicle_id = str(
            data.get("vehicle_id", DEFAULT_VEHICLE_ID)
        ).strip()

        if not vehicle_id:
            return jsonify({"error": "Vehicle ID is required"}), 400

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return jsonify({"error": "Invalid coordinates"}), 400

        if speed < 0 or speed > MAX_PLAUSIBLE_SPEED_KMH:
            return jsonify({"error": "Invalid vehicle speed"}), 400

        if limit <= 0:
            return jsonify({"error": "Invalid speed limit"}), 400

        conn = get_db_connection()

        try:
            with conn.cursor() as cur:

                # Update the latest vehicle status.
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

                # Preserve every incoming GPS reading.
                cur.execute("""
                    INSERT INTO public.vehicle_telemetry
                    (
                        vehicle_id,
                        latitude,
                        longitude,
                        vehicle_speed,
                        speed_limit,
                        recorded_at,
                        geom
                    )

                    VALUES (
                        %s, %s, %s, %s, %s, NOW(),
                        ST_SetSRID(
                            ST_MakePoint(%s, %s), 4326
                        )::geography
                    );
                """, (
                    vehicle_id,
                    lat,
                    lon,
                    speed,
                    limit,
                    lon,
                    lat
                ))

            conn.commit()

        finally:
            conn.close()

        return jsonify({
            "status": "success",
            "vehicle_id": vehicle_id,
            "message": "Live status and telemetry history updated"
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


# =========================================================
# LIVE DASHBOARD API
# =========================================================

@app.route("/api/dashboard", methods=["GET"])
def dashboard_data():

    conn = None

    try:
        vehicle_id = request.args.get(
            "vehicle_id", DEFAULT_VEHICLE_ID
        )

        conn = get_db_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # Latest vehicle information.
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

                WHERE vehicle_id = %s

                ORDER BY updated_at DESC
                LIMIT 1;
            """, (vehicle_id,))

            vehicle = cur.fetchone()

            # Total violations for this vehicle.
            cur.execute("""
                SELECT COUNT(*) AS total
                FROM public.violations
                WHERE vehicle_id = %s;
            """, (vehicle_id,))

            total_violations = cur.fetchone()["total"]

            # Recent violations.
            cur.execute("""
                SELECT
                    latitude,
                    longitude,
                    vehicle_speed,
                    speed_limit,
                    fine_amount,
                    violation_time

                FROM public.violations

                WHERE vehicle_id = %s

                ORDER BY violation_time DESC
                LIMIT 10;
            """, (vehicle_id,))

            recent_violations = cur.fetchall()

        if vehicle:
            vehicle = serialize_rows([vehicle])[0]

        return jsonify({
            "vehicle": vehicle,
            "total_violations": total_violations,
            "recent_violations": serialize_rows(recent_violations)
        }), 200

    except Exception:
        app.logger.exception("Dashboard data request failed")

        return jsonify({
            "error": "Could not load dashboard data"
        }), 500

    finally:
        if conn:
            conn.close()


# =========================================================
# DRIVING ANALYTICS API
# =========================================================

@app.route("/api/analytics", methods=["GET"])
def driving_analytics():

    conn = None

    try:
        vehicle_id = request.args.get(
            "vehicle_id", DEFAULT_VEHICLE_ID
        )

        conn = get_db_connection()

        with conn.cursor(cursor_factory=RealDictCursor) as cur:

            # -------------------------------------------------
            # 1. SPEED, DISTANCE AND OVERSPEED SUMMARY
            # -------------------------------------------------

            cur.execute("""
                WITH ordered AS (
                    SELECT
                        recorded_at,
                        vehicle_speed,
                        speed_limit,
                        geom,

                        LAG(recorded_at) OVER (
                            ORDER BY recorded_at
                        ) AS previous_time,

                        LAG(vehicle_speed) OVER (
                            ORDER BY recorded_at
                        ) AS previous_speed,

                        LAG(speed_limit) OVER (
                            ORDER BY recorded_at
                        ) AS previous_limit,

                        LAG(geom) OVER (
                            ORDER BY recorded_at
                        ) AS previous_geom

                    FROM public.vehicle_telemetry

                    WHERE vehicle_id = %s
                ),

                segments AS (
                    SELECT
                        recorded_at,

                        EXTRACT(
                            EPOCH FROM
                            (recorded_at - previous_time)
                        ) AS interval_seconds,

                        ST_Distance(
                            previous_geom,
                            geom
                        ) AS distance_metres,

                        previous_speed,
                        previous_limit,
                        vehicle_speed,
                        speed_limit

                    FROM ordered

                    WHERE previous_time IS NOT NULL

                    AND recorded_at - previous_time
                        <= INTERVAL '15 seconds'
                ),

                valid_segments AS (
                    SELECT *

                    FROM segments

                    WHERE interval_seconds > 0

                    AND distance_metres <=
                        interval_seconds *
                        (%s / 3.6)

                )

                SELECT

                    COALESCE(
                        (
                            SELECT AVG(vehicle_speed)
                            FROM public.vehicle_telemetry
                            WHERE vehicle_id = %s
                        ), 0
                    ) AS average_speed,

                    COALESCE(
                        (
                            SELECT MAX(vehicle_speed)
                            FROM public.vehicle_telemetry
                            WHERE vehicle_id = %s
                        ), 0
                    ) AS maximum_speed,

                    COALESCE(
                        SUM(distance_metres) / 1000.0,
                        0
                    ) AS total_distance_km,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN previous_speed > previous_limit
                                 AND vehicle_speed > speed_limit
                                THEN interval_seconds
                                ELSE 0
                            END
                        ), 0
                    ) AS overspeed_seconds

                FROM valid_segments;
            """, (
                vehicle_id,
                MAX_PLAUSIBLE_SPEED_KMH,
                vehicle_id,
                vehicle_id
            ))

            summary = dict(cur.fetchone())

            # -------------------------------------------------
            # 2. VIOLATION COUNT
            # -------------------------------------------------

            cur.execute("""
                SELECT
                    COUNT(*) AS total_violations,
                    COALESCE(SUM(fine_amount), 0) AS total_fine

                FROM public.violations

                WHERE vehicle_id = %s;
            """, (vehicle_id,))

            violations = dict(cur.fetchone())

            # -------------------------------------------------
            # 3. DAILY STATISTICS - LAST 7 DAYS
            # -------------------------------------------------

            cur.execute("""
                WITH ordered AS (
                    SELECT
                        recorded_at,
                        vehicle_speed,
                        speed_limit,
                        geom,

                        LAG(recorded_at) OVER (
                            ORDER BY recorded_at
                        ) AS previous_time,

                        LAG(vehicle_speed) OVER (
                            ORDER BY recorded_at
                        ) AS previous_speed,

                        LAG(speed_limit) OVER (
                            ORDER BY recorded_at
                        ) AS previous_limit,

                        LAG(geom) OVER (
                            ORDER BY recorded_at
                        ) AS previous_geom

                    FROM public.vehicle_telemetry

                    WHERE vehicle_id = %s
                ),

                segments AS (
                    SELECT
                        recorded_at,

                        EXTRACT(
                            EPOCH FROM
                            (recorded_at - previous_time)
                        ) AS interval_seconds,

                        ST_Distance(
                            previous_geom,
                            geom
                        ) AS distance_metres,

                        previous_speed,
                        previous_limit,
                        vehicle_speed,
                        speed_limit

                    FROM ordered

                    WHERE previous_time IS NOT NULL

                    AND recorded_at - previous_time
                        <= INTERVAL '15 seconds'
                ),

                valid_segments AS (
                    SELECT *

                    FROM segments

                    WHERE interval_seconds > 0

                    AND distance_metres <=
                        interval_seconds *
                        (%s / 3.6)
                ),

                daily_distance AS (
                    SELECT
                        DATE(recorded_at) AS day,

                        SUM(distance_metres) / 1000.0
                            AS distance_km

                    FROM valid_segments

                    GROUP BY DATE(recorded_at)
                ),

                daily_speed AS (
                    SELECT
                        DATE(recorded_at) AS day,
                        AVG(vehicle_speed) AS average_speed,
                        MAX(vehicle_speed) AS maximum_speed

                    FROM public.vehicle_telemetry

                    WHERE vehicle_id = %s
                    AND recorded_at >= NOW() - INTERVAL '7 days'

                    GROUP BY DATE(recorded_at)
                ),

                daily_violations AS (
                    SELECT
                        DATE(violation_time) AS day,
                        COUNT(*) AS violation_count

                    FROM public.violations

                    WHERE vehicle_id = %s
                    AND violation_time >= NOW() - INTERVAL '7 days'

                    GROUP BY DATE(violation_time)
                )

                SELECT
                    s.day,
                    ROUND(s.average_speed::numeric, 2)
                        AS average_speed,
                    ROUND(s.maximum_speed::numeric, 2)
                        AS maximum_speed,
                    ROUND(
                        COALESCE(d.distance_km, 0)::numeric, 3
                    ) AS distance_km,
                    COALESCE(v.violation_count, 0)
                        AS violations

                FROM daily_speed s

                LEFT JOIN daily_distance d
                    ON d.day = s.day

                LEFT JOIN daily_violations v
                    ON v.day = s.day

                ORDER BY s.day;
            """, (
                vehicle_id,
                MAX_PLAUSIBLE_SPEED_KMH,
                vehicle_id,
                vehicle_id
            ))

            daily_statistics = serialize_rows(cur.fetchall())

            # -------------------------------------------------
            # 4. WEEKLY STATISTICS - LAST 8 WEEKS
            # -------------------------------------------------

            cur.execute("""
                WITH weekly_speed AS (
                    SELECT
                        DATE_TRUNC('week', recorded_at)::date
                            AS week_start,

                        AVG(vehicle_speed) AS average_speed,
                        MAX(vehicle_speed) AS maximum_speed

                    FROM public.vehicle_telemetry

                    WHERE vehicle_id = %s
                    AND recorded_at >= NOW() - INTERVAL '8 weeks'

                    GROUP BY DATE_TRUNC('week', recorded_at)
                ),

                weekly_distance AS (
                    SELECT
                        week_start,
                        SUM(distance_metres) / 1000.0
                            AS distance_km

                    FROM (
                        SELECT
                            DATE_TRUNC('week', recorded_at)::date
                                AS week_start,

                            ST_Distance(
                                previous_geom,
                                geom
                            ) AS distance_metres,

                            EXTRACT(
                                EPOCH FROM
                                (recorded_at - previous_time)
                            ) AS interval_seconds

                        FROM (
                            SELECT
                                recorded_at,
                                geom,

                                LAG(recorded_at) OVER (
                                    ORDER BY recorded_at
                                ) AS previous_time,

                                LAG(geom) OVER (
                                    ORDER BY recorded_at
                                ) AS previous_geom

                            FROM public.vehicle_telemetry

                            WHERE vehicle_id = %s
                        ) t

                        WHERE previous_time IS NOT NULL

                        AND recorded_at - previous_time
                            <= INTERVAL '15 seconds'
                    ) d

                    WHERE interval_seconds > 0

                    AND distance_metres <=
                        interval_seconds *
                        (%s / 3.6)

                    GROUP BY week_start
                ),

                weekly_violations AS (
                    SELECT
                        DATE_TRUNC('week', violation_time)::date
                            AS week_start,

                        COUNT(*) AS violation_count

                    FROM public.violations

                    WHERE vehicle_id = %s
                    AND violation_time >= NOW() - INTERVAL '8 weeks'

                    GROUP BY DATE_TRUNC('week', violation_time)
                )

                SELECT
                    s.week_start,

                    ROUND(s.average_speed::numeric, 2)
                        AS average_speed,

                    ROUND(s.maximum_speed::numeric, 2)
                        AS maximum_speed,

                    ROUND(
                        COALESCE(d.distance_km, 0)::numeric, 3
                    ) AS distance_km,

                    COALESCE(v.violation_count, 0)
                        AS violations

                FROM weekly_speed s

                LEFT JOIN weekly_distance d
                    ON d.week_start = s.week_start

                LEFT JOIN weekly_violations v
                    ON v.week_start = s.week_start

                ORDER BY s.week_start;
            """, (
                vehicle_id,
                vehicle_id,
                MAX_PLAUSIBLE_SPEED_KMH,
                vehicle_id
            ))

            weekly_statistics = serialize_rows(cur.fetchall())

        # -------------------------------------------------
        # RETURN ANALYTICS
        # -------------------------------------------------

        return jsonify({
            "vehicle_id": vehicle_id,

            "summary": {
                "average_speed": round(
                    float(summary["average_speed"]), 2
                ),

                "maximum_speed": round(
                    float(summary["maximum_speed"]), 2
                ),

                "total_distance_km": round(
                    float(summary["total_distance_km"]), 3
                ),

                "total_violations": int(
                    violations["total_violations"]
                ),

                "total_fine": float(
                    violations["total_fine"]
                ),

                "overspeed_duration_seconds": round(
                    float(summary["overspeed_seconds"]), 1
                ),

                "overspeed_duration_minutes": round(
                    float(summary["overspeed_seconds"]) / 60, 2
                )
            },

            "daily_statistics": daily_statistics,
            "weekly_statistics": weekly_statistics

        }), 200

    except Exception:
        app.logger.exception("Driving analytics failed")

        return jsonify({
            "error": "Could not calculate driving analytics"
        }), 500

    finally:
        if conn:
            conn.close()


# =========================================================
# START FLASK SERVER
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000))
    )
