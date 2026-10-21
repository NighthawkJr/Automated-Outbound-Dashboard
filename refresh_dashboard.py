#!/usr/bin/env python3
"""
Refresh the Outbound dashboard from Snowflake.

Reads agents.csv, runs four read-only queries, and rewrites the data blocks in index.html
(the blocks between /*GEN:NAME*/ and /*END:NAME*/ markers, plus a few fields in META).
Everything else in index.html is left alone, including the AOP block.

Environment variables (set as GitHub secrets for the scheduled run):
  SNOWFLAKE_ACCOUNT      e.g. pods-edw  (the account identifier, copied from Snowflake)
  SNOWFLAKE_USER         the read-only service user
  SNOWFLAKE_PRIVATE_KEY  PEM text of the private key  (or use SNOWFLAKE_PASSWORD)
  SNOWFLAKE_PRIVATE_KEY_PASSPHRASE   only if the key is encrypted
  SNOWFLAKE_PASSWORD     alternative to the key
  SNOWFLAKE_WAREHOUSE    a small warehouse
  SNOWFLAKE_ROLE         the read-only role

Run:  python refresh_dashboard.py            (writes index.html)
      python refresh_dashboard.py --dry-run  (runs the queries and checks, writes nothing)
"""
import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
from zoneinfo import ZoneInfo

HERE = pathlib.Path(__file__).resolve().parent
HTML = HERE / "index.html"
AGENTS = HERE / "agents.csv"

YEAR_START = dt.date(2026, 1, 1)      # the dashboard is built for calendar 2026
DAILY_START = dt.date(2026, 8, 1)     # before this date history is kept by month
DEPTS = "('IF Outbound','Concentrix Philippines Outbound')"
SF = 'PROD_SALESFORCE_DATACLOUD."schema_Prod_Salesforce_Objects"'
QUEUE_OWNER = "Khen Suarez"           # holds unassigned leads; kept out of agent numbers
MAX_STALE_DAYS = 5                    # refuse to publish if the newest sale is older than this


# --------------------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------------------
def agent_values(agents):
    return ",".join(f"('{a['id']}')" for a in agents)


# Links each sales login (e.g. KHewitt) to its Salesforce user by matching the alias prefix.
MAP_SQL = """
u AS (SELECT "Id__c" AS uid, "Department__c" AS udept, LOWER(REGEXP_REPLACE("Alias__c",'@.*','')) AS a
      FROM %(SF)s."User_Home__dll"),
mm AS (SELECT agent, uid FROM (
         SELECT ag.agent, u.uid, ROW_NUMBER() OVER (PARTITION BY ag.agent
                ORDER BY IFF(u.udept ILIKE '%%Outbound%%',0,1), LENGTH(u.a) DESC) rn
         FROM ag JOIN u ON (LOWER(ag.agent) LIKE u.a || '%%' OR u.a LIKE LOWER(ag.agent) || '%%') AND LENGTH(u.a) >= 5)
       WHERE rn = 1)
"""


def q_agent_day(agents):
    """One row per agent per day: orders, containers, cancels within 7 days, opportunities, New."""
    return ("""
WITH ag AS (SELECT column1 AS agent FROM VALUES %(values)s),
""" + MAP_SQL + """,
s AS (SELECT "Agent Container Booked By" AS agent, container_booked_date_dim_key::date AS d,
        COUNT(DISTINCT "Order Number") AS ord, SUM("Gross Container Count") AS cont,
        COUNT(DISTINCT IFF("Order Cancelled Timestamp" IS NOT NULL
              AND DATEDIFF('day', container_booked_date_dim_key::date, "Order Cancelled Timestamp"::date) <= 7,
              "Order Number", NULL)) AS cx
      FROM PROD_DW.DW_SEMANTIC.ORDER_CONTAINER_SALES_FACT
      WHERE container_booked_date_dim_key >= '%(start)s' AND "Container Agent Department" IN %(depts)s
        AND "Agent Container Booked By" IN (SELECT agent FROM ag)
      GROUP BY 1,2),
o AS (SELECT mm.agent, TRY_TO_DATE(LEFT(CAST(op."CreatedDate__c" AS VARCHAR),10)) AS d,
        COUNT(*) AS opps, SUM(IFF(op."StageName__c"='New',1,0)) AS nw
      FROM %(SF)s."Opportunity_Home__dll" op JOIN mm ON op."OwnerId__c" = mm.uid
      WHERE TRY_TO_DATE(LEFT(CAST(op."CreatedDate__c" AS VARCHAR),10)) >= '%(start)s' GROUP BY 1,2),
k AS (SELECT agent, d FROM s UNION SELECT agent, d FROM o)
SELECT k.agent, k.d::varchar, COALESCE(s.ord,0), COALESCE(s.cont,0), COALESCE(s.cx,0),
       COALESCE(o.opps,0), COALESCE(o.nw,0)
FROM k LEFT JOIN s ON s.agent = k.agent AND s.d = k.d LEFT JOIN o ON o.agent = k.agent AND o.d = k.d
ORDER BY k.agent, k.d
""") % {"values": agent_values(agents), "start": YEAR_START, "depts": DEPTS, "SF": SF}


