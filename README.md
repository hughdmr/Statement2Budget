# Statement2Budget

Outil personnel qui catégorise automatiquement les transactions d'un relevé bancaire Société Générale et remplit un template de budget mensuel, en s'appuyant sur un LLM (Llama 3.3 70B via Groq).

## Fonctionnement

1. **Lecture du relevé** — Le CSV exporté depuis l'espace SG est chargé et nettoyé (filtrage des virements internes, paris sportifs, etc.).
2. **Few-shot prompting** — Des exemples de relevés déjà catégorisés (mois précédents) sont injectés dans le prompt pour guider le modèle.
3. **Appel LLM** — Le prompt est envoyé à l'API Groq ; le modèle retourne les transactions triées par catégorie au format CSV.
4. **Écriture du budget** — Le résultat est écrit dans une copie du template XLSX à deux tableaux (Dépenses / Revenus).

## Arborescence

```
.
├── main.py                  # Script principal (chargement, prompt, sauvegarde)
├── call_llm.py              # Appel à l'API Groq
├── config.py                # Configuration (clés API, modèle)
├── categories.json          # Catégories dépenses / revenus + mots exclus
├── requirements.txt
├── data/
│   ├── inputs/
│   │   ├── sog_releve/           # Relevés bancaires SG (CSV bruts)
│   │   └── exemples_budget/      # Budgets déjà catégorisés (few-shot)
│   ├── outputs/                  # Budgets générés (.xlsx)
│   └── template/
│       └── template_a_remplir.xlsx
```

## Installation

```bash
git clone <repo-url> && cd Statement2Budget
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine :

```env
GROQ_API_KEY=gsk_...
MODEL=llama-3.3-70b-versatile   # optionnel, valeur par défaut
```

## Utilisation

```bash
# Traiter un relevé
python main.py data/inputs/sog_releve/fevrier2026.csv

# Spécifier un chemin de sortie
python main.py data/inputs/sog_releve/fevrier2026.csv -o mon_budget.xlsx
```

### Options

| Argument | Description |
|---|---|
| `releve` | Chemin vers le relevé CSV SG à traiter (obligatoire) |
| `-o`, `--output` | Chemin de sortie xlsx (par défaut : `data/outputs/budget_<nom_releve>.xlsx`) |

## Catégories

Les catégories sont définies dans [categories.json](categories.json) et peuvent être modifiées librement.

**Dépenses** : ...

**Revenus** : ...

## Stack technique

- **Python 3.10+**
- **pandas** — manipulation des CSV
- **openpyxl** — écriture XLSX
- **Groq SDK** — appel au LLM (Llama 3.3 70B)
- **python-dotenv** — gestion des variables d'environnement
