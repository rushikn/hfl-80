import os
import streamlit as st
from dotenv import load_dotenv


# Load environment variables early
load_dotenv()

# Ensure OPENAI_API_KEY is set in environment before importing LangChain
os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

import pyodbc
import openai
from dynamic_sql_generation import generate_sql_from_nl
import re
import contractions

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DRIVER = os.getenv("Driver")
SERVER = os.getenv("Server")
DATABASE = os.getenv("Database")
UID = os.getenv("UID")
PWD = os.getenv("PWD")

openai.api_key = OPENAI_API_KEY

# Define column data types for Dw.fsales table
COLUMN_TYPES = {
    "DId": "int",
    "BillingDocument": "varchar",
    "BillingDocumentItem": "varchar",
    "BillingDate": "date",
    "SalesOfficeID": "int",
    "DistributionChannel": "varchar",
    "DisivisonCode": "varchar",
    "Route": "varchar",
    "RouteDescription": "varchar",
    "CustomerGroup": "varchar",
    "CustomerID": "varchar",
    "ProductHeirachy1": "varchar",
    "ProductHeirachy2": "varchar",
    "ProductHeirachy3": "varchar",
    "ProductHeirachy4": "varchar",
    "ProductHeirachy5": "varchar",
    "Materialgroup": "varchar",
    "SubMaterialgroup1": "varchar",
    "SubMaterialgroup2": "varchar",
    "SubMaterialgroup3": "varchar",
    "MaterialCode": "varchar",
    "SalesQuantity": "int",
    "SalesUnit": "varchar",
    "TotalAmount": "decimal",
    "TotalTax": "decimal",
    "NetAmount": "decimal",
    "EffectiveStartDate": "date",
    "EffectiveEndDate": "date",
    "IsActive": "bit",
    "SalesOrganizationCode": "varchar",
    "SalesOrgCodeDesc": "varchar",
    "ItemCategory": "varchar",
    "ShipToParty": "varchar"
}

import re

def fix_sql_value_quoting(sql_query):
    # Step 1: Fix broken values like 'ICE 'Cream'/FD'
    broken_value_fixes = {
        "ICE 'Cream'/FD": "ICE CREAM/FD",
        "ICE 'Cream' / FD": "ICE CREAM/FD",
        "'ICE 'Cream'/FD'": "'ICE CREAM/FD'",
    }
    for broken, correct in broken_value_fixes.items():
        sql_query = sql_query.replace(broken, correct)

    # Step 2: Replace ProductHeirachy1 with Materialgroup if "icecream/fd" or "icecream/fp" is mentioned
    if re.search(r"(ice[\s]?cream\s*/(fd|fp))", sql_query, re.IGNORECASE):
        sql_query = re.sub(
            r"(ProductHeirachy1\s*=\s*'[^']*')",
            "Materialgroup = 'ICE CREAM/FD'",
            sql_query,
            flags=re.IGNORECASE
        )
    elif re.search(r"\bice\s+cream\b", sql_query, re.IGNORECASE):
        sql_query = re.sub(
            r"(Materialgroup\s*=\s*'[^']*')",
            "ProductHeirachy1 = 'IceCream'",
            sql_query,
            flags=re.IGNORECASE
        )

    # Step 3: Fix quotes based on column data types
    for column, col_type in COLUMN_TYPES.items():
        pattern = re.compile(rf"({column}\s*=\s*)'([^']*)'", re.IGNORECASE)

        def replacer(match):
            prefix = match.group(1)
            value = match.group(2)
            if col_type in ['int', 'decimal', 'bit']:
                if value.isdigit() or value.lower() in ['true', 'false', '0', '1']:
                    return f"{prefix}{value}"
                else:
                    return match.group(0)
            else:
                return match.group(0)

        sql_query = pattern.sub(replacer, sql_query)

    return sql_query



import re

def validate_sql_query(sql_query):
    # Step 0: Clean leading SQL-like prefixes (e.g., "SQL:", "```sql", etc.)
    sql_query = sql_query.strip()
    sql_query = re.sub(r"^\s*(SQL:?|```sql)?\s*", "", sql_query, flags=re.IGNORECASE)

    # Optional: remove trailing ``` block or semicolon
    sql_query = re.sub(r"```$", "", sql_query).strip()
    sql_query = sql_query.rstrip(";").strip()

    # Step 1: Check for placeholder or example values in the SQL query
    placeholders = ['specific_salesofficeid', 'example_value', 'placeholder']
    for ph in placeholders:
        if ph.lower() in sql_query.lower():
            return False, f"SQL query contains placeholder value: {ph}"

    return True, ""


