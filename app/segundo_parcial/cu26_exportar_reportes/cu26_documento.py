"""Branded, paginated business reports; no remote assets or executable HTML.

Layout uses ReportLab Platypus: https://docs.reportlab.com/reportlab/userguide/ch5_platypus/
"""
from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape
import re
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, LongTable
from reportlab.pdfbase.pdfmetrics import stringWidth

INK=colors.HexColor('#181818')
LIME=colors.HexColor('#DFFF4F')
PAPER=colors.HexColor('#FFFDF5')
MUTED=colors.HexColor('#64645A')
LINE=colors.HexColor('#D5D4C8')
WIDTH=A4[0]-88


def clean(value):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(value))


def inline(value):
    value=escape(clean(value))
    value=re.sub(r'\*\*([^*\n]+)\*\*',r'<b>\1</b>',value)
    value=re.sub(r'`([^`\n]+)`',r'<font name="Courier">\1</font>',value)
    return value.replace('\n','<br/>')


def report_document(report, query, report_id):
    data=report['datos'];out=BytesIO()
    styles={
        'body':ParagraphStyle('body',fontName='Helvetica',fontSize=10,leading=15,textColor=INK,spaceAfter=9,splitLongWords=True),
        'title':ParagraphStyle('title',fontName='Helvetica-Bold',fontSize=27,leading=31,textColor=INK,spaceAfter=16),
        'heading':ParagraphStyle('heading',fontName='Helvetica-Bold',fontSize=16,leading=21,textColor=INK,spaceBefore=16,spaceAfter=10,keepWithNext=True),
        'small':ParagraphStyle('small',fontName='Helvetica',fontSize=8,leading=12,textColor=MUTED,spaceAfter=8),
        'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=9,leading=14,textColor=INK),
        'label':ParagraphStyle('label',fontName='Helvetica-Bold',fontSize=8,leading=12,textColor=INK,spaceAfter=8,keepWithNext=True),
        'number':ParagraphStyle('number',fontName='Helvetica-Bold',fontSize=23,leading=28,textColor=INK,spaceAfter=6),
    }
    def p(value,style='body'):return Paragraph(inline(value),styles[style])
    def table(rows,widths,header=True):
        result=LongTable([[p(v,'cell') for v in row] for row in rows],colWidths=widths,repeatRows=1 if header else 0,hAlign='LEFT',splitByRow=1,splitInRow=1)
        rules=[('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),.4,LINE)]
        if header:rules.extend([('BACKGROUND',(0,0),(-1,0),LIME),('LINEBELOW',(0,0),(-1,0),.8,INK)])
        result.setStyle(TableStyle(rules));return result
    def analysis(text):
        lines=clean(text).splitlines();result=[];i=0;paragraph=[]
        def flush():
            if paragraph:result.append(p(' '.join(paragraph)));paragraph.clear()
        while i<len(lines):
            line=lines[i].strip()
            if '|' in line and i+1<len(lines) and re.match(r'^\s*\|?\s*:?-{2,}',lines[i+1]):
                flush();rows=[[v.strip() for v in line.strip('|').split('|')]];i+=2
                while i<len(lines) and '|' in lines[i] and lines[i].strip():
                    rows.append([v.strip() for v in lines[i].strip().strip('|').split('|')]);i+=1
                count=max(len(row) for row in rows)
                rows=[row+['']*(count-len(row)) for row in rows]
                if count<=6:result.extend([table(rows,[WIDTH/count]*count),Spacer(1,12)])
                else:result.extend(p(' | '.join(row)) for row in rows)
                continue
            heading=re.match(r'^#{1,6}\s+(.+)$',line)
            bullet=re.match(r'^(?:[-*•]|\d+[.)])\s+(.+)$',line)
            if heading:flush();result.append(p(heading.group(1),'heading'))
            elif bullet:flush();result.append(p('— '+bullet.group(1)))
            elif not line:flush()
            else:paragraph.append(line)
            i+=1
        flush();return result
    def page(canvas,document):
        canvas.saveState();w,h=A4
        canvas.setFillColor(PAPER);canvas.rect(0,0,w,h,fill=1,stroke=0)
        canvas.setFillColor(INK);canvas.setFont('Helvetica-Bold',11)
        company=clean(data['empresa'])
        while canvas.stringWidth(company,'Helvetica-Bold',11)>WIDTH-100:company=company[:-2]+'…'
        canvas.drawString(44,h-39,company)
        canvas.setFont('Helvetica',8);canvas.drawRightString(w-44,h-38,f'INFORME #{report_id}')
        canvas.setStrokeColor(INK);canvas.setLineWidth(1);canvas.line(44,h-50,w-44,h-50)
        canvas.line(44,44,w-44,44);canvas.setFont('Helvetica-Bold',9);canvas.drawString(44,28,'DrapeMind.')
        canvas.setFont('Helvetica',8);canvas.drawRightString(w-44,28,f'Página {document.page}')
        canvas.restoreState()
    money=f"{Decimal(str(data['ingreso_neto_cobrado'])):,.2f}"
    metrics=[]
    for label,value,note in [
        ('INGRESO NETO COBRADO','Bs '+money,'Cobros del periodo'),
        ('PEDIDOS PAGADOS',data['pedidos_pagados'],'Pedidos del periodo'),
        ('STOCK DISPONIBLE',data['inventario_actual']['unidades_disponibles'],'Existencias actuales'),
    ]:
        size=min(23,23*(WIDTH/3-24)/max(1,stringWidth(str(value),'Helvetica-Bold',23)))
        number=Paragraph(inline(value),ParagraphStyle('metric',parent=styles['number'],fontSize=max(10,size),leading=max(14,size+5)))
        metrics.append([p(label,'label'),number,p(note,'small')])
    summary=Table([metrics],colWidths=[WIDTH/3]*3,hAlign='LEFT')
    summary.setStyle(TableStyle([('BACKGROUND',(0,0),(0,0),LIME),('BOX',(0,0),(-1,-1),.8,INK),('INNERGRID',(0,0),(-1,-1),.4,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),14),('BOTTOMPADDING',(0,0),(-1,-1),10)]))
    story=[p('REPORTE EMPRESARIAL','small'),p(report['titulo'],'title'),p(f"{data['desde']} a {data['hasta']} · {data['sucursal']}",'small'),Spacer(1,12),summary,Spacer(1,18),p('TU CONSULTA','label'),p(query),p('01 / Lo que dicen tus datos','heading'),*analysis(report['analisis']),p('02 / Prendas en pedidos pagados','heading')]
    products=data.get('prendas_vendidas',[])
    story.append(table([['Prenda','Unidades'],*[[row['nombre'],row['cantidad']] for row in products]],[WIDTH-70,70]) if products else p('No hubo prendas en pedidos pagados durante este periodo.','small'))
    story.append(p('03 / Acciones sugeridas','heading'))
    story.extend(p(f'{i:02d}. {action}') for i,action in enumerate(report.get('recomendaciones',[]),1))
    story.extend([Spacer(1,20),p('ALCANCE DE LOS DATOS','label'),p(data.get('alcance',''),'small')])
    doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=44,rightMargin=44,topMargin=76,bottomMargin=64,title=clean(report['titulo']),author=clean(data['empresa']),pageCompression=1)
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return out.getvalue()
