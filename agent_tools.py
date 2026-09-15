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


# ---------------------------------------------------------------
# Statements are named so the interface can show exactly what ran.
# Every one is parameterised: user text can only ever be a value,
# never syntax. See docs/design-notes.md.
# ---------------------------------------------------------------

SQL_POLICY_DETAILS = """
                SELECT p.policy_type, p.status, c.first_name, c.last_name, c.email
                FROM policies p
                JOIN customers c ON p.customer_id = c.customer_id
                WHERE p.policy_number = %s
            """

SQL_CLAIM_BY_ID = """
                    SELECT claim_id, status, estimated_loss, incident_type
                    FROM claims WHERE claim_id = %s
                """

SQL_CLAIMS_BY_POLICY = """
                    SELECT claim_id, status, estimated_loss, incident_type
                    FROM claims WHERE policy_number = %s LIMIT 3
                """

SQL_BILLING_PENDING = """
                SELECT status, amount_due, due_date
                FROM billing
                WHERE policy_number = %s AND status = 'pending'
                ORDER BY due_date DESC LIMIT 1
            """

# Maps a tool name to the statement(s) it can issue, for the trace view.
TOOL_SQL = {
    "get_policy_details": {"by policy_number": SQL_POLICY_DETAILS},
    "get_claim_status": {"by claim_id": SQL_CLAIM_BY_ID,
                         "by policy_number": SQL_CLAIMS_BY_POLICY},
    "get_billing_info": {"by policy_number": SQL_BILLING_PENDING},
}

# --- TOOL 1: Policy details ---
def get_policy_details(policy_number: str) -> Dict[str, Any]:
    """Fetch a customer's policy details by policy number"""
    logger.info(f"Fetching policy details for: {policy_number}")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # We perform an explicit SELECT to get exactly what we need
            cursor.execute(SQL_POLICY_DETAILS, (policy_number,))
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

# --- TOOL 2: Claim status ---
def get_claim_status(claim_id: str = None, policy_number: str = None) -> Dict[str, Any]:
    """Get claim status and details"""
    logger.info(f"Fetching claim status")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if claim_id:
                cursor.execute(SQL_CLAIM_BY_ID, (claim_id,))
                result = cursor.fetchone()
                if result:
                     return {
                         "claim_id": result[0],
                         "status": result[1],
                         "amount": float(result[2]),
                         "type": result[3]
                     }
            elif policy_number:
                cursor.execute(SQL_CLAIMS_BY_POLICY, (policy_number,))
                results = cursor.fetchall()
                if results:
                    return [
                        {"claim_id": r[0], "status": r[1], "amount": float(r[2]), "type": r[3]}
                        for r in results
                    ]

            return {"error": "Claim not found"}

# --- TOOL 3: Billing info ---
def get_billing_info(policy_number: str = None) -> Dict[str, Any]:
    """Get billing information"""
    logger.info(f"Fetching billing info for: {policy_number}")

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(SQL_BILLING_PENDING, (policy_number,))
            result = cursor.fetchone()

            if result:
                return {
                    "status": result[0],
                    "amount_due": float(result[1]),
                    "due_date": str(result[2])
                }

            return {"error": "No pending bills found"}
