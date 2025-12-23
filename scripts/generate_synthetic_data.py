import json
import random
from pathlib import Path


def slugify(value: str) -> str:
    cleaned = ''.join(ch.lower() if ch.isalnum() else '-' for ch in value.strip())
    while '--' in cleaned:
        cleaned = cleaned.replace('--', '-')
    return cleaned.strip('-')


def load_config(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def build_firms(config: dict) -> list:
    markets = config["markets"]
    prefixes = config["company_name_prefixes"]
    suffixes = config["company_name_suffixes"]
    services_pool = config["services_pool"]
    specialties_pool = config["specialties_pool"]

    firms = []
    for m_idx, market in enumerate(markets):
        for i in range(config["firm_count_per_market"]):
            name = f"{prefixes[i % len(prefixes)]} {market['name']} {suffixes[i % len(suffixes)]}"
            services = random.sample(services_pool, k=4)
            specialties = random.sample(specialties_pool, k=3)
            firms.append({
                "company_name": name,
                "website": f"https://www.{slugify(name)}.com",
                "market": market["name"],
                "main_phone": f"(555) {m_idx}{i}0-{1000 + i}",
                "services": services,
                "specialties": specialties,
            })
    return firms


def build_contacts(config: dict, firms: list) -> dict:
    universities_by_market = config["universities_by_market"]
    cross_unis = config["cross_market_universities"]
    professional_groups = config["professional_groups"]
    first_names = config["first_names"]
    last_names = config["last_names"]
    headline_pool = config["headline_pool"]

    contacts = {}
    contact_index = 0
    for firm in firms:
        market = firm["market"]
        for _ in range(config["contacts_per_firm"]):
            name = f"{random.choice(first_names)} {random.choice(last_names)}"
            key = f"{slugify(name)}-{contact_index}"
            contact_index += 1

            enriched = random.random() < config["enriched_rate"]
            education = []
            base_unis = universities_by_market.get(market, [])
            if base_unis:
                education.append({"school": random.choice(base_unis)})
            if random.random() < config["extra_education_rate"]:
                education.append({"school": random.choice(cross_unis)})

            groups = random.sample(professional_groups, k=random.choice(config["group_count_choices"]))

            contacts[key] = {
                "name": name,
                "linkedin_url": f"https://www.linkedin.com/in/{key}",
                "headline": random.choice(headline_pool),
                "location": f"{market}, {next(m['state'] for m in config['markets'] if m['name'] == market)}",
                "current_company": firm["company_name"],
                "education": education,
                "groups": groups,
                "about": config["about_text"],
                "enriched": enriched,
            }
    return contacts


def build_graph(firms: list, contacts: dict) -> dict:
    nodes = []
    edges = []
    node_ids = set()

    def add_node(node_id: str, node_type: str, label: str, attributes=None):
        if node_id in node_ids:
            return
        node_ids.add(node_id)
        nodes.append({
            "id": node_id,
            "type": node_type,
            "label": label,
            "attributes": attributes or {},
        })

    def add_edge(edge_type: str, from_id: str, to_id: str, attributes=None):
        edges.append({
            "id": f"{edge_type}:{from_id}->{to_id}",
            "type": edge_type,
            "from": from_id,
            "to": to_id,
            "attributes": attributes or {},
        })

    for firm in firms:
        company_id = f"company:{slugify(firm['company_name'])}"
        add_node(company_id, "Company", firm["company_name"], {
            "website": firm.get("website", ""),
            "services": firm.get("services", []),
            "specialties": firm.get("specialties", []),
            "market": firm.get("market", ""),
        })
        market_id = f"market:{slugify(firm['market'])}"
        add_node(market_id, "Market", firm["market"])
        add_edge("operates_in", company_id, market_id)

    for key, person in contacts.items():
        person_id = f"person:{slugify(key)}"
        add_node(person_id, "Person", person["name"], {
            "headline": person.get("headline", ""),
            "location": person.get("location", ""),
            "linkedin_url": person.get("linkedin_url", ""),
            "enriched": person.get("enriched", False),
        })

        company_name = person.get("current_company", "")
        if company_name:
            company_id = f"company:{slugify(company_name)}"
            add_node(company_id, "Company", company_name)
            add_edge("employed_by", person_id, company_id)

        for group in person.get("groups", []):
            if not group:
                continue
            group_id = f"group:{slugify(group)}"
            add_node(group_id, "Group", group)
            add_edge("member_of", person_id, group_id)

        for edu in person.get("education", []):
            school = edu.get("school", "").strip()
            if not school:
                continue
            uni_id = f"university:{slugify(school)}"
            add_node(uni_id, "University", school)
            add_edge("educated_at", person_id, uni_id)

    return {"nodes": nodes, "edges": edges}


def main():
    config_path = Path("config/synthetic.json")
    config = load_config(config_path)
    random.seed(config["seed"])

    firms = build_firms(config)
    contacts = build_contacts(config, firms)
    graph = build_graph(firms, contacts)

    outputs = config["outputs"]
    Path(outputs["firms_js"]).write_text(
        "window.firms = " + json.dumps(firms, indent=2) + ";\n", encoding="utf-8"
    )
    Path(outputs["contacts_js"]).write_text(
        "window.contacts = " + json.dumps(contacts, indent=2) + ";\n", encoding="utf-8"
    )
    Path(outputs["graph_json"]).write_text(
        json.dumps(graph, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Generated {len(firms)} firms, {len(contacts)} contacts.")


if __name__ == "__main__":
    main()
