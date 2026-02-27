import Groq from "groq-sdk";

// --- Catégories et exclusions (miroir de categories.json) --------------------

const CATEGORIES = {
  depenses: [
    "Alimentation", "Cadeaux", "Santé/médecine", "Habitation", "Transports",
    "Dépenses personnelles", "Animaux de compagnie", "Électricité, eau, gaz...",
    "Voyage", "Avec Adèle", "Autres", "Remboursements", "Restaurants", "Bars",
  ],
  revenus: [
    "Épargne", "Salaire", "Bonus", "Intérêts", "Autres", "Remboursements", "Maman",
  ],
  exclusions: [
    "HUGUES D'HARDEMARE", "HUGUES D HARDEMARE",
    "WINAMAX", "BETCLIC", "FDJ", "UNIBET", "BETTING", "SOBRIO",
  ],
};

// --- Parse du CSV Société Générale -------------------------------------------

function parseSGCsv(text) {
  const lines = text.split(/\r?\n/);
  const transactions = [];
  let dataStarted = false;

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;

    // On repère la ligne d'en-tête (commence par "Date")
    if (!dataStarted) {
      if (trimmed.toLowerCase().startsWith("date")) dataStarted = true;
      continue;
    }

    const parts = trimmed.split(";");
    if (parts.length < 5) continue;

    const [date, , detail, montant] = parts;
    const upperDetail = (detail || "").toUpperCase();

    if (CATEGORIES.exclusions.some((p) => upperDetail.includes(p))) continue;

    transactions.push({
      date: date.trim(),
      detail: detail.trim(),
      montant: montant.trim(),
    });
  }

  return transactions;
}

// --- Construction du prompt --------------------------------------------------

function buildPrompt(transactions) {
  const catsDep = CATEGORIES.depenses.join(", ");
  const catsRev = CATEGORIES.revenus.join(", ");

  const csvLines = transactions.map((t) => `${t.date};${t.detail};${t.montant}`);
  const releveCsv = "Date;Detail;Montant\n" + csvLines.join("\n");

  return `Tu es un assistant comptable. Je te donne un relevé bancaire mensuel et tu dois catégoriser chaque transaction.

Catégories DÉPENSES : ${catsDep}
Catégories REVENUS : ${catsRev}
ATTENTION : ne mélange jamais les catégories entre dépenses et revenus.

Relevé à traiter :
${releveCsv}

Instructions : catégorise chaque transaction. Les montants négatifs sont des dépenses, les positifs des revenus. Ne modifie ni les dates, ni les descriptions, ni les montants.

IMPORTANT : retourne UNIQUEMENT le CSV brut (séparateur ;), sans phrase ni markdown :
--- DÉPENSES ---
Date;Montant;Description;Catégorie
...

--- REVENUS ---
Date;Montant;Description;Catégorie
...`;
}

// --- Parse de la réponse LLM -------------------------------------------------

function parseLLMOutput(text) {
  const depenses = [];
  const revenus = [];
  let section = null;

  for (const line of text.split(/\r?\n/)) {
    const s = line.trim();
    if (!s) continue;

    const upper = s.toUpperCase();
    if (upper.includes("DÉPENSES") || upper.includes("DEPENSES")) { section = "dep"; continue; }
    if (upper.includes("REVENUS")) { section = "rev"; continue; }
    if (s.toLowerCase().startsWith("date")) continue;

    const parts = s.includes(";") ? s.split(";") : s.split(",");
    if (parts.length >= 4) {
      const row = {
        date: parts[0].trim(),
        montant: parts[1].trim(),
        description: parts[2].trim(),
        categorie: parts[3].trim(),
      };
      if (section === "dep") depenses.push(row);
      else if (section === "rev") revenus.push(row);
    }
  }

  return { depenses, revenus };
}

// --- Handler Netlify Function ------------------------------------------------

export async function handler(event) {
  // CORS preflight
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
  };

  if (event.httpMethod === "OPTIONS") {
    return { statusCode: 204, headers, body: "" };
  }

  if (event.httpMethod !== "POST") {
    return { statusCode: 405, headers, body: JSON.stringify({ error: "Method not allowed" }) };
  }

  try {
    const { csv } = JSON.parse(event.body);
    if (!csv) {
      return { statusCode: 400, headers, body: JSON.stringify({ error: "Contenu CSV requis" }) };
    }

    const transactions = parseSGCsv(csv);
    if (transactions.length === 0) {
      return { statusCode: 400, headers, body: JSON.stringify({ error: "Aucune transaction trouvée dans le CSV" }) };
    }

    const prompt = buildPrompt(transactions);

    const client = new Groq({ apiKey: process.env.GROQ_API_KEY });
    const response = await client.chat.completions.create({
      model: process.env.MODEL || "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: prompt }],
      temperature: 0.1,
    });

    const raw = response.choices[0].message.content;
    const { depenses, revenus } = parseLLMOutput(raw);

    return {
      statusCode: 200,
      headers,
      body: JSON.stringify({ depenses, revenus, transactionCount: transactions.length }),
    };
  } catch (err) {
    console.error(err);
    return {
      statusCode: 500,
      headers,
      body: JSON.stringify({ error: err.message }),
    };
  }
}
