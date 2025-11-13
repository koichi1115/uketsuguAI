"""
データベース接続管理モジュール
Cloud SQL（PostgreSQL）とGemini APIクライアントの接続を管理
"""
import sqlalchemy
from google.cloud.sql.connector import Connector
from google import genai
from core.config import get_secret

# グローバル変数（遅延初期化）
_engine = None
_connector = None
_gemini_client = None


def get_db_engine():
    """Database Engineを取得（遅延初期化）"""
    global _engine, _connector

    if _engine is None:
        # Database接続設定
        db_connection_name = get_secret('DB_CONNECTION_NAME')
        db_user = get_secret('DB_USER')
        db_password = get_secret('DB_PASSWORD')
        db_name = get_secret('DB_NAME')

        # Cloud SQL Connector
        _connector = Connector()

        def get_db_connection():
            """Cloud SQL接続を取得"""
            conn = _connector.connect(
                db_connection_name,
                "pg8000",
                user=db_user,
                password=db_password,
                db=db_name
            )
            return conn

        # SQLAlchemy エンジン
        _engine = sqlalchemy.create_engine(
            "postgresql+pg8000://",
            creator=get_db_connection,
        )

    return _engine


def get_gemini_client():
    """Gemini Clientを取得（遅延初期化）"""
    global _gemini_client

    if _gemini_client is None:
        gemini_api_key = get_secret('GEMINI_API_KEY')
        _gemini_client = genai.Client(api_key=gemini_api_key)

    return _gemini_client
