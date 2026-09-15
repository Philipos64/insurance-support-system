import logging
from typing import Dict, Any, List
from database import get_db_connection

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('insurance_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- TOOL 1: Ask User ---
def ask_user(question: str, missing_info: str = ""):
    """Ask the user for input and return the response."""
    return {"context": input(f"{question}: "), "source": "User Input"}

# --- TOOL 2: Policy Details (FIXED MAPPING) ---
def get_policy_details(policy_number: str) -> Dict[str, Any]:
    """Fetch a customer's policy details by policy number"""
    logger.info(f"Fetching policy details for: {policy_number}")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # We perform an explicit SELECT to get exactly what we need
            cursor.execute("""
                SELECT p.policy_type, p.status, c.first_name, c.last_name, c.email
                FROM policies p
                JOIN customers c ON p.customer_id = c.customer_id
                WHERE p.policy_number = %s
            """, (policy_number,))
            result = cursor.fetchone()

            if result:
                logger.info(f"Policy found: {policy_number}")
                # MANUALLY MAP DB COLUMNS TO AGENT KEYS
                return {
                    "type": result[0],          # Maps policy_type -> type
                    "status": result[1],
                    "customer_name": f"{result[2]} {result[3]}", # Combines names
                    "email": result[4]
                }

            logger.warning(f"Policy not found: {policy_number}")
            return {"error": "Policy not found"}

# --- TOOL 3: Claim Status ---
def get_claim_status(claim_id: str = None, policy_number: str = None) -> Dict[str, Any]:
    """Get claim status and details"""
    logger.info(f"Fetching claim status")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if claim_id:
                cursor.execute("""
                    SELECT claim_id, status, estimated_loss, incident_type
                    FROM claims WHERE claim_id = %s
                """, (claim_id,))
                result = cursor.fetchone()
                if result:
                     return {
                         "claim_id": result[0],
                         "status": result[1],
                         "amount": float(result[2]),
                         "type": result[3]
                     }
            elif policy_number:
                cursor.execute("""
                    SELECT claim_id, status, estimated_loss, incident_type
                    FROM claims WHERE policy_number = %s LIMIT 3
                """, (policy_number,))
                results = cursor.fetchall()
                if results:
                    return [
                        {"claim_id": r[0], "status": r[1], "amount": float(r[2]), "type": r[3]}
                        for r in results
                    ]

            return {"error": "Claim not found"}

# --- TOOL 4: Billing Info ---
def get_billing_info(policy_number: str = None) -> Dict[str, Any]:
    """Get billing information"""
    logger.info(f"Fetching billing info for: {policy_number}")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT status, amount_due, due_date
                FROM billing
                WHERE policy_number = %s AND status = 'pending'
                ORDER BY due_date DESC LIMIT 1
            """, (policy_number,))
            result = cursor.fetchone()

            if result:
                return {
                    "status": result[0],
                    "amount_due": float(result[1]),
                    "due_date": str(result[2])
                }

            return {"error": "No pending bills found"}

# --- TOOL 5: Payment History ---
def get_payment_history(policy_number: str) -> List[Dict[str, Any]]:
    """Get payment history"""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT p.payment_date, p.amount, p.status, p.payment_method
                FROM payments p
                JOIN billing b ON p.bill_id = b.bill_id
                WHERE b.policy_number = %s
                ORDER BY p.payment_date DESC LIMIT 5
            """, (policy_number,))

            results = cursor.fetchall()
            if results:
                return [{"date": str(r[0]), "amount": float(r[1]), "status": r[2]} for r in results]
            return []

# --- TOOL 6: Auto Details ---
def get_auto_policy_details(policy_number: str) -> Dict[str, Any]:
    """Get vehicle details"""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT vehicle_make, vehicle_model, vehicle_year, vehicle_vin
                FROM auto_policy_details
                WHERE policy_number = %s
            """, (policy_number,))
            result = cursor.fetchone()
            if result:
                return {
                    "make": result[0],
                    "model": result[1],
                    "year": result[2],
                    "vin": result[3]
                }
            return {"error": "Vehicle details not found"}