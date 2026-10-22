# Outbound dashboard: automatic morning refresh

Every morning a scheduled job pulls the latest numbers from Snowflake, rebuilds the data inside `index.html`, and publishes it. Nobody has to open a chat or run anything, and it uses no AI tokens.

## What is in this folder

| File | What it does |
|---|---|
| `index.html` | The dashboard. The data blocks between `/*GEN:...*/` and `/*END:...*/` are rewritten on every refresh. Do not edit those blocks by hand. |
| `refresh_dashboard.py` | Runs five read-only queries and rewrites the data blocks. |
| `agents.csv` | Who is in the dashboard and which team they belong to (`CLW`, `CNX1`, `CNX2`, or `OFF` for agents not on the current roster). |
| `.github/workflows/refresh.yml` | The schedule: runs daily at 12:00 UTC (8:00 AM Eastern in summer, 7:00 AM in winter). |
| `requirements.txt` | Python packages the job needs. |

## One-time setup (about an hour, plus waiting on a Snowflake admin)

### 1. Ask a Snowflake admin for a read-only service user

The scheduled job cannot use your personal login, because nobody is there to sign in. Send your admin this:

> Please create a service user for a read-only dashboard refresh, with key-pair login, a small warehouse, and a role that can only read the objects below. Send me the account identifier, user name, role, warehouse, and the private key.

Objects the role must be able to read:

- `PROD_DW.DW_SEMANTIC.ORDER_CONTAINER_SALES_FACT`
- `PROD_DW.DW_SEMANTIC.CALL_DETAIL_FACT`
- `PROD_DW.DW_SEMANTIC.SMART_ASSIST_AGENT_CALL_ORDER_DETAIL_FACT`
- `PROD_SALESFORCE_DATACLOUD."schema_Prod_Salesforce_Objects"."Opportunity_Home__dll"`
- `PROD_SALESFORCE_DATACLOUD."schema_Prod_Salesforce_Objects"."User_Home__dll"`

A template for the admin (names are suggestions; the Salesforce database may need a different grant style, so they should confirm the role can run `python refresh_dashboard.py --dry-run`):

```sql
CREATE ROLE DASHBOARD_READER;
GRANT USAGE ON WAREHOUSE <small_warehouse> TO ROLE DASHBOARD_READER;
GRANT USAGE ON DATABASE PROD_DW TO ROLE DASHBOARD_READER;
GRANT USAGE ON SCHEMA PROD_DW.DW_SEMANTIC TO ROLE DASHBOARD_READER;
GRANT SELECT ON ALL TABLES IN SCHEMA PROD_DW.DW_SEMANTIC TO ROLE DASHBOARD_READER;   -- or the three objects above
GRANT USAGE ON DATABASE PROD_SALESFORCE_DATACLOUD TO ROLE DASHBOARD_READER;
GRANT USAGE ON SCHEMA PROD_SALESFORCE_DATACLOUD."schema_Prod_Salesforce_Objects" TO ROLE DASHBOARD_READER;
GRANT SELECT ON ALL VIEWS IN SCHEMA PROD_SALESFORCE_DATACLOUD."schema_Prod_Salesforce_Objects" TO ROLE DASHBOARD_READER;
CREATE USER DASHBOARD_SVC DEFAULT_ROLE = DASHBOARD_READER DEFAULT_WAREHOUSE = <small_warehouse>
  RSA_PUBLIC_KEY = '<public key>';
GRANT ROLE DASHBOARD_READER TO USER DASHBOARD_SVC;
```

Fallback if you cannot get a service user: run the script on your own computer on a schedule (see "Running it on your own computer" below). It only works while that computer is on and signed in.

### 2. Put the files in GitHub

1. Create a new repository for the dashboard (or a new folder in your existing dashboard repository, but then move `.github/workflows/refresh.yml` to the repository root and add `working-directory: <folder>` to each step).
2. Upload everything from this folder to the repository root, keeping the `.github/workflows` folder.

### 3. Add the secrets

In the repository: **Settings > Secrets and variables > Actions > New repository secret**. Add:

