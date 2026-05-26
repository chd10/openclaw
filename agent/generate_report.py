import json
import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

DATA_FILE = "/data/confirmations.json"
REPORT_DIR = "/data/reports"

# Регистрируем шрифт с кириллицей
pdfmetrics.registerFont(TTFont('DejaVu', '/app/DejaVuSans.ttf'))

def generate_report():
    os.makedirs(REPORT_DIR, exist_ok=True)
    
    with open(DATA_FILE) as f:
        db = json.load(f)
    
    confirmed = {k: v for k, v in db.items() if v.get("status") == "confirmed"}
    
    filename = f"{REPORT_DIR}/consent_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4,
                           rightMargin=2*cm, leftMargin=2*cm,
                           topMargin=2*cm, bottomMargin=2*cm)
    
    styles = getSampleStyleSheet()
    
    normal = ParagraphStyle('Normal_', fontName='DejaVu', fontSize=10, spaceAfter=6)
    title = ParagraphStyle('Title_', fontName='DejaVu', fontSize=16, spaceAfter=20, alignment=1)
    bold = ParagraphStyle('Bold_', fontName='DejaVu', fontSize=10, spaceAfter=6)
    small = ParagraphStyle('Small_', fontName='DejaVu', fontSize=9, textColor=colors.grey)

    story = []
    
    story.append(Paragraph("Реестр согласий на получение электронной рассылки", title))
    story.append(Paragraph("ООО «Едиском» | eDiscom Network Technologies", normal))
    story.append(Spacer(1, 0.5*cm))
    
    info_data = [
        ["Организация:", "ООО «Едиском»"],
        ["ИНН/КПП:", "9715324641 / 771501001"],
        ["Адрес:", "127549, г. Москва, ул. Бибиревская, д.10, к.1, оф.902Б"],
        ["Дата формирования:", datetime.now().strftime("%d.%m.%Y %H:%M")],
        ["Всего подтверждений:", str(len(confirmed))],
        ["Ответственный:", "Черенков Дмитрий Анатольевич"],
    ]
    
    info_table = Table(info_data, colWidths=[5*cm, 12*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 0.5*cm))
    
    story.append(Paragraph(
        "Настоящий реестр подтверждает, что указанные ниже адреса электронной почты "
        "дали явное согласие на получение информационной рассылки от ООО «Едиском» "
        "путём перехода по персональной ссылке подтверждения, направленной на их "
        "электронный адрес. Согласие получено в соответствии с требованиями "
        "Федерального закона №152-ФЗ «О персональных данных».",
        normal
    ))
    story.append(Spacer(1, 0.5*cm))
    
    table_data = [["#", "Email", "Дата подтверждения", "IP адрес", "Источник"]]
    
    for i, (email, data) in enumerate(sorted(confirmed.items(),
                                              key=lambda x: x[1].get("date", "")), 1):
        table_data.append([
            str(i),
            email,
            data.get("date", "")[:19],
            data.get("ip", "н/д"),
            data.get("source", "email_confirmation")
        ])
    
    col_widths = [1*cm, 6*cm, 4.5*cm, 3.5*cm, 3*cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0066cc')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'DejaVu'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f5f5')]),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(table)
    story.append(Spacer(1, 1*cm))
    
    story.append(Paragraph("Ответственный за рассылку:", normal))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("_______________________  Черенков Д.А.", normal))
    story.append(Paragraph(f"Дата: {datetime.now().strftime('%d.%m.%Y')}", normal))
    
    doc.build(story)
    print(f"Отчёт сохранён: {filename}")
    return filename

if __name__ == "__main__":
    generate_report()
