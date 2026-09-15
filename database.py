import os
import psycopg
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
from dotenv import load_dotenv

# 1. Load Secrets
load_dotenv()

# 2. Setup Connection
def get_db_connection():
    """Connects to PostgreSQL using Psycopg 3"""
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT")
    )

# 3. YOUR Data Generation Code (Exact copy from notebook)
def generate_sample_data(random_state=42):
    """Generate enriched sample data for all tables with 50 first/last names"""
    random.seed(random_state)
    np.random.seed(random_state)

    # Define 50 first and last names
    first_names = [
        "John", "Jane", "Robert", "Maria", "David", "Lisa", "Michael", "Sarah", "James", "Emily",
        "William", "Emma", "Joseph", "Olivia", "Charles", "Ava", "Thomas", "Isabella", "Daniel", "Mia",
        "Matthew", "Sophia", "Anthony", "Charlotte", "Christopher", "Amelia", "Andrew", "Harper",
        "Joshua", "Evelyn", "Ryan", "Abigail", "Brandon", "Ella", "Justin", "Scarlett", "Tyler", "Grace",
        "Alexander", "Chloe", "Kevin", "Victoria", "Jason", "Lily", "Brian", "Hannah", "Eric", "Aria",
        "Kyle", "Zoey"
    ]

    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
        "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"
    ]

    # Generate customers (1000 random name combinations)
    customers = pd.DataFrame({
        'customer_id': [f'CUST{str(i).zfill(5)}' for i in range(1, 1001)],
        'first_name': [random.choice(first_names) for _ in range(1000)],
        'last_name': [random.choice(last_names) for _ in range(1000)],
        'email': [f'user{i}@example.com' for i in range(1, 1001)],
        'phone': [f'555-{str(random.randint(100,999)).zfill(3)}-{str(random.randint(1000,9999)).zfill(4)}' for _ in range(1000)],
        'date_of_birth': [datetime(1980, 1, 1) + timedelta(days=random.randint(0, 10000)) for _ in range(1000)],
        'state': [random.choice(['CA', 'NY', 'TX', 'FL', 'IL', 'PA', 'OH', 'GA']) for _ in range(1000)]
    })

    # Policies
    policies = pd.DataFrame({
        'policy_number': [f'POL{str(i).zfill(6)}' for i in range(1, 1501)],
        'customer_id': [f'CUST{str(random.randint(1, 1000)).zfill(5)}' for _ in range(1500)],
        'policy_type': [random.choice(['auto', 'home', 'life']) for _ in range(1500)],
        'start_date': [datetime(2023, 1, 1) + timedelta(days=random.randint(0, 365)) for _ in range(1500)],
        'premium_amount': [round(random.uniform(50, 500), 2) for _ in range(1500)],
        'billing_frequency': [random.choice(['monthly', 'quarterly', 'annual']) for _ in range(1500)],
        'status': [random.choice(['active', 'active', 'active', 'cancelled']) for _ in range(1500)]
    })

    # Auto Policy Details (subset)
    auto_policies = policies[policies['policy_type'] == 'auto'].copy()
    auto_policy_details = pd.DataFrame({
        'policy_number': auto_policies['policy_number'],
        'vehicle_vin': [f'VIN{random.randint(10000000000000000, 99999999999999999)}' for _ in range(len(auto_policies))],
        'vehicle_make': [random.choice(['Toyota', 'Honda', 'Ford', 'Chevrolet', 'Nissan']) for _ in range(len(auto_policies))],
        'vehicle_model': [random.choice(['Camry', 'Civic', 'F-150', 'Malibu', 'Altima']) for _ in range(len(auto_policies))],
        'vehicle_year': [random.randint(2015, 2023) for _ in range(len(auto_policies))],
        'liability_limit': [random.choice([50000, 100000, 300000]) for _ in range(len(auto_policies))],
        'collision_deductible': [random.choice([250, 500, 1000]) for _ in range(len(auto_policies))],
        'comprehensive_deductible': [random.choice([250, 500, 1000]) for _ in range(len(auto_policies))],
        'uninsured_motorist': [random.choice([0, 1]) for _ in range(len(auto_policies))],
        'rental_car_coverage': [random.choice([0, 1]) for _ in range(len(auto_policies))]
    })

    # Billing
    billing = pd.DataFrame({
        'bill_id': [f'BILL{str(i).zfill(6)}' for i in range(1, 5001)],
        'policy_number': [random.choice(policies['policy_number']) for _ in range(5000)],
        'billing_date': [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(5000)],
        'due_date': [datetime(2024, 1, 15) + timedelta(days=random.randint(0, 90)) for _ in range(5000)],
        'amount_due': [round(random.uniform(100, 1000), 2) for _ in range(5000)],
        'status': [random.choice(['paid', 'pending', 'overdue']) for _ in range(5000)]
    })

    # Payments
    payments = pd.DataFrame({
        'payment_id': [f'PAY{str(i).zfill(6)}' for i in range(1, 4001)],
        'bill_id': [random.choice(billing['bill_id']) for _ in range(4000)],
        'payment_date': [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(4000)],
        'amount': [round(random.uniform(50, 500), 2) for _ in range(4000)],
        'payment_method': [random.choice(['credit_card', 'debit_card', 'bank_transfer']) for _ in range(4000)],
        'transaction_id': [f'TXN{random.randint(100000,999999)}' for _ in range(4000)],
        'status': [random.choice(['completed', 'pending', 'failed']) for _ in range(4000)]
    })

    # Claims
    claims = pd.DataFrame({
        'claim_id': [f'CLM{str(i).zfill(6)}' for i in range(1, 301)],
        'policy_number': [random.choice(policies['policy_number']) for _ in range(300)],
        'claim_date': [datetime(2024, 1, 1) + timedelta(days=random.randint(0, 90)) for _ in range(300)],
        'incident_type': [random.choice(['collision', 'theft', 'property_damage', 'medical', 'liability']) for _ in range(300)],
        'estimated_loss': [round(random.uniform(500, 20000), 2) for _ in range(300)],
        'status': [random.choice(['submitted', 'under_review', 'approved', 'paid', 'denied']) for _ in range(300)]
    })

    return {
        'customers': customers,
        'policies': policies,
        'auto_policy_details': auto_policy_details,
        'billing': billing,
        'payments': payments,
        'claims': claims,
    }

