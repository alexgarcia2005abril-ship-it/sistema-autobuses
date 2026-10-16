
document.querySelectorAll(
    ".seat.free:not([disabled])"
).forEach(button => {

    button.addEventListener("click", () => {

        document.querySelectorAll(
            ".seat.selected"
        ).forEach(item => {
            item.classList.remove("selected");
        });

        button.classList.add("selected");

        const asiento = document.getElementById("asiento");
        const mostrar = document.getElementById("asiento-mostrar");

        if (asiento) {
            asiento.value = button.dataset.asiento;
        }

        if (mostrar) {
            mostrar.value = "Asiento #" + button.dataset.asiento;
        }

    });

});


const destino = document.getElementById("destino");
const precioTotal = document.getElementById("precio-total");

function actualizarPrecio() {

    if (!destino || !precioTotal) return;

    const opcion = destino.options[destino.selectedIndex];

    const precio = Number(opcion?.dataset.precio || 0);

    precioTotal.textContent =
        "$" + precio.toFixed(2) + " MXN";
}

if (destino) {
    destino.addEventListener("change", actualizarPrecio);
    actualizarPrecio();
}


const formulario = document.getElementById("form-operacion");

if (formulario) {

    formulario.addEventListener("submit", event => {

        const asiento = document.getElementById("asiento");

        if (!asiento || !asiento.value) {
            event.preventDefault();
            alert("Selecciona un asiento disponible.");
            return;
        }

        if (destino && !destino.value) {
            event.preventDefault();
            alert("Selecciona un destino.");
        }

    });
}


document.querySelectorAll("[data-filter-table]").forEach(input => {

    input.addEventListener("input", () => {

        const buscar = input.value.toLowerCase();

        const tabla = document.getElementById(
            input.dataset.filterTable
        );

        if (!tabla) return;

        tabla.querySelectorAll("tbody tr").forEach(fila => {

            fila.hidden = !fila.textContent
                .toLowerCase()
                .includes(buscar);

        });

    });

});
