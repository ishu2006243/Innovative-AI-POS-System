
from database import get_connection
import json


def recommend_price(product_id: int):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ------------------------------------------
        # 1. GET PRODUCT DETAILS
        # ------------------------------------------

        cursor.execute(
            """
            SELECT id, name, price, stock
            FROM products
            WHERE id = %s
            """,
            (product_id,)
        )

        product = cursor.fetchone()

        if not product:
            return {
                "status": "not_found",
                "message": "Product not found."
            }

        price = float(product["price"])
        stock = int(product["stock"] or 0)

        # ------------------------------------------
        # 2. GET SALES HISTORY
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(si.quantity), 0) AS total_units,
                DATEDIFF(
                    MAX(DATE(s.created_at)),
                    MIN(DATE(s.created_at))
                ) + 1 AS observed_days
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE si.product_id = %s
            """,
            (product_id,)
        )

        history = cursor.fetchone()

        total_units = int(history["total_units"] or 0)
        observed_days = int(history["observed_days"] or 0)

        # ------------------------------------------
        # 3. LIMITED HISTORY
        # ------------------------------------------

        if observed_days < 7:

            recommended_price = round(price, 2)

            reason = (
                "Limited sales history. Keep the current "
                "price until more data is available."
            )

            result = {
                "product_id": product_id,
                "product_name": product["name"],
                "status": "provisional",
                "current_price": round(price, 2),
                "stock": stock,
                "observed_days": observed_days,
                "recommended_discount_percent": 0,
                "recommended_price": recommended_price,
                "reason": reason
            }

            reason_data = {
                "reason": reason,
                "observed_days": observed_days,
                "total_units": total_units,
                "method": "limited_history_rule"
            }

            model_name = "rule_based"

        # ------------------------------------------
        # 4. CALCULATE PRICING RECOMMENDATION
        # ------------------------------------------

        else:

            daily_demand = total_units / observed_days
            days_of_stock = None

            if stock <= 0:

                discount = 0

                reason = (
                    "Out of stock. Replenish inventory first."
                )

            elif daily_demand <= 0:

                discount = 0

                reason = (
                    "No recorded sales in the observed period."
                )

            else:

                days_of_stock = stock / daily_demand

                if days_of_stock >= 30:

                    discount = 10

                    reason = (
                        "Stock may cover 30 or more days of "
                        "demand. Consider a 10% discount."
                    )

                elif days_of_stock >= 14:

                    discount = 5

                    reason = (
                        "Stock may cover 14 or more days of "
                        "demand. Consider a 5% discount."
                    )

                else:

                    discount = 0

                    reason = (
                        "Stock appears proportionate to demand. "
                        "Keep the current price."
                    )

            recommended_price = round(
                price * (1 - discount / 100),
                2
            )

            result = {
                "product_id": product_id,
                "product_name": product["name"],
                "status": "recommendation",
                "current_price": round(price, 2),
                "stock": stock,
                "average_daily_demand": round(
                    daily_demand, 2
                ),
                "days_of_stock": (
                    round(days_of_stock, 2)
                    if days_of_stock is not None
                    else None
                ),
                "recommended_discount_percent": discount,
                "recommended_price": recommended_price,
                "reason": reason
            }

            reason_data = {
                "reason": reason,
                "observed_days": observed_days,
                "total_units": total_units,
                "average_daily_demand": round(daily_demand, 2),
                "days_of_stock": (
                    round(days_of_stock, 2)
                    if days_of_stock is not None
                    else None
                ),
                "discount_percent": discount,
                "method": "stock_coverage_rule"
            }

            model_name = "rule_based"

        # ------------------------------------------
        # 5. SAVE RECOMMENDATION IN MYSQL
        # ------------------------------------------

        cursor.execute(
            """
            INSERT INTO pricing_recommendations
            (
                product_id,
                current_price,
                recommended_price,
                expected_profit_margin,
                recommendation_reason,
                model_name,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                price,
                recommended_price,
                None,
                json.dumps(reason_data),
                model_name,
                "PENDING"
            )
        )

        recommendation_id = cursor.lastrowid

        conn.commit()

        result["recommendation_id"] = recommendation_id
        result["database_saved"] = True
        result["recommendation_status"] = "PENDING"

        return result

    except Exception:

        if conn:
            conn.rollback()

        raise

    finally:

        if cursor:
            cursor.close()

        if conn:
            conn.close()

