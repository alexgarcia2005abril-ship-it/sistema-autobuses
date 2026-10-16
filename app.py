
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import click

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for
)

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

from base_de_datos.conexion import (
    cerrar_db,
    inicializar_db,
    obtener_db
)

from base_de_datos.rutas import RUTAS
from validaciones.boletos import validar_operacion


app = Flask(__name__)

clave_secreta = os.environ.get("SECRET_KEY")

if not clave_secreta and os.environ.get("RENDER"):
    raise RuntimeError(
        "Configura SECRET_KEY en las variables de Render."
    )

app.config.update(
    SECRET_KEY=clave_secreta or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=1024 * 1024
)

app.teardown_appcontext(cerrar_db)

inicializar_db()


def ahora():
    return datetime.now(
        ZoneInfo("America/Mexico_City")
    )


def sello():
    return ahora().strftime("%Y-%m-%d %H:%M:%S")


def es_admin():
    return (
        g.usuario is not None
        and g.usuario["rol"] == "ADMIN"
    )


@app.before_request
def verificar_sesion_y_csrf():

    g.usuario = None

    usuario_id = session.get("usuario_id")

    if usuario_id:
        g.usuario = obtener_db().execute("""
            SELECT id, usuario, rol, activo
            FROM usuarios
            WHERE id = ?
              AND activo = 1
        """, (usuario_id,)).fetchone()

        if g.usuario is None:
            session.clear()

    if request.method == "POST":
        enviado = (
            request.form.get("_csrf", "")
            or request.headers.get("X-CSRF-Token", "")
        )

        esperado = session.get("_csrf", "")

        if not esperado or not secrets.compare_digest(
            enviado, esperado
        ):
            abort(
                400,
                "Formulario caducado o token de seguridad "
                "inválido. Recarga la página."
            )


def token_csrf():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)

    return session["_csrf"]


@app.context_processor
def contexto_global():
    return {
        "usuario_actual": g.usuario,
        "csrf_token": token_csrf
    }


def acceso(*roles):

    def decorador(funcion):

        @wraps(funcion)
        def envoltura(*args, **kwargs):

            if g.usuario is None:
                return redirect(url_for("login"))

            if g.usuario["rol"] not in roles:
                abort(
                    403,
                    "No tienes permiso para acceder "
                    "a esta sección."
                )

            return funcion(*args, **kwargs)

        return envoltura

    return decorador


@app.template_filter("fecha")
def formato_fecha(valor):
    if not valor:
        return ""

    try:
        return datetime.strptime(
            valor,
            "%Y-%m-%dT%H:%M"
        ).strftime("%d/%m/%Y - %H:%M")

    except ValueError:
        return valor


@app.route("/login", methods=["GET", "POST"])
def login():

    if g.usuario:
        return redirect(url_for("index"))

    if request.method == "POST":

        intentos = session.get("intentos_login", 0)

        if intentos >= 10:
            abort(
                429,
                "Demasiados intentos de inicio de sesión."
            )

        usuario = (
            request.form.get("usuario") or ""
        ).strip()

        clave = request.form.get("contrasena") or ""

        fila = obtener_db().execute("""
            SELECT *
            FROM usuarios
            WHERE usuario = ? COLLATE NOCASE
              AND activo = 1
        """, (usuario,)).fetchone()

        if fila and check_password_hash(
            fila["password_hash"],
            clave
        ):
            session.clear()

            session["usuario_id"] = fila["id"]
            session.permanent = True

            return redirect(url_for("index"))

        session["intentos_login"] = intentos + 1

        flash(
            "Usuario o contraseña incorrectos.",
            "error"
        )

    configurado = obtener_db().execute("""
        SELECT COUNT(*) AS n
        FROM usuarios
        WHERE rol = 'ADMIN'
    """).fetchone()["n"] > 0

    return render_template(
        "login.html",
        configurado=configurado
    )


