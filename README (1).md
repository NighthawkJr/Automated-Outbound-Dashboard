# PODS Outbound Dashboard

The dashboard link always shows whatever `index.html` was loaded into this repository most recently. The newest file you load replaces the old one, whatever version number it carries.

**Link:** https://nighthawkjr.github.io/Automated-Outbound-Dashboard/

## Which file the page reads

- The page reads **one file only: `index.html`, at the top level of the `main` branch.**
- The newest `index.html` committed here is the one that is live. Nothing else is needed, and older copies do not matter once they are replaced.
- The "Dashboard version" number in the page header is only a label for whoever built the file. **Do not use it to decide whether the page is current.** Use the two date lines described below.
- Any other file in this repository (`agents.csv`, `refresh_dashboard.py`, `requirements.txt`, and any other `.html` file) is ignored by the page.

## Daily update (about 2 minutes)

1. Get the newest `index.html` for the day and open it in Notepad.
2. Press **Ctrl + A**, then **Ctrl + C** to copy everything.
3. In this repository, open `index.html` and select the **pencil icon**.
4. Click in the large box, press **Ctrl + A** to select the old contents, then **Ctrl + V** to paste the new ones.
5. Select **Commit changes**, then **Commit changes** again in the pop-up.
6. Wait two to three minutes, then open the link above in a private window and press **Ctrl + F5**.

Edit the existing file, as above. Do not upload a renamed copy: a name such as `index (1).html` or `index.html.html` is a different file, and the page will not read it.

## How to tell the page is the newest one

Read the line under the title, "Outbound Performance." It has three parts. The page is current when all three are true:

| Part | What it should say |
|---|---|
| **Orders booked through** | The most recent day with orders, normally yesterday. Monday morning, it is the weekend day or Friday with the latest orders. |
| **Data refreshed** | The date and time the person who built the file gave you. It must match the message that came with the file. |
| **Opportunities counted through** | The same day as the orders, or one day earlier. Leads for the latest day finish loading overnight, so this is not an error. |

If the "Data refreshed" time is older than the file you loaded, GitHub is serving an earlier copy. See the problems list below.

**Why the latest day can look incomplete.** Orders for yesterday are complete. Opportunities created yesterday are still loading, so the newest day shows a smaller opportunity count. This lowers the opportunities-to-AOP percentage and raises close rate for that day, and it corrects itself in the next day's file. Day and week views of the latest day are the most affected. Use the month view for decisions.

## Common problems

| What you see | Cause | Fix |
|---|---|---|
| Page says **404** | There is no file named exactly `index.html` at the top level. | Check the file list. Fix the name (no spaces, no second `.html`). |
| Old dates still show | The file in GitHub is an older copy, or the browser is holding a saved copy. | Open the raw file (`index.html` > **Raw**) and search for the "Data refreshed" time. If it is old, paste the new file again. If it is new, open the link in a private window and press **Ctrl + F5**. |
| New file name has a number, like `(1)` | Your computer renamed a repeat download. | Do not upload it. Open it in Notepad and paste its contents into the existing `index.html`. |
| File shows `index.html.html` | The extension was typed twice on rename. | Open the file, select the pencil icon, and delete the extra `.html` in the name box. |
| Update does not appear after several minutes | GitHub has not finished publishing. | Open the **Actions** tab. The top "pages build and deployment" run needs a green check. |
| Columns look wrong or the page is blank | The paste was cut short. | Press **Ctrl + End** in the raw file. The last line must be `</html>`. If it is not, paste the whole file again. |

## How weekly numbers are counted

- **Week view = the last completed Monday-to-Sunday week** on or before the "Through" date.
- **Orders, containers, dials and surveys** are for those Monday to Sunday days.
- **Opportunities** are the ones created the **previous Friday through Thursday**, because Friday is when the team works the funnel for the prior days' workload. For the week of Oct 19 to Oct 25, that is opportunities created Oct 16 to Oct 22.
- The weekly tracker under "Progress to AOP" uses the same pairing.
- Day, Month, Quarter, Year to date and Custom views count opportunities by the day they were created.

**Why Snowflake can show fewer opportunities than Salesforce.** Opportunity counts here are by *current owner*. Snowflake does not keep ownership history. When a supervisor or another user takes over a lead after it was assigned to an agent, it leaves that agent's count, and it does not come back. A Salesforce report pulled earlier still shows the lead with the agent. The leads are not missing from Snowflake; they now belong to someone else.

## Who can open the link

The link is public: anyone who has the address can open it. The dashboard shows agent names with sales, close rate, cancel rate, dials and CSAT. Confirm with IT or HR who may receive the link before sharing it outside the company.

## What the numbers are

- **Adjusted total** = opportunities minus those still in New.
- **Close rate** = orders divided by adjusted total.
- **Conversion** = containers divided by adjusted total.
- **Containers per order** = containers divided by orders.
- **7-day cancel** = orders cancelled within 7 days of booking, divided by orders booked at least 7 days earlier. Benchmark: under 10%.
- **AOP** = weekly targets from the plan file, spread across Monday to Friday, compared with the whole outbound department.

The page also has a "How these numbers are calculated" section at the bottom.

## Automatic refresh (optional, not in use)

The files `refresh_dashboard.py`, `agents.csv`, `requirements.txt` and `.github/workflows/refresh.yml` can refresh the page every morning from Snowflake. They need a read-only Snowflake login that IT must approve, so they are not active. Until then, the page updates only when a new `index.html` is loaded, as described above.