def execute_sql_query(sql_query):
    try:
        connection_string = (
            f"DRIVER={{{DRIVER}}};"
            f"SERVER={SERVER};"
            f"DATABASE={DATABASE};"
            f"UID={UID};"
            f"PWD={PWD}"
        )
        with pyodbc.connect(connection_string, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(sql_query)
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            results = [dict(zip(columns, row)) for row in rows]
            return results
    except Exception:
        st.error("please restart your HFL server, It’s not able to fetch data right now because of heavy load.")
        return None

import re
import openai
import streamlit as st

def results_to_natural_language(results, user_query):
    if not results:
        return "Please wait."

    # Extract headers and format markdown table
    column_headers = list(results[0].keys()) if isinstance(results[0], dict) else [f"Col{i+1}" for i in range(len(results[0]))]
    table_rows = [column_headers] + [
        [str(row.get(col, '')) if isinstance(row, dict) else str(val) for col, val in zip(column_headers, row)]
        for row in results[:10]
    ]

    def format_markdown_table(rows):
        header = "| " + " | ".join(rows[0]) + " |"
        separator = "| " + " | ".join(['---'] * len(rows[0])) + " |"
        body = "\n".join("| " + " | ".join(row) + " |" for row in rows[1:])
        return "\n".join([header, separator, body])

    results_str = format_markdown_table(table_rows)

    # System prompt to reduce typos and ensure clear output
    system_prompt = (
        "You are a precise and intelligent business analytics assistant. "
        "display every thing that present in output result"
        "Your role is to interpret SQL query results and provide clear, concise summaries in plain English. "
        "Always describe what the result represents, including the metric, product, region, and time period if available. "
        "Use symbols (like %, ₹, ↑, ↓) and relevant emojis (like 📈, 📊, 🛒) to make the response more understandable and engaging. "
        "Avoid any assumptions not backed by the data. "
        "If the result is a percentage, always show it with the % symbol. "
        "If the result represents a change, clearly show the increase/decrease with arrows and values."
    )

    prompt_text = (
         f"User query: \"{user_query}\"\n\n"
        f"SQL query result:\n\n{results_str}\n\n"
        "display every thing that present in output result."
        "Based on the above result and the user query, provide a clear and direct summary. "
         "Your role is to interpret SQL query results and provide clear, concise summaries in plain English. "
        "Include relevant metric, product, region, and time frame. "
        "Use symbols (% for percentages, ↑ for increase, ↓ for decrease) and emojis (📈 for growth, 📉 for decline, 🛒 for product/sales, etc.) where appropriate. but never use rupee and dollar symbol"
        "Keep the response concise,user query relevent, and based only on the query result.\n\n"
        "Answer:"
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=250,
            temperature=0.2,
            top_p=1.0,
            frequency_penalty=0.0,
            presence_penalty=0.0,
        )
        summary = response.choices[0].message['content'].strip()

        # Optional cleanup
        units = ["$ USD", "€ EUR", "£ GBP", "₹ INR", "¥ JPY", "₩ KRW", "KG", "G", "L", "ML", "Units", "$"]
        for unit in units:
            summary = summary.replace(unit, "")
        summary = re.sub(r'\d+\.\d+', lambda m: str(int(float(m.group()))), summary)

        return summary

    except Exception as e:
        return f"Error generating summary: {e}"
custom_stop_words = {
    'rushi'
}
def remove_custom_stop_words(query, stop_words):
    tokens = query.lower().split()  # lowercase + split
    filtered = [word for word in tokens if word not in stop_words]
    return " ".join(filtered)

def main():
    st.set_page_config(page_title="AskHFL", page_icon="🗄️", layout="centered")
    st.title("Ask Heritage ")

    user_query = st.text_area("Enter your query:")

    sql_query = None  # Initialize sql_query to avoid UnboundLocalError

    if st.button("Run Query"):
        if not user_query.strip():
            st.warning("Please enter a query.")
            return

        with st.spinner("Translating to SQL..."):
            # Preprocess the user query before generating SQL
            #preprocessed_query = contractions.fix(user_query)
            preprocessed_query =  remove_custom_stop_words(user_query, custom_stop_words)
        # Generate SQL from preprocessed query
        sql_query = generate_sql_from_nl(preprocessed_query)

        # Fix SQL value quoting based on column types and other fixes
        sql_query = fix_sql_value_quoting(sql_query)

        print(f"Generated SQL Query: {sql_query}")
        # Removed display of generated SQL query to hide it from front end for elegance
        # st.subheader("Generated SQL Query:")
        # st.code(sql_query, language="sql")

    # Validate SQL query for placeholders
    if sql_query is None:
        st.warning("No SQL query generated.")
        return

    valid, error_msg = validate_sql_query(sql_query)
    if not valid:
        st.error(error_msg)
        return

    with st.spinner("Executing... Its a bit slow, please wait searching in you database."):
        try:
            results = execute_sql_query(sql_query)
        except Exception:
            st.error("please restart your HFL server, It’s not able to fetch data right now because of heavy load.")
            return

    if results is not None:
        st.subheader("Result:")
        summary = results_to_natural_language(results, user_query)
        st.write(summary)

if __name__ == "__main__":
    main()