def q_dept_day():
    """Department totals per day for the AOP section: all outbound agents, including agents who have left."""
    return ("""
WITH ag AS (SELECT DISTINCT "Agent Container Booked By" AS agent FROM PROD_DW.DW_SEMANTIC.ORDER_CONTAINER_SALES_FACT
            WHERE container_booked_date_dim_key >= '%(start)s' AND "Container Agent Department" IN %(depts)s
              AND "Agent Container Booked By" IS NOT NULL),
""" + MAP_SQL + """,
m AS (SELECT DISTINCT uid FROM mm),
s AS (SELECT container_booked_date_dim_key::date AS d, SUM("Gross Container Count") AS cont,
             COUNT(DISTINCT "Order Number") AS ord
      FROM PROD_DW.DW_SEMANTIC.ORDER_CONTAINER_SALES_FACT
      WHERE container_booked_date_dim_key >= '%(start)s' AND "Container Agent Department" IN %(depts)s GROUP BY 1),
o AS (SELECT TRY_TO_DATE(LEFT(CAST(op."CreatedDate__c" AS VARCHAR),10)) AS d, COUNT(*) AS opps
      FROM %(SF)s."Opportunity_Home__dll" op JOIN m ON op."OwnerId__c" = m.uid
      WHERE TRY_TO_DATE(LEFT(CAST(op."CreatedDate__c" AS VARCHAR),10)) >= '%(start)s' GROUP BY 1),
k AS (SELECT d FROM s UNION SELECT d FROM o)
SELECT k.d::varchar, COALESCE(s.cont,0), COALESCE(s.ord,0), COALESCE(o.opps,0)
FROM k LEFT JOIN s ON s.d = k.d LEFT JOIN o ON o.d = k.d ORDER BY k.d
""") % {"start": YEAR_START, "depts": DEPTS, "SF": SF}


def q_dials(agents):
    """Manual outbound calls per agent per day, from the call detail records (one row per call)."""
    return """
WITH ag AS (SELECT column1 AS agent FROM VALUES %(values)s)
SELECT ag.agent, c."Call Date"::varchar, COUNT(*)
FROM PROD_DW.DW_SEMANTIC.CALL_DETAIL_FACT c
JOIN ag ON LOWER(SPLIT_PART(c."Call Agent Email Address", '@', 1)) = LOWER(ag.agent)
WHERE c."Call Date" >= '%(start)s' AND c."Call Type" = 'Manual'
GROUP BY 1,2 ORDER BY 1,2
""" % {"values": agent_values(agents), "start": YEAR_START}


def q_csat(agents):
    """Survey responses and satisfied responses per agent per day (this source lists each call twice)."""
    return """
WITH ag AS (SELECT column1 AS agent FROM VALUES %(values)s)
SELECT ag.agent, a."Call Date"::varchar, SUM(a."Survey Count"), SUM(a."CSAT Score")
FROM PROD_DW.DW_SEMANTIC.SMART_ASSIST_AGENT_CALL_ORDER_DETAIL_FACT a
JOIN ag ON LOWER(SPLIT_PART(a."Call Agent Email Address", '@', 1)) = LOWER(ag.agent)
WHERE a."Call Date" >= '%(start)s' AND a."DEPARTMENT" IN %(depts)s
GROUP BY 1,2 HAVING SUM(a."Survey Count") > 0 ORDER BY 1,2
""" % {"values": agent_values(agents), "start": YEAR_START, "depts": DEPTS}


