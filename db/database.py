"""
Veritabanı katmanı

SQLAlchemy async ile PostgreSQL.
İki tablo:
  - listings: tüm ham ilanlar
  - price_snapshots: fiyat geçmişi (fiyat motoru için)
"""
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer,
    String, Text, create_engine, text, Index
)
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy import select, and_, func


class Base(DeclarativeBase):
    pass


class ListingORM(Base):
    __tablename__ = "listings"

    id = Column(String, primary_key=True)          # "sahibinden_12345"
    source = Column(String, nullable=False)
    url = Column(Text, nullable=False)
    title = Column(String)
    brand = Column(String, index=True)
    model = Column(String, index=True)
    series = Column(String)
    year = Column(Integer, index=True)
    km = Column(Integer)
    price = Column(Integer, index=True)
    color = Column(String)
    fuel_type = Column(String)
    gear_type = Column(String)
    body_type = Column(String)
    location = Column(String)
    seller_type = Column(String)
    seller_id = Column(String)
    is_active = Column(Boolean, default=True)
    listed_at = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.now)
    first_seen_at = Column(DateTime, default=datetime.now)

    # Compound index: fiyat motoru sorguları için kritik
    __table_args__ = (
        Index("ix_brand_model_year", "brand", "model", "year"),
        Index("ix_price_active", "price", "is_active"),
    )


class PriceSnapshotORM(Base):
    __tablename__ = "price_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    listing_id = Column(String, index=True)
    price = Column(Integer)
    recorded_at = Column(DateTime, default=datetime.now)


class Database:
    """
    Sync wrapper (async gerekirse asyncpg + sqlalchemy[asyncio] kullan)
    Hızlı prototip için sync yeterli.
    """

    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(self.engine)
        logger.info("Veritabanı bağlantısı hazır")

    def upsert_listing(self, listing) -> bool:
        """
        İlan yoksa ekle, varsa güncelle.
        Fiyat değişmişse snapshot kaydet.
        Returns: True if new listing
        """
        with Session(self.engine) as session:
            existing = session.get(ListingORM, listing.id)

            if existing:
                # Fiyat değişmiş mi?
                if existing.price != listing.price:
                    snapshot = PriceSnapshotORM(
                        listing_id=listing.id,
                        price=listing.price,
                    )
                    session.add(snapshot)
                    logger.info(f"Fiyat değişikliği: {listing.id} | {existing.price:,} → {listing.price:,} TL")

                # Güncelle
                existing.price = listing.price
                existing.km = listing.km
                existing.is_active = True
                existing.scraped_at = datetime.now()
                session.commit()
                return False
            else:
                # Yeni ilan
                orm = ListingORM(
                    id=listing.id,
                    source=listing.source,
                    url=listing.url,
                    title=listing.title,
                    brand=listing.brand,
                    model=listing.model,
                    series=listing.series,
                    year=listing.year,
                    km=listing.km,
                    price=listing.price,
                    color=listing.color,
                    fuel_type=listing.fuel_type,
                    gear_type=listing.gear_type,
                    body_type=listing.body_type,
                    location=listing.location,
                    seller_type=listing.seller_type,
                    seller_id=listing.seller_id,
                    listed_at=listing.listed_at,
                    scraped_at=listing.scraped_at,
                    first_seen_at=datetime.now(),
                )
                session.add(orm)

                # İlk fiyat snapshot
                snapshot = PriceSnapshotORM(
                    listing_id=listing.id,
                    price=listing.price,
                )
                session.add(snapshot)
                session.commit()
                return True

    def upsert_many(self, listings: list) -> tuple[int, int]:
        """Toplu upsert. Returns: (new_count, updated_count)"""
        new_count = updated_count = 0
        for listing in listings:
            is_new = self.upsert_listing(listing)
            if is_new:
                new_count += 1
            else:
                updated_count += 1
        return new_count, updated_count

    def get_comparables(
        self,
        brand: str,
        model: str,
        year: int,
        km: int,
        days: int = 30,
        tolerance_pct: float = 0.3,
    ) -> list[dict]:
        """
        Fiyat motoru için: benzer araçları çek.
        Yıl ±1, KM ±%30 tolerans.
        """
        km_min = int(km * (1 - tolerance_pct))
        km_max = int(km * (1 + tolerance_pct))
        cutoff = datetime.now().replace(
            hour=0, minute=0, second=0
        ).timestamp() - (days * 86400)

        with Session(self.engine) as session:
            stmt = select(ListingORM).where(
                and_(
                    ListingORM.brand == brand,
                    ListingORM.model == model,
                    ListingORM.year.between(year - 1, year + 1),
                    ListingORM.km.between(km_min, km_max),
                    ListingORM.is_active == True,
                    ListingORM.price > 0,
                )
            ).limit(200)

            results = session.execute(stmt).scalars().all()

            return [
                {
                    "id": r.id,
                    "price": r.price,
                    "km": r.km,
                    "year": r.year,
                    "url": r.url,
                    "location": r.location,
                }
                for r in results
            ]

    def mark_inactive(self, ids_to_keep: list[str], brand: str):
        """Artık listede olmayan ilanları pasif yap"""
        with Session(self.engine) as session:
            stmt = select(ListingORM).where(
                and_(
                    ListingORM.brand == brand,
                    ListingORM.is_active == True,
                )
            )
            active = session.execute(stmt).scalars().all()
            ids_to_keep_set = set(ids_to_keep)

            deactivated = 0
            for listing in active:
                if listing.id not in ids_to_keep_set:
                    listing.is_active = False
                    deactivated += 1

            session.commit()
            if deactivated:
                logger.info(f"{deactivated} ilan pasif yapıldı ({brand})")

    def stats(self) -> dict:
        """Dashboard için özet istatistikler"""
        with Session(self.engine) as session:
            total = session.execute(
                select(func.count()).select_from(ListingORM)
            ).scalar()

            active = session.execute(
                select(func.count()).select_from(ListingORM).where(
                    ListingORM.is_active == True
                )
            ).scalar()

            by_source = session.execute(
                select(ListingORM.source, func.count())
                .group_by(ListingORM.source)
            ).all()

            avg_price = session.execute(
                select(func.avg(ListingORM.price)).where(
                    ListingORM.is_active == True
                )
            ).scalar()

            return {
                "total": total,
                "active": active,
                "by_source": dict(by_source),
                "avg_price": int(avg_price or 0),
            }
