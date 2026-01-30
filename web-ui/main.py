import os
from datetime import datetime, timezone
from typing import Any

from elasticsearch import Elasticsearch
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_NAME = os.getenv("APP_NAME", "PawFund • Панель магазина и помощи приютам")
ELASTIC_URL = os.getenv("ELASTIC_URL", "http://elasticsearch:9200")
ELASTIC_INDEX = os.getenv("ELASTIC_INDEX", "pawfund-events-*")

es = Elasticsearch(ELASTIC_URL)

app = FastAPI(title=APP_NAME)
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def q_time(minutes: int) -> dict[str, Any]:
    return {"range": {"@timestamp": {"gte": f"now-{minutes}m", "lte": "now"}}}


# ---------------- Pages (RU) ----------------
@app.get("/", response_class=HTMLResponse)
def page_overview(request: Request):
    return templates.TemplateResponse("obzor.html", {"request": request, "app_name": APP_NAME})


@app.get("/voronka", response_class=HTMLResponse)
def page_funnel(request: Request):
    return templates.TemplateResponse("voronka.html", {"request": request, "app_name": APP_NAME})


@app.get("/tovary", response_class=HTMLResponse)
def page_products(request: Request):
    return templates.TemplateResponse("tovary.html", {"request": request, "app_name": APP_NAME})


@app.get("/potok", response_class=HTMLResponse)
def page_stream(request: Request, minutes: int = 30, event_name: str | None = None):
    must = [q_time(minutes)]
    if event_name:
        must.append({"term": {"event_name.keyword": event_name}})

    resp = es.search(
        index=ELASTIC_INDEX,
        size=250,
        query={"bool": {"must": must}},
        sort=[{"@timestamp": {"order": "desc"}}],
    )
    items = [h["_source"] for h in resp["hits"]["hits"]]
    return templates.TemplateResponse(
        "potok.html",
        {"request": request, "app_name": APP_NAME, "items": items, "minutes": minutes, "event_name": event_name or ""},
    )


# ---------------- API ----------------
@app.get("/api/obzor")
def api_overview(minutes: int = 60):
    resp = es.search(
        index=ELASTIC_INDEX,
        size=0,
        query=q_time(minutes),
        aggs={
            "per_min": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1m"}},
            "by_event": {"terms": {"field": "event_name.keyword", "size": 14}},

            "shop_paid": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "checkout_completed"}},
                    {"term": {"payment_status.keyword": "paid"}},
                ]}},
                "aggs": {"revenue": {"sum": {"field": "revenue"}}},
            },
            "shop_paid_cnt": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "checkout_completed"}},
                    {"term": {"payment_status.keyword": "paid"}},
                ]}},
            },

            "refunds": {
                "filter": {"term": {"event_name.keyword": "order_refunded"}},
                "aggs": {"sum": {"sum": {"field": "refund_amount"}}},
            },

            "charity_item_paid": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "charity_item_purchased"}},
                    {"term": {"payment_status.keyword": "paid"}},
                ]}},
                "aggs": {"revenue": {"sum": {"field": "revenue"}}},
            },

            "donations_success": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "donation_created"}},
                    {"term": {"donation_status.keyword": "success"}},
                ]}},
                "aggs": {"sum": {"sum": {"field": "amount"}}},
            },

            "failed_payments": {
                "filter": {"bool": {"must": [
                    {"terms": {"event_name.keyword": ["checkout_completed", "charity_item_purchased"]}},
                    {"term": {"payment_status.keyword": "failed"}},
                ]}}
            },

            "failed_donations": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "donation_created"}},
                    {"term": {"donation_status.keyword": "failed"}},
                ]}}
            },

            "device_split": {"terms": {"field": "device.keyword", "size": 6}},
            "source_split": {"terms": {"field": "source.keyword", "size": 6}},
        },
    )

    per_min = [{"t": b["key_as_string"], "c": b["doc_count"]} for b in resp["aggregations"]["per_min"]["buckets"]]
    by_event = [{"k": b["key"], "c": b["doc_count"]} for b in resp["aggregations"]["by_event"]["buckets"]]
    counts = {x["k"]: x["c"] for x in by_event}

    views = counts.get("product_viewed", 0)
    atc = counts.get("add_to_cart", 0)

    shop_revenue = resp["aggregations"]["shop_paid"]["revenue"]["value"] or 0.0
    paid_orders = resp["aggregations"]["shop_paid_cnt"]["doc_count"] or 0
    aov = (shop_revenue / paid_orders) if paid_orders else 0.0

    refunds_sum = resp["aggregations"]["refunds"]["sum"]["value"] or 0.0
    net_shop = max(0.0, shop_revenue - refunds_sum)

    charity_item_revenue = resp["aggregations"]["charity_item_paid"]["revenue"]["value"] or 0.0
    donations_sum = resp["aggregations"]["donations_success"]["sum"]["value"] or 0.0

    fail_pay = resp["aggregations"]["failed_payments"]["doc_count"]
    fail_don = resp["aggregations"]["failed_donations"]["doc_count"]

    pay_attempts = paid_orders + int(fail_pay)
    pay_fail_rate = (fail_pay / pay_attempts) if pay_attempts else 0.0

    atc_rate = (atc / views) if views else 0.0
    conv = (paid_orders / views) if views else 0.0

    def buckets(name):
        return [{"k": b["key"], "c": b["doc_count"]} for b in resp["aggregations"][name]["buckets"]]

    return {
        "minutes": minutes,
        "total_events": resp["hits"]["total"]["value"],
        "generated_at": now_iso(),

        "views": views,
        "add_to_cart": atc,
        "add_to_cart_rate": atc_rate,
        "paid_orders": paid_orders,
        "conversion": conv,

        "shop_revenue": shop_revenue,
        "aov": aov,
        "refunds_sum": refunds_sum,
        "net_shop_revenue": net_shop,

        "donations_sum": donations_sum,
        "charity_item_revenue": charity_item_revenue,

        "fail_payments": fail_pay,
        "pay_fail_rate": pay_fail_rate,
        "fail_donations": fail_don,

        "per_min": per_min,
        "by_event": by_event,
        "device_split": buckets("device_split"),
        "source_split": buckets("source_split"),
    }