from database import get_connection
import json


def recommend_price(product_id: int):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # ------------------------------------------
        # 1. GET PRODUCT DETAILS
        # ------------------------------------------

        cursor.execute(
            """
            SELECT id, name, price, stock
            FROM products
            WHERE id = %s
            """,
            (product_id,)
        )

        product = cursor.fetchone()

        if not product:
            return {
                "status": "not_found",
                "message": "Product not found."
            }

        price = float(product["price"])
        stock = int(product["stock"] or 0)

        # ------------------------------------------
        # 2. GET SALES HISTORY
        # ------------------------------------------

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(si.quantity), 0) AS total_units,
                DATEDIFF(
                    MAX(DATE(s.created_at)),
                    MIN(DATE(s.created_at))
                ) + 1 AS observed_days
            FROM sale_items si
            JOIN sales s ON s.id = si.sale_id
            WHERE si.product_id = %s
            """,
            (product_id,)
        )

        history = cursor.fetchone()

        total_units = int(history["total_units"] or 0)
        observed_days = int(history["observed_days"] or 0)

        # ------------------------------------------
        # 3. LIMITED HISTORY
        # ------------------------------------------

        if observed_days < 7:

            recommended_price = round(price, 2)

            reason = (
                "Limited sales history. Keep the current "
                "price until more data is available."
            )

            result = {
                "product_id": product_id,
                "product_name": product["name"],
                "status": "provisional",
                "current_price": round(price, 2),
                "stock": stock,
                "observed_days": observed_days,
                "recommended_discount_percent": 0,
                "recommended_price": recommended_price,
                "reason": reason
            }

            reason_data = {
                "reason": reason,
                "observed_days": observed_days,
                "total_units": total_units,
                "method": "limited_history_rule"
            }

            model_name = "rule_based"

        # ------------------------------------------
        # 4. CALCULATE PRICING RECOMMENDATION
        # ------------------------------------------

        else:

            daily_demand = total_units / observed_days
            days_of_stock = None

            if stock <= 0:

                discount = 0

                reason = (
                    "Out of stock. Replenish inventory first."
                )

            elif daily_demand <= 0:

                discount = 0

                reason = (
                    "No recorded sales in the observed period."
                )

            else:

                days_of_stock = stock / daily_demand

                if days_of_stock >= 30:

                    discount = 10

                    reason = (
                        "Stock may cover 30 or more days of "
                        "demand. Consider a 10% discount."
                    )

                elif days_of_stock >= 14:

                    discount = 5

                    reason = (
                        "Stock may cover 14 or more days of "
                        "demand. Consider a 5% discount."
                    )

                else:

                    discount = 0

                    reason = (
                        "Stock appears proportionate to demand. "
                        "Keep the current price."
                    )

            recommended_price = round(
                price * (1 - discount / 100),
                2
            )

            result = {
                "product_id": product_id,
                "product_name": product["name"],
                "status": "recommendation",
                "current_price": round(price, 2),
                "stock": stock,
                "average_daily_demand": round(
                    daily_demand, 2
                ),
                "days_of_stock": (
                    round(days_of_stock, 2)
                    if days_of_stock is not None
                    else None
                ),
                "recommended_discount_percent": discount,
                "recommended_price": recommended_price,
                "reason": reason
            }

            reason_data = {
                "reason": reason,
                "observed_days": observed_days,
                "total_units": total_units,
                "average_daily_demand": round(daily_demand, 2),
                "days_of_stock": (
                    round(days_of_stock, 2)
                    if days_of_stock is not None
                    else None
                ),
                "discount_percent": discount,
                "method": "stock_coverage_rule"
            }

            model_name = "rule_based"

        # ------------------------------------------
        # 5. SAVE RECOMMENDATION IN MYSQL
        # ------------------------------------------

        cursor.execute(
            """
            INSERT INTO pricing_recommendations
            (
                product_id,
                current_price,
                recommended_price,
                expected_profit_margin,
                recommendation_reason,
                model_name,
                status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                price,
                recommended_price,
                None,
                json.dumps(reason_data),
                model_name,
                "PENDING"
            )
        )

        recommendation_id = cursor.lastrowid

        conn.commit()

        result["recommendation_id"] = recommendation_id
        result["database_saved"] = True
        result["recommendation_status"] = "PENDING"

        return result

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
# GET SAVED PRICING RECOMMENDATIONS
# --------------------------------------------------

