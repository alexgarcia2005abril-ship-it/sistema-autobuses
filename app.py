
import os
import sqlite3

from datetime import date, datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    abort,
    send_file
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

from base_de_datos.conexion import (
    inicializar_db,
    obtener_db,
    cerrar_db
)

from base_de_datos.rutas import RUTAS
from validaciones.boletos import validar_operacion


app = Flask(__name__)

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "alexito-desarrollo-local-cambiar-clave"
)

app.teardown_appcontext(cerrar_db)

inicializar_db()


def ahora_caja():
    return datetime.now(
        ZoneInfo("America/Mexico_City")
    )


def fecha_caja():
    return ahora_caja().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


@app.template_filter("fecha")
def formato_fecha(valor):
    if not valor:
        return ""

    return datetime.strptime(
        valor, "%Y-%m-%dT%H:%M"
    ).strftime("%d/%m/%Y - %H:%M")


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
        ahora_caja().strftime("%Y-%m-%dT%H:%M"),
    )).fetchall()


def detalle_viaje(viaje_id):
    db = obtener_db()

    viaje = db.execute("""
        SELECT *
        FROM viajes
        WHERE id = ?
          AND codigo_ruta IS NOT NULL
    """, (viaje_id,)).fetchone()

    if viaje is None:
        abort(404)

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


def seleccionar_viaje(viajes):
    valor = (
        request.form.get("viaje_id")
        if request.method == "POST"
        else request.args.get("viaje_id")
    )

    if valor:
        try:
            viaje_id = int(valor)
        except ValueError:
            abort(400)

        if not any(
            v["id"] == viaje_id for v in viajes
        ):
            abort(400)

        return viaje_id

    return viajes[0]["id"] if viajes else None


@app.route("/")
def index():
    db = obtener_db()

    resumen = db.execute("""
        SELECT
            COUNT(*) AS total,

            COALESCE(SUM(
                CASE WHEN estado = 'VENDIDO'
                THEN 1 ELSE 0 END
            ), 0) AS vendidos,

            COALESCE(SUM(
                CASE WHEN estado = 'APARTADO'
                THEN 1 ELSE 0 END
            ), 0) AS apartados

        FROM boletos
    """).fetchone()

    return render_template(
        "index.html",
        viajes=viajes_con_conteo(),
        resumen=resumen,
        activo="inicio"
    )


@app.route("/venta", methods=["GET", "POST"])
def venta():
    return operacion(
        "VENDIDO",
        "venta.html",
        "venta"
    )


@app.route("/apartados", methods=["GET", "POST"])
def apartados():
    return operacion(
        "APARTADO",
        "apartados.html",
        "apartados"
    )


def operacion(estado, plantilla, activo):
    db = obtener_db()

    viajes = viajes_con_conteo()
    viaje_id = seleccionar_viaje(viajes)

    if viaje_id is not None:
        viaje, boletos, estados = detalle_viaje(
            viaje_id
        )
    else:
        viaje, boletos, estados = None, [], {}

    if request.method == "POST" and viaje:

        error, datos = validar_operacion(
            request.form,
            viaje,
            set(estados)
        )

        if error:
            flash(error, "error")

        else:
            try:
                db.execute("BEGIN IMMEDIATE")

                ocupacion = db.execute("""
                    SELECT id
                    FROM boletos
                    WHERE viaje_id = ?
                      AND asiento = ?
                """, (
                    viaje_id,
                    datos["asiento"]
                )).fetchone()

                if ocupacion:
                    raise sqlite3.IntegrityError(
                        "Asiento ocupado"
                    )

                registro = fecha_caja()

                cobrado = (
                    registro
                    if estado == "VENDIDO"
                    else None
                )

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
                        cobrado_en
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    viaje_id,
                    datos["asiento"],
                    datos["pasajero"],
                    datos["telefono"],
                    estado,
                    datos["destino"],
                    datos["precio"],
                    registro,
                    cobrado
                ))

                db.commit()

                if estado == "VENDIDO":
                    flash(
                        "Boleto vendido correctamente.",
                        "success"
                    )
                else:
                    flash(
                        "Asiento apartado correctamente.",
                        "success"
                    )

                return redirect(url_for(
                    activo,
                    viaje_id=viaje_id
                ))

            except sqlite3.IntegrityError:
                db.rollback()

                flash(
                    "El asiento ya está ocupado.",
                    "error"
                )

            except sqlite3.Error:
                db.rollback()

                flash(
                    "Error al guardar la operación.",
                    "error"
                )

        viaje, boletos, estados = detalle_viaje(
            viaje_id
        )

    destinos = {}

    if viaje:
        destinos = RUTAS[
            viaje["codigo_ruta"]
        ]["destinos"]

    return render_template(
        plantilla,
        viajes=viajes,
        viaje=viaje,
        estados=estados,
        ocupados=len(boletos),
        destinos=destinos,
        activo=activo,
        rutas=RUTAS
    )