# 4. Database Initialization Logic (Postgres Specific)
def init_database():
    print("Creating Database Schema in PostgreSQL...")
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS claims CASCADE;")
            cur.execute("DROP TABLE IF EXISTS payments CASCADE;")
            cur.execute("DROP TABLE IF EXISTS billing CASCADE;")
            cur.execute("DROP TABLE IF EXISTS auto_policy_details CASCADE;")
            cur.execute("DROP TABLE IF EXISTS policies CASCADE;")
            cur.execute("DROP TABLE IF EXISTS customers CASCADE;")

            cur.execute("""
                CREATE TABLE customers (
                    customer_id VARCHAR(20) PRIMARY KEY,
                    first_name VARCHAR(50),
                    last_name VARCHAR(50),
                    email VARCHAR(100),
                    phone VARCHAR(20),
                    date_of_birth DATE,
                    state VARCHAR(20)
                );
            """)

            cur.execute("""
                CREATE TABLE policies (
                    policy_number VARCHAR(20) PRIMARY KEY,
                    customer_id VARCHAR(20),
                    policy_type VARCHAR(50),
                    start_date DATE,
                    premium_amount DECIMAL(10,2),
                    billing_frequency VARCHAR(20),
                    status VARCHAR(20),
                    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
                );
            """)

            # Note: Using INTEGER for boolean flags because generated data is 0/1 ints
            cur.execute("""
                CREATE TABLE auto_policy_details (
                    policy_number VARCHAR(20) PRIMARY KEY,
                    vehicle_vin VARCHAR(50),
                    vehicle_make VARCHAR(50),
                    vehicle_model VARCHAR(50),
                    vehicle_year INTEGER,
                    liability_limit DECIMAL(10,2),
                    collision_deductible DECIMAL(10,2),
                    comprehensive_deductible DECIMAL(10,2),
                    uninsured_motorist INTEGER,
                    rental_car_coverage INTEGER,
                    FOREIGN KEY (policy_number) REFERENCES policies(policy_number)
                );
            """)

            cur.execute("""
                CREATE TABLE billing (
                    bill_id VARCHAR(20) PRIMARY KEY,
                    policy_number VARCHAR(20),
                    billing_date DATE,
                    due_date DATE,
                    amount_due DECIMAL(10,2),
                    status VARCHAR(20),
                    FOREIGN KEY (policy_number) REFERENCES policies(policy_number)
                );
            """)

            cur.execute("""
                CREATE TABLE payments (
                    payment_id VARCHAR(20) PRIMARY KEY,
                    bill_id VARCHAR(20),
                    payment_date DATE,
                    amount DECIMAL(10,2),
                    payment_method VARCHAR(50),
                    transaction_id VARCHAR(100),
                    status VARCHAR(20),
                    FOREIGN KEY (bill_id) REFERENCES billing(bill_id)
                );
            """)

            cur.execute("""
                CREATE TABLE claims (
                    claim_id VARCHAR(20) PRIMARY KEY,
                    policy_number VARCHAR(20),
                    claim_date DATE,
                    incident_type VARCHAR(100),
                    estimated_loss DECIMAL(10,2),
                    status VARCHAR(20),
                    FOREIGN KEY (policy_number) REFERENCES policies(policy_number)
                );
            """)
            print("Tables created successfully.")

def populate_database():
    data = generate_sample_data()
    print("Inserting Data into PostgreSQL...")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            def insert_df(df, table_name):
                columns = ",".join(df.columns)
                # Psycopg 3 uses %s as placeholder
                placeholders = ",".join(["%s"] * len(df.columns))
                sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"

                # Convert DataFrame to list of tuples (handles numpy types cleanly)
                values = df.to_numpy().tolist()

                cur.executemany(sql, values)
                print(f"   -> Inserted {len(values)} rows into {table_name}")

            # Insert order matters (Parents first)
            insert_df(data['customers'], 'customers')
            insert_df(data['policies'], 'policies')
            insert_df(data['auto_policy_details'], 'auto_policy_details')
            insert_df(data['billing'], 'billing')
            insert_df(data['payments'], 'payments')
            insert_df(data['claims'], 'claims')

            conn.commit()
    print("Database Population Complete!")

if __name__ == "__main__":
    init_database()
    populate_database()