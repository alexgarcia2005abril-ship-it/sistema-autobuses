import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(__file__).resolve().parent / 'central_autobuses.db'


def obtener_db():
    if 'db' not in g:
        conexion = sqlite3.connect(DB_PATH, timeout=15)
        conexion.row_factory = sqlite3.Row
        conexion.execute('PRAGMA foreign_keys = ON')
        conexion.execute('PRAGMA busy_timeout = 15000')
        g.db = conexion
    return g.db


def cerrar_db(error=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()


def inicializar_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript('''
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS viajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origen TEXT NOT NULL,
            destino TEXT NOT NULL,
            salida TEXT NOT NULL,
            precio REAL NOT NULL CHECK(precio >= 0),
            capacidad INTEGER NOT NULL CHECK(capacidad > 0)
        );
        CREATE TABLE IF NOT EXISTS boletos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            viaje_id INTEGER NOT NULL REFERENCES viajes(id),
            asiento INTEGER NOT NULL CHECK(asiento > 0),
            pasajero TEXT NOT NULL,
            telefono TEXT NOT NULL,
            estado TEXT NOT NULL CHECK(estado IN ('VENDIDO', 'APARTADO')),
            creado_en TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(viaje_id, asiento)
        );
        CREATE INDEX IF NOT EXISTS idx_boletos_viaje ON boletos(viaje_id);
    ''')
    total = con.execute('SELECT COUNT(*) FROM viajes').fetchone()[0]
    if not total:
        from datetime import datetime, timedelta
        fecha = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
        if fecha <= datetime.now():
            fecha += timedelta(days=1)
        ejemplos = [
            ('Teposcolula', 'Oaxaca de Juárez', fecha, 180, 40),
            ('Teposcolula', 'Nochixtlán', fecha.replace(hour=10, minute=30), 75, 36),
            ('Nochixtlán', 'Huajuapan de León', fecha.replace(hour=14, minute=0), 140, 40),
            ('Oaxaca de Juárez', 'Teposcolula', fecha.replace(hour=17, minute=30), 180, 40),
        ]
        con.executemany('INSERT INTO viajes (origen,destino,salida,precio,capacidad) VALUES (?,?,?,?,?)', [
            (o, d, f.strftime('%Y-%m-%dT%H:%M'), p, c) for o, d, f, p, c in ejemplos
        ])
    con.commit()
    con.close()
