import asyncio
import csv
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.engine import engine
from db.models import TheoryResource

async def dump():
    print("Reading database...")
    async with AsyncSession(engine) as session:
        statement = select(TheoryResource)
        results = await session.execute(statement)
        resources = results.scalars().all()
        
        if not resources:
            print("No resources found in the database.")
            return

        keys = ["id", "title", "resource_type", "url", "description", "tags", "is_dead"]
        with open('emergency_dump.csv', 'w', newline='', encoding='utf-8') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            for r in resources:
                # We skip file_data binary to keep the dump clean and fast
                dict_writer.writerow({
                    "id": r.id,
                    "title": r.title,
                    "resource_type": r.resource_type,
                    "url": r.url,
                    "description": r.description,
                    "tags": r.tags,
                    "is_dead": r.is_dead
                })
    print(f"✅ Successfully dumped {len(resources)} resources to emergency_dump.csv")

if __name__ == "__main__":
    asyncio.run(dump())