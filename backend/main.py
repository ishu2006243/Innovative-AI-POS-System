
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

from database import get_connection
from ai.demand_forecast import forecast_demand
from ai.dynamic_pricing import recommend_price
from ai.behavioral_anomaly import detect_anomaly
from decimal import Decimal
from typing import List


app = FastAPI(
    title="Intelligent POS System API",
    description="POS backend with AI forecasting, pricing, and anomaly detection",
    version="1.0.0"
)


# --------------------------------------------------
# CORS CONFIGURATION
# --------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# --------------------------------------------------
# HOME AND DATABASE TEST
# --------------------------------------------------

@app.get("/")
def home():
    return {
        "message": "POS Backend is running"
    }


@app.get("/test-db")
def test_db():
    conn = None

    try:
        conn = get_connection()

        return {
            "message": "MySQL connected successfully"
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

    finally:
        if conn:
            conn.close()


# --------------------------------------------------
# GET ALL PRODUCTS
# --------------------------------------------------

@app.get("/products")
def get_products():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM products
            ORDER BY id
        """)

        products = cursor.fetchall()

        return products

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load products: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# UPDATE PRODUCT STOCK
# Used by the Retailer workspace
# Example:
# PUT /products/3982/stock?stock=75
# --------------------------------------------------

@app.put("/products/{product_id}/stock")
def update_product_stock(product_id: int, stock: int):
    conn = None
    cursor = None

    if product_id <= 0:
        raise HTTPException(
            status_code=400,
            detail="Product ID must be positive."
        )

    if stock < 0:
        raise HTTPException(
            status_code=400,
            detail="Stock cannot be negative."
        )

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Check whether the product exists.
        cursor.execute(
            """
            SELECT id, name
            FROM products
            WHERE id = %s
            """,
            (product_id,)
        )

        product = cursor.fetchone()

        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found."
            )

        # Save the new stock quantity in MySQL.
        cursor.execute(
            """
            UPDATE products
            SET stock = %s
            WHERE id = %s
            """,
            (stock, product_id)
        )

        conn.commit()

        return {
            "message": "Stock updated successfully",
            "product_id": product_id,
            "product_name": product["name"],
            "stock": stock
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Stock update failed: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# SALES HISTORY
# Used by the Revenue Report and Anomaly Detection
# --------------------------------------------------

@app.get("/sales/history")
def get_sales_history():
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                s.id AS sale_id,
                COALESCE(
                    s.customer_name,
                    'Walk-in customer'
                ) AS user_name,
                GROUP_CONCAT(
                    CONCAT(p.name, ' × ', si.quantity)
                    ORDER BY p.name
                    SEPARATOR ', '
                ) AS products,
                s.created_at AS sale_time,
                s.payment_method AS payment_mode,
                s.total
            FROM sales s
            JOIN sale_items si
                ON s.id = si.sale_id
            JOIN products p
                ON si.product_id = p.id
            GROUP BY
                s.id,
                s.customer_name,
                s.created_at,
                s.payment_method,
                s.total
            ORDER BY s.created_at DESC
        """)

        return cursor.fetchall()

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load sales history: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# PRODUCT SYNCHRONIZATION
# --------------------------------------------------

class ProductSyncItem(BaseModel):
    name: str
    category: str
    price: float


@app.post("/products/sync")
def sync_products(items: List[ProductSyncItem]):
    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        added = 0
        updated = 0

        for item in items:
            cursor.execute(
                """
                SELECT id
                FROM products
                WHERE name = %s AND category = %s
                LIMIT 1
                """,
                (item.name, item.category)
            )

            existing = cursor.fetchone()

            if existing:
                cursor.execute(
                    """
                    UPDATE products
                    SET price = %s
                    WHERE id = %s
                    """,
                    (item.price, existing["id"])
                )

                updated += 1

            else:
                cursor.execute(
                    """
                    INSERT INTO products
                        (name, category, price, stock)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        item.name,
                        item.category,
                        item.price,
                        100
                    )
                )

                added += 1

        conn.commit()

        return {
            "message": "Products synchronized successfully",
            "added": added,
            "updated": updated
        }

    except Exception as e:
        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Product sync failed: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# SALE MODELS
# --------------------------------------------------

class SaleItem(BaseModel):
    product_id: int
    quantity: int
    price: float


class SaleData(BaseModel):
    customer_name: str = "Walk-in customer"
    subtotal: float
    discount: float
    total: float
    payment_method: str
    items: List[SaleItem]


# --------------------------------------------------
# CREATE SALE
# Stores transaction and sale items in MySQL
# Automatically reduces product stock
# --------------------------------------------------

@app.post("/sales")
def create_sale(sale: SaleData):
    conn = None
    cursor = None

    try:
        if not sale.items:
            raise HTTPException(
                status_code=400,
                detail="A sale must contain at least one item."
            )

        for item in sale.items:
            if item.quantity <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Item quantity must be positive."
                )

            if item.price < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Item price cannot be negative."
                )

        conn = get_connection()
        cursor = conn.cursor()

        # Create the sale record.
        cursor.execute(
            """
            INSERT INTO sales
                (
                    customer_name,
                    subtotal,
                    discount,
                    total,
                    payment_method
                )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                sale.customer_name,
                sale.subtotal,
                sale.discount,
                sale.total,
                sale.payment_method
            )
        )

        sale_id = cursor.lastrowid

        # Insert sale items and reduce stock.
        for item in sale.items:
            cursor.execute(
                """
                SELECT stock
                FROM products
                WHERE id = %s
                FOR UPDATE
                """,
                (item.product_id,)
            )

            product = cursor.fetchone()

            if not product:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"Product ID {item.product_id} not found."
                    )
                )

            current_stock = product[0]

            if current_stock < item.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Insufficient stock for product "
                        f"ID {item.product_id}. "
                        f"Available: {current_stock}"
                    )
                )

            line_total = item.quantity * item.price

            cursor.execute(
                """
                INSERT INTO sale_items
                    (
                        sale_id,
                        product_id,
                        quantity,
                        price,
                        line_total
                    )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    sale_id,
                    item.product_id,
                    item.quantity,
                    item.price,
                    line_total
                )
            )

            cursor.execute(
                """
                UPDATE products
                SET stock = stock - %s
                WHERE id = %s
                """,
                (
                    item.quantity,
                    item.product_id
                )
            )

        conn.commit()

        return {
            "message": "Sale saved successfully",
            "sale_id": sale_id
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Sale failed: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()

        if conn:
            conn.close()


# --------------------------------------------------
# AI: DEMAND FORECASTING
# --------------------------------------------------

@app.get("/ai/demand-forecast/{product_id}")
def demand_forecast(product_id: int):
    return forecast_demand(product_id)


# --------------------------------------------------
# AI: DYNAMIC PRICING
# --------------------------------------------------

@app.get("/ai/dynamic-pricing/{product_id}")
def dynamic_pricing(product_id: int):
    return recommend_price(product_id)


# --------------------------------------------------
# GET SAVED PRICING RECOMMENDATIONS
# --------------------------------------------------

@app.get("/ai/pricing-recommendations")
def get_pricing_recommendations(status: str = "PENDING"):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT r.*, p.name AS product_name
            FROM pricing_recommendations r
            JOIN products p ON p.id = r.product_id
            WHERE r.status = %s
            ORDER BY r.created_at DESC
            """,
            (status,)
        )

        return cursor.fetchall()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --------------------------------------------------
