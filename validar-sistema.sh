#!/bin/bash
# Script de validación del workflow bloqueo/desbloqueo
# Ejecutar después de deployment en Railway

set -e

echo "=================================="
echo "Validación del Sistema IncaNeurobaeza"
echo "=================================="

# Colores
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Variables
API_URL="https://web-production-95ed.up.railway.app"
ADMIN_TOKEN="0b9685e9a9ff3c24652acaad881ec7b2b4c17f6082ad164d10a6e67589f3f67c"

echo ""
echo "📋 TEST 1: Verificar que el backend está online"
echo "-------------------------------------------"
if curl -s "$API_URL/ping" | grep -q "alive"; then
    echo -e "${GREEN}✅ PASS${NC}: Backend respondiendo"
else
    echo -e "${RED}❌ FAIL${NC}: Backend no responde"
    exit 1
fi

echo ""
echo "📋 TEST 2: Verificar endpoint de bloqueo"
echo "-------------------------------------------"
# Usando un serial de prueba (puede no existir)
TEST_SERIAL="1085043374 01 01 2026 02 02 2026"
TEST_SERIAL_ENCODED="1085043374%2001%2001%202026%2002%2002%202026"

# Este debería retornar 404 si el caso no existe (que es correcto)
STATUS=$(curl -s -w "%{http_code}" -o /dev/null -X POST \
  -H "x-admin-token: $ADMIN_TOKEN" \
  -F "accion=bloquear" \
  -F "motivo=Test" \
  "$API_URL/validador/casos/$TEST_SERIAL_ENCODED/toggle-bloqueo")

if [ "$STATUS" == "404" ] || [ "$STATUS" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Endpoint toggle-bloqueo accesible (HTTP $STATUS)"
else
    echo -e "${RED}❌ FAIL${NC}: Endpoint retorna error HTTP $STATUS"
fi

echo ""
echo "📋 TEST 3: Verificar endpoint de verificación de bloqueo"
echo "-------------------------------------------"
STATUS=$(curl -s -w "%{http_code}" -o /dev/null \
  "$API_URL/verificar-bloqueo/1085043374")

if [ "$STATUS" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Endpoint verificar-bloqueo accesible"
else
    echo -e "${RED}❌ FAIL${NC}: Endpoint retorna HTTP $STATUS"
fi

echo ""
echo "📋 TEST 4: Verificar base de datos conectada"
echo "-------------------------------------------"
STATUS=$(curl -s -w "%{http_code}" -o /dev/null "$API_URL/status")

if [ "$STATUS" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Base de datos conectada"
else
    echo -e "${RED}❌ FAIL${NC}: Base de datos con problemas"
fi

echo ""
echo "📋 TEST 5: Verificar Google Drive"
echo "-------------------------------------------"
STATUS=$(curl -s -w "%{http_code}" -o /dev/null "$API_URL/drive/health")

if [ "$STATUS" == "200" ]; then
    echo -e "${GREEN}✅ PASS${NC}: Google Drive conectado"
else
    echo -e "${YELLOW}⚠️  WARNING${NC}: Google Drive puede tener problemas"
fi

echo ""
echo "=================================="
echo "✅ VALIDACIÓN COMPLETADA"
echo "=================================="
echo ""
echo "Para más información, revisar:"
echo "  - ESTADO_BLOQUEO_DESBLOQUEO.md"
echo "  - Railway logs: railway logs"
echo ""
