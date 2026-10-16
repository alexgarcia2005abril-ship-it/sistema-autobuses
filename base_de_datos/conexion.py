
import os
import sqlite3
from pathlib import Path
from flask import g
from werkzeug.security import generate_password_hash

DB_PATH = Path(
    os.environ.get(
        "DATABASE_PATH",
        str(
            Path(__file__).resolve().parent
            / "central_autobuses.db"
        )
    )
)


def obtener_db():
    if "db" not in g:
        con = sqlite3.connect(
            str(DB_PATH),
            timeout=15
        )
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 15000")
        g.db = con

    return g.db


def cerrar_db(error=None):
    con = g.pop("db", None)

    if con is not None:
        con.close()


def _columnas(con, tabla):
    return {
        fila[1]
        for fila in con.execute(
            f"PRAGMA table_info({tabla})"
        )
    }


def inicializar_db():
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    con = sqlite3.connect(
        str(DB_PATH),
        timeout=15
    )

    try:
        con.execute("PRAGMA foreign_keys = ON")

        con.executescript("""
            CREATE TABLE IF NOT EXISTS viajes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                origen TEXT NOT NULL,
                destino TEXT NOT NULL,
                salida TEXT NOT NULL,
                precio REAL NOT NULL,
                capacidad INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS boletos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                viaje_id INTEGER NOT NULL
                    REFERENCES viajes(id),
                asiento INTEGER NOT NULL,
                pasajero TEXT NOT NULL,
                telefono TEXT NOT NULL,
                estado TEXT NOT NULL
                    CHECK(estado IN ('VENDIDO','APARTADO')),
                creado_en TEXT NOT NULL DEFAULT
                    (datetime('now','localtime')),
                UNIQUE(viaje_id, asiento)
            );
        """)

        if "codigo_ruta" not in _columnas(con, "viajes"):
            con.execute("""
                ALTER TABLE viajes
                ADD COLUMN codigo_ruta TEXT
            """)

        columnas_nuevas = (
            ("destino_boleto", "TEXT"),
            ("precio_boleto", "REAL"),
            ("cobrado_en", "TEXT"),
            ("creado_por", "INTEGER")
        )

        for columna, tipo in columnas_nuevas:
            if columna not in _columnas(con, "boletos"):
                con.execute(
                    f"ALTER TABLE boletos "
                    f"ADD COLUMN {columna} {tipo}"
                )

        con.execute("""
            UPDATE boletos
            SET cobrado_en = creado_en
            WHERE estado = 'VENDIDO'
              AND cobrado_en IS NULL
        """)

        con.executescript("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT NOT NULL
                    COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                rol TEXT NOT NULL
                    CHECK(rol IN ('ADMIN','EMPLEADO')),
                activo INTEGER NOT NULL DEFAULT 1,
                creado_en TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cancelaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boleto_id INTEGER NOT NULL,
                viaje_id INTEGER NOT NULL
                    REFERENCES viajes(id),
                asiento INTEGER NOT NULL,
                pasajero TEXT NOT NULL,
                telefono TEXT NOT NULL,
                estado_anterior TEXT NOT NULL,
                destino_boleto TEXT,
                precio_boleto REAL,
                creado_en TEXT,
                cobrado_en TEXT,
                cancelado_en TEXT NOT NULL,
                cancelado_por INTEGER
                    REFERENCES usuarios(id),
                motivo TEXT NOT NULL,
                reembolso REAL NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_boletos_viaje
            ON boletos(viaje_id);

            CREATE INDEX IF NOT EXISTS idx_viajes_ruta
            ON viajes(codigo_ruta, salida);

            CREATE INDEX IF NOT EXISTS idx_boletos_cobrado
            ON boletos(estado,cobrado_en);

            CREATE INDEX IF NOT EXISTS idx_cancelaciones_fecha
            ON cancelaciones(cancelado_en);
        """)

        nombre = os.environ.get(
            "ADMIN_USERNAME", ""
        ).strip()

        clave = os.environ.get(
            "ADMIN_PASSWORD", ""
        )

        administradores = con.execute("""
            SELECT COUNT(*)
            FROM usuarios
            WHERE rol = 'ADMIN'
        """).fetchone()[0]

        if (
            administradores == 0
            and nombre
            and len(clave) >= 12
        ):
            con.execute("""
                INSERT INTO usuarios (
                    usuario,
                    password_hash,
                    rol
                )
                VALUES (?, ?, 'ADMIN')
            """, (
                nombre,
                generate_password_hash(clave)
            ))

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()