@app.get("/api/voronka")
def api_funnel(minutes: int = Query(120, ge=5, le=720)):
    must = [q_time(minutes)]

    def cnt(event: str, extra: list[dict] | None = None) -> int:
        m = list(must)
        m.append({"term": {"event_name.keyword": event}})
        if extra:
            m.extend(extra)
        return es.search(index=ELASTIC_INDEX, size=0, query={"bool": {"must": m}})["hits"]["total"]["value"]

    views = cnt("product_viewed")
    atc = cnt("add_to_cart")
    coupon = cnt("coupon_applied")
    delivery = cnt("delivery_selected")
    paid = cnt("checkout_completed", [{"term": {"payment_status.keyword": "paid"}}])
    failed = cnt("checkout_completed", [{"term": {"payment_status.keyword": "failed"}}])
    refunded = cnt("order_refunded")

    return {
        "minutes": minutes,
        "views": views,
        "add_to_cart": atc,
        "coupon_applied": coupon,
        "delivery_selected": delivery,
        "paid": paid,
        "failed": failed,
        "refunded": refunded,
        "atc_rate": (atc / views) if views else 0.0,
        "conversion": (paid / views) if views else 0.0,
        "fail_rate": (failed / (paid + failed)) if (paid + failed) else 0.0,
        "refund_rate_paid": (refunded / paid) if paid else 0.0,
        "generated_at": now_iso(),
    }


@app.get("/api/tovary/list")
def api_products(minutes: int = 4320):
    resp = es.search(
        index=ELASTIC_INDEX,
        size=0,
        query=q_time(minutes),
        aggs={"products": {"terms": {"field": "product_name.keyword", "size": 200}}},
    )
    items = [b["key"] for b in resp["aggregations"]["products"]["buckets"]]
    items = [x for x in items if x and x != "-"]
    return {"minutes": minutes, "items": items, "generated_at": now_iso()}


@app.get("/api/tovar/stat")
def api_product_stat(
    product: str = Query(..., min_length=1),
    minutes: int = Query(180, ge=5, le=4320),
    activity: str = Query("all"),
):
    must = [q_time(minutes), {"term": {"product_name.keyword": product}}]
    if activity != "all":
        must.append({"term": {"event_name.keyword": activity}})

    resp = es.search(
        index=ELASTIC_INDEX,
        size=0,
        query={"bool": {"must": must}},
        aggs={
            "events_per_min": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1m"}},
            "by_action": {"terms": {"field": "event_name.keyword", "size": 20}},
            "top_users_events": {"terms": {"field": "user_id", "size": 10}},

            # revenue per minute: sum(revenue) for paid checkout for this product
            "revenue_paid": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "checkout_completed"}},
                    {"term": {"payment_status.keyword": "paid"}},
                    {"term": {"product_name.keyword": product}},
                ]}},
                "aggs": {
                    "per_min": {"date_histogram": {"field": "@timestamp", "fixed_interval": "1m"}},
                    "sum_total": {"sum": {"field": "revenue"}},
                    "sum_per_min": {"sum": {"field": "revenue"}},
                },
            },

            "top_users_revenue": {
                "filter": {"bool": {"must": [
                    {"term": {"event_name.keyword": "checkout_completed"}},
                    {"term": {"payment_status.keyword": "paid"}},
                    {"term": {"product_name.keyword": product}},
                ]}},
                "aggs": {
                    "by_user": {
                        "terms": {"field": "user_id", "size": 10},
                        "aggs": {"rev": {"sum": {"field": "revenue"}}},
                    }
                },
            },
        },
    )

    events_per_min = [{"t": b["key_as_string"], "c": b["doc_count"]} for b in resp["aggregations"]["events_per_min"]["buckets"]]
    by_action = [{"k": b["key"], "c": b["doc_count"]} for b in resp["aggregations"]["by_action"]["buckets"]]
    top_users_events = [{"user_id": b["key"], "events": b["doc_count"]} for b in resp["aggregations"]["top_users_events"]["buckets"]]

    rev_ag = resp["aggregations"]["revenue_paid"]
    revenue_total = rev_ag["sum_total"]["value"] or 0.0
    revenue_per_min = [{"t": b["key_as_string"], "v": (b.get("sum_per_min", {}).get("value") or 0.0)} for b in rev_ag["per_min"]["buckets"]]

    top_users_revenue = []
    for b in resp["aggregations"]["top_users_revenue"]["by_user"]["buckets"]:
        top_users_revenue.append({"user_id": b["key"], "revenue": b["rev"]["value"] or 0.0})

    return {
        "product": product,
        "minutes": minutes,
        "activity": activity,
        "total_events": resp["hits"]["total"]["value"],
        "events_per_min": events_per_min,
        "by_action": by_action,
        "revenue_total": revenue_total,
        "revenue_per_min": revenue_per_min,
        "top_users_events": top_users_events,
        "top_users_revenue": top_users_revenue,
        "generated_at": now_iso(),
    }