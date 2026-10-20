"""Curated links to official cannabis health guidance; no scraping or model-generated URLs."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Guide:
    title: str
    context: str
    links: tuple[tuple[str, str], ...]

GUIDES = {
    "overview": Guide("Cannabis & cannabinoids",
        "Start with definitions, medical-use research and known uncertainties.",
        (("NIH NCCIH: Cannabis and Cannabinoids",
          "https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know"),
         ("CDC: Cannabis Health Effects",
          "https://www.cdc.gov/cannabis/health-effects/index.html"))),
    "health": Guide("General health risks",
        "Learn about memory, dependence, mental health, impairment and risk factors.",
        (("CDC: Cannabis Health Effects",
          "https://www.cdc.gov/cannabis/health-effects/index.html"),
         ("CDC: Cannabis FAQ", "https://www.cdc.gov/cannabis/faq/"))),
    "heart": Guide("Heart health",
        "Explore cardiovascular effects and uncertainties in available research.",
        (("CDC: Cannabis and Heart Health",
          "https://www.cdc.gov/cannabis/health-effects/heart-health.html"),)),
    "lungs": Guide("Smoking and lung health",
        "Read about smoke exposure, symptoms and remaining knowledge gaps.",
        (("CDC: Cannabis and Lung Health",
          "https://www.cdc.gov/cannabis/health-effects/lung-health.html"),)),
    "medicines": Guide("FDA-approved medicines",
        "Understand the difference between approved cannabinoid drugs and unapproved cannabis products.",
        (("FDA: Cannabis Research and Drug Approval",
          "https://www.fda.gov/news-events/public-health-focus/fda-and-cannabis-research-and-drug-approval-process"),
         ("NIH NCCIH: Cannabis and Cannabinoids",
          "https://www.nccih.nih.gov/health/cannabis-marijuana-and-cannabinoids-what-you-need-to-know"))),
    "products": Guide("CBD product safety",
        "Read FDA guidance about CBD labeling, contaminants and unapproved claims.",
        (("FDA: Consumer Guide to Cannabis and CBD",
          "https://www.fda.gov/consumers/consumer-updates/what-you-need-know-and-what-were-working-find-out-about-products-containing-cannabis-or-cannabis"),)),
}

def guide_message(topic: str) -> str:
    """Link directory only. Never scrape, diagnose, infer benefit or invent sources."""
    entry = GUIDES.get(topic)
    if not entry:
        return "Unknown guide. Select a topic from the menu."
    lines = [f"**Official Science Guide | {entry.title}**", entry.context, "",
             "**NIH / CDC / FDA references:**"]
    for title, url in entry.links:
        lines.extend([f"• {title}", f"  {url}"])
    lines.extend(["", "Official sources are for education, not individualized medical advice. "
                        "Review linked pages for their latest details."])
    return "\n".join(lines)