@app.post("/salir")
@acceso("ADMIN", "EMPLEADO")
def salir():
    session.clear()

    return redirect(url_for("login"))


@app.cli.command("crear-admin")
@click.option(
    "--usuario",
    prompt="Usuario administrador"
)
@click.password_option(
    confirmation_prompt=True
)
def crear_admin(usuario, password):

    if not re.fullmatch(
        r"[A-Za-z0-9_.-]{3,32}",
        usuario
    ):
        raise click.ClickException(
            "Usuario inválido. Utiliza entre "
            "3 y 32 caracteres."
        )

    if len(password) < 12:
        raise click.ClickException(
            "La contraseña debe tener mínimo "
            "12 caracteres."
        )

    con = obtener_db()

    try:
        con.execute("""
            INSERT INTO usuarios (
                usuario,
                password_hash,
                rol
            )
            VALUES (?, ?, 'ADMIN')
        """, (
            usuario,
            generate_password_hash(password)
        ))

        con.commit()

    except sqlite3.IntegrityError as exc:
        con.rollback()

        raise click.ClickException(
            "El usuario ya existe."
        ) from exc

    click.echo("Administrador creado correctamente.")


def viajes_con_conteo():

    db = obtener_db()

    return db.execute("""
        SELECT
            v.*,

            COUNT(b.id) AS ocupados,

            COALESCE(SUM(
                CASE WHEN b.estado = 'VENDIDO'
                THEN 1 ELSE 0 END
            ), 0) AS vendidos,

            COALESCE(SUM(
                CASE WHEN b.estado = 'APARTADO'
                THEN 1 ELSE 0 END
            ), 0) AS apartados

        FROM viajes v

        LEFT JOIN boletos b
            ON b.viaje_id = v.id

        WHERE v.codigo_ruta IS NOT NULL
          AND v.salida > ?

        GROUP BY v.id
        ORDER BY v.salida, v.id
    """, (
        ahora().strftime("%Y-%m-%dT%H:%M"),
    )).fetchall()


def detalle_viaje(viaje_id):

    db = obtener_db()

    viaje = db.execute("""
        SELECT *
        FROM viajes
        WHERE id = ?
          AND codigo_ruta IS NOT NULL
    """, (viaje_id,)).fetchone()

    if (
        not viaje
        or viaje["codigo_ruta"] not in RUTAS
    ):
        abort(
            404,
            "Salida no disponible."
        )

    boletos = db.execute("""
        SELECT *
        FROM boletos
        WHERE viaje_id = ?
        ORDER BY asiento
    """, (viaje_id,)).fetchall()

    estados = {
        b["asiento"]: b["estado"]
        for b in boletos
    }

    return viaje, boletos, estados


def salida_seleccionada():

    ruta = request.args.get("ruta", "").strip()
    fecha = request.args.get("fecha", "").strip()
    hora = request.args.get("hora", "").strip()

    if not any((ruta, fecha, hora)):
        return None, ruta, fecha, hora, None

    if ruta not in RUTAS:
        return (
            None, ruta, fecha, hora,
            "Selecciona una ruta válida."
        )

    try:
        datetime.strptime(
            f"{fecha}T{hora}",
            "%Y-%m-%dT%H:%M"
        )

    except ValueError:
        return (
            None, ruta, fecha, hora,
            "Selecciona una fecha y hora válidas."
        )

    viaje = obtener_db().execute("""
        SELECT *
        FROM viajes
        WHERE codigo_ruta = ?
          AND salida = ?
        ORDER BY id
        LIMIT 1
    """, (
        ruta,
        f"{fecha}T{hora}"
    )).fetchone()

    if viaje is None:
        return (
            None, ruta, fecha, hora,
            "Esa salida no está programada. "
            "Pide al administrador que la registre."
        )

    return viaje, ruta, fecha, hora, None


