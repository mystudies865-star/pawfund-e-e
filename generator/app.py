import os, json, time, random, math, signal
from datetime import datetime, timezone
from faker import Faker
from confluent_kafka import Producer, KafkaException

fake = Faker()

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "events.pawfund")

SERVICE_NAME = os.getenv("SERVICE_NAME", "pawfund-generator")
ENV = os.getenv("ENV", "local")

BASE_RPS = float(os.getenv("BASE_RPS", "18"))
SCENARIO = os.getenv("SCENARIO", "normal").lower()  # normal | spike | payment_outage | promo_day

SPIKE_MULT = float(os.getenv("SPIKE_MULT", "4"))
SPIKE_EVERY_SEC = int(os.getenv("SPIKE_EVERY_SEC", "120"))
SPIKE_DURATION_SEC = int(os.getenv("SPIKE_DURATION_SEC", "25"))

# funnel
P_ADD_TO_CART = float(os.getenv("P_ADD_TO_CART", "0.25"))
P_PURCHASE = float(os.getenv("P_PURCHASE", "0.07"))

# charity
P_DONATION = float(os.getenv("P_DONATION", "0.02"))
P_CHARITY_ITEM = float(os.getenv("P_CHARITY_ITEM", "0.015"))

# extra commerce features (to make project clearly different)
P_COUPON = float(os.getenv("P_COUPON", "0.12"))
P_DELIVERY = float(os.getenv("P_DELIVERY", "0.80"))
P_REFUND = float(os.getenv("P_REFUND", "0.012"))

SEED = os.getenv("SEED")
if SEED:
    random.seed(int(SEED))

_running = True
def _stop(*_):
    global _running
    _running = False
signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def in_window(ts: float, every: int, dur: int) -> bool:
    return (int(ts) % every) < dur

def current_rps(ts: float) -> float:
    rps = BASE_RPS
    if SCENARIO == "spike" and in_window(ts, SPIKE_EVERY_SEC, SPIKE_DURATION_SEC):
        rps *= SPIKE_MULT
    return max(0.2, rps)

def scenario_purchase_params() -> tuple[float, float]:
    """
    Returns:
      p_purchase_effective,
      payment_fail_multiplier
    """
    if SCENARIO == "payment_outage":
        return (P_PURCHASE * 0.85, 4.0)
    if SCENARIO == "promo_day":
        return (P_PURCHASE * 1.35, 1.0)
    return (P_PURCHASE, 1.0)

PRODUCTS = [
    {"id": "cat-001", "name": "Корм для кошек 2кг", "category": "food", "pet_type": "cat", "price": 1290.0},
    {"id": "cat-002", "name": "Наполнитель 10л", "category": "hygiene", "pet_type": "cat", "price": 790.0},
    {"id": "cat-003", "name": "Игрушка «мышка»", "category": "toys", "pet_type": "cat", "price": 190.0},
    {"id": "dog-001", "name": "Корм для собак 3кг", "category": "food", "pet_type": "dog", "price": 1690.0},
    {"id": "dog-002", "name": "Лакомства 250г", "category": "food", "pet_type": "dog", "price": 340.0},
    {"id": "dog-003", "name": "Поводок нейлон", "category": "accessories", "pet_type": "dog", "price": 610.0},
]

CAMPAIGNS = [
    {"id": "camp-101", "name": "Корм для приюта «Лапки»", "cause": "food"},
    {"id": "camp-102", "name": "Помощь кошкам на передержке", "cause": "food"},
    {"id": "camp-103", "name": "Стерилизация + корм", "cause": "mixed"},
]

CHARITY_ITEMS = [
    {"id": "char-001", "name": "Мешок корма 10кг для приюта", "category": "charity_food", "pet_type": "mixed", "price": 2500.0},
    {"id": "char-002", "name": "Корм 3кг для кошек (пожертвование)", "category": "charity_food", "pet_type": "cat", "price": 1200.0},
    {"id": "char-003", "name": "Корм 5кг для собак (пожертвование)", "category": "charity_food", "pet_type": "dog", "price": 2100.0},
]

COUPONS = [
    {"code": "SAVE10", "pct": 0.10, "w": 5},
    {"code": "PET5", "pct": 0.05, "w": 8},
    {"code": "HELP15", "pct": 0.15, "w": 2},
]

