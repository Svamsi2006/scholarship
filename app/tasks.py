"""Task prompts/templates – profile-driven, no student-specific hardcoding, strict evidence rules."""

from __future__ import annotations

import json
from typing import Any

from app.models import Candidate, RankedOpportunity, StudentProfile, VerifiedOpportunity


def _today() -> str:
    # Explicit anchor per project specification: Oct 22, 2026
    return "2026-10-22"


def profile_analysis_prompt(
    resume_text: str,
    marksheet_text: str,
    github_data: dict | None,
    extra_links: list[str],
    form_fields: dict,
) -> str:
    github_section = ""
    if github_data and "error" not in github_data:
        github_section = f"\n\n## GitHub Profile\n```json\n{json.dumps(github_data, indent=2)}\n```"

    links_section = ""
    if extra_links:
        links_section = "\n\n## Extra Links (LinkedIn, Portfolio, etc.)\n" + "\n".join(f"- {link}" for link in extra_links)

    form_section = "\n\n## Form Inputs\n"
    for k, v in form_fields.items():
        if v:
            form_section += f"- {k}: {v}\n"

    return f"""Analyze the following student documents, GitHub repositories, and links to build a complete StudentProfile JSON object.

## Resume
{resume_text or '[No resume provided]'}

## Marksheet / Transcripts
{marksheet_text or '[No marksheet provided]'}
{github_section}
{links_section}
{form_section}

STRICT PROFILE EXTRACTION RULES:
1. Extract ALL facts present in the inputs above without hallucination.
2. SKILLS & PROJECTS MUST BE POPULATED: If GitHub profile or resume data is available, you MUST actively extract and populate the "skills" (languages, frameworks, tools) and "projects" (name, description, tech stack) arrays. DO NOT output empty arrays if repositories or resume text exist.
3. CITIZENSHIP VS TARGET COUNTRY: Explicitly extract "citizenship" (e.g. "Indian", "German", "Nigerian") or default to "International". Set "residency_status" (e.g. "Non-Resident", "Citizen"). NEVER assume target_countries (e.g. ["USA"]) means the student is a US citizen.
4. Extract "linkedin_url" and "portfolio_url" from links if provided.
5. For each field, record its source in field_sources (e.g. "resume", "marksheet", "github", "form", "links").
6. Form fields override document-derived values for target_level, target_fields, target_countries, funding_need, citizenship.
7. Compute gaps: things commonly required for scholarship eligibility but missing (e.g. no English test score, missing GRE, unstated graduation year).
8. Today's date: {_today()}

Return valid JSON conforming to the StudentProfile schema."""


def query_planner_prompt(
    profile: StudentProfile,
    round_number: int = 1,
    tried_queries: list[str] | None = None,
    feedback: str = "",
) -> str:
    countries = ", ".join(profile.target_countries) if profile.target_countries else "USA, Germany, UK, Canada"
    fields = ", ".join(profile.target_fields) if profile.target_fields else "Computer Science"
    level = profile.target_level or "Masters"

    tried_section = ""
    if tried_queries:
        tried_section = "\nAlready tried queries (do NOT repeat):\n" + "\n".join(f"- {q}" for q in tried_queries[-15:])

    feedback_section = f"\nFeedback from previous round:\n{feedback}" if feedback else ""

    return f"""You are an Academic Scholarship Research Specialist.
Formulate Google Dork and web search queries to find graduate scholarships, fellowships, and assistantships.

Candidate Profile:
- Round: {round_number}
- Degree Level: {level}
- Target Fields: {fields}
- Target Countries: {countries}
- Citizenship: {profile.citizenship or 'International'} (Residency: {profile.residency_status or 'Non-Resident'})
- Funding Need: {profile.funding_need}
{feedback_section}
{tried_section}

CRITICAL RULES FOR SCHOLARSHIP QUERIES:
1. NEVER include programming tools, libraries, or markup languages (e.g., "Jupyter Notebook", "HTML", "TypeScript", "Python", "CSS", "JavaScript", "React") in scholarship queries. Scholarships NEVER grant awards based on git repo languages!
2. Focus strictly on:
   - Degree Level: "{level}" OR "Graduate" OR "MS"
   - Academic Domain: "{fields}"
   - Funding Type: "fully funded", "graduate research assistantship", "teaching assistantship", "tuition waiver", "fellowship", "stipend"
   - Country / Nationality Eligibility: "international students"
   - Target Countries: {countries}
3. Exclude non-matching demographics automatically in queries using negative keywords:
   Add "-undergraduate -women -female -hispanic -latino -chicano -community" when the applicant does not qualify for those restricted demographic buckets.
4. Use official search syntax (e.g., site:.edu, site:.gov, site:.ac.uk).
5. Produce 8 to 10 distinct, targeted queries covering different country and funding facets.

Return JSON only with key "queries": ["query 1", "query 2", ...]"""


