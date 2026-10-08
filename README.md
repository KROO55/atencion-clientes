# Atención a clientes
Aplicación con **Python/FastAPI**, **SQLite** y **Angular 20** para una fila virtual atendida por cuatro mesas.

## Funciones
- Apartado Turnos con botón **Tomar turno**, folio, posición y mesa asignada.
- Pantalla pública con fila por orden de llegada y cuatro mesas.
- Panel de atención: llamar siguiente, finalizar y pausar una mesa libre.
- SQLite conserva los turnos al reiniciar. Las transacciones evitan asignaciones duplicadas.
- Cancelación del turno en espera y recuperación del turno del navegador.
- Panel protegido por clave de operador; los turnos públicos no exponen claves de seguimiento.

## Ejecutar en Windows
Requiere Python 3.11+ y Node.js 22.12+.
Clona este repositorio y ejecuta en PowerShell:

```powershell
git clone https://github.com/KROO55/atencion-clientes.git
cd atencion-clientes
.\start-local.ps1
```

El script instala las dependencias y abre dos terminales. Frontend: http://localhost:4200. API: http://127.0.0.1:8000/api/health. La clave de operador se guarda en el archivo local ignorado `.operator-key`.
Para detener el servicio, pulsa Ctrl+C en ambas terminales.

También puedes iniciar manualmente (dos terminales):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
$env:OPERATOR_KEY = 'elige-una-clave-local-de-al-menos-16-caracteres'
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd frontend
npm install
npm start
```

En Angular abre **Mesas de atención** e introduce la misma clave. El cliente y la pantalla pública no necesitan esa clave.
La actualización entre navegadores ocurre cada dos segundos.

## Pruebas
```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
cd frontend
npm run build
```
GitHub Actions ejecuta las pruebas del backend y la compilación del frontend en cada push.
El código se publicó desde el conector porque el entorno local de Codex no permite ejecutar procesos; consultar Actions para el resultado real de validación.

## Configuración
- `OPERATOR_KEY`: obligatoria, mínimo 16 caracteres. No subirla a GitHub.
- `QUEUE_DB`: ruta SQLite, predeterminada `backend/data/queue.db`.
- La API acepta CORS únicamente de localhost:4200; Angular usa proxy /api.
- El folio es una secuencia global persistente y no se reinicia cada día.
- Una mesa solo puede atender un turno. Finalizar no llama automáticamente al siguiente: pulsa **Llamar siguiente**.
- El turno del cliente se conserva en localStorage de ese navegador. Cierra/cancela el turno antes de utilizar el mismo navegador para otra persona.
- Versión para uso local. Para exposición pública hacen falta HTTPS, gestión de identidades de operadores, limitación de solicitudes, política de retención y despliegue adecuado.
