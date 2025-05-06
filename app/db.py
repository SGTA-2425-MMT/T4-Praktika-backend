from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = AsyncIOMotorClient(settings.MONGODB_URI)
# Use default database name from the MongoDB URI or default to 'civgame'
try:
    db = client.get_default_database()
except Exception:
    # If get_default_database() is not available, use the default database name from the URI
    db_name = settings.MONGODB_URI.split('/')[-1]
    # If the database name is not specified in the URI, default to 'civgame'
    if db_name == '':
        db = client['civgame']
    else:
        db = client[db_name]