def research_prompt(
    profile: StudentProfile,
    round_number: int,
    exclude_ids: list[str],
    exclude_urls: list[str],
    feedback: str,
) -> str:
    countries = ", ".join(profile.target_countries) if profile.target_countries else "USA, Germany, UK, Canada"
    fields = ", ".join(profile.target_fields) if profile.target_fields else "Computer Science"
    level = profile.target_level or "Masters"

    exclude_section = ""
    if exclude_urls or exclude_ids:
        exclude_items = [f"URL: {u}" for u in exclude_urls[:30]] + [f"ID: {i}" for i in exclude_ids[:10]]
        exclude_section = (
            "\n\nALREADY SEARCHED (do NOT return these URLs again):\n"
            + "\n".join(f"- {item}" for item in exclude_items)
        )

    feedback_section = ""
    if feedback:
        feedback_section = f"\n\nFEEDBACK FROM PREVIOUS ROUND:\n{feedback}"

    return f"""You are an Academic Scholarship Research Specialist searching for verified scholarships and assistantships.

Candidate Profile:
- Round: {round_number}
- Level: {level}
- Fields: {fields}
- Target Countries: {countries}
- Citizenship: {profile.citizenship or 'International'}
- Funding Need: {profile.funding_need}
- Has GitHub: {'yes' if profile.github else 'no'}
{feedback_section}
{exclude_section}

SEARCH DIRECTIVES:
1. NEVER search for programming languages (e.g. "Jupyter Notebook", "TypeScript"). Search strictly for academic degrees and domains ("{fields} {level} scholarship").
2. Target graduate assistantships, international tuition waivers, departmental fellowships, and government grants.
3. Apply negative keywords for non-matching groups: "-undergraduate -women -hispanic -community college".
4. Return high-relevance candidates matching the student's background."""


queries_generation_prompt = query_planner_prompt



def candidate_classifier_prompt(
    search_results: list[dict[str, Any]],
    profile: StudentProfile,
) -> str:
    results_summary = ""
    for i, r in enumerate(search_results[:35], 1):
        results_summary += f"\n[{i}] Title: {r.get('title')}\nURL: {r.get('url')}\nSnippet: {r.get('snippet')}\n"

    return f"""From these search results, return only real, specific scholarship or funded program opportunities (not listicles, blog posts, or broad search engines).

Search Results:
{results_summary}

Target student field: {', '.join(profile.target_fields)}
Target countries: {', '.join(profile.target_countries)}
Target level: {profile.target_level}

RULES:
1. Extract candidate opportunities that correspond to real institutions, programs, or named scholarships.
2. For each candidate, provide:
   - "name": Official name of the scholarship or program
   - "institution": University, foundation, or government body offering it
   - "country": Country where it is hosted or eligible
   - "kind": One of ["scholarship", "program", "program_with_funding"]
   - "source_url": The exact URL copied verbatim from the search result above (DO NOT invent URLs)
   - "found_by_query": Context or search source
3. Return at most 18 high-quality candidates.
4. Return JSON only with key "candidates": [ ... ]"""