| Secret | Value |
|---|---|
| `SNOWFLAKE_ACCOUNT` | The account identifier from Snowflake (it may look like `pods-edw` or `orgname-accountname`). |
| `SNOWFLAKE_USER` | The service user name. |
| `SNOWFLAKE_PRIVATE_KEY` | The full private key text, including the `BEGIN` and `END` lines. |
| `SNOWFLAKE_PRIVATE_KEY_PASSPHRASE` | Only if the key has a passphrase. |
| `SNOWFLAKE_WAREHOUSE` | The warehouse name. |
| `SNOWFLAKE_ROLE` | `DASHBOARD_READER` (or whatever the admin named it). |

### 4. Turn on the website

**Settings > Pages**: deploy from the `main` branch, root folder. After a minute you get a link such as `https://<account>.github.io/<repository>/`. Share that link with your team.

> **Who can open it:** a standard GitHub Pages link is public to anyone who has the address. The dashboard shows agent names with sales, close rate and cancel rate. Check with IT or HR before sharing outside the company. A private link needs GitHub Enterprise Cloud or a company-hosted page.

### 5. Test it

**Actions tab > Refresh outbound dashboard > Run workflow.** It should finish in a few minutes. Then reload the dashboard: the header line ends with "Data refreshed ... ET" and the date matches today. If it fails, open the run and read the red step; the script's messages say what went wrong.

## What happens each morning

1. The job runs at 12:00 UTC.
2. It pulls data from January 1 through today and rebuilds the data blocks.
3. If anything changed, it commits `index.html`, and GitHub Pages publishes it within a minute or two.
4. If the job fails, GitHub emails the repository owner. The dashboard keeps showing the last good data and the "Data refreshed" stamp tells everyone how old it is.

**Safety checks.** The script refuses to publish, and says why, if: the newest sale is more than 5 days old, the query results are suspiciously small, or the survey data stops being double-counted (the source table currently lists each survey twice, and the script halves it).

**Timing.** The morning job assumes yesterday's orders are loaded by 8:00 AM Eastern. If the run happens before the load finishes, the dashboard shows the day before, and the next day's run catches up. Move the time in `refresh.yml` if needed. Opportunities for the latest day load overnight, so the dashboard counts opportunities through the day before the latest sale; this is deliberate.

## Things you still maintain by hand

- **Agents and teams:** edit `agents.csv` (add a row for a new agent, change the `team` column when someone moves, use `OFF` for agents who left or are not on the roster). Commit the change and run the workflow.
- **AOP targets:** the weekly AOP numbers sit in the `const AOP = {...}` line in `index.html`. Replace that line when the plan changes. It is not touched by the refresh.
- **Team leads and colors:** the `TEAMS` block near the top of the script section in `index.html`.
- **Next year:** the dashboard is built for calendar 2026 (start dates and the AOP week numbering). It needs a new version for 2027.
- **A new agent not matching in Salesforce:** the script links each sales login to Salesforce by the first characters of the alias. If an agent's opportunities show as zero, send the login and Salesforce name to whoever maintains the script.

## Running it on your own computer

```
pip install -r requirements.txt
set SNOWFLAKE_ACCOUNT=...        (macOS or Linux: export instead of set)
set SNOWFLAKE_USER=...
set SNOWFLAKE_PASSWORD=...       (or SNOWFLAKE_PRIVATE_KEY)
set SNOWFLAKE_WAREHOUSE=...
set SNOWFLAKE_ROLE=...
python refresh_dashboard.py --dry-run   (checks the queries and the data, writes nothing)
python refresh_dashboard.py             (rewrites index.html)
```

Then commit and push `index.html`. To schedule it, use Windows Task Scheduler (or cron) to run the last command each morning followed by `git add index.html`, `git commit`, and `git push`.

## What was tested

- Each query was run against Snowflake with a short date window and returned data in the expected shape.
- The data-block builder was tested by rebuilding today's dashboard data from its own rows, and the result is identical, including the survey halving and the safety checks.
- The rebuilt page loads without errors and shows the same totals as the current dashboard.
- Not tested: the connection from GitHub itself, because it needs your service user. The first manual run in step 5 is that test.
