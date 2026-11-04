# -*- coding: utf-8 -*-
"""Замер качества поиска на 17 вопросах с известным документом (+3 посторонних, +1 критичный).

Работает по HTTP с любым запущенным приложением, только стандартная библиотека
и httpx из окружения backend. Пример для ноутбука:

    python scripts/eval_search.py --base-url http://localhost:5173 --label dense --out reports/eval_dense.json

Логин и пароль берутся из FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD (окружение или .env).
Предполагается, что в базе загружены 49 документов ТУСУР (см. docs/laptop-dense-search.md).
"""
import argparse, json, os, re, statistics, sys, time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def _dotenv() -> dict:
    values = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip("'\"")
    return values


_env = _dotenv()
parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://localhost:5173")
parser.add_argument("--username", default=os.environ.get("FIRST_SUPERUSER") or _env.get("FIRST_SUPERUSER"))
parser.add_argument("--password", default=os.environ.get("FIRST_SUPERUSER_PASSWORD") or _env.get("FIRST_SUPERUSER_PASSWORD"))
parser.add_argument("--label", default="run")
parser.add_argument("--out", default=None)
ARGS = parser.parse_args()
API = ARGS.base_url.rstrip("/") + "/api/v1"
Q=[
("Сколько стоит обучение на очной форме в 2026/27 году?","Prikaz_No_529"),
("Когда выплачивают стипендию?","Grafik_vyplaty_stipendii"),
("Какие правила проживания в студенческом общежитии?","obscheghitii|obschezhitii"),
("Как перевестись на другую образовательную программу?","Poryadok_perevoda"),
("Как восстановиться после отчисления?","Poryadok_perevoda"),
("Как оформить академический отпуск?","Poryadok_oformleniya"),
("Кто является учредителем ТУСУР?","Ustav"),
("Как назначается повышенная академическая стипендия за достижения?","PGAS"),
("Какой размер повышенной стипендии в осеннем семестре?","Prikaz_o_razmere_PGAS"),
("Как проводится текущий контроль успеваемости и промежуточная аттестация?","tekushchego_kontrolya"),
("Сколько длится академический час и какие перерывы между занятиями?","Reghim_zanyatiy"),
("Какие документы нужны для поступления?","Pravila_priema"),
("Что такое исследовательская магистратура?","Issledovatelskaya"),
("В какой срок университет отвечает на обращение гражданина?","obrascheniyami|obrascheniya_grazhdan"),
("Сколько стоит обучение на ФДО?","FDO"),
("Какие правила внутреннего распорядка для обучающихся?","Pravila_rasporyadka"),
("Как оформляется приостановление образовательных отношений, академический отпуск?","Poryadok_oformleniya"),
]
OFF=["Какой рецепт борща самый вкусный?","Кто выиграл чемпионат мира по футболу?","Как настроить домашний роутер?"]
CRIT=[("Какие гарантии работникам предусмотрены коллективным договором?","Kollektivnyi")]
c=httpx.Client(timeout=120)
tok=c.post(f"{API}/login/access-token",data={"username":ARGS.username,"password":ARGS.password}).json()["access_token"]
c.headers["Authorization"]=f"Bearer {tok}"
def ask(q):
    t=time.perf_counter(); r=c.post(f"{API}/support/ask",json={"question":q,"channel":"web"}).json(); return r, (time.perf_counter()-t)*1000
res=[]; lat=[]
for q,exp in Q+CRIT:
    r,ms=ask(q); lat.append(ms)
    titles=[s["source_title"] for s in r["sources"]]
    rank=next((i+1 for i,t in enumerate(titles) if re.search(exp,t)),None)
    res.append(dict(q=q,exp=exp,mode=r["mode"],route=r["route_reason"],top=round(r["decision_metrics"]["top_score"],2),rank=rank,top1=titles[0] if titles else None,ms=round(ms)))
for q in OFF:
    r,ms=ask(q); lat.append(ms)
    res.append(dict(q=q,exp="OFF",mode=r["mode"],route=r["route_reason"],top=round(r["decision_metrics"]["top_score"],2),rank=None,top1=(r["sources"][0]["source_title"] if r["sources"] else None),ms=round(ms)))
for x in res: print(json.dumps(x,ensure_ascii=False))
docs=res[:len(Q)]
print("hit@1",sum(1 for x in docs if x["rank"]==1),"/",len(docs),"hit@3",sum(1 for x in docs if x["rank"] and x["rank"]<=3),"hit@5",sum(1 for x in docs if x["rank"]),
      "answered(rag)",sum(1 for x in docs if x["mode"]=="rag"),"offtopic->operator",sum(1 for x in res[len(Q)+1:] if x["mode"]=="operator"),"/",len(OFF),
      "critical->operator",res[len(Q)]["mode"])
print("latency ms median",round(statistics.median(lat)),"p90",round(sorted(lat)[int(len(lat)*0.9)-1]),"max",round(max(lat)))

if ARGS.out:
    Path(ARGS.out).parent.mkdir(parents=True, exist_ok=True)
    summary = dict(
        label=ARGS.label,
        hit1=sum(1 for x in docs if x["rank"] == 1),
        hit3=sum(1 for x in docs if x["rank"] and x["rank"] <= 3),
        hit5=sum(1 for x in docs if x["rank"]),
        answered=sum(1 for x in docs if x["mode"] == "rag"),
        median_ms=round(statistics.median(lat)),
    )
    Path(ARGS.out).write_text(json.dumps(dict(summary=summary, results=res), ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", ARGS.out, summary)