def q_queue(month_start):
    return """
SELECT COUNT(*), COALESCE(SUM(IFF(op."StageName__c"='New',1,0)),0)
FROM %(SF)s."Opportunity_Home__dll" op JOIN %(SF)s."User_Home__dll" u ON op."OwnerId__c" = u."Id__c"
WHERE u."Name__c" = '%(owner)s'
  AND TRY_TO_DATE(LEFT(CAST(op."CreatedDate__c" AS VARCHAR),10)) >= '%(ms)s'
""" % {"SF": SF, "owner": QUEUE_OWNER, "ms": month_start}


# --------------------------------------------------------------------------------------
# Snowflake connection
# --------------------------------------------------------------------------------------
def connect():
    import snowflake.connector
    kw = dict(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
              warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"), role=os.environ.get("SNOWFLAKE_ROLE"),
              database="PROD_DW", session_parameters={"TIMEZONE": "America/New_York"})
    pem = os.environ.get("SNOWFLAKE_PRIVATE_KEY")
    if pem:
        from cryptography.hazmat.primitives import serialization
        pw = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        key = serialization.load_pem_private_key(pem.encode(), password=pw.encode() if pw else None)
        kw["private_key"] = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption())
    else:
        kw["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    return snowflake.connector.connect(**kw)


def run(cur, sql):
    cur.execute(sql)
    return cur.fetchall()


# --------------------------------------------------------------------------------------
# Building the data blocks (pure functions, no Snowflake needed)
# --------------------------------------------------------------------------------------
def read_agents():
    with open(AGENTS, newline="", encoding="utf8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["id"], r["name"], r["team"] = r["id"].strip(), r["name"].strip(), r["team"].strip()
        assert r["team"] in ("CLW", "CNX1", "CNX2", "OFF"), f"bad team for {r['id']}"
    return rows


def day_index(d, base):
    return (d - base).days


def as_date(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def build_raw(agents, rows):
    """RAW block: per agent daily rows from DAILY_START and monthly rows before it."""
    daily = {a["id"]: [] for a in agents}
    monthly = {a["id"]: {} for a in agents}
    for agent, d, ord_, cont, cx, opps, nw in rows:
        d = as_date(d)
        vals = [int(ord_), int(cont), int(cx), int(opps), int(nw)]
        if agent not in daily:
            continue
        if d >= DAILY_START:
            daily[agent].append(f"{day_index(d, DAILY_START)}," + ",".join(map(str, vals)))
        else:
            cur = monthly[agent].setdefault(d.month, [0] * 5)
            for i, v in enumerate(vals):
                cur[i] += v
    out = {}
    for a in agents:
        i = a["id"]
        out[i] = {"d": ";".join(daily[i]),
                  "m": ";".join(f"{mo}," + ",".join(map(str, v)) for mo, v in sorted(monthly[i].items()))}
    return out


def build_dept(rows):
    return ";".join(f"{day_index(as_date(d), YEAR_START)},{int(c)},{int(o)},{int(p)}" for d, c, o, p in rows)


def build_extra(agents, dial_rows, csat_rows):
    ex = {a["id"]: {"d": [], "m": {}, "s": [], "sm": {}} for a in agents}
    for agent, d, n in dial_rows:
        d = as_date(d)
        if agent not in ex:
            continue
        if d >= DAILY_START:
            ex[agent]["d"].append(f"{day_index(d, DAILY_START)},{int(n)}")
        else:
            ex[agent]["m"][d.month] = ex[agent]["m"].get(d.month, 0) + int(n)
    for agent, d, sv, cs in csat_rows:
        d = as_date(d)
        sv, cs = int(sv), int(cs)
        if sv % 2 or cs % 2:      # the source repeats every survey twice; if that stops, do not publish wrong numbers
            raise SystemExit(f"CSAT check failed: odd survey or satisfied count for {agent} on {d}. "
                             "The source may have stopped double counting. Review before publishing.")
        sv, cs = sv // 2, cs // 2
        if agent not in ex:
            continue
        if d >= DAILY_START:
            ex[agent]["s"].append(f"{day_index(d, DAILY_START)},{sv},{cs}")
        else:
            t = ex[agent]["sm"].setdefault(d.month, [0, 0])
            t[0] += sv
            t[1] += cs
    out = {}
    for a, v in ex.items():
        item = {"d": ";".join(v["d"]), "m": ";".join(f"{m},{n}" for m, n in sorted(v["m"].items()))}
        if v["s"]:
            item["s"] = ";".join(v["s"])
        if v["sm"]:
            item["sm"] = ";".join(f"{m},{x[0]},{x[1]}" for m, x in sorted(v["sm"].items()))
        out[a] = item
    return out


def js_object(name, obj):
    return f"const {name} = " + json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + ";"


def replace_block(html, tag, new_text):
    pat = re.compile(r"(/\*GEN:%s\*/\n).*?(\n/\*END:%s\*/)" % (tag, tag), re.S)
    if not pat.search(html):
        raise SystemExit(f"Marker /*GEN:{tag}*/ not found in index.html")
    return pat.sub(lambda m: m.group(1) + new_text + m.group(2), html, count=1)


def set_meta(html, **fields):
    for key, value in fields.items():
        html, n = re.subn(r'%s:"[^"]*"' % key, lambda m: f'{key}:"{value}"', html, count=1)
        if n != 1:
            raise SystemExit(f"META field {key} not found")
    return html


def build_html(html, agents, agent_rows, dept_rows, dial_rows, csat_rows, queue, today, now_et):
    raw = build_raw(agents, agent_rows)
    sold = [as_date(d) for d, c, o, p in dept_rows if int(c) > 0]
    if not sold:
        raise SystemExit("No sales returned for the department. Not publishing.")
    latest = max(sold)
    if (today - latest).days > MAX_STALE_DAYS:
        raise SystemExit(f"Newest sale is {latest}, more than {MAX_STALE_DAYS} days old. Not publishing.")
    # The latest day's leads finish loading overnight, so opportunities are counted through the day before.
    opps_through = latest - dt.timedelta(days=1)
    names = {a["id"]: a["name"] for a in agents}
    roster = {t: [a["id"] for a in agents if a["team"] == t] for t in ("CLW", "CNX1", "CNX2", "OFF")}
    html = replace_block(html, "ROSTER", js_object("ROSTER", roster))
    html = replace_block(html, "NAMES", js_object("NAMES", names))
    html = replace_block(html, "RAW", js_object("RAW", raw))
    html = replace_block(html, "EXTRA", js_object("EXTRA", build_extra(agents, dial_rows, csat_rows)))
    html = replace_block(html, "DEPT", 'const DEPT_RAW = "' + build_dept(dept_rows) + '";')
    html = set_meta(html, latest=latest.isoformat(), oppsThrough=opps_through.isoformat(),
                    updated=now_et.strftime("%b %-d, %Y %-I:%M %p ET"))
    q = {"owner": QUEUE_OWNER, "total": int(queue[0]), "news": int(queue[1]), "month": latest.strftime("%B")}
    html = re.sub(r"queue:\{[^}]*\}", lambda m: "queue:" + json.dumps(q), html, count=1)
    return html, latest


# --------------------------------------------------------------------------------------
def main():
    dry = "--dry-run" in sys.argv
    agents = read_agents()
    now_et = dt.datetime.now(ZoneInfo("America/New_York"))
    today = now_et.date()
    conn = connect()
    try:
        cur = conn.cursor()
        agent_rows = run(cur, q_agent_day(agents))
        dept_rows = run(cur, q_dept_day())
        dial_rows = run(cur, q_dials(agents))
        csat_rows = run(cur, q_csat(agents))
        # Queue owner's opportunities for the month of the newest sale
        sold = [as_date(d) for d, c, o, p in dept_rows if int(c) > 0]
        month_start = max(sold).replace(day=1) if sold else today.replace(day=1)
        queue = run(cur, q_queue(month_start))[0]
    finally:
        conn.close()

    print(f"agent-day rows: {len(agent_rows)}, department days: {len(dept_rows)}, "
          f"dial rows: {len(dial_rows)}, survey rows: {len(csat_rows)}")
    # Safety checks before anything is written
    with_sales = {r[0] for r in agent_rows if int(r[2]) > 0}
    if len(agent_rows) < 1000 or len(with_sales) < 25:
        raise SystemExit(f"Query results look too small ({len(agent_rows)} rows, {len(with_sales)} agents with sales). Not publishing.")

    html = HTML.read_text(encoding="utf8")
    new_html, latest = build_html(html, agents, agent_rows, dept_rows, dial_rows, csat_rows, queue, today, now_et)
    print("newest sale date:", latest)
    if dry:
        print("dry run: nothing written")
        return
    HTML.write_text(new_html, encoding="utf8")
    print("index.html updated")


if __name__ == "__main__":
    main()
