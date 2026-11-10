from copy import deepcopy
from app.segundo_parcial.cu26_exportar_reportes.cu26_documento import report_document

REPORT={'titulo':'Balance de la colección','analisis':'## Ventas del periodo\n\nLas prendas **más vendidas** mantienen su disponibilidad.\n\n| Prenda | Unidades |\n|---|---|\n| Camisa | 14 |',
 'recomendaciones':['Revisar las tallas de mayor salida.'],
 'datos':{'empresa':'Moda Oriente','desde':'2026-11-01','hasta':'2026-11-10','sucursal':'Todas las sucursales','pedidos_pagados':12,'ingreso_neto_cobrado':'1250.50','inventario_actual':{'unidades_disponibles':84,'variantes_con_stock_bajo':3},'prendas_vendidas':[{'nombre':'Camisa de algodón','cantidad':14}], 'alcance':'Cobros confirmados del periodo. El inventario corresponde al momento de la consulta.'}}

def test_branded_report_preserves_unicode_and_handles_long_content():
    report=deepcopy(REPORT)
    report['analisis']='\n\n'.join([REPORT['analisis']]*35)+'\n\n<img src="https://invalid.example/image.png"/> <script>alert(1)</script>'
    report['datos']['empresa']='Empresa con un nombre extenso para comprobar el encabezado '+('regional '*20)
    report['datos']['ingreso_neto_cobrado']='1234567890.12'
    report['datos']['prendas_vendidas']=[{'nombre':f'Prenda {i} con descripción y talla M','cantidad':i+1} for i in range(75)]
    result=report_document(report,'Analiza las ventas, prendas y stock de mi tienda.',71)
    assert result.startswith(b'%PDF-') and result.rstrip().endswith(b'%%EOF')
    assert b'/Subtype /Image' not in result # Untrusted report HTML cannot fetch a remote asset.
    assert b'/Helvetica-Bold' in result and b'/Count 1 ' not in result

def test_empty_sales_report_is_valid_without_inventing_rows():
    report=deepcopy(REPORT);report['datos']['prendas_vendidas']=[]
    report['datos']['ingreso_neto_cobrado']='0.00';report['datos']['pedidos_pagados']=0
    result=report_document(report,'Consulta los cobros del día.',72)
    assert result.startswith(b'%PDF-') and len(result)>1000
