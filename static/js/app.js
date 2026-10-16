document.querySelectorAll('.seat.free:not([disabled])').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.seat.selected').forEach(item => item.classList.remove('selected'));
    button.classList.add('selected');
    const input = document.getElementById('asiento');
    const display = document.getElementById('asiento-mostrar');
    if (input) input.value = button.dataset.asiento;
    if (display) display.value = 'Asiento #' + button.dataset.asiento;
  });
});
const operationForm = document.getElementById('form-operacion');
if (operationForm) operationForm.addEventListener('submit', event => {
  if (!document.getElementById('asiento').value) {
    event.preventDefault();
    alert('Selecciona un asiento disponible antes de continuar.');
  }
});
document.querySelectorAll('[data-filter-table]').forEach(input => {
  input.addEventListener('input', () => {
    const value = input.value.toLocaleLowerCase();
    const table = document.getElementById(input.dataset.filterTable);
    table?.querySelectorAll('tbody tr').forEach(row => {
      row.hidden = !row.textContent.toLocaleLowerCase().includes(value);
    });
  });
});
