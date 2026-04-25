@echo off
REM Script para probar configuración de WhatsApp Business API
REM Necesitas configurar estas variables con tus valores reales

setlocal enabledelayedexpansion

echo.
echo =============================================================================
echo PRUEBA DE CONFIGURACION WHATSAPP - Variables de Entorno Necesarias
echo =============================================================================
echo.
echo Este script necesita que configures estas variables de entorno primero:
echo.
echo 1. WHATSAPP_BUSINESS_API_TOKEN
echo    Origen: https://developers.facebook.com/ 
echo    App: incapacidades patprimo
echo    Tools -^> API Explorer -^> GET /{phone_id}/about
echo    Copiar el "Access Token" que aparece
echo    Formato: EAAL...
echo.
echo 2. WHATSAPP_PHONE_NUMBER_ID
echo    Valor: 1065658909966623
echo.
echo Opción 1: Configurar variables global en Windows
echo ---
echo set WHATSAPP_BUSINESS_API_TOKEN=tu_token_aqui
echo set WHATSAPP_PHONE_NUMBER_ID=1065658909966623
echo python test_whatsapp_config.py
echo.
echo Opción 2: Configurar manualmente en este script
echo ---
REM DESCOMENTA Y CONFIGURA TUS VALORES:
REM set WHATSAPP_BUSINESS_API_TOKEN=tu_token_aqui
REM set WHATSAPP_PHONE_NUMBER_ID=1065658909966623
echo.

if not defined WHATSAPP_BUSINESS_API_TOKEN (
    echo ERROR: WHATSAPP_BUSINESS_API_TOKEN no está definido
    echo.
    echo INSTRUCCIONES:
    echo 1. Abre una terminal (cmd o PowerShell)
    echo 2. Ejecuta:
    echo    set WHATSAPP_BUSINESS_API_TOKEN=tu_token_aqui
    echo    set WHATSAPP_PHONE_NUMBER_ID=1065658909966623
    echo 3. Luego ejecuta:
    echo    python test_whatsapp_config.py
    echo.
    pause
    exit /b 1
)

if not defined WHATSAPP_PHONE_NUMBER_ID (
    echo ERROR: WHATSAPP_PHONE_NUMBER_ID no está definido
    echo.
    set WHATSAPP_PHONE_NUMBER_ID=1065658909966623
    echo Usando valor por defecto: !WHATSAPP_PHONE_NUMBER_ID!
)

echo Ejecutando prueba con:
echo - Token: !WHATSAPP_BUSINESS_API_TOKEN:~0,15!...!WHATSAPP_BUSINESS_API_TOKEN:~-5!
echo - Phone ID: !WHATSAPP_PHONE_NUMBER_ID!
echo.

python test_whatsapp_config.py

pause
