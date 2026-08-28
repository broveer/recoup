"""
Recoup v0.3.0 - Live Webhook Recovery Test Runner
Posts authentic Razorpay 'payment.failed' webhook events to the server and observes the recovery actions.
"""

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import time
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(force_terminal=True, safe_box=True)

# 3 Realistic Razorpay Webhook Payloads
WEBHOOK_PAYLOADS = [
    {
        "entity": "event",
        "account_id": "acc_78xHjKl90",
        "event": "payment.failed",
        "contains": ["payment", "order"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RZP_Live_90112",
                    "entity": "payment",
                    "amount": 349900,  # ₹3,499.00 in paise
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_RZP_88102",
                    "method": "card",
                    "email": "rahul.verma@example.com",
                    "contact": "+919876543210",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Customer session expired during OTP 3DS authentication.",
                    "error_reason": "otp_expired",
                    "notes": {
                        "customer_name": "Rahul Verma",
                        "cltv_inr": "12000.0",
                        "tier": "standard"
                    }
                }
            },
            "order": {
                "entity": {
                    "id": "order_RZP_88102",
                    "amount": 349900,
                    "currency": "INR",
                    "status": "attempted"
                }
            }
        },
        "created_at": int(time.time())
    },
    {
        "entity": "event",
        "account_id": "acc_78xHjKl90",
        "event": "payment.failed",
        "contains": ["payment", "order"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RZP_Live_90113",
                    "entity": "payment",
                    "amount": 189900,  # ₹1,899.00 in paise
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_RZP_88103",
                    "method": "upi",
                    "email": "aditi.sharma@example.com",
                    "contact": "+919811223344",
                    "error_code": "GATEWAY_ERROR",
                    "error_description": "NPCI switch timed out during UPI communication with issuing bank.",
                    "error_reason": "bank_downtime",
                    "notes": {
                        "customer_name": "Aditi Sharma",
                        "cltv_inr": "18500.0",
                        "tier": "standard"
                    }
                }
            },
            "order": {
                "entity": {
                    "id": "order_RZP_88103",
                    "amount": 189900,
                    "currency": "INR",
                    "status": "attempted"
                }
            }
        },
        "created_at": int(time.time())
    },
    {
        "entity": "event",
        "account_id": "acc_78xHjKl90",
        "event": "payment.failed",
        "contains": ["payment", "order"],
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_RZP_Live_90114",
                    "entity": "payment",
                    "amount": 99900,  # ₹999.00 in paise
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_RZP_88104",
                    "method": "card",
                    "email": "vikram.singh@example.com",
                    "contact": "+919712345678",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Card validity date has passed (Expired 07/26).",
                    "error_reason": "card_expired",
                    "notes": {
                        "customer_name": "Vikram Singh",
                        "cltv_inr": "999.0",
                        "tier": "new"
                    }
                }
            },
            "order": {
                "entity": {
                    "id": "order_RZP_88104",
                    "amount": 99900,
                    "currency": "INR",
                    "status": "attempted"
                }
            }
        },
        "created_at": int(time.time())
    }
]


def run_live_webhook_tests():
    console.print("\n[bold cyan]====================================================================[/bold cyan]")
    console.print("[bold yellow]      🚀 RECOUP v0.3.0 - LIVE RAZORPAY WEBHOOK INGESTION TEST       [/bold yellow]")
    console.print("[bold cyan]====================================================================[/bold cyan]\n")

    base_url = "http://127.0.0.1:8000"

    with httpx.Client(timeout=30.0) as client:
        # Check server health
        try:
            health = client.get(f"{base_url}/health")
            console.print(f"[bold green]Connected to Webhook Server:[/bold green] {health.json()}\n")
        except Exception:
            console.print("[bold red]Webhook server is not running on http://127.0.0.1:8000. Start it with: uvicorn webhook_server:app --port 8000[/bold red]\n")
            return

        for idx, payload in enumerate(WEBHOOK_PAYLOADS, 1):
            p_entity = payload["payload"]["payment"]["entity"]
            tx_id = p_entity["id"]
            amt = p_entity["amount"] / 100.0
            cust = p_entity["notes"]["customer_name"]
            err = p_entity["error_reason"]

            console.print(f"[bold white on blue] TEST EVENT {idx} [/bold white on blue] Triggering Razorpay Webhook for [bold]{tx_id}[/bold] (₹{amt:,.2f}, {cust})")
            
            response = client.post(f"{base_url}/webhook/razorpay", json=payload)
            data = response.json()

            table = Table(show_header=True, header_style="bold magenta", expand=True)
            table.add_column("Property", style="cyan", width=24)
            table.add_column("Value & Live Output", style="white")

            table.add_row("HTTP Status Code", f"[green]{response.status_code}[/green]")
            table.add_row("AI Recommendation", f"[bold yellow]{data.get('ai_recommendation')}[/bold yellow]")
            table.add_row("Enforced Final Action", f"[bold green]{data.get('enforced_action')}[/bold green]")

            execution = data.get("execution", {})
            if "payment_link" in execution:
                plink = execution["payment_link"]
                table.add_row("Razorpay Payment Link", f"[bold underline cyan]{plink.get('short_url')}[/bold underline cyan] (ID: {plink.get('id')})")
                table.add_row("Notification Channels", "[green]WhatsApp + SMS Enabled[/green]")
            elif "retry_delay_seconds" in execution:
                table.add_row("Dynamic Backoff", f"[yellow]Scheduled silent retry in {execution['retry_delay_seconds']}s[/yellow]")
            else:
                table.add_row("Action Status", f"[red]{execution.get('status')}[/red]")

            console.print(table)
            console.print("-" * 75 + "\n")

        # Fetch aggregated metrics
        metrics = client.get(f"{base_url}/api/metrics").json()
        console.print(Panel(
            f"[bold green]Total Events Processed:[/bold green] {metrics.get('total_events_processed')}\n"
            f"[bold green]Total Revenue at Risk:[/bold green] ₹{metrics.get('total_revenue_at_risk_inr'):,.2f}\n"
            f"[bold cyan]Payment Links Created:[/bold cyan] {metrics.get('payment_links_generated')}\n"
            f"[bold red]Hard Stops Enforced:[/bold red] {metrics.get('hard_stops_enforced')}",
            title="[bold yellow]Live Server Recovery Metrics[/bold yellow]",
            border_style="cyan"
        ))


if __name__ == "__main__":
    run_live_webhook_tests()
