import os

import mysql.connector
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    required_settings = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
    missing_settings = [name for name in required_settings if not os.getenv(name)]
    if missing_settings:
        raise RuntimeError(
            "Missing database configuration: " + ", ".join(missing_settings)
        )

    return mysql.connector.connect(
        host=os.environ["DB_HOST"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
    )