DELIVERY_TYPES = [
    ("courier", 220.0, 6),
    ("pickup", 0.0, 4),
]

def choose_weighted(items, weights):
    total = sum(weights)
    r = random.uniform(0, total)
    upto = 0.0
    for it, w in zip(items, weights):
        if upto + w >= r:
            return it
        upto += w
    return items[-1]

def choose_product():
    weights = [4.0 if p["category"] == "food" else 1.5 for p in PRODUCTS]
    return choose_weighted(PRODUCTS, weights)

def choose_charity_item():
    weights = [2.8 if "Мешок" in p["name"] else 1.8 for p in CHARITY_ITEMS]
    return choose_weighted(CHARITY_ITEMS, weights)

def choose_coupon():
    weights = [c["w"] for c in COUPONS]
    return choose_weighted(COUPONS, weights)

def choose_delivery():
    weights = [w for _t, _p, w in DELIVERY_TYPES]
    t, price, _w = choose_weighted(DELIVERY_TYPES, weights)
    return t, float(price)

def donation_amount():
    v = random.lognormvariate(mu=math.log(500), sigma=0.75)
    return float(max(50.0, min(v, 20000.0)))

def base_event(user_id: int, session_id: str):
    return {
        "ts": iso_now(),
        "event_version": "1.1",
        "service": SERVICE_NAME,
        "env": ENV,
        "scenario": SCENARIO,
        "user_id": user_id,
        "session_id": session_id,
        "request_id": fake.uuid4(),
        "country": fake.country_code(),
        "city": fake.city(),
        "device": random.choice(["mobile", "desktop"]),
        "source": random.choice(["web", "android", "ios"]),
    }

def payment_status(fail_mult: float = 1.0):
    fail_w = 4.0 * max(1.0, fail_mult)
    paid_w = max(1.0, 100.0 - fail_w)
    return random.choices(["paid", "failed"], weights=[paid_w, fail_w], k=1)[0]

def donation_status():
    return random.choices(["success", "failed"], weights=[97, 3], k=1)[0]

def build_shop_funnel_events():
    user_id = int(min(200000, 1 + (random.paretovariate(1.35) * 50)))
    session_id = fake.uuid4()
    prod = choose_product()
    b = base_event(user_id, session_id)

    p_purchase_eff, fail_mult = scenario_purchase_params()
    p_coupon_eff = P_COUPON * (1.8 if SCENARIO == "promo_day" else 1.0)

    events = []

    events.append({
        **b,
        "event_name": "product_viewed",
        "product_id": prod["id"],
        "product_name": prod["name"],
        "category": prod["category"],
        "pet_type": prod["pet_type"],
        "product_price": prod["price"],
    })

    if random.random() < P_ADD_TO_CART:
        qty = random.choice([1, 1, 1, 2, 3])
        events.append({
            **b,
            "event_name": "add_to_cart",
            "product_id": prod["id"],
            "product_name": prod["name"],
            "category": prod["category"],
            "pet_type": prod["pet_type"],
            "product_price": prod["price"],
            "quantity": qty,
        })

        # coupon
        discount_amount = 0.0
        if random.random() < min(0.95, p_coupon_eff):
            coupon = choose_coupon()
            discount_amount = float(round(qty * prod["price"] * coupon["pct"], 2))
            events.append({
                **b,
                "event_name": "coupon_applied",
                "coupon_code": coupon["code"],
                "discount_pct": coupon["pct"],
                "discount_amount": discount_amount,
                "product_id": prod["id"],
                "quantity": qty,
            })

        # delivery
        delivery_price = 0.0
        if random.random() < P_DELIVERY:
            delivery_type, delivery_price = choose_delivery()
            events.append({
                **b,
                "event_name": "delivery_selected",
                "delivery_type": delivery_type,
                "delivery_price": float(round(delivery_price, 2)),
            })

        # purchase
        if random.random() < p_purchase_eff:
            oid = f"ord-{fake.uuid4()}"
            st = payment_status(fail_mult)

            gross = float(qty * prod["price"])
            net = gross - discount_amount + delivery_price
            net = float(max(0.0, round(net, 2)))

            revenue = net if st == "paid" else 0.0

            events.append({
                **b,
                "event_name": "checkout_completed",
                "order_id": oid,
                "currency": "RUB",
                "payment_status": st,
                "revenue": revenue,
                "gross": gross,
                "discount_amount": discount_amount,
                "delivery_price": float(round(delivery_price, 2)),
                "items": [{"product_id": prod["id"], "quantity": qty, "price": prod["price"]}],
            })

            # refunds (only paid)
            if st == "paid" and random.random() < P_REFUND:
                refund_amount = float(round(revenue * random.uniform(0.3, 1.0), 2))
                events.append({
                    **b,
                    "event_name": "order_refunded",
                    "order_id": oid,
                    "refund_id": f"ref-{fake.uuid4()}",
                    "refund_reason": random.choice(["damaged", "late_delivery", "changed_mind", "wrong_item"]),
                    "refund_amount": refund_amount,
                    "currency": "RUB",
                })

    return events

