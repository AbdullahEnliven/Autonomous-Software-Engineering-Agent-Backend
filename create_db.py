import asyncio
import asyncpg
from urllib.parse import urlparse

DATABASE_URL = "postgresql+asyncpg://postgres:Moosajutt786@localhost:5432/Asea"

async def create_db():
    parsed = urlparse(DATABASE_URL)
    username = parsed.username
    password = parsed.password
    host = parsed.hostname
    port = parsed.port
    database = parsed.path.lstrip('/')
    
    # Connect to the default 'postgres' database to create the new one
    try:
        sys_conn = await asyncpg.connect(
            user=username,
            password=password,
            host=host,
            port=port,
            database='postgres'
        )
        # Execute CREATE DATABASE outside a transaction block
        await sys_conn.execute(f'CREATE DATABASE "{database}"')
        print(f"Database {database} created successfully.")
        await sys_conn.close()
    except asyncpg.exceptions.DuplicateDatabaseError:
        print(f"Database {database} already exists.")
    except Exception as e:
        print(f"Error creating database: {e}")

if __name__ == "__main__":
    asyncio.run(create_db())
