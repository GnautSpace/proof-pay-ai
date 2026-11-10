import os, time
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
import paypal_client as pp
from agent import split_chunks, run_worker, verify

st.set_page_config(page_title="AuraLock", page_icon="🔒", layout="wide")
st.title("🔒 AuraLock: pay-per-proof compute")
st.caption("Workers only get paid when their output passes verification. "
           "Failed steps pay nothing and unspent escrow is always refunded.")

WORKERS = [e.strip() for e in os.getenv("WORKER_EMAILS", "").split(",") if e.strip()]
if not WORKERS:
    st.error("Set WORKER_EMAILS in .env"); st.stop()

SAMPLE = ("Payments are moving from human clicks to autonomous software. "
          "When an agent buys compute or data on your behalf, trust becomes the bottleneck. "
          "Escrow lets a buyer lock funds before work starts. Verification lets the system "
          "check each piece of work independently. Micro-payouts release money in small "
          "increments so that no single failure can drain the whole budget. "
          "Refunds return whatever was never earned. Together these primitives make "
          "pay-as-you-go machine labor safe for strangers to trade with each other. "
          "The same pattern applies to rendering, retrieval, labeling and inference jobs.")

ss = st.session_state
for k, v in {"order_id": None, "capture_id": None, "deposit": 0.0,
             "approve_url": None, "ledger": []}.items():
    ss.setdefault(k, v)

task = st.text_area("Job input (a long text to process)", SAMPLE, height=200)
c1, c2, c3 = st.columns(3)
n = c1.slider("Verified steps", 3, 6, 5)
price = c2.number_input("Price per step (USD)", 0.10, 5.00, 0.50, 0.10)
sabotage = c3.selectbox("Make a worker cheat at…", [0] + list(range(1, n + 1)),
                        format_func=lambda x: "nobody" if x == 0 else f"step {x}")
mode = st.radio("When a worker fails a step",
                ["Halt the job", "Reassign to next worker"], horizontal=True)
use_judge = st.checkbox("Also use AI judge (extra API calls)", value=False)
with st.expander("Acceptance rules: what a worker must pass to get paid", expanded=True):
    r1, r2, r3 = st.columns(3)
    max_chars = r1.slider("Max summary length (chars)", 100, 500, 300, 10)
    min_ground = r2.slider("Min key terms found in source", 0, 3, 2)
    banned_text = r3.text_input("Banned words (comma separated)", "")
rules = {"max_summary_chars": max_chars,
         "min_grounded_terms": min_ground,
         "banned_words": banned_text.split(",")}
budget = round(n * price, 2)

st.subheader(f"1) Fund escrow: ${budget:.2f}")
if st.button("Create escrow order"):
    order = pp.create_escrow_order(budget, os.getenv("RETURN_URL", "https://example.com"))
    ss.order_id, ss.deposit = order["id"], budget
    ss.approve_url, ss.capture_id = pp.approval_link(order), None

if ss.order_id and not ss.capture_id:
    st.link_button("Open PayPal and approve (log in as the sandbox BUYER)", ss.approve_url)
    if st.button("I approved, capture the funds"):
        ss.capture_id = pp.capture_order(ss.order_id)
        st.rerun()

if ss.capture_id:
    st.success(f"Escrow funded: ${ss.deposit:.2f} (capture {ss.capture_id})")

st.subheader("2) Run the job")
if st.button("▶ Run job", disabled=not ss.capture_id):
    if round(n * price, 2) > ss.deposit:
        st.error("Budget exceeds the funded escrow. Create a new escrow order."); st.stop()
    chunks = split_chunks(task, n)
    paid, ss.ledger = 0.0, []
    try:
        for i, chunk in enumerate(chunks, 1):
            step_done = False
            for attempt in range(len(WORKERS)):
                worker = WORKERS[(i - 1 + attempt) % len(WORKERS)]
                cheat = (sabotage == i and attempt == 0)
                with st.status(f"Step {i}/{len(chunks)}: worker {worker}", expanded=True) as status:
                    out, h = run_worker(chunk, cheat)
                    checks = verify(chunk, out, h, use_judge, rules)
                    st.json({"output": out, "hash": h[:16] + "...", "checks": checks})
                    if all(checks.values()):
                        batch = pp.send_payout(worker, price, f"AuraLock step {i}",
                                               f"aura-{ss.order_id[:8]}-{i}-{attempt}-{int(time.time())}")
                        paid = round(paid + price, 2)
                        ss.ledger.append({"step": i, "worker": worker, "result": "PAID",
                                          "usd": price, "payout_batch": batch})
                        status.update(label=f"Step {i} verified → paid ${price:.2f}", state="complete")
                        step_done = True
                    else:
                        ss.ledger.append({"step": i, "worker": worker, "result": "FAILED, NOT PAID",
                                          "usd": 0, "payout_batch": "-"})
                        status.update(label=f"Step {i} FAILED by {worker}", state="error")
                if step_done or mode == "Halt the job":
                    break
            if not step_done:
                st.error(f"Step {i} could not be completed. Halting job.")
                break
    except Exception as e:
        st.error(f"Job crashed: {str(e)[:300]}")
        ss.ledger.append({"step": "-", "worker": "SYSTEM", "result": "CRASH, HALTED",
                          "usd": 0, "payout_batch": "-"})
    finally:
        refund_amt = round(ss.deposit - paid, 2)
        if refund_amt > 0:
            try:
                rid = pp.refund_capture(ss.capture_id, refund_amt)
                ss.ledger.append({"step": "-", "worker": "BUYER", "result": "REFUNDED",
                                  "usd": refund_amt, "payout_batch": rid})
            except Exception as e:
                st.error(f"Refund failed: {str(e)[:300]}")
        st.success(f"Paid to workers: ${paid:.2f} | Refunded to you: ${max(refund_amt, 0):.2f}")
        ss.order_id = ss.capture_id = None

if ss.ledger:
    st.subheader("Ledger")
    st.dataframe(ss.ledger, use_container_width=True)
