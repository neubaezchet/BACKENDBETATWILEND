"""
Códigos de Checks Disponibles para el Sistema de Validación
IncaNeurobaeza - 2024
"""

# Diccionario completo de checks disponibles
CHECKS_DISPONIBLES = {
    # ========== DOCUMENTOS FALTANTES ==========
    'incapacidad_faltante': {
        'label': 'Falta soporte de incapacidad',
        'descripcion': 'Falta el soporte original de incapacidad emitido por la EPS o ARL. Verifique que sea oficial, completo y legible.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'epicrisis_faltante': {
        'label': 'Falta epicrisis/resumen',
        'descripcion': 'Falta la epicrisis o resumen clínico. Si no cuenta con este soporte, debe acercarse al punto de atención de su EPS para solicitarlo completo.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'epicrisis_incompleta': {
        'label': 'Epicrisis incompleta',
        'descripcion': 'La epicrisis o resumen clínico está incompleta. Debe adjuntar todas las páginas que indique el documento.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'soat_faltante': {
        'label': 'Falta SOAT',
        'descripcion': 'Falta el SOAT del vehículo. Si el vehículo fue identificado, debe adjuntar el documento vigente y completamente visible.',
        'aplica_tipos': ['Accidente de Tránsito']
    },
    'furips_faltante': {
        'label': 'Falta FURIPS',
        'descripcion': 'Falta el FURIPS (Formato Único de Reporte de Accidente). Debe incluirlo completo y legible.',
        'aplica_tipos': ['Accidente de Tránsito']
    },
    'licencia_maternidad_faltante': {
        'label': 'Falta licencia maternidad',
        'descripcion': 'Falta la licencia de maternidad de la madre emitida por la EPS. Debe incluir el documento completo y legible.',
        'aplica_tipos': ['Paternidad']
    },
    'registro_civil_faltante': {
        'label': 'Falta registro civil',
        'descripcion': 'Falta el registro civil del bebé. Debe adjuntar una copia completa, clara y legible.',
        'aplica_tipos': ['Maternidad', 'Paternidad']
    },
    'nacido_vivo_faltante': {
        'label': 'Falta certificado nacido vivo',
        'descripcion': 'Falta el certificado de nacido vivo. Debe incluir el documento completo, legible y original.',
        'aplica_tipos': ['Maternidad', 'Paternidad']
    },
    'cedula_padre_faltante': {
        'label': 'Falta cédula del padre',
        'descripcion': 'Falta la cédula del padre (ambas caras). Debe asegurarse de que sea visible, sin recortes y con buena calidad.',
        'aplica_tipos': ['Paternidad']
    },
    
    # ========== PROBLEMAS DE LEGIBILIDAD ==========
    'ilegible_recortada': {
        'label': 'Documento recortado',
        'descripcion': 'Los soportes se encuentran incompletos o recortados. Asegúrese de que todos los bordes del documento sean visibles y no haya partes cortadas.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'ilegible_borrosa': {
        'label': 'Documento borroso',
        'descripcion': 'Los soportes están borrosos o con baja calidad. Se deben tomar fotos claras, legibles y con buena iluminación.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'ilegible_manchada': {
        'label': 'Documento manchado/con reflejos',
        'descripcion': 'El documento presenta manchas o reflejos que impiden su lectura. Debe volver a adjuntarlo limpio, claro y legible.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    
    # ========== OBSERVACIONES GENERALES ==========
    'incompleta_general': {
        'label': 'Soportes incompletos (general)',
        'descripcion': 'Los soportes se encuentran incompletos o no cumplen los requisitos. Debe verificar que todos los documentos estén claros, completos y sin recortes.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'ilegible_general': {
        'label': 'Problemas de calidad (general)',
        'descripcion': 'Los soportes presentan problemas de calidad o legibilidad. Se deben volver a cargar en formato claro, completo y con buena resolución.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'faltante_general': {
        'label': 'Documentos faltantes (general)',
        'descripcion': 'Se identificó que faltan documentos obligatorios para este tipo de incapacidad. Adjunte nuevamente los soportes faltantes.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'solicitar_en_punto': {
        'label': 'Solicitar en punto de atención',
        'descripcion': 'Si no cuenta con el documento requerido, debe acercarse al punto de atención de su EPS y solicitarlo directamente.',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    
    # ========== PARA TALENTO HUMANO ==========
    'solicitar_epicrisis_tthh': {
        'label': 'Solicitar epicrisis a colaboradora',
        'descripcion': 'TTHH debe solicitar directamente la epicrisis',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
    'solicitar_transcripcion_tthh': {
        'label': 'Solicitar transcripción EPS',
        'descripcion': 'TTHH debe solicitar que se transcriba en la EPS',
        'aplica_tipos': ['Maternidad', 'Paternidad', 'Accidente de Tránsito', 'Enfermedad General', 'Enfermedad Laboral']
    },
}

def obtener_checks_por_tipo(tipo_incapacidad):
    """
    Retorna solo los checks que aplican para un tipo de incapacidad específico
    
    Args:
        tipo_incapacidad (str): Tipo de incapacidad
        
    Returns:
        dict: Diccionario con los checks aplicables
    """
    return {
        key: value for key, value in CHECKS_DISPONIBLES.items()
        if tipo_incapacidad in value['aplica_tipos']
    }

def obtener_checks_documentos(tipo_incapacidad):
    """Retorna solo checks relacionados con documentos faltantes"""
    checks = obtener_checks_por_tipo(tipo_incapacidad)
    return {k: v for k, v in checks.items() 
            if 'faltante' in k or 'incompleta' in k}

def obtener_checks_legibilidad(tipo_incapacidad):
    """Retorna solo checks relacionados con legibilidad"""
    checks = obtener_checks_por_tipo(tipo_incapacidad)
    return {k: v for k, v in checks.items() if 'ilegible' in k}

def obtener_checks_tthh(tipo_incapacidad):
    """Retorna solo checks para Talento Humano"""
    checks = obtener_checks_por_tipo(tipo_incapacidad)
    return {k: v for k, v in checks.items() if 'tthh' in k}

def obtener_checks_generales(tipo_incapacidad):
    """Retorna solo checks generales"""
    checks = obtener_checks_por_tipo(tipo_incapacidad)
    return {k: v for k, v in checks.items() if 'general' in k or 'solicitar_en_punto' in k}