# PowerShell Script para Verificar Configuración de WhatsApp Business API
# Ejecución: PowerShell -ExecutionPolicy Bypass -File test_whatsapp.ps1

Write-Host "`n" -ForegroundColor White
Write-Host "="*100 -ForegroundColor Cyan
Write-Host "🧪 VERIFICADOR DE CONFIGURACIÓN WHATSAPP BUSINESS API" -ForegroundColor Cyan
Write-Host "="*100 -ForegroundColor Cyan
Write-Host "`n"

# ═══════════════════════════════════════════════════════════════════════════════════
# 1. VERIFICAR VARIABLES DE ENTORNO
# ═══════════════════════════════════════════════════════════════════════════════════

Write-Host "1️⃣ VERIFICANDO VARIABLES DE ENTORNO LOCAL" -ForegroundColor Yellow
Write-Host "-" * 100

$WHATSAPP_TOKEN = $env:WHATSAPP_BUSINESS_API_TOKEN
$WHATSAPP_PHONE_ID = $env:WHATSAPP_PHONE_NUMBER_ID

if ($WHATSAPP_TOKEN) {
    Write-Host "✅ WHATSAPP_BUSINESS_API_TOKEN está configurada" -ForegroundColor Green
    $tokenDisplay = $WHATSAPP_TOKEN.Substring(0, [Math]::Min(15, $WHATSAPP_TOKEN.Length)) + "..." + $WHATSAPP_TOKEN.Substring([Math]::Max(0, $WHATSAPP_TOKEN.Length - 5))
    Write-Host "   Valor: $tokenDisplay" -ForegroundColor Green
    Write-Host "   Longitud: $($WHATSAPP_TOKEN.Length) caracteres" -ForegroundColor Green
} else {
    Write-Host "❌ WHATSAPP_BUSINESS_API_TOKEN NO está configurada en este terminal" -ForegroundColor Red
    Write-Host "   → Necesitas configurarla primero" -ForegroundColor Red
}

Write-Host ""

