def get_template(variant, name, confirm_link, unsubscribe_link, track_url=""):

    header = """
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
    <div style="border-bottom: 3px solid #0066cc; padding-bottom: 15px; margin-bottom: 25px;">
        <span style="font-size: 20px; font-weight: bold; color: #0066cc;">eDiscom</span>
    </div>
    """

    button1 = f'<div style="text-align: center; margin: 30px 0;"><a href="{confirm_link}" style="background-color: #2ecc71; color: white; padding: 14px 35px; text-decoration: none; border-radius: 4px; font-size: 15px; font-weight: bold;">Подтвердить подписку</a></div>'

    button2 = f'<div style="text-align: center; margin: 30px 0;"><a href="{confirm_link}" style="background-color: #2ecc71; color: white; padding: 14px 35px; text-decoration: none; border-radius: 4px; font-size: 15px; font-weight: bold;">Да, я хочу получать письма от eDiscom</a></div>'

    button3 = f'<div style="text-align: center; margin: 30px 0;"><a href="{confirm_link}" style="background-color: #2ecc71; color: white; padding: 14px 35px; text-decoration: none; border-radius: 4px; font-size: 15px; font-weight: bold;">Подтвердить - мне интересно</a></div>'

    nb_block = '<div style="background:#f8f9fa; padding:15px; border-radius:4px; margin: 20px 0; font-size:13px; color:#333;"><strong>NB:</strong> <a href="https://www.ediscom.ru" style="color:#0066cc; text-decoration:none;">eDiscom</a> занимается поставками телекоммуникационного оборудования Cisco, Huawei, Fortinet, Aruba, Juniper, Brocade, HPE, Dell и другие. Официально с ГТД. Сроки от 7 рабочих дней.</div>'

    footer = f'<hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;"><p style="color: #999; font-size: 11px; line-height: 1.6;">Если вы не запрашивали подписку - просто проигнорируйте это письмо.<br>Ссылка действительна 48 часов.<br><br>С уважением,<br><strong>Электронный секретарь</strong> (на базе OpenClaw)<br>Контроль и ответственность: Черенков Дмитрий Анатольевич<br>Отдел маркетинга, ООО "Едиском"<br><a href="https://www.ediscom.ru" style="color: #0066cc;">www.ediscom.ru</a> | тел: +7-495-710-71-02</p><p style="font-size: 11px;"><a href="{unsubscribe_link}" style="color: #999;">Отписаться от рассылки</a></p></body></html>'

    if variant == 1:
        body = f'<h2 style="color: #0066cc;">Подтверждение подписки</h2><p>Приветствую, {name}!</p><p>Вы давний клиент eDiscom, и мы ценим это. В связи с вступлением в силу обновлённых требований Федерального закона №152-ФЗ "О персональных данных" и изменениями в регулировании электронных рассылок, мы обязаны получить ваше явное согласие на продолжение информирования.</p><p>Если вы хотите по-прежнему получать от нас актуальные новости, специальные предложения и экспертные материалы по сетевой инфраструктуре - просто подтвердите подписку. Займёт одну секунду.</p>' + button1 + '<p style="color: #666; font-size: 13px;">Если не подтвердите - мы уважаем ваше решение и просто удалим адрес из базы. Без обид.</p>'

    elif variant == 2:
        body = f'<h2 style="color: #0066cc;">Подтверждение подписки</h2><p>Приветствую, {name}!</p><p>Мы в eDiscom давно и регулярно присылали вам письма - надеемся, они были полезны. Но времена меняются: новые требования к рассылкам обязывают нас получить ваше явное согласие, прежде чем продолжать.</p><p>Один клик - и всё останется как было: новости рынка телекоммуникаций, обзоры оборудования, специальные условия для постоянных клиентов.</p>' + button2 + '<p style="color: #666; font-size: 13px;">Не хотите - нажмите "Отписаться" ниже. Никаких вопросов.</p>'

    elif variant == 3:
        body = f'<h2 style="color: #0066cc;">Подтверждение подписки</h2><p>Приветствую, {name}!</p><p>Вы неоднократно получали наши письма и, надеемся, они были полезны. Мы ценим каждого клиента и хотим быть с вами на связи - но только если вы этого хотите.</p><p>В соответствии с актуальными требованиями законодательства о персональных данных просим вас подтвердить, что наши письма вам интересны.</p>' + button3 + '<p style="color: #666; font-size: 13px;">Спасибо, что были с нами. И надеемся, что останетесь.</p>'

    valli_block = (
        '<div style="background:#f0f7ff; padding:15px; border-radius:4px; margin: 20px 0; text-align:center;">'
        '<p style="margin:0 0 10px 0; font-size:14px; color:#333;">'
        'Узнайте цены на оборудование Cisco, Huawei, Fortinet мгновенно 🤖'
        '</p>'
        '<a href="https://t.me/Wally0526_bot?start=email_utm" '
        'style="background-color:#0066cc; color:white; padding:10px 25px; '
        'text-decoration:none; border-radius:4px; font-size:14px;">'
        'Спросить у Валли →'
        '</a>'
        '<p style="margin:10px 0 0 0; font-size:12px; color:#666;">🔒 Ваши запросы конфиденциальны</p>'
        '</div>'
    )

    pixel = (f'<img src="{track_url}" width="1" height="1" style="display:none" alt="">'
             if track_url else "")
    return header + body + nb_block + valli_block + footer.replace("</body></html>", pixel + "</body></html>")