@app.route("/boletos")
def boletos():
    db = obtener_db()

    registros = db.execute("""
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


@app.route("/disponibilidad")
def disponibilidad():
    viajes = viajes_con_conteo()
    viaje_id = seleccionar_viaje(viajes)

    if viaje_id:
        viaje, boletos, estados = detalle_viaje(
            viaje_id
        )
    else:
        viaje, boletos, estados = None, [], {}

    return render_template(
        "disponibilidad.html",
        viajes=viajes,
        viaje=viaje,
        boletos=boletos,
        estados=estados,
        rutas=RUTAS,
        activo="disponibilidad"
    )


@app.post("/apartados/<int:boleto_id>/confirmar")
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
            "El apartado no está disponible.",
            "error"
        )
        return redirect(
            url_for("disponibilidad")
        )

    resultado = db.execute("""
        UPDATE boletos
        SET estado = 'VENDIDO',
            cobrado_en = ?
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (
        fecha_caja(),
        boleto_id
    ))

    db.commit()

    flash(
        "Apartado confirmado."
        if resultado.rowcount
        else "No se pudo confirmar.",
        "success" if resultado.rowcount else "error"
    )

    return redirect(url_for(
        "disponibilidad",
        viaje_id=fila["viaje_id"]
    ))


@app.post("/apartados/<int:boleto_id>/liberar")
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
            "El apartado no existe.",
            "error"
        )
        return redirect(
            url_for("disponibilidad")
        )

    resultado = db.execute("""
        DELETE FROM boletos
        WHERE id = ?
          AND estado = 'APARTADO'
    """, (boleto_id,))

    db.commit()

    flash(
        "Asiento liberado."
        if resultado.rowcount
        else "No se pudo liberar.",
        "success" if resultado.rowcount else "error"
    )

    return redirect(url_for(
        "disponibilidad",
        viaje_id=fila["viaje_id"]
    ))


def filtros_caja():
    hoy = ahora_caja().date().isoformat()

    desde = request.args.get("desde") or hoy
    hasta = request.args.get("hasta") or hoy

    try:
        inicio = date.fromisoformat(desde)
        fin = date.fromisoformat(hasta)
    except ValueError:
        abort(400, "Fecha no válida")

    if inicio > fin:
        abort(
            400,
            "La fecha inicial no puede ser mayor que la final"
        )

    return desde, hasta


def consultar_ventas(desde, hasta):
    db = obtener_db()

    fecha_fin = (
        date.fromisoformat(hasta) + timedelta(days=1)
    ).isoformat()

    return db.execute("""
        SELECT
            b.id,
            b.pasajero,
            b.asiento,
            b.creado_en,
            b.cobrado_en,
            b.cobrado_en AS fecha_cobro,
            b.destino_boleto,
            b.precio_boleto,
            v.origen,
            v.destino AS destino_final,
            v.codigo_ruta

        FROM boletos b

        INNER JOIN viajes v
            ON b.viaje_id = v.id

        WHERE b.estado = 'VENDIDO'
          AND b.cobrado_en >= ?
          AND b.cobrado_en < ?

        ORDER BY b.cobrado_en DESC, b.id DESC
    """, (
        desde + " 00:00:00",
        fecha_fin + " 00:00:00"
    )).fetchall()


def calcular_corte(desde, hasta):
    registros = consultar_ventas(desde, hasta)

    total = 0.0
    sin_precio = 0
    rutas = {}

    for boleto in registros:
        codigo = (
            boleto["codigo_ruta"] or "SIN_RUTA"
        )

        if codigo not in rutas:
            info = RUTAS.get(codigo, {})

            rutas[codigo] = {
                "codigo": codigo,
                "nombre": info.get(
                    "nombre", codigo
                ),
                "cantidad": 0,
                "total": 0.0
            }

        rutas[codigo]["cantidad"] += 1

        precio = boleto["precio_boleto"]

        if precio is None:
            sin_precio += 1
        else:
            importe = float(precio)

            total += importe
            rutas[codigo]["total"] += importe

    return {
        "registros": registros,
        "total": round(total, 2),
        "cantidad": len(registros),
        "sin_precio": sin_precio,
        "por_ruta": list(rutas.values())
    }


