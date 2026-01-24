// ============================================
// DIAGNÓSTICO: Conexión Backend → N8N
// ============================================

const axios = require('axios');

// Configuración desde tu .env
const N8N_WEBHOOK_URL = process.env.N8N_WEBHOOK_URL || 'https://railway-n8n-production-5a3f.up.railway.app/webhook/incapacidades';

/**
 * Test 1: Verificar que N8N esté accesible
 */
async function testN8NConnection() {
  console.log('\n🔍 TEST 1: Verificando conexión con N8N...');
  console.log('URL:', N8N_WEBHOOK_URL);
  
  try {
    const response = await axios.post(N8N_WEBHOOK_URL, {
      test: true,
      timestamp: new Date().toISOString()
    }, {
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    console.log('✅ N8N responde correctamente');
    console.log('Status:', response.status);
    console.log('Respuesta:', JSON.stringify(response.data, null, 2));
    return true;
  } catch (error) {
    console.log('❌ Error al conectar con N8N');
    
    if (error.code === 'ECONNREFUSED') {
      console.log('   → N8N no está accesible. ¿Está el servicio corriendo?');
    } else if (error.code === 'ETIMEDOUT') {
      console.log('   → Timeout. N8N tarda mucho en responder o no está disponible.');
    } else if (error.response) {
      console.log('   → N8N respondió con error:', error.response.status);
      console.log('   → Mensaje:', error.response.data);
    } else {
      console.log('   → Error desconocido:', error.message);
    }
    
    return false;
  }
}

/**
 * Test 2: Enviar notificación de confirmación (sin adjuntos)
 */
async function testConfirmacionNotification() {
  console.log('\n🔍 TEST 2: Enviando notificación de confirmación...');
  
  const payload = {
    tipo_notificacion: 'confirmacion',
    email: 'davidbaezaospino@gmail.com', // Tu email para prueba
    subject: 'TEST - Confirmación de Incapacidad',
    html_content: `
      <h2>Prueba de Notificación</h2>
      <p>Tu incapacidad ha sido recibida correctamente.</p>
      <p><a href="https://drive.google.com/file/ejemplo">Ver documento en Drive</a></p>
    `,
    cc_email: '',
    adjuntos: [] // Sin adjuntos
  };
  
  try {
    const response = await axios.post(N8N_WEBHOOK_URL, payload, {
      timeout: 15000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    console.log('✅ Notificación enviada');
    console.log('Status:', response.status);
    console.log('Respuesta:', JSON.stringify(response.data, null, 2));
    return true;
  } catch (error) {
    console.log('❌ Error al enviar notificación');
    console.log('   → Error:', error.message);
    if (error.response) {
      console.log('   → Detalles:', JSON.stringify(error.response.data, null, 2));
    }
    return false;
  }
}

/**
 * Test 3: Enviar notificación incompleta (con adjuntos simulados)
 */
async function testIncompletaWithAttachments() {
  console.log('\n🔍 TEST 3: Enviando notificación incompleta con adjuntos...');
  
  // Crear un PDF base64 pequeño de prueba (1x1 pixel PDF)
  const testPdfBase64 = 'JVBERi0xLjQKJeLjz9MKMyAwIG9iago8PC9UeXBlL1BhZ2UvUGFyZW50IDIgMCBSL1Jlc291cmNlczw8L0ZvbnQ8PC9GMSAxIDAgUj4+Pj4vTWVkaWFCb3hbMCAwIDYxMiA3OTJdL0NvbnRlbnRzIDQgMCBSPj4KZW5kb2JqCjQgMCBvYmoKPDwvTGVuZ3RoIDQ0Pj4Kc3RyZWFtCkJUCi9GMSA0OCBUZgoxMCAxMCBUZAooVGVzdCkgVGoKRVQKZW5kc3RyZWFtCmVuZG9iago=';
  
  const payload = {
    tipo_notificacion: 'incompleta',
    email: 'davidbaezaospino@gmail.com',
    subject: 'TEST - Documentación Incompleta',
    html_content: `
      <h2>Documentación Incompleta</h2>
      <p>Falta información en tu incapacidad. Por favor revisa el documento adjunto.</p>
    `,
    cc_email: '',
    adjuntos: [
      {
        filename: 'test-documento.pdf',
        content: testPdfBase64,
        mimetype: 'application/pdf'
      }
    ]
  };
  
  try {
    const response = await axios.post(N8N_WEBHOOK_URL, payload, {
      timeout: 20000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
    
    console.log('✅ Notificación con adjuntos enviada');
    console.log('Status:', response.status);
    console.log('Respuesta:', JSON.stringify(response.data, null, 2));
    return true;
  } catch (error) {
    console.log('❌ Error al enviar notificación con adjuntos');
    console.log('   → Error:', error.message);
    if (error.response) {
      console.log('   → Detalles:', JSON.stringify(error.response.data, null, 2));
    }
    return false;
  }
}

/**
 * Test 4: Verificar formato de datos que envía tu backend
 */
function validatePayloadFormat(payload) {
  console.log('\n🔍 TEST 4: Validando formato de payload...');
  
  const required = ['tipo_notificacion', 'email', 'subject', 'html_content'];
  const missing = [];
  
  required.forEach(field => {
    if (!payload[field]) {
      missing.push(field);
    }
  });
  
  if (missing.length > 0) {
    console.log('❌ Campos requeridos faltantes:', missing.join(', '));
    return false;
  }
  
  // Validar tipo_notificacion
  const validTypes = ['confirmacion', 'incompleta', 'ilegible', 'completa', 'eps', 'tthh', 'extra', 'recordatorio', 'alerta_jefe'];
  if (!validTypes.includes(payload.tipo_notificacion)) {
    console.log('❌ tipo_notificacion inválido:', payload.tipo_notificacion);
    console.log('   → Valores válidos:', validTypes.join(', '));
    return false;
  }
  
  // Validar adjuntos
  if (payload.adjuntos && Array.isArray(payload.adjuntos)) {
    payload.adjuntos.forEach((adj, index) => {
      if (!adj.filename || !adj.content || !adj.mimetype) {
        console.log(`❌ Adjunto ${index} incompleto. Debe tener: filename, content, mimetype`);
        return false;
      }
    });
  }
  
  console.log('✅ Formato de payload válido');
  return true;
}

/**
 * Test 5: Verificar variables de entorno
 */
function checkEnvironmentVariables() {
  console.log('\n🔍 TEST 5: Verificando variables de entorno...');
  
  const vars = {
    'N8N_WEBHOOK_URL': process.env.N8N_WEBHOOK_URL,
    'SMTP_EMAIL': process.env.SMTP_EMAIL,
    'GOOGLE_CLIENT_ID': process.env.GOOGLE_CLIENT_ID ? '✓ Configurado' : undefined
  };
  
  let allOk = true;
  
  Object.entries(vars).forEach(([key, value]) => {
    if (value) {
      console.log(`✅ ${key}: ${value}`);
    } else {
      console.log(`❌ ${key}: NO CONFIGURADO`);
      allOk = false;
    }
  });
  
  return allOk;
}

/**
 * Ejecutar todos los tests
 */
async function runAllTests() {
  console.log('╔════════════════════════════════════════╗');
  console.log('║  DIAGNÓSTICO BACKEND → N8N             ║');
  console.log('╚════════════════════════════════════════╝');
  
  // Test de variables de entorno
  const envOk = checkEnvironmentVariables();
  
  if (!envOk) {
    console.log('\n⚠️  Faltan variables de entorno. Configúralas antes de continuar.');
    return;
  }
  
  // Test de conexión
  const connectionOk = await testN8NConnection();
  
  if (!connectionOk) {
    console.log('\n⚠️  No se pudo conectar con N8N. Verifica que el servicio esté corriendo.');
    return;
  }
  
  // Test de notificación simple
  await new Promise(resolve => setTimeout(resolve, 2000));
  await testConfirmacionNotification();
  
  // Test de notificación con adjuntos
  await new Promise(resolve => setTimeout(resolve, 2000));
  await testIncompletaWithAttachments();
  
  console.log('\n╔════════════════════════════════════════╗');
  console.log('║  DIAGNÓSTICO COMPLETADO                ║');
  console.log('╚════════════════════════════════════════╝');
  console.log('\n💡 Revisa tu email (davidbaezaospino@gmail.com) para ver si llegaron los correos de prueba.');
}

// Exportar funciones para uso en tu aplicación
module.exports = {
  testN8NConnection,
  testConfirmacionNotification,
  testIncompletaWithAttachments,
  validatePayloadFormat,
  checkEnvironmentVariables,
  runAllTests
};

// Si se ejecuta directamente desde consola
if (require.main === module) {
  runAllTests().catch(console.error);
}