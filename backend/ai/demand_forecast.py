
import pandas as pd
import shap
import json

from datetime import date, timedelta
from sklearn.linear_model import LinearRegression
from database import get_connection


# --------------------------------------------------
# GET HISTORICAL SALES DATA
# --------------------------------------------------

def get_sales_data(product_id: int):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                DATE(s.created_at) AS sale_date,
                SUM(si.quantity) AS quantity
            FROM sales s
            JOIN sale_items si
                ON s.id = si.sale_id
            WHERE si.product_id = %s
            GROUP BY DATE(s.created_at)
            ORDER BY sale_date
            """,
            (product_id,)
        )

        return cursor.fetchall()

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# SAVE FORECAST RESULTS IN MYSQL
# --------------------------------------------------

def save_forecast_results(product_id: int, result: dict):

    forecasts = result.get("forecast_next_7_days", [])

    if not forecasts:
        return 0

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        model_name = result.get("method", "unknown")

        # Forecast starts from tomorrow.
        start_date = date.today() + timedelta(days=1)

        # Replace the previous active 7-day forecast
        # for this product to avoid duplicate predictions.
        cursor.execute(
            """
            DELETE FROM demand_forecasts
            WHERE product_id = %s
              AND horizon_days = 7
              AND forecast_for_date >= %s
            """,
            (product_id, start_date)
        )

        for index, item in enumerate(forecasts):

            forecast_date = start_date + timedelta(days=index)

            if isinstance(item, dict):

                predicted_quantity = float(
                    item["predicted_demand"]
                )

                explanation_data = {
                    "method": "SHAP",
                    "baseline_prediction": item.get(
                        "baseline_prediction"
                    ),
                    "shap_contribution": item.get(
                        "shap_contribution"
                    ),
                    "explanation": item.get("explanation")
                }

            else:

                predicted_quantity = float(item)

                explanation_data = {
                    "method": "rule_based",
                    "explanation": result.get("explanation"),
                    "historical_days": result.get(
                        "historical_days"
                    )
                }

            cursor.execute(
                """
                INSERT INTO demand_forecasts
                (
                    product_id,
                    forecast_for_date,
                    horizon_days,
                    predicted_quantity,
                    lower_bound,
                    upper_bound,
                    model_name,
                    confidence_score,
                    explanation
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    product_id,
                    forecast_date,
                    7,
                    predicted_quantity,
                    None,
                    None,
                    model_name,
                    None,
                    json.dumps(explanation_data)
                )
            )

        conn.commit()

        return len(forecasts)

    except Exception:
        if conn:
            conn.rollback()

        raise

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# DEMAND FORECASTING
# --------------------------------------------------

def forecast_demand(product_id: int):

    data = get_sales_data(product_id)

    if not data:
        return {
            "product_id": product_id,
            "status": "no_data",
            "message": "No sales data found for this product."
        }

    df = pd.DataFrame(data)

    df["sale_date"] = pd.to_datetime(df["sale_date"])
    df["quantity"] = pd.to_numeric(df["quantity"])

    # Fill dates without sales with zero.
    df = (
        df.set_index("sale_date")[["quantity"]]
        .resample("D")
        .sum()
        .fillna(0)
        .reset_index()
    )

    historical_days = len(df)
    average_demand = float(df["quantity"].mean())

    # --------------------------------------------------
    # PROVISIONAL FORECAST
    # --------------------------------------------------

    if historical_days < 7:

        result = {
            "product_id": product_id,
            "status": "provisional",
            "method": "average_baseline",
            "historical_days": historical_days,
            "average_daily_sales": round(average_demand, 2),

            "forecast_next_7_days": [
                round(average_demand, 2)
            ] * 7,

            "explanation_method": "rule_based",

            "explanation": (
                f"Only {historical_days} historical sales day(s) "
                "are available. The forecast uses average daily "
                f"sales of {average_demand:.2f} units. More "
                "historical data is needed for a trained model "
                "and SHAP explanation."
            ),

            "message": (
                "Provisional estimate. Collect more "
                "historical sales for a better forecast."
            )
        }

        saved_records = save_forecast_results(
            product_id,
            result
        )

        result["database_saved"] = True
        result["saved_records"] = saved_records

        return result

    # --------------------------------------------------
    # TRAIN LINEAR REGRESSION MODEL
    # --------------------------------------------------

    df["day_number"] = range(historical_days)

    X = df[["day_number"]]
    y = df["quantity"]

    model = LinearRegression()
    model.fit(X, y)

    # --------------------------------------------------
    # SHAP EXPLANATION
    # --------------------------------------------------

    explainer = shap.LinearExplainer(model, X)

    future_days = pd.DataFrame({
        "day_number": range(
            historical_days,
            historical_days + 7
        )
    })

    predictions = model.predict(future_days)

    shap_results = explainer(future_days)

    forecast = []

    for i, value in enumerate(predictions):

        contribution = float(shap_results.values[i][0])
        baseline = float(shap_results.base_values[i])

        forecast.append({
            "day": i + 1,

            "predicted_demand": max(
                0,
                round(float(value), 2)
            ),

            "baseline_prediction": round(baseline, 2),

            "shap_contribution": round(contribution, 2),

            "explanation": (
                "The time trend increased the prediction."
                if contribution > 0
                else "The time trend decreased the prediction."
                if contribution < 0
                else "The time trend did not change the baseline prediction."
            )
        })

    # --------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------

    result = {
        "product_id": product_id,
        "status": "success",
        "method": "linear_regression",
        "explanation_method": "SHAP",
        "historical_days": historical_days,
        "forecast_next_7_days": forecast
    }

    # Save predictions into MySQL.
    saved_records = save_forecast_results(
        product_id,
        result
    )

    result["database_saved"] = True
    result["saved_records"] = saved_records

    return result
