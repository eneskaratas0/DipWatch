# DipWatch

[Türkçe](README.md) | **English**

A monitoring system that automatically collects international-politics news from local and international outlets,
groups articles that describe the same development into a single "event", and presents a Turkish summary of each
event together with its sources.

- Live site: https://eneskaratas0.github.io/DipWatch/
- Detailed technical guide (setup, commands, settings; in Turkish): [docs/TEKNIK.md](docs/TEKNIK.md)

This document describes the project in the structure of a research-methods write-up: problem, design, data sources
and sampling, data collection, analysis, validity, limitations and ethics.

> Note: the site, summaries and code identifiers are in Turkish, since the project is built for a Turkish-speaking
> reader. Most sources are in English.

---

## Contents

1. [Abstract](#1-abstract)
2. [Research problem and aim](#2-research-problem-and-aim)
3. [Research design](#3-research-design)
4. [Data sources and sampling](#4-data-sources-and-sampling)
5. [Data collection](#5-data-collection)
6. [Data processing and analysis](#6-data-processing-and-analysis)
7. [Validity and reliability](#7-validity-and-reliability)
8. [Limitations and possible biases](#8-limitations-and-possible-biases)
9. [Ethical and legal considerations](#9-ethical-and-legal-considerations)
10. [Presentation of findings: outputs](#10-presentation-of-findings-outputs)
11. [Usage](#11-usage)
12. [Project structure](#12-project-structure)

---

## 1. Abstract

DipWatch scans 74 news feeds across 10 source groups every 30 minutes. Collected articles are grouped into events
first by lexical similarity (TF-IDF) and then by multilingual semantic similarity (an embedding model). Events
reported by at least two different sources are summarized in Turkish by a large language model (LLM); each summary
includes the event's region, the countries involved and an importance score from 1 to 5. Results are published on a
static website and, optionally, as Telegram alerts. Every summary lists links to all of the source articles it is
based on.

## 2. Research problem and aim

**Problem.** An international development is reported by outlets in different countries, in different languages, at
different times and with different narratives. Scanning these sources by hand is time-consuming for a single reader,
while relying on a single source narrows the perspective.

**Aim.** To monitor regional and global outlets systematically, bring together the articles that belong to the same
event, present the event in a neutral Turkish summary, and always point the reader back to the original sources.

**Research questions.**

1. How accurately can articles from outlets in different languages and countries be grouped under the same event automatically?
2. In which outlets, in what order and with which differing narratives does an event appear?
3. In which regions do events make it onto the agenda of more than one outlet?

## 3. Research design

| Element | Choice |
|---|---|
| Type | Descriptive, continuous (longitudinal) monitoring; automated content collection and computational text analysis |
| Unit of analysis | **Event**: a cluster of articles reporting the same concrete development (the same attack, meeting, statement) |
| Unit of observation | **Article**: a single item published by an outlet (headline, short description, link, time) |
| Time window | The site shows the last 72 hours; an event closes if it receives no new article for 36 hours |
| Frequency | Every 30 minutes (on GitHub Actions) |
| Approach | Rule-based, reproducible thresholds (TF-IDF, embeddings) combined with LLM-assisted summarization |

## 4. Data sources and sampling

**Sampling method:** purposive sampling. Sources were not chosen at random but according to these criteria:

- **Regional coverage:** for each region, the region's own press ("local") together with global agencies and broadcasters.
- **Diversity of perspective:** outlets from different sides of a conflict (e.g. Israeli press alongside Arab and
  Iranian press; Ukrainian press alongside the Russian state agency TASS and Russian independent outlets).
- **Language:** English and Turkish sources.
- **Type:** news agencies, newspapers, think tanks and official sources.
- **Accessibility:** free sources that have an RSS feed or can be followed through a Google News "site:" query.

**Source groups** (full list and fields: [`sources.yaml`](sources.yaml)):

| Group | Count | Sources |
|---|---:|---|
| Global | 9 | BBC World, Reuters, AP, Al Jazeera English, The Guardian, France 24, DW, New York Times, NPR |
| Middle East | 14 | BBC Middle East, Al-Monitor, Middle East Eye, Times of Israel, Haaretz, Jerusalem Post, Arab News, Asharq Al-Awsat, Al Arabiya, The National, Tehran Times, Iran International, L'Orient Today, Rudaw |
| Russia, Ukraine, Caucasus | 8 | Kyiv Independent, Ukrainska Pravda, TASS, Meduza, The Moscow Times, RFE/RL, OC Media, Eurasianet |
| Europe | 5 | Politico Europe, Euronews, EUobserver, Balkan Insight, BBC Europe |
| Asia-Pacific | 9 | South China Morning Post, Global Times, Nikkei Asia, The Japan Times, Yonhap, The Diplomat, The Hindu, Dawn, BBC Asia |
| Africa | 5 | BBC Africa, AllAfrica, Africanews, Premium Times, The East African |
| Americas | 3 | BBC US & Canada, BBC Latin America, MercoPress |
| Türkiye | 7 | Daily Sabah, Hürriyet Daily News, Bianet English, TRT Haber, Anadolu Agency, NTV, Sözcü |
| World news in Turkish | 7 | AA World, TRT Haber World, BBC Türkçe, DW Türkçe, Euronews Türkçe, Independent Türkçe, Medyascope |
| Analysis and official | 7 | International Crisis Group, Foreign Policy, CFR, Carnegie, SETA, ORSAM, UN News |

Distribution: 61 English and 13 Turkish feeds; 50 come from the outlet's own RSS feed and 24 via Google News.

A separate module also follows technology and cybersecurity news (The Hacker News, BleepingComputer, Krebs on
Security, The Record, CISA, Ars Technica; see [`teknoloji/kaynaklar.yaml`](teknoloji/kaynaklar.yaml)).

## 5. Data collection

- **Tool:** a Python collector (`collector/`) reading RSS with `feedparser`.
- **Method:** each source is fetched from its own RSS feed. Sources without RSS, or whose feed blocks automated access,
  are followed through a Google News query of the form `site:domain when:1d` (Turkish sources are searched in the
  Google News Türkiye edition).
- **Fields collected:** headline, short description, link, publication time, outlet name, the outlet's region and
  language. Full article text is not collected.
- **Storage:** an SQLite database (`data/dipwatch.db`), kept between runs so data accumulates over time.
- **Source health:** the latest status of each feed (working, error, empty) is recorded (`python -m collector feed-durum`).

## 6. Data processing and analysis

1. **Pre-processing and cleaning.** Links are stripped of tracking parameters; the "- Outlet" suffix in Google News
   headlines is removed. The same link, or the same headline from the same outlet, is not stored twice. Non-news rows
   such as careers, subscription or imprint pages are discarded. Each article gets a content-type label from its
   headline pattern: `haber` (news), `analiz` (analysis), `canli` (live).
2. **Event clustering (lexical level).** Headline and description are turned into a TF-IDF vector. An article whose
   cosine similarity with an event updated in the last 36 hours exceeds 0.28 joins that event; otherwise it opens a
   new one. An event's vector is limited to its last 15 articles, and likely proper nouns and numbers get extra weight.
3. **Cross-language merging (semantic level).** Because TF-IDF cannot match a Turkish article with an English one,
   each headline is turned into a meaning vector by a multilingual embedding model
   (`paraphrase-multilingual-MiniLM-L12-v2`). Pairs of events from the last 72 hours with similarity above 0.85 are
   merged. The threshold is deliberately high to avoid "mega-events" that pull in unrelated articles.
4. **Region classification.** If an LLM summary exists, its region is used. Otherwise the region is decided by majority
   vote over country, city and leader names found in the headline and summary (Turkish and English dictionary). Topics
   that belong to no particular region (UN, Nobel, Olympics, etc.) are classed as "global".
5. **Summarization (qualitative synthesis).** Events with at least 2 distinct sources are summarized by an LLM (Claude,
   Gemini or Groq). The model is instructed to use only the information in the given articles, not to add speculation,
   and to state explicitly when sources contradict each other or present different narratives. The output follows a
   fixed schema: headline, a 2-4 sentence summary, region, countries, tags and an importance score from 1 (routine) to
   5 (major crisis). When no LLM is available, the event's most representative headline is shown, or the headline is
   machine-translated into Turkish and marked "makine çevirisi" (machine translation).

## 7. Validity and reliability

- **Source transparency:** every summary is followed by a timeline and links to all the articles it draws on, so the
  reader can verify each claim at its original source.
- **Triangulation:** only events reported by at least two independent outlets are summarized and listed by default;
  single-source items can be shown on request.
- **Reproducibility:** clustering thresholds are fixed and defined explicitly in
  [`collector/config.py`](collector/config.py) or via environment variables; the same data yields the same clusters.
  `python -m collector yeniden-grupla` re-clusters a time window from scratch.
- **Data-quality measurement:** [`veri_kalite.py`](veri_kalite.py) reports the share of non-news rows, duplicates,
  events with a likely wrong region, articles far from their cluster centre (probably off-topic) and how many events a
  single topic is split into; two measurements can be compared with each other.
- **Tests:** offline tests check the collector, the website, Telegram alerts and the technology module using fake feeds
  and fake model responses (`tests/`).

## 8. Limitations and possible biases

- **Selection bias:** the source list is a purposive sample, not a representative sample of the world's press. English
  sources dominate (61 of 74 feeds) and Western-based global broadcasters have a large share. Local press in languages
  such as Arabic, Persian, Russian or Chinese is mostly represented through those outlets' English editions.
- **Access-related gaps:** RSS feeds may not include every article; for sources followed through Google News, Google's
  own ranking and filtering apply. Paywalled content is not collected.
- **Headline and short description only:** analysis relies on headlines and descriptions, not full text, so detail and
  context can be lost.
- **Clustering errors:** different events with similar wording can merge (false positives), and the same event written
  in different words can stay apart (false negatives). The thresholds are a trade-off between these two errors.
- **LLM limitations:** summaries can contain wrong generalizations or misplaced emphasis; the importance score is the
  model's judgement, not an objective measurement. When free-tier quotas run out, some events stay unsummarized.
- **Region assignment:** without an LLM, the dictionary-based region guess is occasionally wrong.
- **Time limit:** the system focuses on the last 72 hours; it is not designed for long-term archival analysis.

## 9. Ethical and legal considerations

- **Copyright:** full article text is neither copied nor republished. Only the headline, a short description and a
  link to the original article are used; the reader is always sent to the source.
- **Attribution:** every summary clearly shows the outlets and links it is based on.
- **Personal data:** no user or personal data is collected; only publicly available news headlines are processed. The
  content sent to free LLM tiers is likewise limited to these public headlines and descriptions.
- **Respecting access rules:** for sites that block automated access, protections are not circumvented; an open channel
  such as Google News is used instead.
- **Neutrality:** the summarization instructions require neutral language and require differences in narrative
  between sources to be stated rather than hidden. Automated summaries are not a substitute for editorial judgement or
  verified information.
- **Security:** API keys and Telegram bot credentials are kept only in a local `.env` file or in GitHub Actions
  secrets, never in the repository. Review against the OWASP Top 10:
  [`security-review-2026-10-08.md`](security-review-2026-10-08.md).

## 10. Presentation of findings: outputs

- **Website** (https://eneskaratas0.github.io/DipWatch/): events from the last 72 hours ordered by day and
  importance; region pages; for each event a Turkish summary, a timeline and source links grouped by outlet; search;
  dark theme and mobile support. Plus a "Technology & Cyber" page.
- **Telegram alerts:** a message arrives when a new event appears in the chosen regions or keywords, or when a
  reported event grows ([`bildirim.yaml`](bildirim.yaml)).
- **Data files:** `data/events.json` (machine-readable), `data/son_olaylar.md` (readable list), `data/teknoloji.json`.

## 11. Usage

```bash
pip install -r requirements.txt
cp .env.example .env                 # optional: LLM key and Telegram details
python -m collector tur --site public  # one round: collect, cluster, summarize and build the site
python -m collector dongu --aralik 300 --site  # every 5 minutes
python -m collector feed-durum       # source status
python veri_kalite.py                # data-quality report
python -m tests.test_collector       # offline test
```

It also runs without any API key; in that case a representative headline or a machine translation is shown instead
of a summary. For the free options (Gemini, Groq), all settings, Telegram setup and GitHub Pages publishing, see
[docs/TEKNIK.md](docs/TEKNIK.md) (Turkish).

## 12. Project structure

```
sources.yaml          source list (the sample)
collector/            collection, clustering, merging, region, summary, Telegram
teknoloji/            technology and cybersecurity module
web/                  static site generator
tests/                offline tests
veri_kalite.py        data-quality measurement
bildirim.yaml         Telegram alert preferences
.github/workflows/    automatic collection and publishing every 30 minutes
docs/TEKNIK.md        detailed technical guide (Turkish)
```
