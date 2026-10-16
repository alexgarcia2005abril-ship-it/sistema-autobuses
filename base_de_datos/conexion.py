
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from flask import g
from base_de_datos.rutas import RUTAS

DB_PATH = Path(__file__).resolve().parent / "central_autobuses.db"


def obtener_db():
    if "db" not in g:
        conexion = sqlite3.connect(DB_PATH, timeout=15)
        conexion.row_factory = sqlite3.Row
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.execute("PRAGMA busy_timeout = 15000")
        g.db = conexion

    return g.db


def cerrar_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def inicializar_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH, timeout=15)

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
                viaje_id INTEGER NOT NULL REFERENCES viajes(id),
                asiento INTEGER NOT NULL,
                pasajero TEXT NOT NULL,
                telefono TEXT NOT NULL,
                estado TEXT NOT NULL
                    CHECK(estado IN ('VENDIDO', 'APARTADO')),
                creado_en TEXT NOT NULL DEFAULT
                    (datetime('now','localtime')),
                UNIQUE(viaje_id, asiento)
            );
        """)

        columnas_viajes = {
            fila[1]
            for fila in con.execute("PRAGMA table_info(viajes)")
        }

        if "codigo_ruta" not in columnas_viajes:
            con.execute(
                "ALTER TABLE viajes ADD COLUMN codigo_ruta TEXT"
            )

        columnas_boletos = {
            fila[1]
            for fila in con.execute("PRAGMA table_info(boletos)")
        }

        if "destino_boleto" not in columnas_boletos:
            con.execute(
                "ALTER TABLE boletos ADD COLUMN destino_boleto TEXT"
            )

        if "precio_boleto" not in columnas_boletos:
            con.execute(
                "ALTER TABLE boletos ADD COLUMN precio_boleto REAL"
            )

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_boletos_viaje
            ON boletos(viaje_id)
        """)

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_viajes_ruta
            ON viajes(codigo_ruta, salida)
        """)

        manana = datetime.now().date() + timedelta(days=1)

        for codigo, ruta in RUTAS.items():
            fecha_salida = (
                f"{manana.isoformat()}T{ruta['hora_demo']}"
            )

            existe = con.execute("""
                SELECT id FROM viajes
                WHERE codigo_ruta = ?
                AND salida = ?
            """, (codigo, fecha_salida)).fetchone()

            if existe is None:
                precio_final = ruta["destinos"][
                    ruta["destino_final"]
                ]

                con.execute("""
                    INSERT INTO viajes (
                        origen, destino, salida,
                        precio, capacidad, codigo_ruta
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    "Teposcolula",
                    ruta["destino_final"],
                    fecha_salida,
                    precio_final,
                    40,
                    codigo
                ))

        con.commit()

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()
