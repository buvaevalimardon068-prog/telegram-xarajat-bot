import aiosqlite
from datetime import datetime


DB_NAME = "finance_bot.db"


# =========================================================
# DATABASE YARATISH
# =========================================================

async def init_db():

    async with aiosqlite.connect(
        DB_NAME
    ) as db:

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                user_id INTEGER NOT NULL,

                transaction_type TEXT NOT NULL,

                product_name TEXT,

                quantity REAL,

                unit TEXT,

                unit_price REAL,

                total REAL NOT NULL,

                category TEXT,

                note TEXT,

                created_at TEXT NOT NULL,

                deleted_at TEXT
            )
            """
        )

        # Eski bazani buzmaslik uchun
        # mavjud ustunlarni tekshiramiz.

        cur = await db.execute(
            "PRAGMA table_info(transactions)"
        )

        columns = {
            row[1]
            for row in await cur.fetchall()
        }

        new_columns = {

            "product_name":
                "TEXT",

            "quantity":
                "REAL",

            "unit":
                "TEXT",

            "unit_price":
                "REAL",

            "category":
                "TEXT",

            "note":
                "TEXT",

            "deleted_at":
                "TEXT",
        }

        for column, definition in new_columns.items():

            if column not in columns:

                await db.execute(
                    f"""
                    ALTER TABLE transactions
                    ADD COLUMN {column}
                    {definition}
                    """
                )

        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_transactions_user

            ON transactions(
                user_id,
                deleted_at,
                created_at
            )
            """
        )

        await db.commit()


# =========================================================
# TRANSACTION QO‘SHISH
# =========================================================

async def add_transaction(

    user_id,

    transaction_type,

    total,

    created_at,

    product_name=None,

    quantity=None,

    unit=None,

    unit_price=None,

    category=None,

    note=None,
):

    async with aiosqlite.connect(
        DB_NAME
    ) as db:

        cur = await db.execute(

            """
            INSERT INTO transactions

            (
                user_id,
                transaction_type,
                product_name,
                quantity,
                unit,
                unit_price,
                total,
                category,
                note,
                created_at,
                deleted_at
            )

            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,

            (

                user_id,

                transaction_type,

                product_name,

                quantity,

                unit,

                unit_price,

                total,

                category,

                note,

                created_at,
            )
        )

        await db.commit()

        return cur.lastrowid


# =========================================================
# BALANS
# =========================================================

async def get_balance(
    user_id
):

    async with aiosqlite.connect(
        DB_NAME
    ) as db:

        cur = await db.execute(

            """
            SELECT

                COALESCE(
                    SUM(
                        CASE
                            WHEN transaction_type='income'
                            THEN total
                            ELSE 0
                        END
                    ),
                    0
                ),

                COALESCE(
                    SUM(
                        CASE
                            WHEN transaction_type='expense'
                            THEN total
                            ELSE 0
                        END
                    ),
                    0
                )

            FROM transactions

            WHERE
                user_id=?
                AND deleted_at IS NULL
            """,

            (user_id,)
        )

        return await cur.fetchone()


# =========================================================
# TRANSAKSIYALAR
# =========================================================

async def get_transactions(

    user_id,

    transaction_type=None,

    include_archived=False,
):

    async with aiosqlite.connect(
        DB_NAME
    ) as db:

        where = [
            "user_id=?"
        ]

        params = [
            user_id
        ]

        if transaction_type:

            where.append(
                "transaction_type=?"
            )

            params.append(
                transaction_type
            )

        if not include_archived:

            where.append(
                "deleted_at IS NULL"
            )

        query = f"""

            SELECT

                id,
                transaction_type,
                product_name,
                quantity,
                unit,
                unit_price,
                total,
                category,
                note,
                created_at,
                deleted_at

            FROM transactions

            WHERE
                {' AND '.join(where)}

            ORDER BY id DESC
        """

        cur = await db.execute(
            query,
            params
        )

        return await cur.fetchall()


# =========================================================
# BARCHA MA'LUMOTNI ARXIVLASH
# =========================================================

async def archive_all(
    user_id
):

    archive_time = (
        datetime.now()
        .strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    )

    async with aiosqlite.connect(
        DB_NAME
    ) as db:

        cur = await db.execute(

            """
            UPDATE transactions

            SET deleted_at=?

            WHERE
                user_id=?
                AND deleted_at IS NULL
            """,

            (
                archive_time,
                user_id
            )
        )

        await db.commit()

        return cur.rowcount


# =========================================================
# ARXIVNI OLISH
# =========================================================

async def get_archived_transactions(
    user_id
):

    return await get_transactions(

        user_id=user_id,

        transaction_type=None,

        include_archived=True,
    )