@app.route("/")
@acceso("ADMIN", "EMPLEADO")
def index():

    db = obtener_db()

    resumen = db.execute("""
        SELECT
            COUNT(*) AS total,

            COALESCE(SUM(
                estado = 'VENDIDO'
            ), 0) AS vendidos,

            COALESCE(SUM(
                estado = 'APARTADO'
            ), 0) AS apartados

        FROM boletos
    """).fetchone()

    return render_template(
        "index.html",
        resumen=resumen,
        viajes=viajes_con_conteo(),
        activo="inicio"
    )


@app.route("/salidas", methods=["GET", "POST"])
@acceso("ADMIN")
def salidas():

    if request.method == "POST":

        ruta = request.form.get("ruta", "")
        fecha = request.form.get("fecha", "")
        hora = request.form.get("hora", "")

        if ruta not in RUTAS:
            flash(
                "Selecciona una ruta válida.",
                "error"
            )

        else:
            try:
                salida = datetime.strptime(
                    f"{fecha}T{hora}",
                    "%Y-%m-%dT%H:%M"
                )

                if salida <= ahora().replace(
                    tzinfo=None
                ):
                    raise ValueError(
                        "Fecha anterior"
                    )

            except ValueError:
                flash(
                    "La fecha y hora deben ser "
                    "futuras y válidas.",
                    "error"
                )

            else:
                db = obtener_db()

                try:
                    db.execute("BEGIN IMMEDIATE")

                    fecha_salida = salida.strftime(
                        "%Y-%m-%dT%H:%M"
                    )

                    existe = db.execute("""
                        SELECT id
                        FROM viajes
                        WHERE codigo_ruta = ?
                          AND salida = ?
                    """, (
                        ruta,
                        fecha_salida
                    )).fetchone()

                    if existe:
                        flash(
                            "Esta salida ya está registrada.",
                            "error"
                        )

                    else:
                        info = RUTAS[ruta]

                        db.execute("""
                            INSERT INTO viajes (
                                origen,
                                destino,
                                salida,
                                precio,
                                capacidad,
                                codigo_ruta
                            )
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            "Teposcolula",
                            info["destino_final"],
                            fecha_salida,
                            info["destinos"][
                                info["destino_final"]
                            ],
                            40,
                            ruta
                        ))

                        flash(
                            "Salida programada correctamente.",
                            "success"
                        )

                    db.commit()

                except sqlite3.Error:
                    db.rollback()
                    raise

        return redirect(url_for("salidas"))

    return render_template(
        "salidas.html",
        viajes=viajes_con_conteo(),
        rutas=RUTAS,
        hoy=ahora().date().isoformat(),
        activo="salidas"
    )


@app.post("/salidas/<int:viaje_id>/eliminar")
@acceso("ADMIN")
def eliminar_salida(viaje_id):

    db = obtener_db()

    try:
        db.execute("BEGIN IMMEDIATE")

        uso = db.execute("""
            SELECT COUNT(*)
            FROM boletos
            WHERE viaje_id = ?
        """, (viaje_id,)).fetchone()[0]

        cancelaciones = db.execute("""
            SELECT COUNT(*)
            FROM cancelaciones
            WHERE viaje_id = ?
        """, (viaje_id,)).fetchone()[0]

        if uso or cancelaciones:
            flash(
                "No se puede eliminar una salida "
                "que tuvo movimientos.",
                "error"
            )

        else:
            resultado = db.execute("""
                DELETE FROM viajes
                WHERE id = ?
            """, (viaje_id,))

            flash(
                "Salida eliminada."
                if resultado.rowcount
                else "Salida inexistente.",
                "success"
                if resultado.rowcount
                else "error"
            )

        db.commit()

    except sqlite3.Error:
        db.rollback()
        raise

    return redirect(url_for("salidas"))


@app.route("/venta", methods=["GET", "POST"])
@acceso("ADMIN", "EMPLEADO")
def venta():

    return operacion(
        "VENDIDO",
        "venta.html",
        "venta"
    )


@app.route("/apartados", methods=["GET", "POST"])
@acceso("ADMIN")
def apartados():

    return operacion(
        "APARTADO",
        "apartados.html",
        "apartados"
    )


def operacion(estado, plantilla, activo):

    if request.method == "POST":

        valor = request.form.get("viaje_id", "")

        if not valor.isdigit():
            abort(
                400,
                "Selecciona una salida programada."
            )

        viaje, boletos, estados = detalle_viaje(
            int(valor)
        )

        error, datos = validar_operacion(
            request.form,
            viaje,
            set(estados)
        )

        if error:
            flash(error, "error")

            return redirect(url_for(
                activo,
                ruta=viaje["codigo_ruta"],
                fecha=viaje["salida"][:10],
                hora=viaje["salida"][11:16]
            ))

        db = obtener_db()

        try:
            db.execute("BEGIN IMMEDIATE")

            ocupado = db.execute("""
                SELECT id
                FROM boletos
                WHERE viaje_id = ?
                  AND asiento = ?
            """, (
                viaje["id"],
                datos["asiento"]
            )).fetchone()

            if ocupado:
                raise sqlite3.IntegrityError(
                    "Asiento ocupado."
                )

            momento = sello()

            db.execute("""
                INSERT INTO boletos (
                    viaje_id,
                    asiento,
                    pasajero,
                    telefono,
                    estado,
                    destino_boleto,
                    precio_boleto,
                    creado_en,
                    cobrado_en,
                    creado_por
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                viaje["id"],
                datos["asiento"],
                datos["pasajero"],
                datos["telefono"],
                estado,
                datos["destino"],
                datos["precio"],
                momento,
                momento if estado == "VENDIDO" else None,
                g.usuario["id"]
            ))

            db.commit()

            flash(
                "Boleto vendido."
                if estado == "VENDIDO"
                else "Asiento apartado.",
                "success"
            )

        except sqlite3.IntegrityError:
            db.rollback()

            flash(
                "Ese asiento ya está ocupado "
                "o apartado.",
                "error"
            )

        except sqlite3.Error:
            db.rollback()
            raise

        return redirect(url_for(
            activo,
            ruta=viaje["codigo_ruta"],
            fecha=viaje["salida"][:10],
            hora=viaje["salida"][11:16]
        ))

    viaje, ruta, fecha, hora, error = (
        salida_seleccionada()
    )

    if viaje:
        viaje, boletos, estados = detalle_viaje(
            viaje["id"]
        )

    else:
        boletos, estados = [], {}

    return render_template(
        plantilla,
        rutas=RUTAS,
        viaje=viaje,
        ruta_elegida=ruta,
        fecha_elegida=fecha,
        hora_elegida=hora,
        consulta_error=error,
        viajes=viajes_con_conteo(),
        estados=estados,
        ocupados=len(boletos),
        destinos=(
            RUTAS[viaje["codigo_ruta"]]["destinos"]
            if viaje
            else {}
        ),
        activo=activo
    )


