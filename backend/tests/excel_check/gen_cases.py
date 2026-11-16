import random, json, sys
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
TYPES = ["Комната", "Гостиная", "Кухня", "Кухня-гостиная", "Прихожая / коридор", "Санузел", "Гардеробная", "Балкон / лоджия", "Другое"]
B = lambda p=0.5: random.random() < p
cases = []
# 0 — пример из файла (значения по умолчанию)
cases.append({"object": "Квартира 60 м², ЖК …", "area": 60, "sockets": 42, "lv": 3, "switches": 12, "lights": 9, "out220": 1,
  "junctions": 0, "cust_cable25": 0, "draw15": 0, "draw25": 0, "windows": 8, "chase": True, "route": "ceiling", "discount": False,
  "phase": "3", "main_a": 32, "brand": "Dekraft", "case_type": "flush", "kup": None, "oven": True, "hob": True, "hob_len": None,
  "dishwasher": True, "washer": True, "dryer": False, "apron": True, "fridge": True, "flow": False, "flow_len": None, "boiler": False,
  "neptun": False, "master": "none", "router": True, "media": False,
  "rooms": [{"name":"Спальня","type":"Комната","sockets":True,"floor":False,"ac":True},{"name":"Детская","type":"Комната","sockets":True,"floor":False,"ac":False},
            {"name":"Кухня-гостиная","type":"Кухня-гостиная","sockets":True,"floor":False,"ac":False},{"name":"Прихожая","type":"Прихожая / коридор","sockets":False,"floor":False,"ac":False},
            {"name":"Санузел","type":"Санузел","sockets":False,"floor":True,"ac":False},{"name":"Балкон","type":"Балкон / лоджия","sockets":False,"floor":False,"ac":False}],
  "extra": [], "tariff": "turnkey"})
for i in range(N):
    nrooms = random.randint(0, 12)
    rooms = []
    for j in range(nrooms):
        t = random.choice(TYPES)
        rooms.append({"name": random.choice(["", f"Пом{j}", "Спальня", "Кабинет"]), "type": t, "sockets": B(0.6), "floor": B(0.25), "ac": B(0.25)})
    ph = random.choice(["3", "3", "1"])
    c = {"object": f"Тест {i}", "area": round(random.uniform(20, 220), random.choice([0, 1, 2])),
         "sockets": random.randint(0, 140), "lv": random.randint(0, 15), "switches": random.randint(0, 70), "lights": random.randint(0, 80),
         "out220": random.randint(0, 12), "junctions": random.choice([0, 0, 0, random.randint(1, 15)]),
         "cust_cable25": random.choice([0, 0, 0, 100, 250, 1000]), "draw15": random.choice([0, 0, round(random.uniform(50, 500), 1)]),
         "draw25": random.choice([0, 0, round(random.uniform(50, 700), 1)]), "windows": random.randint(0, 15),
         "chase": B(0.7), "route": random.choice(["ceiling", "ceiling", "floor"]), "discount": B(0.4),
         "phase": ph, "main_a": random.choice([25, 32, 40, 50, 63]), "brand": random.choice(["Dekraft", "ABB"]),
         "case_type": "flush", "kup": random.choice([None, None, random.randint(0, 4)]),
         "oven": B(), "hob": B(), "hob_len": random.choice([None, None, random.randint(5, 30)]),
         "dishwasher": B(), "washer": B(), "dryer": B(0.3), "apron": B(), "fridge": B(), "flow": B(0.3),
         "flow_len": random.choice([None, random.randint(5, 30)]), "boiler": B(0.3), "neptun": B(0.3),
         "master": random.choice(["none", "none", "light", "all"]), "router": B(), "media": B(0.2),
         "rooms": rooms, "extra": [{"name": f"Доп {k}", "qty": random.randint(1, 20), "price": random.choice([100, 250.5, 1200])} for k in range(random.randint(0, 3))],
         "tariff": random.choice(["basic", "std", "turnkey"])}
    cases.append(c)
json.dump(cases, open('cases.json', 'w'), ensure_ascii=False, indent=0)
print(len(cases))
