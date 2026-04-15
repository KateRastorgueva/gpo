# UI Examples For Support Page

## 1) FAQ mode
Question:
`where can i get enrollment certificate`

Expected:
- `mode=faq`
- short answer from FAQ

## 2) RAG mode
Question:
`Где смотреть расписание занятий ТУСУР?`

Expected:
- `mode=rag`
- answer with source link `https://timetable.tusur.ru/`

## 3) Operator mode
Question:
`Мне нужен официальный ответ по редкому регламенту, которого нет на сайте`

Expected:
- `mode=operator`
- escalation text and queue entry in `/admin-support`

## 4) Critical topic escalation
Question:
`Какой точный срок оплаты обучения и какие штрафы при просрочке?`

Expected:
- either confident sourced answer with warning, or
- `mode=operator` for manual verification