@app.route("/boletos")
@acceso("ADMIN", "EMPLEADO")
def boletos():

    registros = obtener_db().execute("""
        SELECT
            b.*,
            v.origen,
            v.destino AS destino_final,
            v.salida,
            v.codigo_ruta

        FROM boletos b

        JOIN viajes v
            ON v.id = b.viaje_id

        WHERE b.estado = 'VENDIDO'

        ORDER BY b.id DESC
    """).fetchall()

    return render_template(
        "boletos.html",
        registros=registros,
        rutas=RUTAS,
        activo="boletos"
    )


@app.post("/boletos/<int:boleto_id>/cancelar")
@acceso("ADMIN", "EMPLEADO")
def cancelar_boleto(boleto_id):

    motivo = (
        request.form.get("motivo") or ""
    ).strip()

    tipo = request.form.get(
        "reembolso",
        "no"
    )

    if (
        not 5 <= len(motivo) <= 300
        or tipo not in ("no", "completo")
    ):
        flash(
            "Escribe un motivo de 5 a 300 caracteres "
            "y selecciona el reembolso.",
            "error"
        )

        return redirect(url_for("boletos"))

    db = obtener_db()

    try:
        db.execute("BEGIN IMMEDIATE")

        b = db.execute("""
            SELECT *
            FROM boletos
            WHERE id = ?
              AND estado = 'VENDIDO'
        """, (boleto_id,)).fetchone()

        if b is None:
            db.rollback()

            flash(
                "El boleto ya no está disponible "
                "para cancelar.",
                "error"
            )

            return redirect(url_for("boletos"))

        reembolso = (
            float(b["precio_boleto"] or 0)
            if tipo == "completo"
            else 0
        )

        db.execute("""
            INSERT INTO cancelaciones (
                boleto_id,
                viaje_id,
                asiento,
                pasajero,
                telefono,
                estado_anterior,
                destino_boleto,
                precio_boleto,
                creado_en,
                cobrado_en,
                cancelado_en,
                cancelado_por,
                motivo,
                reembolso
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            b["id"],
            b["viaje_id"],
            b["asiento"],
            b["pasajero"],
            b["telefono"],
            b["estado"],
            b["destino_boleto"],
            b["precio_boleto"],
            b["creado_en"],
            b["cobrado_en"],
            sello(),
            g.usuario["id"],
            motivo,
            reembolso
        ))

        db.execute("""
            DELETE FROM boletos
            WHERE id = ?
              AND estado = 'VENDIDO'
        """, (boleto_id,))

        db.commit()

        flash(
            "Boleto cancelado y asiento liberado. "
            "Movimiento registrado.",
            "success"
        )

    except sqlite3.Error:
        db.rollback()
        raise

    return redirect(url_for("boletos"))


@app.route("/disponibilidad")
@acceso("ADMIN", "EMPLEADO")
def disponibilidad():

    viaje, ruta, fecha, hora, error = (
        salida_seleccionada()
    )

    if viaje:
        viaje, boletos, estados = detalle_viaje(
            viaje["id"]
        )

    else:
        boletos, estados = [], {}

    return render_template(
        "disponibilidad.html",
        rutas=RUTAS,
        viaje=viaje,
        boletos=boletos,
        estados=estados,
        ruta_elegida=ruta,
        fecha_elegida=fecha,
        hora_elegida=hora,
        consulta_error=error,
        activo="disponibilidad"
    )


@app.post("/apartados/<int:boleto_id>/confirmar")
@acceso("ADMIN")
def confirmar_apartado(boleto_id):

    db = obtener_db()

    fila = db.execute("""
        SELECT viaje_id
        FROM boletos
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (boleto_id,)).fetchone()

    if fila is None:
        flash(
            "Apartado no disponible.",
            "error"
        )

        return redirect(url_for("disponibilidad"))

    db.execute("""
        UPDATE boletos
        SET estado = 'VENDIDO',
            cobrado_en = ?
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (
        sello(),
        boleto_id
    ))

    db.commit()

    return _redirigir_viaje(
        fila["viaje_id"],
        "Apartado confirmado y cobrado."
    )


@app.post("/apartados/<int:boleto_id>/liberar")
@acceso("ADMIN")
def liberar_apartado(boleto_id):

    db = obtener_db()

    fila = db.execute("""
        SELECT viaje_id
        FROM boletos
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (boleto_id,)).fetchone()

    if fila is None:
        flash(
            "Apartado no disponible.",
            "error"
        )

        return redirect(url_for("disponibilidad"))

    db.execute("""
        DELETE FROM boletos
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (boleto_id,))

    db.commit()

    return _redirigir_viaje(
        fila["viaje_id"],
        "Apartado liberado."
    )


def _redirigir_viaje(viaje_id, mensaje):

    viaje = obtener_db().execute("""
        SELECT codigo_ruta, salida
        FROM viajes
        WHERE id = ?
    """, (viaje_id,)).fetchone()

    flash(mensaje, "success")

    if viaje:
        return redirect(url_for(
            "disponibilidad",
            ruta=viaje["codigo_ruta"],
            fecha=viaje["salida"][:10],
            hora=viaje["salida"][11:16]
        ))

    return redirect(url_for("disponibilidad"))


@app.route("/usuarios", methods=["GET", "POST"])
@acceso("ADMIN")
def usuarios():

    db = obtener_db()

    if request.method == "POST":

        nombre = (
            request.form.get("usuario") or ""
        ).strip()

        clave = request.form.get("contrasena") or ""

        rol = request.form.get(
            "rol",
            "EMPLEADO"
        )

        if (
            not re.fullmatch(
                r"[A-Za-z0-9_.-]{3,32}",
                nombre
            )
            or len(clave) < 12
            or rol not in ("ADMIN", "EMPLEADO")
        ):
            flash(
                "Usuario inválido o contraseña "
                "menor de 12 caracteres.",
                "error"
            )

        else:
            try:
                db.execute("""
                    INSERT INTO usuarios (
                        usuario,
                        password_hash,
                        rol
                    )
                    VALUES (?, ?, ?)
                """, (
                    nombre,
                    generate_password_hash(clave),
                    rol
                ))

                db.commit()

                flash(
                    "Usuario registrado correctamente.",
                    "success"
                )

            except sqlite3.IntegrityError:
                db.rollback()

                flash(
                    "Ese nombre de usuario ya existe.",
                    "error"
                )

        return redirect(url_for("usuarios"))

    todos = db.execute("""
        SELECT id, usuario, rol, activo
        FROM usuarios
        ORDER BY id
    """).fetchall()

    return render_template(
        "usuarios.html",
        usuarios=todos,
        activo="usuarios"
    )


@app.post("/usuarios/<int:usuario_id>/estado")
@acceso("ADMIN")
def cambiar_estado_usuario(usuario_id):

    db = obtener_db()

    usuario = db.execute("""
        SELECT *
        FROM usuarios
        WHERE id = ?
    """, (usuario_id,)).fetchone()

    if (
        usuario is None
        or usuario["rol"] != "EMPLEADO"
    ):
        abort(
            400,
            "Solo puedes cambiar el estado de empleados."
        )

    nuevo_estado = (
        0 if usuario["activo"] else 1
    )

    db.execute("""
        UPDATE usuarios
        SET activo = ?
        WHERE id = ?
    """, (
        nuevo_estado,
        usuario_id
    ))

    db.commit()

    flash(
        "Estado del empleado actualizado.",
        "success"
    )

    return redirect(url_for("usuarios"))


def filtros_caja():

    hoy = ahora().date().isoformat()

    desde = (
        request.args.get("desde") or hoy
    )

    hasta = (
        request.args.get("hasta") or hoy
    )

    try:
        inicio = date.fromisoformat(desde)
        fin = date.fromisoformat(hasta)

        if inicio > fin:
            raise ValueError("Periodo inválido")

    except ValueError:
        abort(
            400,
            "El periodo de fechas no es válido."
        )

    return desde, hasta


def _rango(desde, hasta):

    inicio = desde + " 00:00:00"

    fin = (
        date.fromisoformat(hasta)
        + timedelta(days=1)
    ).isoformat() + " 00:00:00"

    return inicio, fin


def calcular_corte(desde, hasta):

    db = obtener_db()

    inicio, fin = _rango(desde, hasta)

    ventas = db.execute("""
        SELECT
            b.id,
            b.asiento,
            b.cobrado_en AS fecha_cobro,
            b.precio_boleto,
            b.destino_boleto,
            v.codigo_ruta,
            0 AS cancelado

        FROM boletos b

        JOIN viajes v
            ON v.id = b.viaje_id

        WHERE b.estado = 'VENDIDO'
          AND b.cobrado_en >= ?
          AND b.cobrado_en < ?

        UNION ALL

        SELECT
            c.boleto_id,
            c.asiento,
            c.cobrado_en,
            c.precio_boleto,
            c.destino_boleto,
            v.codigo_ruta,
            1 AS cancelado

        FROM cancelaciones c

        JOIN viajes v
            ON v.id = c.viaje_id

        WHERE c.estado_anterior = 'VENDIDO'
          AND c.cobrado_en >= ?
          AND c.cobrado_en < ?

        ORDER BY fecha_cobro DESC, 1 DESC
    """, (
        inicio,
        fin,
        inicio,
        fin
    )).fetchall()

    cancelaciones = db.execute("""
        SELECT
            c.id,
            c.boleto_id,
            c.cancelado_en,
            c.reembolso,
            c.motivo,
            c.asiento,
            v.codigo_ruta

        FROM cancelaciones c

        JOIN viajes v
            ON v.id = c.viaje_id

        WHERE c.cancelado_en >= ?
          AND c.cancelado_en < ?

        ORDER BY c.cancelado_en DESC
    """, (
        inicio,
        fin
    )).fetchall()

    bruto = 0.0
    faltantes = 0
    por_ruta = {}

    for b in ventas:

        codigo = (
            b["codigo_ruta"] or "SIN_RUTA"
        )

        if codigo not in por_ruta:
            nombre = RUTAS.get(
                codigo, {}
            ).get("nombre", codigo)

            por_ruta[codigo] = {
                "nombre": nombre,
                "cantidad": 0,
                "total": 0.0,
                "reembolsos": 0.0
            }

        por_ruta[codigo]["cantidad"] += 1

        if b["precio_boleto"] is None:
            faltantes += 1

        else:
            valor = float(
                b["precio_boleto"]
            )

            bruto += valor
            por_ruta[codigo]["total"] += valor

    reembolsos = 0.0

    for c in cancelaciones:

        valor = float(
            c["reembolso"] or 0
        )

        reembolsos += valor

        codigo = (
            c["codigo_ruta"] or "SIN_RUTA"
        )

        if codigo not in por_ruta:
            nombre = RUTAS.get(
                codigo, {}
            ).get("nombre", codigo)

            por_ruta[codigo] = {
                "nombre": nombre,
                "cantidad": 0,
                "total": 0.0,
                "reembolsos": 0.0
            }

        por_ruta[codigo]["reembolsos"] += valor

    return {
        "registros": ventas,
        "cantidad": len(ventas),
        "sin_precio": faltantes,
        "total": round(bruto, 2),
        "reembolsos": round(reembolsos, 2),
        "neto": round(
            bruto - reembolsos, 2
        ),
        "cancelaciones": cancelaciones,
        "cantidad_cancelaciones": len(cancelaciones),
        "por_ruta": list(por_ruta.values())
    }


@app.route("/corte-caja")
@acceso("ADMIN")
def corte_caja():

    hoy = ahora().date().isoformat()

    desde, hasta = filtros_caja()

    return render_template(
        "corte_caja.html",
        activo="corte",
        desde=desde,
        hasta=hasta,
        corte_hoy=calcular_corte(hoy, hoy),
        corte_periodo=calcular_corte(
            desde, hasta
        )
    )


@app.route("/corte-caja/pdf")
@acceso("ADMIN")
def corte_caja_pdf():

    desde, hasta = filtros_caja()

    corte = calcular_corte(
        desde, hasta
    )

    archivo = BytesIO()

    documento = SimpleDocTemplate(
        archivo,
        pagesize=A4,
        leftMargin=30,
        rightMargin=30
    )

    estilos = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph(
        "AUTOBUSES ALEXITO",
        estilos["Title"]
    ))

    elementos.append(Paragraph(
        "Corte de caja",
        estilos["Heading2"]
    ))

    elementos.append(Paragraph(
        f"Periodo: {desde} al {hasta}",
        estilos["Normal"]
    ))

    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        f"Boletos cobrados: {corte['cantidad']}",
        estilos["Normal"]
    ))

    elementos.append(Paragraph(
        f"Ventas: ${corte['total']:,.2f}",
        estilos["Normal"]
    ))

    elementos.append(Paragraph(
        f"Reembolsos: ${corte['reembolsos']:,.2f}",
        estilos["Normal"]
    ))

    elementos.append(Paragraph(
        f"Neto: ${corte['neto']:,.2f} MXN",
        estilos["Heading2"]
    ))

    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        "Detalle por ruta",
        estilos["Heading3"]
    ))

    datos_rutas = [[
        "Ruta",
        "Boletos",
        "Ventas",
        "Reembolsos"
    ]]

    for ruta in corte["por_ruta"]:
        datos_rutas.append([
            Paragraph(
                escape(ruta["nombre"]),
                estilos["BodyText"]
            ),
            str(ruta["cantidad"]),
            f"${ruta['total']:,.2f}",
            f"${ruta['reembolsos']:,.2f}"
        ])

    if len(datos_rutas) == 1:
        datos_rutas.append([
            "Sin movimientos",
            "0",
            "$0.00",
            "$0.00"
        ])

    tabla_rutas = Table(
        datos_rutas,
        colWidths=[210, 70, 110, 110],
        repeatRows=1
    )

    tabla_rutas.setStyle(TableStyle([
        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#19365c")
        ),
        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            colors.white
        ),
        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.4,
            colors.lightgrey
        ),
        (
            "VALIGN",
            (0, 0),
            (-1, -1),
            "MIDDLE"
        ),
        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            7
        )
    ]))

    elementos.append(tabla_rutas)
    elementos.append(Spacer(1, 14))

    elementos.append(Paragraph(
        "Boletos cobrados",
        estilos["Heading3"]
    ))

    detalle = [[
        "Folio",
        "Fecha de cobro",
        "Asiento",
        "Importe"
    ]]

    for b in corte["registros"]:
        importe = (
            f"${float(b['precio_boleto']):,.2f}"
            if b["precio_boleto"] is not None
            else "Sin precio"
        )

        detalle.append([
            str(b["id"]),
            str(b["fecha_cobro"] or "")[:16],
            str(b["asiento"]),
            importe
        ])

    if len(detalle) == 1:
        detalle.append([
            "-",
            "Sin ventas",
            "-",
            "-"
        ])

    tabla_detalle = Table(
        detalle,
        colWidths=[80, 180, 100, 140],
        repeatRows=1
    )

    tabla_detalle.setStyle(TableStyle([
        (
            "BACKGROUND",
            (0, 0),
            (-1, 0),
            colors.HexColor("#19365c")
        ),
        (
            "TEXTCOLOR",
            (0, 0),
            (-1, 0),
            colors.white
        ),
        (
            "GRID",
            (0, 0),
            (-1, -1),
            0.4,
            colors.lightgrey
        ),
        (
            "BOTTOMPADDING",
            (0, 0),
            (-1, -1),
            7
        )
    ]))

    elementos.append(tabla_detalle)
    elementos.append(Spacer(1, 12))

    elementos.append(Paragraph(
        "Cancelaciones registradas: "
        f"{corte['cantidad_cancelaciones']}",
        estilos["Normal"]
    ))

    if corte["sin_precio"]:
        elementos.append(Paragraph(
            f"Aviso: {corte['sin_precio']} "
            "boletos sin precio registrado.",
            estilos["Normal"]
        ))

    documento.build(elementos)

    archivo.seek(0)

    return send_file(
        archivo,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=(
            f"corte_caja_{desde}_{hasta}.pdf"
        )
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get("PORT", 5000)
        ),
        debug=False
    )