if ($WHATSAPP_PHONE_ID) {
    Write-Host "✅ WHATSAPP_PHONE_NUMBER_ID está configurada" -ForegroundColor Green
    Write-Host "   Valor: $WHATSAPP_PHONE_ID" -ForegroundColor Green
} else {
    Write-Host "❌ WHATSAPP_PHONE_NUMBER_ID NO está configurada en este terminal" -ForegroundColor Red
    Write-Host "   → Valor esperado: 1065658909966623" -ForegroundColor Red
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════════════
# 2. INSTRUCCIONES PARA CONFIGURAR VARIABLES
# ═══════════════════════════════════════════════════════════════════════════════════

if (-not $WHATSAPP_TOKEN -or -not $WHATSAPP_PHONE_ID) {
    Write-Host "🔧 INSTRUCCIONES PARA CONFIGURAR VARIABLES" -ForegroundColor Yellow
    Write-Host "-" * 100
    
    Write-Host ""
    Write-Host "Opción 1: Configurar para este terminal (sesión actual)" -ForegroundColor Cyan
    Write-Host ""
    Write-Host '$env:WHATSAPP_BUSINESS_API_TOKEN = "tu_token_aqui"' -ForegroundColor Green
    Write-Host '$env:WHATSAPP_PHONE_NUMBER_ID = "1065658909966623"' -ForegroundColor Green
    Write-Host ""
    
    Write-Host "Opción 2: Configurar permanentemente en Windows" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[Environment]::SetEnvironmentVariable('WHATSAPP_BUSINESS_API_TOKEN', 'tu_token_aqui', 'User')" -ForegroundColor Green
    Write-Host "[Environment]::SetEnvironmentVariable('WHATSAPP_PHONE_NUMBER_ID', '1065658909966623', 'User')" -ForegroundColor Green
    Write-Host ""
    
    Write-Host "PASOS:" -ForegroundColor Yellow
    Write-Host "1. Abre https://developers.facebook.com/" -ForegroundColor White
    Write-Host "2. Selecciona app: 'incapacidades patprimo'" -ForegroundColor White
    Write-Host "3. Abre: Tools → API Explorer" -ForegroundColor White
    Write-Host "4. Busca el campo 'Access Token' en la parte superior" -ForegroundColor White
    Write-Host "5. Copia el token completo (comienza con EAAL)" -ForegroundColor White
    Write-Host "6. Asegúrate que sea PERMANENTE (Never Expires), no temporal (1 hour)" -ForegroundColor White
    Write-Host "7. Pega el token en el comando de arriba" -ForegroundColor White
    Write-Host ""
    
    Write-Host "⚠️ IMPORTANTE:" -ForegroundColor Red
    Write-Host "   - NO copies comillas, solo el token" -ForegroundColor Red
    Write-Host "   - El token debe comenzar con EAAL..." -ForegroundColor Red
    Write-Host "   - Sin espacios al inicio o final" -ForegroundColor Red
    Write-Host ""
    
    exit
}

# ═══════════════════════════════════════════════════════════════════════════════════
# 3. VALIDAR FORMATO DEL TOKEN
# ═══════════════════════════════════════════════════════════════════════════════════

Write-Host "2️⃣ VALIDANDO FORMATO DEL TOKEN" -ForegroundColor Yellow
Write-Host "-" * 100

if ($WHATSAPP_TOKEN.StartsWith("EAAL")) {
    Write-Host "✅ Token comienza con 'EAAL' (formato correcto)" -ForegroundColor Green
} elseif ($WHATSAPP_TOKEN.StartsWith("EAA")) {
    Write-Host "⚠️ Token comienza con 'EAA' (posible token temporal)" -ForegroundColor Yellow
    Write-Host "   → Deberías generar uno PERMANENTE" -ForegroundColor Yellow
} else {
    Write-Host "❌ Token NO comienza con EAAL o EAA (formato incorrecto)" -ForegroundColor Red
    Write-Host "   → Valor: $($WHATSAPP_TOKEN.Substring(0, [Math]::Min(20, $WHATSAPP_TOKEN.Length)))" -ForegroundColor Red
}

Write-Host ""

# Validar espacios
if ($WHATSAPP_TOKEN -ne $WHATSAPP_TOKEN.Trim()) {
    Write-Host "❌ Token tiene espacios al inicio o final (PROBLEMA)" -ForegroundColor Red
} else {
    Write-Host "✅ Token no tiene espacios al inicio o final" -ForegroundColor Green
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════════════
# 4. PROBAR CONEXIÓN A META API
# ═══════════════════════════════════════════════════════════════════════════════════

Write-Host "3️⃣ PROBANDO CONEXIÓN A META GRAPH API" -ForegroundColor Yellow
Write-Host "-" * 100

$API_VERSION = "v19.0"
$API_BASE_URL = "https://graph.instagram.com/$API_VERSION"
$TEST_URL = "$API_BASE_URL/$WHATSAPP_PHONE_ID/about"

Write-Host "URL: $TEST_URL" -ForegroundColor Cyan
Write-Host ""

$headers = @{
    "Authorization" = "Bearer $WHATSAPP_TOKEN"
    "Content-Type" = "application/json"
}

try {
    Write-Host "📡 Enviando GET request..." -ForegroundColor White
    
    $response = Invoke-WebRequest -Uri $TEST_URL -Headers $headers -Method Get -TimeoutSec 10 -ErrorAction Stop
    $statusCode = $response.StatusCode
    $body = $response.Content | ConvertFrom-Json
    
    Write-Host "✅ RESPUESTA EXITOSA (HTTP $statusCode)" -ForegroundColor Green
    Write-Host ""
    Write-Host "📋 Información del Número de Teléfono:" -ForegroundColor Green
    Write-Host ($body | ConvertTo-Json -Depth 2) -ForegroundColor Green
    
} catch {
    $response = $_.Exception.Response
    $statusCode = [int]$response.StatusCode
    $stream = $response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $errorBody = $reader.ReadToEnd() | ConvertFrom-Json
    
    Write-Host "❌ ERROR HTTP $statusCode" -ForegroundColor Red
    Write-Host ""
    
    if ($statusCode -eq 401) {
        Write-Host "AUTENTICACIÓN FALLIDA - Error 401" -ForegroundColor Red
        Write-Host ""
        Write-Host "Mensaje: $($errorBody.error.message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "🔧 POSIBLES SOLUCIONES:" -ForegroundColor Yellow
        Write-Host "1. Token es TEMPORAL (expira cada hora)" -ForegroundColor White
        Write-Host "   → Generar token PERMANENTE ('Never Expires')" -ForegroundColor White
        Write-Host ""
        Write-Host "2. Token es del tipo INCORRECTO" -ForegroundColor White
        Write-Host "   → Asegúrate generar desde 'incapacidades patprimo'" -ForegroundColor White
        Write-Host "   → NO desde 'Neurobaeza'" -ForegroundColor White
        Write-Host ""
        Write-Host "3. Token está CORRUPTO" -ForegroundColor White
        Write-Host "   → Copia nuevamente sin espacios" -ForegroundColor White
        
    } elseif ($statusCode -eq 400) {
        Write-Host "ERROR 400 - Solicitud Inválida" -ForegroundColor Red
        Write-Host ""
        Write-Host "Mensaje: $($errorBody.error.message)" -ForegroundColor Red
        Write-Host ""
        Write-Host "🔧 VERIFICAR:" -ForegroundColor Yellow
        Write-Host "1. Phone Number ID: $WHATSAPP_PHONE_ID" -ForegroundColor White
        Write-Host "   → Valor esperado: 1065658909966623" -ForegroundColor White
        
    } else {
        Write-Host "Mensaje: $($errorBody.error.message)" -ForegroundColor Red
    }
    
    Write-Host ""
}

Write-Host ""

# ═══════════════════════════════════════════════════════════════════════════════════
# 5. RESUMEN
# ═══════════════════════════════════════════════════════════════════════════════════

Write-Host "="*100 -ForegroundColor Cyan
Write-Host "📊 PRÓXIMOS PASOS" -ForegroundColor Cyan
Write-Host "="*100 -ForegroundColor Cyan
Write-Host ""

Write-Host "1. Si viste ✅ RESPUESTA EXITOSA:" -ForegroundColor Green
Write-Host "   → La configuración es CORRECTA en LOCAL" -ForegroundColor Green
Write-Host "   → Verifica que Railway tenga las MISMAS variables" -ForegroundColor Green
Write-Host "   → Si ya están, espera 2-3 min después del redeploy" -ForegroundColor Green
Write-Host ""

Write-Host "2. Si viste ❌ ERROR 401 (Autenticación Fallida):" -ForegroundColor Red
Write-Host "   → El token es temporal o inválido" -ForegroundColor Red
Write-Host "   → Genera uno PERMANENTE desde Meta" -ForegroundColor Red
Write-Host "   → Verifica que sea desde 'incapacidades patprimo'" -ForegroundColor Red
Write-Host "   → Actualiza en Railway y redeploy" -ForegroundColor Red
Write-Host ""

Write-Host "3. Para actualizar en Railway:" -ForegroundColor Cyan
Write-Host "   → Ir a: https://railway.app/" -ForegroundColor White
Write-Host "   → Proyecto: BACKEND" -ForegroundColor White
Write-Host "   → Pestanya: Variables" -ForegroundColor White
Write-Host "   → Editar: WHATSAPP_BUSINESS_API_TOKEN" -ForegroundColor White
Write-Host "   → Pegar nuevo token" -ForegroundColor White
Write-Host "   → Guardar y Redeploy" -ForegroundColor White
Write-Host ""

Write-Host "="*100 -ForegroundColor Cyan
Write-Host ""
