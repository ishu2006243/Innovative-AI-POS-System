
from database import get_connection
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import pandas as pd
import json


def detect_anomaly(sale_id: int):

    conn = None
    cursor = None

    try:
        # Connect to MySQL
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch all transaction details
        cursor.execute("""
            SELECT
                s.id AS sale_id,
                s.subtotal,
                s.discount,
                s.total,
                s.created_at,
                COUNT(si.id) AS item_lines,
                COALESCE(SUM(si.quantity), 0) AS total_quantity
            FROM sales s
            LEFT JOIN sale_items si
                ON s.id = si.sale_id
            GROUP BY
                s.id,
                s.subtotal,
                s.discount,
                s.total,
                s.created_at
            ORDER BY s.id
        """)

        rows = cursor.fetchall()

        # Find requested transaction
        target = next(
            (
                row for row in rows
                if int(row["sale_id"]) == sale_id
            ),
            None
        )

        if target is None:
            return {
                "status": "not_found",
                "message": "Transaction not found."
            }

        # Previous transactions for training
        history = [
            row for row in rows
            if int(row["sale_id"]) < sale_id
        ]

        if len(history) < 10:
            return {
                "status": "insufficient_data",
                "sale_id": sale_id,
                "historical_transactions": len(history),
                "message": (
                    "At least 10 previous transactions "
                    "are required."
                )
            }

        # Feature extraction
        def extract_features(row):

            subtotal = float(row["subtotal"] or 0)
            discount = float(row["discount"] or 0)

            timestamp = pd.to_datetime(
                row["created_at"]
            )

            return [
                subtotal,
                discount,
                float(row["total"] or 0),
                discount / subtotal if subtotal > 0 else 0,
                float(row["item_lines"] or 0),
                float(row["total_quantity"] or 0),
                timestamp.hour
            ]

        feature_names = [
            "subtotal",
            "discount",
            "total",
            "discount_ratio",
            "item_lines",
            "total_quantity",
            "hour"
        ]

        X_train = pd.DataFrame(
            [extract_features(row) for row in history],
            columns=feature_names
        )

        X_target = pd.DataFrame(
            [extract_features(target)],
            columns=feature_names
        )

        # Standardize features
        scaler = StandardScaler()

        X_train_scaled = scaler.fit_transform(X_train)

        X_target_scaled = scaler.transform(X_target)

        # Isolation Forest model
        model = IsolationForest(
            n_estimators=100,
            contamination=0.1,
            random_state=42
        )

        model.fit(X_train_scaled)

        # Predict anomaly
        prediction = int(
            model.predict(X_target_scaled)[0]
        )

        score = float(
            model.score_samples(X_target_scaled)[0]
        )

        is_anomaly = prediction == -1

        anomaly_score = round(-score, 5)

        risk_level = (
            "HIGH" if is_anomaly else "LOW"
        )

        # Explanation
        explanation = {
            "total": float(target["total"]),
            "subtotal": float(target["subtotal"]),
            "discount": float(target["discount"]),
            "total_quantity": int(
                target["total_quantity"]
            ),
            "item_lines": int(target["item_lines"]),
            "historical_transactions": len(history),
            "features_analyzed": feature_names,
            "message": (
                "Unusual transaction pattern detected. "
                "Manager review recommended."
                if is_anomaly
                else "No unusual transaction pattern detected."
            )
        }

        # Save result into MySQL
        cursor.execute(
            """
            SELECT id
            FROM anomaly_detection_results
            WHERE sale_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (sale_id,)
        )

        existing = cursor.fetchone()

        if existing:

            cursor.execute(
                """
                UPDATE anomaly_detection_results
                SET
                    anomaly_score = %s,
                    risk_level = %s,
                    is_anomaly = %s,
                    explanation = %s,
                    model_name = %s,
                    review_status = 'PENDING',
                    detected_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    anomaly_score,
                    risk_level,
                    is_anomaly,
                    json.dumps(explanation),
                    "IsolationForest",
                    existing["id"]
                )
            )

            result_id = existing["id"]

        else:

            cursor.execute(
                """
                INSERT INTO anomaly_detection_results
                (
                    sale_id,
                    anomaly_score,
                    risk_level,
                    is_anomaly,
                    explanation,
                    model_name,
                    review_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'PENDING')
                """,
                (
                    sale_id,
                    anomaly_score,
                    risk_level,
                    is_anomaly,
                    json.dumps(explanation),
                    "IsolationForest"
                )
            )

            result_id = cursor.lastrowid

        conn.commit()

        # Return result
        return {
            "result_id": result_id,
            "sale_id": sale_id,
            "status": (
                "review_recommended"
                if is_anomaly
                else "normal_pattern"
            ),
            "is_anomaly": is_anomaly,
            "anomaly_score": anomaly_score,
            "risk_level": risk_level,
            "historical_transactions": len(history),
            "explanation": explanation,
            "review_status": "PENDING",
            "model_name": "IsolationForest",
            "message": (
                "Anomaly result saved successfully."
            )
        }

    except Exception as e:

        if conn:
            conn.rollback()

        raise RuntimeError(
            f"Behavioral anomaly detection failed: {str(e)}"
        )

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()
