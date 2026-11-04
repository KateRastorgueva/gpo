"""Темы классификатора Кати (репозиторий KateRastorgueva/Chat-bot, папка «чат бот»).

Модель обучалась с sklearn LabelEncoder: номер класса = позиция имени темы в
алфавитном порядке. Поэтому список восстанавливается без `label_encoder.pkl`
(pickle при загрузке может выполнить произвольный код).
"""

CATEGORY_LABELS: dict[str, str] = {
    "akademicheskiy_otpusk": "Академический отпуск",
    "dopolnitelnoe_obrazovanie": "Дополнительное образование",
    "fakultety": "Факультеты и кафедры",
    "gpo": "ГПО",
    "lgoty": "Льготы",
    "materialnaya_pomoshch": "Материальная помощь",
    "medpunkt": "Медпункт",
    "mezhdunarodnoe": "Международная деятельность",
    "nauka": "Наука",
    "obshchaga": "Общежитие",
    "olimpiady": "Олимпиады",
    "oplata": "Оплата обучения",
    "postuplenie": "Поступление",
    "praktika": "Практика",
    "profkom": "Профком",
    "psiholog": "Психологическая помощь",
    "sport": "Спорт",
    "stipendiya": "Стипендия",
    "studencheskaya_zhizn": "Студенческая жизнь",
    "studotryady": "Студотряды",
    "trudoustroystvo": "Трудоустройство",
    "tusur_info": "О ТУСУРе",
    "ucheba": "Учёба",
    "volonterstvo": "Волонтёрство",
}

CATEGORIES: list[str] = sorted(CATEGORY_LABELS)
