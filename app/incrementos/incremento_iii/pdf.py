"""Paginated PDFs with standard fonts and no remote images or HTML execution."""
import textwrap

def document(title,lines):
    wrapped=[]
    for line in [title,'',*lines]:
        wrapped.extend(textwrap.wrap(str(line),width=92,replace_whitespace=False) or [''])
    pages=[wrapped[i:i+46] for i in range(0,len(wrapped),46)] or [[]]
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    kids=[]
    for i,rows in enumerate(pages):
        page_id=len(objects)+1;stream_id=page_id+1;kids.append(f'{page_id} 0 R')
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>'.encode())
        def escape(s):return s.encode('cp1252','replace').replace(b'\\',b'\\\\').replace(b'(',b'\\(').replace(b')',b'\\)')
        commands=[b'BT /F1 10 Tf 42 795 Td 15 TL']
        for row in rows:commands.extend([b'('+escape(row)+b') Tj',b'T*'])
        commands.extend([b'ET',b'BT /F1 9 Tf 42 30 Td ('+escape(f'DrapeMind | Página {i+1} de {len(pages)}')+b') Tj ET'])
        stream=b'\n'.join(commands);objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    objects[1]=f'<< /Type /Pages /Count {len(kids)} /Kids [{" ".join(kids)}] >>'.encode()
    output=bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(output));output.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref=len(output);output.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(output)