def verifier_extraction_prompt(
    candidate: Candidate,
    profile: StudentProfile,
    page_text: str,
) -> str:
    return f"""Today is {_today()}. Below is the text of an official scholarship/program page.
Extract deadline, funding, how to apply, and eligibility criteria.

## Candidate
- Name: {candidate.name}
- Institution: {candidate.institution or 'N/A'}
- Country: {candidate.country or 'N/A'}
- URL: {candidate.source_url}

## Student Summary for Eligibility Comparison
- Target Level: {profile.target_level}
- Target Fields: {', '.join(profile.target_fields)}
- CGPA: {profile.education[0].cgpa if profile.education and profile.education[0].cgpa else 'N/A'} (Scale: {profile.education[0].cgpa_scale if profile.education else 'N/A'})
- Test Scores: {', '.join(f'{t.name}: {t.score}' for t in profile.test_scores) if profile.test_scores else 'None'}
- Target Countries: {', '.join(profile.target_countries)}

## Page Text
{page_text}

INSTRUCTIONS & STRICT RULES:
1. Every value (deadline, funding, how_to_apply, requirement criterion) MUST be accompanied by an "evidence_quote" copied EXACTLY from the page text above.
2. If the text does not state the information, return value null and evidence_quote null. NEVER infer or invent details.
3. For each requirement in "requirements":
   - "criterion": State the requirement
   - "student_value": What the student has based on profile
   - "result": "met", "not_met", or "unknown"
   - "evidence_quote": Verbatim quote from the page text establishing this criterion
4. Classify "deadline_type" and determine "deadline_state":
   - "deadline_type": "fixed" (specific calendar closing date) | "rolling" (rolling admissions/open year-round) | "cycle" (recurring annual cycle, e.g. "opens each autumn") | "anticipated" (estimated future cycle) | "unknown" (unclear or not specified)
   - "deadline_state":
     * "open": deadline is strictly after {_today()}
     * "closed": deadline is before or on {_today()}
     * "rolling": rolling admission
     * "unknown": no deadline found or unparseable
5. Classify "source_tier":
   - "official": official university (.edu, .ac.*, .de) or government or official foundation portal
   - "aggregator": scholarship portal, directory, or blog
   - "other": general webpage
6. Classify "status":
   - "verified": official/trustworthy, key fields evidenced, student eligible
   - "partial": some evidence found but missing core info
   - "rejected": clearly not eligible (e.g. wrong nationality or closed with no upcoming cycle)

Return JSON only matching the schema:
{{
  "official_url": "...",
  "source_tier": "official|aggregator|other",
  "status": "verified|partial|rejected",
  "deadline": {{"value": "...", "evidence_quote": "..."}},
  "deadline_type": "fixed|rolling|cycle|anticipated|unknown",
  "deadline_state": "open|closed|rolling|unknown",
  "funding": {{"value": "...", "evidence_quote": "..."}},
  "requirements": [
    {{"criterion": "...", "student_value": "...", "result": "met|not_met|unknown", "evidence_quote": "..."}}
  ],
  "how_to_apply": {{"value": "...", "evidence_quote": "..."}},
  "missing_info": ["..."]
}}"""


def ranking_prompt(
    opportunities: list[VerifiedOpportunity],
    profile: StudentProfile,
) -> str:
    opps_summary = ""
    for i, opp in enumerate(opportunities, 1):
        opps_summary += f"""
### [{i}] {opp.candidate.name}
- Institution: {opp.candidate.institution or 'N/A'} | Country: {opp.candidate.country or 'N/A'}
- Status: {opp.status} | Tier: {opp.source_tier}
- Deadline: {opp.deadline.value or 'Unknown'} (State: {opp.deadline_state})
- Funding: {opp.funding.value or 'Unknown'}
- Criteria Met: {sum(1 for r in opp.requirements if r.result == 'met')}/{len(opp.requirements)}
- Criteria Checks: {', '.join(f'{r.criterion}: {r.result}' for r in opp.requirements)}
- How to Apply: {opp.how_to_apply.value or 'N/A'}
- URL: {opp.official_url or opp.candidate.source_url}
"""

    return f"""Rank the following verified opportunities for this student.

## Student Profile
- Name: {profile.name}
- Citizenship: {profile.citizenship} (Residency: {profile.residency_status})
- Target Level: {profile.target_level}
- Target Fields: {', '.join(profile.target_fields)}
- Target Countries: {', '.join(profile.target_countries)}
- CGPA: {profile.education[0].cgpa if profile.education and profile.education[0].cgpa else 'N/A'}
- Skills: {', '.join(profile.skills[:12])}
- Projects: {', '.join(p.name for p in profile.projects[:4])}
- Funding Need: {profile.funding_need}
- Gaps: {', '.join(profile.gaps) if profile.gaps else 'None'}

## Verified Opportunities
{opps_summary}

## Scoring Rubric (weights)
- Eligibility fit (met criteria, no not_met): 35%
- Funding coverage relative to funding_need: 25%
- Alignment with target field/level/country: 15%
- Deadline feasibility (open > rolling > closed): 15%
- Source trust (official > aggregator): 10%

Today's date: {_today()}

ZERO-TOLERANCE HARD ELIGIBILITY FILTERING:
1. If ANY mandatory requirement is marked as "not_met" (e.g. "PhD only" for a "Masters" applicant, or "US Citizens only" for an International student), the eligibility_fit score MUST immediately be set to 0. DO NOT rank ineligible candidates.
2. Rank open deadlines above closed ones.
3. For strong but closed opportunities: mark deadline as closed, note "check next cycle" in risks.
4. why_fit MUST cite concrete profile facts (e.g. specific project name, CGPA, technical skills).
5. next_steps come from how_to_apply evidence only.
6. readiness: Include score (0-100) and blockers list.
7. actions: List concrete action items with why and by_when based on evidence.
8. Return at most 5 top opportunities. If fewer qualify, return fewer.

Return JSON only with key "ranked": [ ... ] matching RankedOpportunity schema."""


