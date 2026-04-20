-- ═══════════════════════════════════════════════════════════════════════════════
-- FIX CC EMAILS: Verificar y reparar configuración de copia en notificaciones
-- ═══════════════════════════════════════════════════════════════════════════════

-- 1️⃣ VERIFICAR: Empleados sin correo en BD
-- ═══════════════════════════════════════════════════════════════════════════════
SELECT 
    COUNT(*) as total_sin_correo,
    cedula,
    nombre,
    empresa_id
FROM employees
WHERE correo IS NULL OR correo = ''
GROUP BY empresa_id
ORDER BY COUNT(*) DESC;

-- Ejemplo para ver empleados sin correo:
SELECT cedula, nombre, correo, empresa_id FROM employees 
WHERE correo IS NULL OR correo = '' 
LIMIT 20;

-- ─────────────────────────────────────────────────────────────────────────────

-- 2️⃣ VERIFICAR: Qué empresas tienen emails en el directorio
-- ─────────────────────────────────────────────────────────────────────────────
SELECT 
    COALESCE(c.id, 'NULL') as company_id,
    COALESCE(c.nombre, 'GENERAL') as empresa,
    COUNT(*) as cantidad_emails,
    GROUP_CONCAT(cn.email SEPARATOR ', ') as emails
FROM correos_notificacion cn
LEFT JOIN companies c ON cn.company_id = c.id
WHERE cn.area = 'empresas' AND cn.activo = 1
GROUP BY company_id, empresa;

-- ─────────────────────────────────────────────────────────────────────────────

-- 3️⃣ VERIFICAR: Empresas SIN emails en directorio
-- ─────────────────────────────────────────────────────────────────────────────
SELECT 
    c.id,
    c.nombre,
    COUNT(e.id) as empleados_sin_notif,
    c.email_copia
FROM companies c
LEFT JOIN employees e ON e.empresa_id = c.id
WHERE c.id NOT IN (
    SELECT DISTINCT company_id FROM correos_notificacion 
    WHERE area = 'empresas' AND company_id IS NOT NULL AND activo = 1
)
GROUP BY c.id
ORDER BY COUNT(e.id) DESC;

-- ═══════════════════════════════════════════════════════════════════════════════
-- SOLUCIÓN: Agregar emails faltantes
-- ═══════════════════════════════════════════════════════════════════════════════

-- OPCIÓN A: Usar email_copia de companies como fallback
-- Si cada empresa tiene email_copia configurado, se puede usar como CC

-- OPCIÓN B: Poblar directorio correos_notificacion manualmente
-- Agregar un email CC para cada empresa:
-- INSERT INTO correos_notificacion (email, area, company_id, activo, created_at, updated_at)
-- VALUES ('soporte@incaneurobaeza.com', 'empresas', 14, 1, NOW(), NOW());

-- Ejemplo completo para la empresa del empleado 1085043374:
-- 1. Primero obtener company_id:
SELECT DISTINCT c.id, c.nombre, c.email_copia
FROM employees e
JOIN companies c ON e.empresa_id = c.id
WHERE e.cedula = '1085043374';

-- 2. Luego agregar email al directorio si no existe:
-- INSERT INTO correos_notificacion (email, area, company_id, activo, created_at, updated_at)
-- VALUES ('hr@empresa.com', 'empresas', 14, 1, NOW(), NOW())
-- WHERE NOT EXISTS (SELECT 1 FROM correos_notificacion 
--                   WHERE email = 'hr@empresa.com' AND company_id = 14);

-- ═══════════════════════════════════════════════════════════════════════════════
-- OPCIÓN DE FALLBACK: Si email_copia existe en companies, usarlo como CC
-- ═══════════════════════════════════════════════════════════════════════════════
-- Esta es una corrección temporal si no hay emails en correos_notificacion

SELECT 
    c.id,
    c.nombre,
    c.email_copia,
    COUNT(e.id) as empleados,
    COUNT(DISTINCT cn.id) as emails_directorio
FROM companies c
LEFT JOIN employees e ON e.empresa_id = c.id
LEFT JOIN correos_notificacion cn ON cn.company_id = c.id AND cn.area = 'empresas' AND cn.activo = 1
WHERE c.activa = 1
GROUP BY c.id, c.nombre, c.email_copia
HAVING COUNT(DISTINCT cn.id) = 0 AND c.email_copia IS NOT NULL;

