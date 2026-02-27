import pandas as pd
import os
import argparse
import json
from datetime import datetime
from copy import copy
from call_llm import call_llm

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Configuration -----------------------------------------------------------

def load_config() -> dict:
    """Charge categories.json (catégories + exclusions)."""
    with open(os.path.join(BASE_DIR, 'categories.json'), encoding='utf-8') as f:
        return json.load(f)

CONFIG = load_config()

# --- Chargement des données --------------------------------------------------

def load_releve(filepath: str) -> pd.DataFrame:
    """Charge un relevé bancaire SG et filtre les transactions exclues."""
    df = pd.read_csv(filepath, sep=';', skiprows=2, encoding='latin-1', decimal=',')
    df.columns = ['Date', 'Libelle', 'Detail', 'Montant', 'Devise']

    exclusions = CONFIG.get('exclusions', [])
    mask = df['Detail'].str.upper().apply(lambda d: not any(p in d for p in exclusions))
    return df[mask].reset_index(drop=True)


def load_budget_csv(filepath: str) -> dict:
    """Parse un budget CSV (deux tableaux côte à côte) en dépenses / revenus."""
    df = pd.read_csv(filepath, encoding='utf-8', header=None, skiprows=3)

    depenses = df.iloc[1:, 1:5].copy()
    depenses.columns = ['Date', 'Montant', 'Description', 'Catégorie']
    depenses = depenses.dropna(how='all').reset_index(drop=True)

    revenus = df.iloc[1:, 6:10].copy()
    revenus.columns = ['Date', 'Montant', 'Description', 'Catégorie']
    revenus = revenus.dropna(how='all').reset_index(drop=True)

    return {'depenses': depenses, 'revenus': revenus}


def load_exemples() -> dict:
    """Charge les exemples (few-shot) depuis data/inputs/."""
    releves_dir = os.path.join(BASE_DIR, 'data', 'inputs', 'sog_releve')
    budgets_dir = os.path.join(BASE_DIR, 'data', 'inputs', 'exemples_budget')
    exemples = {}

    if not os.path.exists(releves_dir) or not os.path.exists(budgets_dir):
        return exemples

    releves = [f for f in os.listdir(releves_dir) if f.endswith('.csv')]
    budgets = [f for f in os.listdir(budgets_dir) if f.endswith('.csv')]

    for releve_file in releves:
        month = releve_file.replace('.csv', '').rstrip('0123456789')
        year = releve_file.replace('.csv', '')[len(month):]
        budget_file = next((b for b in budgets if month in b.lower() and year in b), None)
        if budget_file:
            exemples[month] = {
                'releve': load_releve(os.path.join(releves_dir, releve_file)),
                'budget': load_budget_csv(os.path.join(budgets_dir, budget_file)),
            }
    return exemples

# --- Prompt ------------------------------------------------------------------

def build_prompt(releve: pd.DataFrame, exemples: dict) -> str:
    """Construit le prompt pour le LLM."""
    cats_dep = ', '.join(CONFIG['depenses'])
    cats_rev = ', '.join(CONFIG['revenus'])

    prompt = f"""Tu es un assistant comptable. Je te donne un relevé bancaire mensuel et tu dois catégoriser chaque transaction.

Catégories DÉPENSES : {cats_dep}
Catégories REVENUS : {cats_rev}
ATTENTION : ne mélange jamais les catégories entre dépenses et revenus.

"""
    if exemples:
        prompt += "Exemples de relevés déjà catégorisés :\n"
        for month, data in exemples.items():
            ex_releve = data['releve'][['Date', 'Detail', 'Montant']].to_csv(index=False, sep=';')
            ex_dep = data['budget']['depenses'].to_csv(index=False, sep=';')
            ex_rev = data['budget']['revenus'].to_csv(index=False, sep=';')
            prompt += f"\n--- Exemple {month} ---\nRelevé:\n{ex_releve}\nDÉPENSES:\n{ex_dep}\nREVENUS:\n{ex_rev}\n"

    releve_str = releve[['Date', 'Detail', 'Montant']].to_csv(index=False, sep=';')
    prompt += f"""
Relevé à traiter :
{releve_str}

Instructions : catégorise chaque transaction en te basant sur les exemples. Ne modifie ni les dates, ni les descriptions, ni les montants.

IMPORTANT : retourne UNIQUEMENT le CSV brut (séparateur ;), sans phrase ni markdown :
--- DÉPENSES ---
Date;Montant;Description;Catégorie
...

--- REVENUS ---
Date;Montant;Description;Catégorie
...
"""
    return prompt

