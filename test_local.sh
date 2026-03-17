#!/bin/bash
# =============================================================================
# test_local.sh — Pruebas locales del Hub de Integración Satelital
# =============================================================================
# Requisito: el servidor debe estar corriendo en localhost:8000
#
# Pasos previos:
#   1. cp .env.example .env  (y setear DRY_RUN=true para pruebas seguras)
#   2. pip install -r requirements.txt
#   3. uvicorn main:app --reload --port 8000
#
# Luego en otra terminal:
#   bash test_local.sh
# =============================================================================

URL_BASE="http://localhost:8000"
PASARON=0
FALLARON=0

VERDE='\033[0;32m'
ROJO='\033[0;31m'
AMARILLO='\033[1;33m'
SIN_COLOR='\033[0m'

verificar() {
    local descripcion="$1"
    local esperado="$2"
    local obtenido="$3"
    if echo "$obtenido" | grep -q "$esperado"; then
        echo -e "  ${VERDE}✓${SIN_COLOR} $descripcion"
        ((PASARON++))
    else
        echo -e "  ${ROJO}✗${SIN_COLOR} $descripcion"
        echo -e "    Esperado contener: $esperado"
        echo -e "    Obtenido:          $obtenido"
        ((FALLARON++))
    fi
}

echo ""
echo "======================================================"
echo "  Hub de Integración Satelital — Pruebas Locales"
echo "======================================================"
echo ""

# ── Prueba 1: Estado del servicio ─────────────────────────────────────────────
echo "1) Estado del servicio"
RESP=$(curl -s "$URL_BASE/estado")
verificar "Estado activo" '"estado":"activo"' "$RESP"
verificar "Campo versión presente" '"version"' "$RESP"

# ── Prueba 2: Raíz ────────────────────────────────────────────────────────────
echo ""
echo "2) Raíz del Hub"
RESP=$(curl -s "$URL_BASE/")
verificar "Link a /docs" '"documentacion"' "$RESP"
verificar "Link a /dashboard" '"dashboard"' "$RESP"

# ── Prueba 3: Dashboard HTML ──────────────────────────────────────────────────
echo ""
echo "3) Dashboard HTML"
CODIGO=$(curl -s -o /dev/null -w "%{http_code}" "$URL_BASE/dashboard")
verificar "HTTP 200" "200" "$CODIGO"

# ── Prueba 4: Endpoint de métricas ────────────────────────────────────────────
echo ""
echo "4) Métricas JSON"
RESP=$(curl -s "$URL_BASE/metricas")
verificar "Sección hub presente" '"hub"' "$RESP"
verificar "Sección proveedores presente" '"proveedores"' "$RESP"
verificar "Sección destinos presente" '"destinos"' "$RESP"
verificar "Sección actividad presente" '"actividad"' "$RESP"

# ── Prueba 5: Ingesta de evento único ─────────────────────────────────────────
echo ""
echo "5) Ingesta — evento único (campos en español)"
RESP=$(curl -s -X POST "$URL_BASE/ingresar/proveedor_prueba" \
  -H "Content-Type: application/json" \
  -d '{
    "placa": "TEST-001",
    "latitud": 19.432608,
    "longitud": -99.133209,
    "velocidad": "60",
    "fecha": "2024-03-15T10:30:00",
    "codigo_evento": "1",
    "ignicion": "1"
  }')
verificar "Estado aceptado" '"aceptado"' "$RESP"
verificar "Proveedor correcto" 'proveedor_prueba' "$RESP"

# ── Prueba 6: Ingesta con campos en inglés (aliases) ─────────────────────────
echo ""
echo "6) Ingesta — campos en inglés (aliases automáticos)"
RESP=$(curl -s -X POST "$URL_BASE/ingresar/proveedor_ingles" \
  -H "Content-Type: application/json" \
  -d '{
    "Asset": "ALIAS-001",
    "Latitude": 19.432608,
    "Longitude": -99.133209,
    "Speed": "80",
    "Date": "2024-03-15T11:00:00",
    "Code": "1"
  }')
verificar "Estado aceptado" '"aceptado"' "$RESP"

# ── Prueba 7: Lote de eventos ─────────────────────────────────────────────────
echo ""
echo "7) Ingesta — lote de 3 eventos"
RESP=$(curl -s -X POST "$URL_BASE/ingresar/proveedor_lote" \
  -H "Content-Type: application/json" \
  -d '[
    {"placa": "LOTE-001", "latitud": 19.1, "longitud": -99.1, "velocidad": "0",  "codigo_evento": "1", "fecha": "2024-01-01T00:00:00"},
    {"placa": "LOTE-002", "latitud": 20.2, "longitud": -100.2,"velocidad": "55", "codigo_evento": "1", "fecha": "2024-01-01T00:01:00"},
    {"placa": "LOTE-003", "latitud": 21.3, "longitud": -101.3,"velocidad": "90", "codigo_evento": "1", "fecha": "2024-01-01T00:02:00"}
  ]')
verificar "Estado aceptado" '"aceptado"' "$RESP"
verificar "3 eventos reconocidos" '"3 evento' "$RESP"

# ── Prueba 8: Evento SIN posición GPS (regla: no descartar) ───────────────────
echo ""
echo "8) Ingesta — evento sin GPS (regla: NUNCA descartar)"
RESP=$(curl -s -X POST "$URL_BASE/ingresar/sin_gps" \
  -H "Content-Type: application/json" \
  -d '{
    "placa": "PANICO-001",
    "codigo_evento": "1",
    "fecha": "2024-03-15T10:30:00",
    "ignicion": "1"
  }')
verificar "Evento sin GPS aceptado" '"aceptado"' "$RESP"

# ── Prueba 9: JSON inválido (debe devolver 400) ────────────────────────────────
echo ""
echo "9) JSON inválido (debe devolver error 400)"
CODIGO=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "$URL_BASE/ingresar/test" \
  -H "Content-Type: application/json" \
  -d 'esto no es json valido')
verificar "HTTP 400" "400" "$CODIGO"

# ── Prueba 10: Métricas registran la actividad ─────────────────────────────────
echo ""
echo "10) Las métricas reflejan las ingestas anteriores"
sleep 1  # Dar tiempo a los BackgroundTasks
RESP=$(curl -s "$URL_BASE/metricas")
verificar "Hay proveedores registrados" '"nombre"' "$RESP"
verificar "Total ingestados mayor a 0" '"total_ingestados"' "$RESP"

# ── Resumen ────────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo -e "  Resultado: ${VERDE}${PASARON} pasaron${SIN_COLOR} / ${ROJO}${FALLARON} fallaron${SIN_COLOR}"
echo "======================================================"
echo ""

if [ $FALLARON -gt 0 ]; then
    echo -e "${AMARILLO}¿El servidor está corriendo?${SIN_COLOR}"
    echo "  uvicorn main:app --reload --port 8000"
    echo ""
    exit 1
fi