@app.route("/corte-caja")
def corte_caja():
    hoy = ahora_caja().date().isoformat()

    desde, hasta = filtros_caja()

    corte_hoy = calcular_corte(
        hoy, hoy
    )

    corte_periodo = calcular_corte(
        desde, hasta
    )

    return render_template(
        "corte_caja.html",
        activo="corte",
        hoy=hoy,
        desde=desde,
        hasta=hasta,
        corte_hoy=corte_hoy,
        corte_periodo=corte_periodo,
        rutas=RUTAS
    )


@app.route("/corte-caja/pdf")
def corte_caja_pdf():
    desde, hasta = filtros_caja()

    corte = calcular_corte(
        desde, hasta
    )

    archivo = BytesIO()

    documento = SimpleDocTemplate(
        archivo,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=35,
        bottomMargin=35
    )

    estilos = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph(
        "SISTEMA DE ALEXITO",
        estilos["Title"]
    ))

    elementos.append(Paragraph(
        "Reporte de Corte de Caja",
        estilos["Heading2"]
    ))

    elementos.append(Spacer(1, 15))

    elementos.append(Paragraph(
        f"Periodo: {desde} al {hasta}",
        estilos["Normal"]
    ))

    elementos.append(Paragraph(
        f"Boletos cobrados: {corte['cantidad']}",
        estilos["Normal"]
    ))

    elementos.append(Paragraph(
        f"Total recaudado: ${corte['total']:,.2f} MXN",
        estilos["Heading2"]
    ))

    elementos.append(Spacer(1, 18))

    elementos.append(Paragraph(
        "Recaudacion por ruta",
        estilos["Heading2"]
    ))

    datos_rutas = [[
        "Ruta", "Boletos", "Total"
    ]]

    for ruta in corte["por_ruta"]:
        datos_rutas.append([
            ruta["nombre"],
            str(ruta["cantidad"]),
            f"${ruta['total']:,.2f}"
        ])

    if len(datos_rutas) == 1:
        datos_rutas.append([
            "Sin ventas", "0", "$0.00"
        ])

    tabla_rutas = Table(
        datos_rutas,
        colWidths=[280, 100, 130],
        repeatRows=1
    )

    tabla_rutas.setStyle(TableStyle([
        (
            "BACKGROUND", (0, 0), (-1, 0),
            colors.HexColor("#17365d")
        ),
        (
            "TEXTCOLOR", (0, 0), (-1, 0),
            colors.white
        ),
        (
            "GRID", (0, 0), (-1, -1),
            0.5, colors.lightgrey
        ),
        (
            "ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.whitesmoke]
        ),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7)
    ]))

    elementos.append(tabla_rutas)
    elementos.append(Spacer(1, 18))

    datos_tabla = [[
        "Folio", "Fecha", "Asiento", "Precio"
    ]]

    for boleto in corte["registros"]:
        importe = (
            f"${float(boleto['precio_boleto']):,.2f}"
            if boleto["precio_boleto"] is not None
            else "Sin precio"
        )

        datos_tabla.append([
            str(boleto["id"]),
            str(boleto["fecha_cobro"])[:16],
            str(boleto["asiento"]),
            importe
        ])

    if len(datos_tabla) == 1:
        datos_tabla.append([
            "-", "Sin ventas", "-", "-"
        ])

    tabla = Table(
        datos_tabla,
        colWidths=[80, 180, 100, 150],
        repeatRows=1
    )

    tabla.setStyle(TableStyle([
        (
            "BACKGROUND", (0, 0), (-1, 0),
            colors.HexColor("#17365d")
        ),
        (
            "TEXTCOLOR", (0, 0), (-1, 0),
            colors.white
        ),
        (
            "GRID", (0, 0), (-1, -1),
            0.5, colors.lightgrey
        ),
        (
            "ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.whitesmoke]
        ),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 9)
    ]))

    elementos.append(tabla)

    if corte["sin_precio"]:
        elementos.append(Spacer(1, 12))

        elementos.append(Paragraph(
            f"Aviso: {corte['sin_precio']} boletos "
            "no tienen precio registrado y no "
            "se incluyen en el total recaudado.",
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
        port=int(os.environ.get("PORT", 5000)),
        debug=False,
        threaded=True
    )