def build_charity_donation_event():
    user_id = int(min(200000, 1 + (random.paretovariate(1.35) * 50)))
    session_id = fake.uuid4()
    camp = random.choice(CAMPAIGNS)
    b = base_event(user_id, session_id)

    st = donation_status()
    amt = donation_amount()

    return {
        **b,
        "event_name": "donation_created",
        "donation_id": f"don-{fake.uuid4()}",
        "campaign_id": camp["id"],
        "campaign_name": camp["name"],
        "cause": camp["cause"],
        "amount": float(round(amt, 2)) if st == "success" else float(round(amt * random.uniform(0.2, 1.0), 2)),
        "currency": "RUB",
        "donation_status": st,
    }

def build_charity_item_purchase_events():
    user_id = int(min(200000, 1 + (random.paretovariate(1.35) * 50)))
    session_id = fake.uuid4()
    camp = random.choice(CAMPAIGNS)
    item = choose_charity_item()
    b = base_event(user_id, session_id)

    qty = random.choice([1, 1, 2])
    _p_purchase_eff, fail_mult = scenario_purchase_params()

    st = payment_status(fail_mult)
    rev = float(qty * item["price"]) if st == "paid" else 0.0
    oid = f"ord-{fake.uuid4()}"

    return [{
        **b,
        "event_name": "charity_item_purchased",
        "order_id": oid,
        "campaign_id": camp["id"],
        "campaign_name": camp["name"],
        "product_id": item["id"],
        "product_name": item["name"],
        "category": item["category"],
        "pet_type": item["pet_type"],
        "quantity": qty,
        "product_price": item["price"],
        "currency": "RUB",
        "payment_status": st,
        "revenue": rev,
    }]

def main():
    producer = Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "acks": "all",
        "retries": 10,
        "linger.ms": 15,
        "enable.idempotence": True,
        "compression.type": "snappy",
        "client.id": f"gen-{SERVICE_NAME}-{SCENARIO}",
    })

    print(f"[generator] topic={KAFKA_TOPIC} base_rps={BASE_RPS} scenario={SCENARIO}")

    sent = 0
    last = time.time()

    while _running:
        now = time.time()
        rps = current_rps(now)
        sleep_s = random.expovariate(rps)

        batch = []
        batch += build_shop_funnel_events()

        # donation slightly correlated with shopping activity
        if random.random() < (P_DONATION * (1.25 if SCENARIO in ("promo_day", "spike") else 1.0)):
            batch.append(build_charity_donation_event())

        if random.random() < P_CHARITY_ITEM:
            batch += build_charity_item_purchase_events()

        for ev in batch:
            payload = json.dumps(ev, ensure_ascii=False).encode("utf-8")
            key = str(ev.get("user_id", "")).encode("utf-8")
            try:
                producer.produce(topic=KAFKA_TOPIC, key=key, value=payload)
                sent += 1
            except BufferError:
                producer.poll(0.2)
            except KafkaException:
                producer.poll(0)

        producer.poll(0)

        if time.time() - last >= 5:
            print(f"[generator] sent={sent} rps~{rps:.1f}")
            last = time.time()

        time.sleep(min(sleep_s, 1.0))

    producer.flush(10)
    print("[generator] stopped")

if __name__ == "__main__":
    main()