def sop_prompt(
    profile: StudentProfile,
    opportunity: VerifiedOpportunity,
) -> str:
    projects_desc = "\n".join(
        f"- {p.name}: {p.description} (Tech: {', '.join(p.tech)})"
        for p in profile.projects[:5]
    ) or "None listed"

    return f"""Draft a highly tailored Statement of Purpose for this student's application.

## Student Profile
- Name: {profile.name}
- Citizenship: {profile.citizenship}
- Target Level: {profile.target_level} in {', '.join(profile.target_fields)}
- Education: {', '.join(f'{e.degree} in {e.field or "N/A"} from {e.institution}' for e in profile.education)}
- CGPA: {profile.education[0].cgpa if profile.education and profile.education[0].cgpa else 'unknown'}
- Technical Skills: {', '.join(profile.skills[:20])}
- Extracted Projects & Tech Stack:
{projects_desc}
- Achievements: {', '.join(profile.achievements[:8])}
- GitHub: {profile.github.profile_url if profile.github else 'N/A'}

## Target Opportunity
- Name: {opportunity.candidate.name}
- Institution: {opportunity.candidate.institution or 'N/A'}
- Country: {opportunity.candidate.country or 'N/A'}
- Funding: {opportunity.funding.value or 'Full funding'}

RULES & CONTEXTUAL SOP GENERATION:
1. WEAVE EXTRACTED PROJECTS & SKILLS: The SOP draft MUST actively integrate the student's actual projects (e.g. {', '.join(p.name for p in profile.projects[:3])}) and skills into the narrative.
2. NO GENERIC PLACEHOLDERS: Use the real project details provided above.
3. NEVER INVENT ACHIEVEMENTS: Never invent achievements, test scores, or personal motivations. Where a needed detail is genuinely missing from the profile (such as specific faculty lab name, advisor, or personal motivation), keep an explicit '[ADD: ...]' placeholder (e.g. '[ADD: Specific faculty research lab and advisor name]') and list them in the placeholders array. Do not remove placeholders to look polished.
4. List every fact used in facts_used.
5. Start text with this exact banner:
   "DRAFT ONLY – Review and edit before use. Nothing has been submitted."

Return JSON only with keys: "target_name", "text", "facts_used", "placeholders"."""


def supervisor_condense_prompt(payload_dict: dict[str, Any]) -> str:
    """Lightweight summarization prompt to strip redundant data before agent handoffs."""
    return f"""You are the Master Swarm Supervisor. Compress and clean the following agent output.
Strip out HTML boilerplate, redundant descriptors, and verbose commentary.
Keep only: entity names, country, verified deadlines, funding figures, and concrete criteria checks.

Input:
{json.dumps(payload_dict, default=str)[:3500]}

Return compressed JSON only."""


def chatbot_assistant_prompt(
    user_query: str,
    profile: StudentProfile | None,
    ranked: list[RankedOpportunity],
    verified: list[VerifiedOpportunity],
    swarm_status: str,
) -> str:
    """Prompt for conversational interaction in the Chatbot interface."""
    profile_summary = f"{profile.name} ({profile.target_level} in {', '.join(profile.target_fields or [])}, {profile.citizenship})" if profile else "Profile in progress"
    recommendations = "\n".join(f"- #{r.rank}: {r.opportunity.candidate.name} ({r.opportunity.candidate.country}) - Score {r.score} - Deadline: {r.opportunity.deadline.value or 'N/A'}" for r in ranked[:5])

    return f"""You are the ScholarSwarm AI Supervisor Agent converse with the student in the chatbot interface.
Answer the user's question accurately using ONLY the live discovered scholarship data and background swarm state.

## Current State:
- Swarm Status: {swarm_status}
- Student: {profile_summary}
- Discovered Opportunities ({len(verified)} checked):
{recommendations or 'Verification currently in progress.'}

User Question: "{user_query}"

Provide a direct, helpful, and concise response in markdown. If asked for recommendations or deadlines, cite the verified facts."""