def get_subject(variant):
    subjects = {
        1: "Подтвердите подписку на рассылку eDiscom",
        2: "Один клик - и мы остаёмся на связи",
        3: "Вы с нами? Подтвердите подписку"
    }
    return subjects[variant]


VALLI_INVITE_SUBJECT = "Специальное предложение для подписчиков eDiscom"

VALLI_BOT_URL = "https://t.me/Wally0526_bot"


def get_valli_invite_template(name, unsubscribe_link, track_url=""):
    header = """
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
    <div style="border-bottom: 3px solid #0066cc; padding-bottom: 15px; margin-bottom: 25px;">
        <span style="font-size: 20px; font-weight: bold; color: #0066cc;">eDiscom</span>
    </div>
    """

    button = (
        f'<div style="text-align: center; margin: 30px 0;">'
        f'<a href="{VALLI_BOT_URL}" style="background-color: #0066cc; color: white; '
        f'padding: 14px 35px; text-decoration: none; border-radius: 4px; '
        f'font-size: 15px; font-weight: bold;">Написать Валли</a></div>'
    )

    body = (
        f'<h2 style="color: #0066cc;">Для вас — кое-что особенное</h2>'
        f'<p>Здравствуйте, {name}!</p>'
        f'<p>Спасибо, что подтвердили подписку на рассылку eDiscom. Это важно для нас — '
        f'значит, вы цените то, о чём мы пишем.</p>'
        f'<p>Именно для таких клиентов у нас есть кое-что новое. '
        f'Знакомьтесь — <strong>Валли</strong>, наш робот-закупщик. '
        f'Он знает цены на сетевое оборудование, умеет искать по артикулам и '
        f'отвечает быстрее любого менеджера.</p>'
        f'<p>И да — у Валли есть <strong>предложение, от которого сложно отказаться</strong>. '
        f'Но узнать о нём можно только лично.</p>'
        + button +
        f'<p style="color: #666; font-size: 13px;">'
        f'Валли работает в Telegram. Просто напишите ему артикул или модель оборудования — '
        f'и он всё найдёт.</p>'
    )

    nb_block = (
        '<div style="background:#f8f9fa; padding:15px; border-radius:4px; margin: 20px 0; '
        'font-size:13px; color:#333;"><strong>NB:</strong> '
        '<a href="https://www.ediscom.ru" style="color:#0066cc; text-decoration:none;">eDiscom</a> '
        '— дистрибьютор сетевого оборудования Cisco, Huawei, Fortinet, Aruba, HPE и других брендов. '
        'Официально, с ГТД, сроки от 7 рабочих дней.</div>'
    )

    pixel = (
        f'<img src="{track_url}" width="1" height="1" style="display:none" alt="">'
        if track_url else ""
    )

    footer = (
        f'<hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">'
        f'<p style="color: #999; font-size: 11px; line-height: 1.6;">'
        f'С уважением,<br>'
        f'<strong>Черенков Дмитрий</strong><br>'
        f'Отдел маркетинга, ООО «Едиском»<br>'
        f'<a href="https://www.ediscom.ru" style="color:#0066cc;">www.ediscom.ru</a> '
        f'| тел: +7-495-710-71-02</p>'
        f'<p style="font-size: 11px;">'
        f'<a href="{unsubscribe_link}" style="color: #999;">Отписаться от рассылки</a></p>'
        f'{pixel}</body></html>'
    )

    return header + body + nb_block + footer