# --- Parsing de la réponse LLM -----------------------------------------------

def parse_llm_output(text: str) -> tuple[list, list]:
    """Parse la sortie du LLM en listes de [Date, Montant, Description, Catégorie]."""
    depenses, revenus = [], []
    section = None

    for line in text.strip().splitlines():
        s = line.strip()
        if not s:
            continue
        upper = s.upper()
        if 'DÉPENSES' in upper or 'DEPENSES' in upper:
            section = 'dep'; continue
        if 'REVENUS' in upper:
            section = 'rev'; continue
        if s.lower().startswith('date'):
            continue

        parts = s.split(';') if ';' in s else s.split(',')
        if len(parts) >= 4:
            row = [p.strip() for p in parts[:4]]
            (depenses if section == 'dep' else revenus).append(row)

    return depenses, revenus

# --- Écriture du xlsx --------------------------------------------------------

def fill_xlsx(depenses: list, revenus: list, template_path: str, output_path: str):
    """Remplit une copie du template xlsx avec les transactions catégorisées."""
    import openpyxl

    wb = openpyxl.load_workbook(template_path)
    ws = wb['Transactions']

    # Copier les styles de la ligne 5 (première ligne de données)
    def copy_style(cell):
        return {
            'font': copy(cell.font), 'border': copy(cell.border),
            'fill': copy(cell.fill), 'number_format': cell.number_format,
            'alignment': copy(cell.alignment),
        }

    cols = ['B', 'C', 'D', 'E', 'G', 'H', 'I', 'J']
    styles = {c: copy_style(ws[f'{c}5']) for c in cols}

    # Effacer les données existantes (à partir de la ligne 5)
    for row in range(5, ws.max_row + 1):
        for c in cols:
            ws[f'{c}{row}'].value = None

    def parse_date(s):
        try:
            return datetime.strptime(s.strip(), '%d/%m/%Y')
        except (ValueError, AttributeError):
            return s

    def parse_montant(s):
        try:
            return abs(float(str(s).replace(',', '.')))
        except (ValueError, TypeError):
            return 0.0

    def write_rows(rows, col_letters, start_row=5):
        for i, row in enumerate(rows):
            r = start_row + i
            ws[f'{col_letters[0]}{r}'] = parse_date(row[0])
            ws[f'{col_letters[1]}{r}'] = parse_montant(row[1])
            ws[f'{col_letters[2]}{r}'] = row[2]
            ws[f'{col_letters[3]}{r}'] = row[3]
            for c in col_letters:
                for attr, val in styles[c].items():
                    setattr(ws[f'{c}{r}'], attr, val)

    write_rows(depenses, ['B', 'C', 'D', 'E'])
    write_rows(revenus, ['G', 'H', 'I', 'J'])

    wb.save(output_path)

# --- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Catégorise un relevé bancaire SG dans un budget xlsx')
    parser.add_argument('releve', help='Chemin vers le relevé bancaire CSV')
    parser.add_argument('-o', '--output', help='Chemin de sortie xlsx')
    args = parser.parse_args()

    # Charger le relevé
    print(f"Chargement du relevé : {args.releve}")
    releve = load_releve(args.releve)
    print(f"{len(releve)} transactions chargées")

    # Charger les exemples (few-shot)
    exemples = load_exemples()

    # Construire le prompt et appeler le LLM
    prompt = build_prompt(releve, exemples)
    print("Appel au LLM...")
    result = call_llm(prompt)

    # Parser et remplir le xlsx
    depenses, revenus = parse_llm_output(result)
    print(f"{len(depenses)} dépenses, {len(revenus)} revenus catégorisés")

    template_xlsx = os.path.join(BASE_DIR, 'data', 'template', 'template_a_remplir.xlsx')
    if args.output:
        output_path = args.output
    else:
        name = os.path.splitext(os.path.basename(args.releve))[0]
        output_path = os.path.join(BASE_DIR, 'data', 'outputs', f'budget_{name}.xlsx')

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fill_xlsx(depenses, revenus, template_xlsx, output_path)
    print(f"Budget sauvegardé : {output_path}")


if __name__ == "__main__":
    main()