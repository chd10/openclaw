import os
import json
import requests
import anthropic
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from main import send_email, generate_email_text, save_to_sent

BOT_TOKEN = os.getenv("BOT_TOKEN")
STATS_URL = "http://localhost:5000/stats"
PAUSE_FLAG = "/data/paused"
CAMPAIGN_PROGRESS_FILE = "/data/campaign_progress.json"
CONFIRMATIONS_FILE = "/data/confirmations.json"
TOTAL_CONTACTS = 2820
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ALLOWED_USERS = [40603594]  # MANAGER_CHAT_ID


def manager_only(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.message.reply_text("Доступ запрещён.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def manager_only_callback(func):
    from functools import wraps
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id not in ALLOWED_USERS:
            await update.callback_query.answer("Доступ запрещён.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

user_data = {}
chat_history = {}

@manager_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📧 Новая рассылка", callback_data="new")],
        [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton("📋 База контактов", callback_data="contacts")],
        [InlineKeyboardButton("⚙️ Настройки письма", callback_data="settings")],
    ]
    await update.message.reply_text(
        "👋 Добро пожаловать в OpenClaw!\n\n"
        "Выберите действие или просто напишите что нужно сделать.\n\n"
        "Примеры:\n"
        "- отправь письмо на ivan@mail.ru Ивану\n"
        "- покажи статистику\n"
        "- когда следующая рассылка?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

@manager_only
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text

    if uid not in chat_history:
        chat_history[uid] = []
    if uid not in user_data:
        user_data[uid] = {"tone": "официальный", "context": "сетевое оборудование и телекоммуникации"}

    chat_history[uid].append({"role": "user", "content": text})

    try:
        r = requests.get(STATS_URL, timeout=3).json()
        stats_text = f"confirmed={r['confirmed']}, unsubscribed={r['unsubscribed']}, total={r['total']}"
    except:
        stats_text = "недоступна"

    system = (
        f"Тебя зовут Эва. Ты ассистент проекта OpenClaw — системы email-рассылок и работы с базой ООО «Едиском».\n"
        f"Сегодняшняя дата: {__import__('datetime').datetime.now().strftime('%d.%m.%Y')}. Используй её при ответах на вопросы о датах — не выдумывай даты.\n"
        "Ты управляешь рассылками и отвечаешь на вопросы по проекту OpenClaw. "
        "Не упоминай праздники, выходные или нерабочие дни, если они явно не заданы в расписании (schedule.json).\n"
        "\n"
        "История проекта OpenClaw:\n"
        "- OpenClaw создан для ООО «Едиском» (сетевое оборудование и телекоммуникации), чтобы автоматизировать "
        "переписку с базой контактов и реактивацию ушедших клиентов.\n"
        "- В системе две независимые рассылки, Telegram-бот для управления (это ты), Flask web-сервис "
        "(подтверждения/отписки на /confirm и /unsubscribe), генерация PDF-отчёта о согласиях и cron-планировщик.\n"
        "- Прогресс сохраняется в JSON-файлах в /data: campaign_progress.json, reactivation_progress.json, "
        "confirmations.json, schedule.json.\n"
        "\n"
        "Рассылка №1 — основная кампания:\n"
        "- База: export_20260511_Актив.xlsx, 2820 контактов.\n"
        "- Расписание по умолчанию: каждый день в 10:00, 50 писем.\n"
        "- Отправитель: SMTP mail.privateemail.com:587 (учётка SMTP_USER/SMTP_PASS).\n"
        "- Код: campaign.py, прогресс в campaign_progress.json.\n"
        "- Шаблоны: templates.py, три варианта чередуются автоматически (счётчик в main.py: 1→2→3→1→…), "
        "выбираются на каждое письмо в send_email() через next_variant().\n"
        "\n"
        "Точное содержание шаблонов основной рассылки (используй для превью; {name} подставляется автоматически):\n"
        "\n"
        "Вариант 1\n"
        "  Тема: «Подтвердите подписку на рассылку eDiscom»\n"
        "  Заголовок в письме: «Подтверждение подписки»\n"
        "  Приветствие: «Приветствую, {name}!»\n"
        "  Текст: «Вы давний клиент eDiscom, и мы ценим это. В связи с вступлением в силу обновлённых "
        "требований Федерального закона №152-ФЗ \"О персональных данных\" и изменениями в регулировании "
        "электронных рассылок, мы обязаны получить ваше явное согласие на продолжение информирования. "
        "Если вы хотите по-прежнему получать от нас актуальные новости, специальные предложения и "
        "экспертные материалы по сетевой инфраструктуре — просто подтвердите подписку. Займёт одну секунду.»\n"
        "  Кнопка: «Подтвердить подписку»\n"
        "  Постскриптум: «Если не подтвердите — мы уважаем ваше решение и просто удалим адрес из базы. Без обид.»\n"
        "\n"
        "Вариант 2\n"
        "  Тема: «Один клик - и мы остаёмся на связи»\n"
        "  Заголовок в письме: «Подтверждение подписки»\n"
        "  Приветствие: «Приветствую, {name}!»\n"
        "  Текст: «Мы в eDiscom давно и регулярно присылали вам письма — надеемся, они были полезны. Но "
        "времена меняются: новые требования к рассылкам обязывают нас получить ваше явное согласие, "
        "прежде чем продолжать. Один клик — и всё останется как было: новости рынка телекоммуникаций, "
        "обзоры оборудования, специальные условия для постоянных клиентов.»\n"
        "  Кнопка: «Да, я хочу получать письма от eDiscom»\n"
        "  Постскриптум: «Не хотите — нажмите \"Отписаться\" ниже. Никаких вопросов.»\n"
        "\n"
        "Вариант 3\n"
        "  Тема: «Вы с нами? Подтвердите подписку»\n"
        "  Заголовок в письме: «Подтверждение подписки»\n"
        "  Приветствие: «Приветствую, {name}!»\n"
        "  Текст: «Вы неоднократно получали наши письма и, надеемся, они были полезны. Мы ценим каждого "
        "клиента и хотим быть с вами на связи — но только если вы этого хотите. В соответствии с "
        "актуальными требованиями законодательства о персональных данных просим вас подтвердить, что "
        "наши письма вам интересны.»\n"
        "  Кнопка: «Подтвердить - мне интересно»\n"
        "  Постскриптум: «Спасибо, что были с нами. И надеемся, что останетесь.»\n"
        "\n"
        "Общие элементы всех трёх шаблонов:\n"
        "  NB-блок: «eDiscom занимается поставками телекоммуникационного оборудования Cisco, Huawei, "
        "Fortinet, Aruba, Juniper, Brocade, HPE, Dell и другие. Официально с ГТД. Сроки от 7 рабочих дней.»\n"
        "  Подпись: «Электронный секретарь (на базе OpenClaw). Контроль и ответственность: Черенков "
        "Дмитрий Анатольевич, отдел маркетинга, ООО \"Едиском\". www.ediscom.ru, тел: +7-495-710-71-02.»\n"
        "  Внизу — ссылка «Отписаться от рассылки». Ссылка подтверждения действительна 48 часов.\n"
        "\n"
        "Рассылка №2 — реактивация:\n"
        "- Отправитель: newsletter@ediscom.ru через Яндекс SMTP (smtp.yandex.ru:465 SSL, "
        "переменные SMTP_EDISCOM_USER/SMTP_EDISCOM_PASS).\n"
        "- Расписание: 10:30, 11:30, 12:30 — по 10 писем (итого 30/день).\n"
        "- Контакты подтягиваются из Битрикс24, прогресс в reactivation_progress.json.\n"
        "- Код: reactivation_campaign.py.\n"
        "\n"
        "Интеграция с Битрикс24:\n"
        "- Вебхук задаётся переменной окружения BITRIX_WEBHOOK в .env.\n"
        "- Используется для выборки контактов и лидов (crm.contact.list, crm.lead.list, "
        "crm.lead.productrows.get) при формировании списка для реактивации.\n"
        "\n"
        f"Настройки текущего пользователя: тон={user_data[uid]['tone']}, контекст={user_data[uid]['context']}\n"
        f"Текущая статистика подтверждений/отписок: {stats_text}\n"
        "\n"
        "Команды бота: /start, /send, /pause, /resume, /report, /schedule, /reactivation_stats, "
        "/daily_report, /campaign_progress, /week_report, /last_send, /email_log, /export_log, "
        "/client, /send_valli_invite.\n"
        "/email_log — последние 10 записей лога отправок (email, тема, кампания, статус доставки/открытия/ответа).\n"
        "/export_log — отправляет CSV файл с полным логом отправок в Telegram.\n"
        "\n"
        "Маппинг фраз на действия (используй строго):\n"
        "«отчёт за сегодня» / «дневной отчёт» / «итоги дня» / «что сегодня» / «покажи отчёт» → daily_report\n"
        "«статистика» / «общая статистика» / «сколько подтверждений» → stats\n"
        "«прогресс кампании» / «сколько осталось» / «прогресс рассылки» → campaign_progress\n"
        "«отчёт за неделю» / «недельная статистика» / «за 7 дней» → week_report\n"
        "«отправь приглашение валли» / «разошли валли» / «инвайт валли» → send_valli_invite\n"
        "«история клиента [email]» / «покажи клиента [email]» / «кто такой [email]» → client с email\n"
        "\n"
        "Действия через JSON (только если пользователь явно просит выполнить действие):\n"
        'send: {"action":"send","email":"...","name":"..."}\n'
        'stats: {"action":"stats"}\n'
        'daily_report: {"action":"daily_report"}\n'
        'campaign_progress: {"action":"campaign_progress"}\n'
        'week_report: {"action":"week_report"}\n'
        'send_valli_invite: {"action":"send_valli_invite"}\n'
        'client: {"action":"client","email":"..."}\n'
        'set_tone: {"action":"set_tone","tone":"..."}\n'
        'set_context: {"action":"set_context","context":"..."}\n'
        'preview: {"action":"preview","name":"...","context":"..."}\n'
        "Если нужно действие — отвечай ТОЛЬКО JSON. Если это вопрос/обсуждение — отвечай текстом от лица Эвы."
    )

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=500,
        system=system,
        messages=chat_history[uid]
    )

    reply = response.content[0].text
    chat_history[uid].append({"role": "assistant", "content": reply})

    try:
        reply_clean = reply.strip().replace("```json", "").replace("```", "").strip()
        data = json.loads(reply_clean)
        action = data.get("action")

        if action == "send":
            email = data.get("email")
            name = data.get("name", "Клиент")
            await update.message.reply_text(f"⏳ Отправляю письмо на {email}...")
            token, msg = send_email(email, name)
            save_to_sent(msg)
            await update.message.reply_text(f"✅ Письмо отправлено на {email}!")

        elif action == "stats":
            r = requests.get(STATS_URL, timeout=5).json()
            await update.message.reply_text(
                f"📊 Статистика:\n\n"
                f"📧 Всего: {r['total']}\n"
                f"✅ Подтверждено: {r['confirmed']}\n"
                f"❌ Отписались: {r['unsubscribed']}\n"
                f"⏳ Ожидают: {r['total'] - r['confirmed'] - r['unsubscribed']}"
            )

        elif action == "set_tone":
            user_data[uid]["tone"] = data.get("tone")
            await update.message.reply_text(f"✅ Тон изменён: {data.get('tone')}")

        elif action == "set_context":
            user_data[uid]["context"] = data.get("context")
            await update.message.reply_text(f"✅ Контекст сохранён: {data.get('context')}")

        elif action == "daily_report":
            await daily_report_command(update, context)

        elif action == "campaign_progress":
            await campaign_progress_command(update, context)

        elif action == "week_report":
            await week_report_command(update, context)

        elif action == "send_valli_invite":
            await send_valli_invite_command(update, context)

        elif action == "client":
            email_arg = data.get("email", "")
            if not email_arg:
                await update.message.reply_text("Укажите email клиента")
            else:
                context.args = [email_arg]
                await client_command(update, context)

        elif action == "preview":
            name = data.get("name", "Клиент")
            ctx = data.get("context", user_data[uid]["context"])
            text_preview = generate_email_text(name, ctx)
            keyboard = [
                [InlineKeyboardButton("✅ Одобрить", callback_data="approve")],
                [InlineKeyboardButton("🔄 Переделать", callback_data="regenerate")],
            ]
            await update.message.reply_text(
                f"📝 Предпросмотр:\n\n{text_preview}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except (json.JSONDecodeError, ValueError):
        await update.message.reply_text(reply)

@manager_only_callback
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "stats":
        try:
            r = requests.get(STATS_URL, timeout=5).json()
            await query.edit_message_text(
                f"📊 Статистика:\n\n"
                f"📧 Всего: {r['total']}\n"
                f"✅ Подтверждено: {r['confirmed']}\n"
                f"❌ Отписались: {r['unsubscribed']}\n"
                f"⏳ Ожидают: {r['total'] - r['confirmed'] - r['unsubscribed']}"
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка: {e}")

    elif query.data == "contacts":
        await query.edit_message_text(
            "📋 База контактов:\n\n"
            "Всего: 2820 контактов\n"
            "Файл: export_20260511_Актив.xlsx\n"
            "Рассылка: 50 писем в день в 10:00"
        )

    elif query.data == "new":
        await query.edit_message_text(
            "📧 Новая рассылка\n\n"
            "Напишите кому отправить:\n"
            "отправь письмо на ivan@mail.ru Иван Иванов"
        )

    elif query.data == "settings":
        keyboard = [
            [InlineKeyboardButton("😊 Дружеский", callback_data="tone_friendly")],
            [InlineKeyboardButton("👔 Официальный", callback_data="tone_formal")],
            [InlineKeyboardButton("🎯 Деловой", callback_data="tone_business")],
        ]
        await query.edit_message_text(
            "⚙️ Выберите тон письма:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("tone_"):
        tone_map = {"tone_friendly": "дружеский", "tone_formal": "официальный", "tone_business": "деловой"}
        tone = tone_map.get(query.data, "официальный")
        if uid not in user_data:
            user_data[uid] = {}
        user_data[uid]["tone"] = tone
        await query.edit_message_text(f"✅ Тон установлен: {tone}")

@manager_only
async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Использование: /send email@example.com Имя Фамилия")
        return
    email = context.args[0]
    name = " ".join(context.args[1:])
    await update.message.reply_text(f"⏳ Отправляю письмо на {email}...")
    try:
        token, msg = send_email(email, name)
        save_to_sent(msg)
        await update.message.reply_text(f"✅ Письмо отправлено на {email}!")
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

@manager_only
async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(PAUSE_FLAG):
        await update.message.reply_text("⏸ Рассылка уже на паузе")
        return
    open(PAUSE_FLAG, "w").close()
    await update.message.reply_text("⏸ Рассылка приостановлена. /resume для возобновления.")

@manager_only
async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(PAUSE_FLAG):
        await update.message.reply_text("▶️ Рассылка уже активна")
        return
    os.remove(PAUSE_FLAG)
    await update.message.reply_text("▶️ Рассылка возобновлена")

@manager_only
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    import generate_report
    await update.message.reply_text("📄 Генерирую отчёт...")
    try:
        filename = generate_report.generate_report()
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=open(filename, "rb"),
            filename=f"consent_report_{datetime.now().strftime('%Y%m%d')}.pdf",
            caption="📄 Реестр согласий на рассылку ООО «Едиском»"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default

def _confirmations_on_date(confs, date_str):
    confirmed, unsubscribed = [], []
    for email, info in confs.items():
        d = info.get("date", "")
        if d.startswith(date_str):
            status = info.get("status")
            if status == "confirmed":
                confirmed.append(email)
            elif status == "unsubscribed":
                unsubscribed.append(email)
    return confirmed, unsubscribed


@manager_only
async def daily_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime
    progress = _load_json(CAMPAIGN_PROGRESS_FILE,
                          {"sent": [], "failed": [], "today_count": 0, "today_date": None})
    react = _load_json("/data/reactivation_progress.json",
                       {"sent": [], "today_count": 0, "today_date": None})
    confs = _load_json(CONFIRMATIONS_FILE, {})
    opens = _load_json("/data/opens.json", [])

    today = str(datetime.now().date())
    sent_today = progress.get("today_count", 0) if progress.get("today_date") == today else 0
    total_sent = len(progress.get("sent", []))
    remaining = max(TOTAL_CONTACTS - total_sent, 0)
    confirmed_today, unsubscribed_today = _confirmations_on_date(confs, today)

    react_today = react.get("today_count", 0) if react.get("today_date") == today else 0
    react_total = len(react.get("sent", []))

    opens_today = sum(1 for o in opens if o.get("date") == today)

    await update.message.reply_text(
        f"📆 Отчёт за сегодня ({today})\n\n"
        f"📧 Основная рассылка\n"
        f"   Отправлено сегодня: {sent_today}\n"
        f"   Всего: {total_sent} / {TOTAL_CONTACTS}\n"
        f"   Осталось: {remaining}\n\n"
        f"🔄 Реактивация\n"
        f"   Отправлено сегодня: {react_today}\n"
        f"   Всего: {react_total}\n\n"
        f"👁 Открытий сегодня: {opens_today}\n\n"
        f"✅ Новых подтверждений: {len(confirmed_today)}\n"
        f"❌ Новых отписок: {len(unsubscribed_today)}"
    )


@manager_only
async def campaign_progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    progress = _load_json(CAMPAIGN_PROGRESS_FILE,
                          {"sent": [], "today_count": 0, "today_date": None})
    total_sent = len(progress.get("sent", []))
    remaining = max(TOTAL_CONTACTS - total_sent, 0)
    percent = (total_sent / TOTAL_CONTACTS * 100) if TOTAL_CONTACTS else 0.0

    pace = progress.get("today_count") or 50
    days_left = ((remaining + pace - 1) // pace) if pace > 0 else 0

    await update.message.reply_text(
        f"📈 Прогресс кампании\n\n"
        f"📨 Отправлено: {total_sent} / {TOTAL_CONTACTS}\n"
        f"⏳ Осталось: {remaining}\n"
        f"📊 Выполнено: {percent:.1f}%\n\n"
        f"🚀 Темп: {pace} писем/день\n"
        f"📅 До конца: ~{days_left} дн."
    )


@manager_only
async def week_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from datetime import datetime, timedelta
    confs = _load_json(CONFIRMATIONS_FILE, {})
    progress = _load_json(CAMPAIGN_PROGRESS_FILE, {"sent": [], "today_count": 0, "today_date": None})

    today = datetime.now().date()
    rows = []
    total_conf, total_unsub = 0, 0
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        d_str = str(d)
        c, u = _confirmations_on_date(confs, d_str)
        total_conf += len(c)
        total_unsub += len(u)
        rows.append((d_str, len(c), len(u)))

    msg = "📅 Статистика за 7 дней\n\n"
    msg += "Дата          ✅   ❌\n"
    for d_str, c, u in rows:
        msg += f"{d_str}   {c:>2}   {u:>2}\n"
    msg += f"\nПодтверждений: {total_conf}\n"
    msg += f"Отписок: {total_unsub}\n"

    all_sent = len(progress.get("sent", []))
    if all_sent > 0:
        pct = total_conf / all_sent * 100
        msg += f"\nПроцент подтверждений (от всех отправленных, {all_sent} шт.): {pct:.1f}%"
    else:
        msg += "\nПроцент подтверждений: —"

    msg += ("\n\nℹ️ Подённой истории отправок нет в campaign_progress.json — "
            "поэтому показаны подтверждения/отписки по датам, а отправки — суммарно.")
    await update.message.reply_text(msg)


@manager_only
async def last_send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    progress = _load_json(CAMPAIGN_PROGRESS_FILE,
                          {"sent": [], "failed": [], "today_count": 0,
                           "today_date": None, "last_run": None})
    today_count = progress.get("today_count", 0)
    today_date = progress.get("today_date") or "—"
    last_run = progress.get("last_run") or "—"
    sent_list = progress.get("sent", [])
    failed_list = progress.get("failed", []) or []

    last_emails = sent_list[-today_count:] if today_count > 0 else []

    msg = (
        f"📊 Последний день отправки: {today_date}\n"
        f"🕐 Время запуска: {last_run}\n"
        f"📧 Писем отправлено: {today_count}\n\n"
    )

    if last_emails:
        msg += "Адреса:\n" + "\n".join(f"  • {e}" for e in last_emails) + "\n"
    else:
        msg += "Адреса: —\n"

    if failed_list:
        msg += f"\n❌ Ошибок за всю кампанию: {len(failed_list)}\n"
        for e in failed_list[-10:]:
            msg += f"  • {e}\n"
        if len(failed_list) > 10:
            msg += f"  …и ещё {len(failed_list) - 10}\n"
    else:
        msg += "\n✅ Ошибок не было"

    if len(msg) > 4000:
        msg = msg[:3990] + "\n…"
    await update.message.reply_text(msg)


@manager_only
async def reactivation_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    path = "/data/reactivation_progress.json"
    if not os.path.exists(path):
        await update.message.reply_text(
            "📊 Реактивация — статистика\n\n"
            "Прогресс-файл ещё не создан — кампания не запускалась.\n"
            "Расписание: 10:30, 11:30, 12:30 (по 10 писем, итого 30/день)."
        )
        return

    try:
        with open(path) as f:
            p = json.load(f)
    except Exception as e:
        await update.message.reply_text(f"❌ Не удалось прочитать прогресс: {e}")
        return

    sent_total = len(p.get("sent", []))
    failed_total = len(p.get("failed", []))
    today_count = p.get("today_count", 0)
    today_date = p.get("today_date") or "—"
    last_run = p.get("last_run") or "ещё не запускалась"

    await update.message.reply_text(
        "📊 Реактивация — статистика\n\n"
        f"📧 Отправлено всего: {sent_total}\n"
        f"✅ Сегодня ({today_date}): {today_count} / 30\n"
        f"❌ Ошибок: {failed_total}\n"
        f"🕐 Последний запуск: {last_run}\n\n"
        "📅 Расписание: 10:30, 11:30, 12:30"
    )


@manager_only
async def email_log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import email_log as el
    records = el.get_last_n(10)
    if not records:
        await update.message.reply_text("📭 Лог отправок пуст")
        return
    def _bool_label(val):
        if val is True or val == "да":
            return "да"
        return "нет"

    lines = []
    for r in records:
        opened = _bool_label(r["opened"])
        if r.get("opened_time"):
            opened += f" ({r['opened_time'][:16]})"
        reply = _bool_label(r["reply"])
        if r.get("reply_date"):
            reply += f" ({r['reply_date'][:16]})"
        delivered = r.get("delivered", "—")
        lines.append(
            f"#{r['id']} {r['email']}\n"
            f"  {r['subject'][:45]}\n"
            f"  {r['date'][:16]} | {r['campaign']} v{r['template_variant']}\n"
            f"  Доставлен: {delivered} | Открыт: {opened} | Ответ: {reply}"
        )
    msg = "📋 Последние 10 отправок:\n\n" + "\n\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n…"
    await update.message.reply_text(msg)


@manager_only
async def export_log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import email_log as el
    xlsx_path = el.get_xlsx_path()
    if not os.path.exists(xlsx_path):
        await update.message.reply_text("📭 Excel файл ещё не создан — нет записей в логе")
        return
    from datetime import datetime as dt
    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=open(xlsx_path, "rb"),
        filename=f"emails_log_{dt.now().strftime('%Y%m%d_%H%M')}.xlsx",
        caption="📊 Лог email отправок"
    )


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule ЧАС:МИНУТЫ КОЛИЧЕСТВО\n\n"
            "Пример:\n/schedule 10:00 20 13:00 20 16:00 10"
        )
        return

    args = context.args
    if len(args) % 2 != 0:
        await update.message.reply_text("Ошибка: укажите пары время-количество")
        return

    import subprocess, json
    schedule = []
    for i in range(0, len(args), 2):
        time_str = args[i]
        count = args[i+1]
        hour, minute = time_str.split(":")
        schedule.append({"hour": hour, "minute": minute, "count": count})

    result = subprocess.run(
        ['python3', '/opt/openclaw/schedule_manager.py', json.dumps(schedule)],
        capture_output=True, text=True
    )

    msg = "✅ Расписание обновлено:\n\n"
    for s in schedule:
        msg += f"- {s['hour']}:{s['minute']} - {s['count']} писем\n"
    await update.message.reply_text(msg)

    if not context.args:
        await update.message.reply_text(
            "Использование: /schedule ЧАС:МИНУТЫ КОЛИЧЕСТВО [ЧАС:МИНУТЫ КОЛИЧЕСТВО ...]\n\n"
            "Пример:\n"
            "/schedule 10:00 20 13:00 20 16:00 10\n\n"
            "Текущее расписание: каждый день в 10:00 - 50 писем"
        )
        return

    args = context.args
    if len(args) % 2 != 0:
        await update.message.reply_text("Ошибка: укажите пары время-количество")
        return

    schedule = []
    for i in range(0, len(args), 2):
        time_str = args[i]
        count = args[i+1]
        hour, minute = time_str.split(":")
        schedule.append({"hour": hour, "minute": minute, "count": count})
    import json
    schedule_file = "/opt/openclaw/data/schedule.json"
    with open(schedule_file, "w") as f:
        json.dump(schedule, f)

    # Читаем текущий crontab
    import subprocess, json
    result = subprocess.run(
      ['python3', '/opt/openclaw/schedule_manager.py', json.dumps(schedule)],
      capture_output=True, text=True
)


    lines = [l for l in result.stdout.splitlines() if 'campaign' not in l]

    # Добавляем новые задачи
    for s in schedule:
        line = f"{s['minute']} {s['hour']} * * * docker exec openclaw python -c \"import campaign; campaign.run_campaign(limit={s['count']})\" >> /opt/openclaw/logs/campaign.log 2>&1"
        lines.append(line)

    new_crontab = "\n".join(lines) + "\n"
    subprocess.run(['crontab', '-'], input=new_crontab, text=True)

    msg = "✅ Расписание обновлено:\n\n"
    for s in schedule:
        msg += f"- {s['hour']}:{s['minute']} - {s['count']} писем\n"
    await update.message.reply_text(msg)

def _bitrix_call(method: str, params: dict):
    webhook = os.getenv("BITRIX_WEBHOOK", "").rstrip("/")
    if not webhook:
        return None
    try:
        r = requests.get(f"{webhook}/{method}.json", params=params, timeout=10)
        r.raise_for_status()
        result = r.json().get("result")
        return result
    except Exception:
        return None


def _bitrix_search(email: str) -> dict | None:
    contacts = _bitrix_call("crm.contact.list", {
        "FILTER[EMAIL]": email,
        "SELECT[]": ["ID", "NAME", "LAST_NAME", "SECOND_NAME", "COMPANY_ID", "DATE_CREATE"],
    }) or []

    leads = _bitrix_call("crm.lead.list", {
        "FILTER[EMAIL]": email,
        "SELECT[]": ["ID", "TITLE", "NAME", "LAST_NAME", "STATUS_ID",
                     "DATE_CREATE", "COMPANY_TITLE", "OPPORTUNITY", "CURRENCY_ID"],
    }) or []

    if not contacts and not leads:
        return None

    deals = []
    for c in contacts:
        cid = c.get("ID")
        if cid:
            batch = _bitrix_call("crm.deal.list", {
                "FILTER[CONTACT_ID]": cid,
                "SELECT[]": ["ID", "TITLE", "STAGE_ID", "OPPORTUNITY", "CURRENCY_ID",
                             "DATE_CREATE", "CLOSEDATE"],
            }) or []
            deals.extend(batch)

    companies = []
    seen = set()
    for c in contacts:
        co_id = c.get("COMPANY_ID")
        if co_id and co_id != "0" and co_id not in seen:
            seen.add(co_id)
            co = _bitrix_call("crm.company.get", {"id": co_id})
            if isinstance(co, dict):
                companies.append(co)

    return {"contacts": contacts, "leads": leads, "deals": deals, "companies": companies}


def _format_bitrix_card(email: str, data: dict) -> str:
    lines = [f"📋 История клиента: {email}", "", "🔷 Битрикс24:"]

    contacts = data.get("contacts", [])
    companies = data.get("companies", [])
    leads = data.get("leads", [])
    deals = data.get("deals", [])

    if contacts:
        lines.append(f"\n👤 Контакты ({len(contacts)}):")
        for c in contacts:
            parts = [c.get("NAME", ""), c.get("SECOND_NAME", ""), c.get("LAST_NAME", "")]
            name = " ".join(p for p in parts if p).strip() or "—"
            created = (c.get("DATE_CREATE") or "")[:10]
            lines.append(f"  • {name}  (ID {c.get('ID')}, создан {created})")

    if companies:
        lines.append(f"\n🏢 Компании ({len(companies)}):")
        for co in companies:
            lines.append(f"  • {co.get('TITLE', '—')}  (ID {co.get('ID')})")

    if leads:
        lines.append(f"\n📋 Лиды ({len(leads)}):")
        for lead in leads[:5]:
            title = (lead.get("TITLE") or
                     f"{lead.get('NAME','')} {lead.get('LAST_NAME','')}".strip() or "—")
            status = lead.get("STATUS_ID", "—")
            created = (lead.get("DATE_CREATE") or "")[:10]
            amt = lead.get("OPPORTUNITY")
            cur = lead.get("CURRENCY_ID", "")
            amount_str = f"{amt} {cur}".strip() if amt else "—"
            lines.append(f"  • [{status}] {title} | {amount_str} | {created}")
        if len(leads) > 5:
            lines.append(f"  …и ещё {len(leads) - 5}")

    if deals:
        lines.append(f"\n💼 Сделки ({len(deals)}):")
        for deal in deals[:5]:
            title = deal.get("TITLE") or "—"
            stage = deal.get("STAGE_ID", "—")
            amt = deal.get("OPPORTUNITY")
            cur = deal.get("CURRENCY_ID", "")
            amount_str = f"{amt} {cur}".strip() if amt else "—"
            created = (deal.get("DATE_CREATE") or "")[:10]
            lines.append(f"  • [{stage}] {title} | {amount_str} | {created}")
        if len(deals) > 5:
            lines.append(f"  …и ещё {len(deals) - 5}")

    return "\n".join(lines)


async def client_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /client email@example.com")
        return

    email = context.args[0].strip().lower()

    campaign    = _load_json(CAMPAIGN_PROGRESS_FILE, {"sent": [], "failed": []})
    reactivation = _load_json("/data/reactivation_progress.json", {"sent": [], "failed": []})
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    opens   = _load_json("/data/opens.json", [])
    bounced = _load_json("/data/bounced.json", [])
    email_log_records = _load_json("/data/emails_log.json", [])

    def _in(lst):
        return any(e.lower() == email for e in lst)

    in_campaign     = _in(campaign.get("sent", []))
    in_reactivation = _in(reactivation.get("sent", []))

    # Per-email send dates from email_log
    campaign_date     = None
    reactivation_date = None
    for r in email_log_records:
        if r.get("email", "").lower() != email:
            continue
        if r.get("campaign") == "re-permission" and not campaign_date:
            campaign_date = (r.get("date") or "")[:16]
        if r.get("campaign") == "reactivation" and not reactivation_date:
            reactivation_date = (r.get("date") or "")[:16]

    client_opens   = [o for o in opens   if o.get("email", "").lower() == email]
    client_bounced = [b for b in bounced if b.get("email", "").lower() == email]
    conf_info = confirmations.get(email) or confirmations.get(context.args[0].strip())

    # Nothing found locally — try Bitrix24
    if not in_campaign and not in_reactivation and not conf_info and not client_opens and not client_bounced:
        await update.message.reply_text("🔍 В локальных базах не найден, ищу в Битрикс24…")
        bx_data = _bitrix_search(email)
        if not bx_data:
            webhook_set = bool(os.getenv("BITRIX_WEBHOOK"))
            suffix = "" if webhook_set else "\n\n⚠️ BITRIX_WEBHOOK не задан — поиск в CRM недоступен"
            await update.message.reply_text(f"❓ Клиент {email} не найден ни в одной базе данных{suffix}")
        else:
            msg = _format_bitrix_card(email, bx_data)
            if len(msg) > 4000:
                msg = msg[:3990] + "\n…"
            await update.message.reply_text(msg)
        return

    lines = [f"📋 История клиента: {email}", ""]

    # Campaigns
    lines.append("📧 Рассылки:")
    if in_campaign:
        suffix = f" ({campaign_date})" if campaign_date else ""
        lines.append(f"- Re-permission: отправлено{suffix}")
    else:
        lines.append("- Re-permission: не отправлялось")

    if in_reactivation:
        suffix = f" ({reactivation_date})" if reactivation_date else ""
        lines.append(f"- Реактивация: отправлено{suffix}")
    else:
        lines.append("- Реактивация: не отправлялось")

    # Opens
    lines.append("")
    lines.append("👁 Открытия:")
    if client_opens:
        for o in sorted(client_opens, key=lambda x: x.get("time") or x.get("date", "")):
            t = (o.get("time") or o.get("date", ""))[:16]
            lines.append(f"- {t}")
    else:
        lines.append("- нет данных")

    # Subscription status
    lines.append("")
    if conf_info:
        status = conf_info.get("status", "")
        date   = (conf_info.get("date") or "")[:16]
        if status == "confirmed":
            lines.append(f"✅ Статус подписки: подтвердил ({date})")
        elif status == "unsubscribed":
            lines.append(f"🚫 Статус подписки: отписался ({date})")
        else:
            lines.append(f"⏳ Статус подписки: {status}")
    else:
        lines.append("⏳ Статус подписки: ожидает")

    # Bounce
    if client_bounced:
        b = client_bounced[0]
        lines.append(f"❌ Bounce: да ({b.get('date', '')} — {b.get('reason', '')})")
    else:
        lines.append("✅ Bounce: нет")

    # Last contact
    all_dates = []
    if campaign_date:
        all_dates.append(campaign_date[:10])
    if reactivation_date:
        all_dates.append(reactivation_date[:10])
    for o in client_opens:
        d = (o.get("time") or o.get("date", ""))[:10]
        if d:
            all_dates.append(d)
    if conf_info:
        d = (conf_info.get("date") or "")[:10]
        if d:
            all_dates.append(d)
    for b in client_bounced:
        d = (b.get("date") or "")[:10]
        if d:
            all_dates.append(d)

    lines.append("")
    lines.append(f"📅 Последний контакт: {max(all_dates)}" if all_dates else "📅 Последний контакт: нет данных")

    await update.message.reply_text("\n".join(lines))


async def send_valli_invite_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import valli_invite
    limit = None
    if context.args:
        try:
            limit = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Использование: /send_valli_invite [лимит]")
            return
    await update.message.reply_text("⏳ Запускаю рассылку приглашений Валли...")
    try:
        results = valli_invite.run_invites(limit=limit)
        failed_count = len(results["failed"])
        msg = (
            f"✅ Рассылка Валли завершена\n\n"
            f"📧 Отправлено: {len(results['sent'])}\n"
            f"⏭ Уже получили: {len(results['skipped'])}\n"
            f"❌ Ошибок: {failed_count}"
        )
        if failed_count:
            msg += "\n\nОшибки:\n" + "\n".join(
                f"  • {f['email']}: {f['error']}" for f in results["failed"][:5]
            )
            if failed_count > 5:
                msg += f"\n  …и ещё {failed_count - 5}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(CommandHandler("pause", pause_command))
    app.add_handler(CommandHandler("resume", resume_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("schedule", schedule_command))
    app.add_handler(CommandHandler("reactivation_stats", reactivation_stats_command))
    app.add_handler(CommandHandler("daily_report", daily_report_command))
    app.add_handler(CommandHandler("campaign_progress", campaign_progress_command))
    app.add_handler(CommandHandler("week_report", week_report_command))
    app.add_handler(CommandHandler("last_send", last_send_command))
    app.add_handler(CommandHandler("email_log", email_log_command))
    app.add_handler(CommandHandler("export_log", export_log_command))
    app.add_handler(CommandHandler("client", client_command))
    app.add_handler(CommandHandler("send_valli_invite", send_valli_invite_command))
    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