# APPROVE PRICING RECOMMENDATION
# --------------------------------------------------

@app.post("/ai/pricing-recommendations/{recommendation_id}/approve")
def approve_pricing_recommendation(recommendation_id: int):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM pricing_recommendations
            WHERE id = %s
            FOR UPDATE
            """,
            (recommendation_id,)
        )

        recommendation = cursor.fetchone()

        if not recommendation:
            raise HTTPException(
                status_code=404,
                detail="Recommendation not found."
            )

        if recommendation["status"] != "PENDING":
            raise HTTPException(
                status_code=400,
                detail="Recommendation is not pending."
            )

        product_id = recommendation["product_id"]

        cursor.execute(
            """
            SELECT id, name, price
            FROM products
            WHERE id = %s
            FOR UPDATE
            """,
            (product_id,)
        )

        product = cursor.fetchone()

        if not product:
            raise HTTPException(
                status_code=404,
                detail="Product not found."
            )

        old_price = Decimal(str(product["price"]))
        recorded_price = Decimal(
            str(recommendation["current_price"])
        )
        new_price = Decimal(
            str(recommendation["recommended_price"])
        )

        if old_price != recorded_price:
            raise HTTPException(
                status_code=409,
                detail="Product price has changed. Generate a new recommendation."
            )

        # Update actual product price.
        cursor.execute(
            """
            UPDATE products
            SET price = %s
            WHERE id = %s
            """,
            (new_price, product_id)
        )

        # Save the price change.
        cursor.execute(
            """
            INSERT INTO price_history
            (
                product_id,
                recommendation_id,
                old_price,
                new_price,
                change_source,
                changed_by
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                product_id,
                recommendation_id,
                old_price,
                new_price,
                "AI_APPROVED",
                "Owner"
            )
        )

        # Update recommendation status.
        cursor.execute(
            """
            UPDATE pricing_recommendations
            SET status = 'APPLIED',
                approved_at = NOW()
            WHERE id = %s
            """,
            (recommendation_id,)
        )

        conn.commit()

        return {
            "message": "Price recommendation approved successfully",
            "product_id": product_id,
            "old_price": float(old_price),
            "new_price": float(new_price),
            "status": "APPLIED"
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Approval failed: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# --------------------------------------------------
# REJECT PRICING RECOMMENDATION
# --------------------------------------------------

@app.post("/ai/pricing-recommendations/{recommendation_id}/reject")
def reject_pricing_recommendation(recommendation_id: int):

    conn = None
    cursor = None

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, status
            FROM pricing_recommendations
            WHERE id = %s
            FOR UPDATE
            """,
            (recommendation_id,)
        )

        recommendation = cursor.fetchone()

        if not recommendation:
            raise HTTPException(
                status_code=404,
                detail="Recommendation not found."
            )

        if recommendation["status"] != "PENDING":
            raise HTTPException(
                status_code=400,
                detail="Recommendation is not pending."
            )

        cursor.execute(
            """
            UPDATE pricing_recommendations
            SET status = 'REJECTED'
            WHERE id = %s
            """,
            (recommendation_id,)
        )

        conn.commit()

        return {
            "message": "Recommendation rejected",
            "recommendation_id": recommendation_id,
            "status": "REJECTED"
        }

    except HTTPException:
        if conn:
            conn.rollback()
        raise

    except Exception as e:
        if conn:
            conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Rejection failed: {str(e)}"
        )

    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# --------------------------------------------------
# AI: BEHAVIORAL ANOMALY DETECTION
# --------------------------------------------------

@app.get("/ai/anomaly-detection/{sale_id}")
def behavioral_anomaly(sale_id: int):
    return detect_anomaly(sale_id)
