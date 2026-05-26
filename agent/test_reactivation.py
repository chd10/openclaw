"""Тестовая отправка: берём первый реальный контакт из Битрикс, шлём на chd10@ya.ru."""
import sys
sys.path.insert(0, "/app")

from reactivation_campaign import fetch_contacts, find_last_lead, lead_products, contact_name, send_email

TEST_EMAIL = "chd10@ya.ru"

contact = next(fetch_contacts(), None)
if not contact:
    print("Контакты не найдены — выборка пустая")
    sys.exit(1)

name = contact_name(contact)
cid = contact["ID"]
real_email = None
for e in (contact.get("EMAIL") or []):
    v = (e.get("VALUE") or "").strip()
    if v:
        real_email = v
        break

print(f"Контакт: ID={cid}, имя={name!r}, реальный email={real_email}")

try:
    lead = find_last_lead(cid)
    lead_title = lead.get("TITLE") if lead else None
    products = lead_products(lead["ID"]) if lead else []
except Exception as e:
    print(f"Не удалось получить лид: {e}")
    lead_title, products = None, []

print(f"Лид: {lead_title!r}, товары: {products}")
print(f"Отправляю на {TEST_EMAIL}...")

send_email(TEST_EMAIL, name, lead_title, products)
print("Готово.")
