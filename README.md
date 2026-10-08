# Atención a clientes
Aplicación con **Python/FastAPI**, **SQLite** y **Angular 20** para una fila virtual atendida por cuatro mesas.

## Funciones
- Apartado Turnos con botón **Tomar turno**, folio, posición y mesa asignada.
- Pantalla pública con fila por orden de llegada y cuatro mesas.
- Panel de atención: Agregar turno para registrar varios clientes, Finalizar atención y pausar una mesa libre.
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

El script instala las dependencias e inicia ambos servicios en segundo plano. Frontend: http://127.0.0.1:4301. API: http://127.0.0.1:8010/api/health. Los puertos se pueden configurar mediante FrontendPort y BackendPort. Las dependencias Python se instalan dentro de .python-packages para evitar problemas con entornos virtuales en Windows. La clave de operador se guarda en el archivo local ignorado `.operator-key`.
Para detener los servicios, ejecuta `.\\stop-local.ps1`. Consulta `.logs/` para ver los registros.

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
La app fue verificada en Windows con acceso completo en Codex: creación de turno desde el navegador, llamada a Mesa 1 y finalización. Las cuatro pruebas del backend pasaron.

## Configuración
- `OPERATOR_KEY`: obligatoria, mínimo 16 caracteres. No subirla a GitHub.
- `QUEUE_DB`: ruta SQLite, predeterminada `backend/data/queue.db`.
- La API acepta CORS únicamente de localhost:4200; Angular usa proxy /api.
- El folio es una secuencia global persistente y no se reinicia cada día.
- Los turnos nuevos ocupan automáticamente la primera mesa libre (1 a 4). Si todas están ocupadas o pausadas, quedan en fila por orden de llegada. Al finalizar, se asigna el siguiente turno automáticamente; al reactivar una mesa, también se atiende la fila. Una mesa solo puede atender un turno.
- El turno del cliente se conserva en localStorage de ese navegador. Para registrar varios clientes desde la misma laptop, entra en Mesas de atención y usa Agregar turno; cada clic genera un folio independiente.
- Versión para uso local. Para exposición pública hacen falta HTTPS, gestión de identidades de operadores, limitación de solicitudes, política de retención y despliegue adecuado.

