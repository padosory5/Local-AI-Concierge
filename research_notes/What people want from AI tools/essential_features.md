# What people want from AI tools: essential features, retention and new ideas (for Noir)

Evidence date: searched 2026-11-01. Each finding carries a strength label so measured data stays apart from anecdote.

- **[Measured]** logs, card or transaction panels, app-store data, or a controlled study.
- **[Survey]** a sampled survey (self-report). Stronger if representative.
- **[Company]** a figure the company reports about itself, unaudited.
- **[Reported]** press reporting, often one source or secondhand.
- **[Anecdote]** forum posts, reader polls, reviews, opinion.
- **[Weak]** SEO, vendor or aggregator pages. Use only with care.

Method limits: most pages were read through a summarising fetch tool, so exact figures should be checked against the primary source before publication. Menlo's 2026 PDF was too large to open, so figures come from Menlo's own web version of the report. Menlo is not neutral: it is an Anthropic investor (Claude is marked as a portfolio company on the report page) and it led Wispr's August 2026 round. Treat Menlo's voice and Claude findings with that in mind.

## What are the table-stakes features of an AI assistant in 2026 that users expect by default?

### Takeaway
Chat that can read files, search the web, remember the user and work on a phone is now the baseline set by ChatGPT, Gemini and Claude. Voice has moved close to baseline in self-reported use. Connectors to email and calendar are widely offered, but evidence says they are a paid, opt-in, minority behaviour rather than a default habit.

### Cited Findings

Scale and context
- ChatGPT passed 900M weekly actives by early 2026 ([a16z 6th edition, Mar 9 2026](https://a16z.com/100-gen-ai-apps-6/)) and about 1.2B by the 7th edition, as reported there ([a16z 7th edition, Oct 5 2026](https://a16z.com/100-gen-ai-apps-7/)). Sensor Tower estimated 1B monthly app users in May 2026 ([Mobile World Live](https://www.mobileworldlive.com/french/chatgpt-atteint-le-milliard-dutilisateurs-en-un-temps-record/)). [Measured estimate]
- Daily use has converged across three sources at about a quarter of US adults: Menlo 25% (up from 19%), and 39% among AI users, survey of 5,067 US adults, July 2026 ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)); a16z about 25% ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). Pew found 49% of US adults use chatbots at all, up from 33% in 2024 ([TNW on Pew](https://thenextweb.com/news/pew-research-americans-ai-chatbot-skepticism-regulation-distrust-2026?type=AI)). [Survey, strong because independent sources agree]
- Pew's breakdown by age: 18-29 66%, 30-49 61%, 50-64 42%, 65+ 23% ([Pew, Jun 17 2026, n=5,119, Feb 17-23](https://www.pewresearch.org/internet/2026/06/17/why-dont-people-use-chatbots/)). [Survey]

Voice
- 19% of AI users call voice their main way of using AI, 27% switch between voice and typing, so 46% speak to AI at least sometimes. Alexa use fell from 32% to 22% and Siri from 25% to 20% ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey, Menlo has a stake in Wispr]
- I found no vendor or log-based figure for voice share of ChatGPT or Gemini messages. See Gaps.

Memory
- Google launched Personal Intelligence in January 2026, tying Gemini to Gmail, Photos, YouTube and Search. a16z argues context compounds as switching cost, but this is an argument, not a measurement ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). [Reported]
- Anthropic shipped a memory import tool in March 2026 that pulls memories out of ChatGPT, Gemini or Copilot ([PCWorld](https://pcworld.com/article/3076376/claude-can-now-import-chat-histories-from-chatgpt-and-other-ais.html)) and reportedly extended memory to free users ([Storyboard18](https://storyboard18.com/digital/anthropic-launches-claude-memory-tool-overtakes-chatgpt-in-app-store-91155.htm)); plan eligibility is reported inconsistently across sources. [Reported]

Connectors
- ChatGPT's Gmail, Calendar and Contacts connectors rolled out to Plus and Pro in August 2025 ([BetaNews](https://betanews.com/2025/08/14/chatgpt-now-integrates-with-gmail-google-calendar-and-contacts/)), and must be switched on by hand ([Search Engine Journal](https://www.searchenginejournal.com/chatgpt-5-now-connects-to-gmail-calendar-and-contacts/553718/)). [Reported]
- Among agent users only, access granted was: email 36%, browser 33%, messaging 31%, cloud storage 29%, calendar 27%, health apps 23%, financial accounts 20% ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey, self-selected group]

Mobile
- ChatGPT's mobile lead over rivals is larger than its web lead: 2.5x Gemini and 14x Claude on mobile, against about 2x and 6x on web ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Measured estimate]
- Rankings by web and mobile traffic undercount desktop and embedded AI tools, per a16z itself ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). [Reported]

Web search, files and images
- The top three topics, Practical Guidance, Seeking Information and Writing, make up nearly 80% of ChatGPT conversations ([NBER 34255, Sep 2025](https://www.nber.org/papers/w34255)). [Measured] Seeking Information cannot be served well without live search, which supports treating search as baseline.
- Researching personal interests is the most common AI activity, at 26% of US adults ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey]

### Inferences
- Rough baseline for 2026: file reading, web search, memory, voice, mobile. Noir has file reading only. Her missing items rank, by evidence, roughly: web search (a local model has no live facts, and information seeking is a top-three use), memory (cheap to add, naturally private, and every leader now has it), voice (46% self-report, and local dictation is feasible), connectors (useful but opt-in and minority), phone (where the mass of users is, but a local model cannot run there without a different design).
- Users do not need Noir to match every item. They need her not to feel broken on the first three.
- Reading the screen has no usage evidence either way in this research. See question 7 on personal-memory products.

### Gaps
- No vendor-published share of messages that use voice, memory, web search, image upload or file upload. No measured figure on how many users turn on connectors. A search for these returned only blogs.
- No evidence found on sharing features. I cannot say whether sharing is table stakes.
- The Pew 24% daily figure appeared in a search summary but not on the pages I opened, so it is left out of the triangulation above.

## Which features have the strongest evidence of driving daily use and retention, and which are used far less than the hype suggests?

### Takeaway
What keeps people is a general assistant that absorbs more of their jobs over time, and narrow tools that replace an existing habit. Thin AI apps churn faster than ordinary apps. The overhyped items are the general-purpose agent, in-chat app stores and scheduled proactive feeds, each of which saw weak or falling use.

### Cited Findings

Stronger evidence of staying power
- General assistants deepen with age: OpenAI data cited by Menlo shows messages per weekly user rising within every sign-up cohort, including cohorts over two years old. 52% of AI users say they use AI more than a year ago ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Measured via a secondary citation, plus Survey]
- Gemini and ChatGPT show best-in-class US paid retention, per Yipit data ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). [Measured, no figure given]
- People stick with one assistant: 91% of users turn to their favourite general tool for nearly every job ([Menlo 2025](https://menlovc.com/perspective/2025-the-state-of-consumer-ai/)). Only 8% of US ChatGPT subscribers also pay for Claude, and only 13% who pay for one AI product pay for another ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Survey and Measured]
- Free multi-tool use is common even so: about 20% of weekly ChatGPT web users also used Gemini in a given week ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)), and 72% use both general and specialised tools ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). The two pictures fit: people try many, pay for one.
- Habit-replacing tools: Wispr claims 70% 12-month retention, 100x user growth, and that after three months the average user writes over half their characters by dictation ([Ventureburn, Nov 22 2025](https://ventureburn.com/wispr-ai-raise-25m/?noamp=mobile)), and about 80% six-month active retention in earlier reporting ([Wikipedia, citing 36Kr and Good Returns, Jul 2025](https://en.wikipedia.org/wiki/Wispr_Flow)). [Company, no cohort definition published]
- Granola: YipitData's B2B spend panel shows near-zero churn, customers up 25% month over month in February 2026, and switching that runs mostly one way, from Fathom, Fireflies and Otter to Granola ([YipitData](https://www.yipitdata.com/resources/granola-vs-fathom-otter-fireflies-ai-notetaking)). Granola itself has published no retention numbers ([TNW, Mar 25 2026](https://thenextweb.com/news/granola-series-c-meeting-ai-enterprise-context)). [Measured, but mid-market firms only and no numeric churn]
- Workload fit, from API usage rather than consumers: first cohorts of a model that solves a high-value problem stick (about 35-40% retained at 4-5 months), while later cohorts churn ([a16z, Dec 8 2025](https://a16z.com/the-cinderella-glass-slipper-effect-retention-rules-in-the-ai-era/)). [Measured, developers on OpenRouter, not ordinary users]

Weak retention in general
- RevenueCat 2026: AI apps retain 21.1% of annual subscribers after a year against 30.7% for non-AI apps; monthly 6.1% against 9.5%; weekly 2.5% against 1.7%. AI apps convert trials better (8.5% against 5.6%) and earn more per customer ($30.16 against $21.37 annual lifetime value) and have higher refunds (4.2% against 3.5%) ([TechCrunch, Mar 10 2026](https://techcrunch.com/2026/03/10/ai-powered-apps-struggle-with-long-term-retention-new-report-shows)). [Measured, mobile subscription apps, medians] This describes small AI apps, not the big assistants.
- Depth is uneven: 29% of AI users spend under 15 minutes a day, 24% over an hour ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). The top 1% of spenders account for 19.5% of observed spend, more than the bottom 50% ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Survey and Measured]
- Claude's daily sessions fell in July and August 2026, and US churn rose while new sign-ups slowed, after a surge a16z links to the Pentagon dispute ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). Attention spikes do not hold on their own. [Measured, no figures given]

Used less than the hype
- ChatGPT Agent: peaked at about 4M weekly paying users, about 11% of 35M payers, then fell below 1M within months. Reasons given: users did not know what it was for or that it existed, plus speed, reliability and security problems. OpenAI shifted to narrow agents such as Shopping Research ([The Decoder, Jan 29 2026, citing The Information](https://the-decoder.com/chatgpt-agent-reportedly-lost-75-of-its-users-because-nobody-knew-what-it-was-actually-for/)). [Reported, single source]
- ChatGPT app store: 300+ integrations six months in, with sluggish adoption, hidden placement and limited function ([Seeking Alpha on Bloomberg, Mar 30 2026](https://seekingalpha.com/news/4570132-openais-chatgpt-app-store-initiative-sees-sluggish-start); [Bloomberg Law](https://news.bgov.com/legal-tech-and-ops/openai-plan-for-chatgpt-super-app-hobbled-by-gatekeeping-gripes)). [Reported, developer interviews, not usage logs]
- ChatGPT Pulse, the daily proactive feed launched in 2025, was sunset in June 2026 and folded into Scheduled tasks ([Gigazine, Jun 19 2026](https://gigazine.net/gsc_news/en/20260619-chatgpt-scheduled-tasks/)). [Reported] A claim that 31% of paid users rely on Pulse could not be traced, so do not use it.
- Apple Intelligence: 73% of iPhone users said AI features added little or no value, in a SellCell survey of about 1,000 users taken before iOS 18.2 ([Futurism](https://futurism.com/the-byte/iphone-unimpressed-apple-intelligence-ai)). A reader poll also showed low use ([TidBITS, Jun 2025](https://tidbits.com/2025/06/20/do-you-use-it-apple-intelligence-sees-weak-adoption/)). [Survey and Anecdote, older, predates later features]

A claim that needs care
- Menlo says 24% of AI users use an agent regularly, and 92% of agent users pay ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). That sits badly with ChatGPT Agent's collapse. a16z's user data for agents comes from early-user group chats and company claims ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). "Agent" is probably being read loosely by respondents.
- Menlo's paying share is 55% of AI users in 2026 against 3% in 2025 ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)), while card-panel data shows 4.5% of eligible US consumers paying for ChatGPT, Gemini or Claude, up from 2.1% ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). The denominators differ, but a jump from 3% to 55% is far larger than spend growth of about 3.3x, so the two Menlo figures are probably not comparable.

### Inferences
- The most useful pattern for Noir: narrow job, named plainly, that replaces something the user already does every day. The least useful: a general "agent" with an unclear purpose, which is the exact failure ChatGPT Agent reported.
- Her minimized circle that asks yes-or-no questions is proactive, but on a narrow job with a clear answer. That differs from a feed like Pulse. Evidence does not yet show whether this form retains people, so it should be measured locally by acceptance rate.
- A local app has no subscription churn, but it has the same risk: curiosity on day one, nothing on day thirty.

### Gaps
- No public day-1, day-7 or day-30 retention for ChatGPT, Gemini or Claude. No published experiment that isolates memory or voice as a cause of retention.
- No retention evidence for any local AI app.

## What are the highest-value everyday jobs for ordinary people, and which can a small local model do well?

### Takeaway
The biggest jobs are writing help, practical how-to guidance, information lookup, schoolwork and health questions. A small local model is good at short text work where the facts are in front of it. It is weak on live facts, long documents without splitting, multi-step agent tasks, and anything high-stakes without a specialised model and checks.

### Cited Findings

Demand
- Non-work use grew from 53% to over 70% of ChatGPT messages. Writing dominates work tasks; programming and self-expression are small. Around 10% of adults worldwide used it by July 2025 ([NBER 34255](https://www.nber.org/papers/w34255)). [Measured]
- Writing was about 40% of work-related messages and programming 4.2% in June 2025 ([summary of the NBER paper via search; see primary](https://www.nber.org/papers/w34255)). [Measured, secondhand]
- Of people who do a task, the share using AI for it: writing 61%, coding 58%, school and work assignments 56%, image creation 53%, presentations 52% ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey]
- Across all US adults in 2025: emails 19%; to-do lists, research and writing 18% each; meal planning 16%; expenses, notes and images 15% each; health 14% ([Menlo 2025](https://menlovc.com/perspective/2025-the-state-of-consumer-ai/)). [Survey, older]
- Parents used AI daily at about twice the rate of non-parents (29% against 15%), and 85% of students 18+ reported use ([Menlo 2025](https://menlovc.com/perspective/2025-the-state-of-consumer-ai/)). [Survey]

Health and money
- OpenAI says over 40M people worldwide ask ChatGPT health questions daily, over 5% of messages are about health, 1 in 4 of 800M+ regular users asks weekly, and there are 1.6-1.9M insurance questions a week ([Axios, Jan 5 2026](https://axios.com/2026/01/05/chatgpt-openai-health-insurance-aca)). Some outlets wrongly say 40M Americans. [Company]
- AI for health questions rose from 14% to 25%, mental health support from 8% to 14%. For a diagnosis, 63% prefer a human and 19% prefer AI ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey]

What local models can do
- Some local model could answer 88.7% of single-turn chat and reasoning queries; the best single local model rose from 23.2% coverage in 2023 to 71.3% in 2025. Chat and simple retrieval are nearly saturated locally; browser agent tasks and coding still favour cloud. Open-weight models trail the frontier by 6-12 months on most personal-AI tasks ([Stanford Hazy Research, May 15 2026](https://hazyresearch.stanford.edu/blog/2026-05-15-minions-to-openjarvis-retrospective)). [Measured, research benchmarks, not all on a typical laptop]
- Local models fail on long contexts and complex multi-step instructions. Splitting work into short simple pieces brings it back into reach ([Hazy Research](https://hazyresearch.stanford.edu/blog/2026-05-15-minions-to-openjarvis-retrospective)). [Measured]
- Local models below 3B parameters are not effective for the Minions protocol ([Hazy Research, Feb 2025](https://hazyresearch.stanford.edu/blog/2025-02-24-minions)). [Measured, one task family]
- On a 16GB laptop with no separate graphics card, Qwen3 8B is the common recommendation ([PromptQuorum, Jul 2026](https://www.promptquorum.com/prompt-bites/best-local-llm-16gb-ram-laptop)). [Weak, guides agree but show no independent tests]
- General-purpose models produced unacceptable hallucination rates in clinical use in Uganda. A fine-tuned MedGemma 4B with prompt and safety filtering cut hallucination by 62%, and the tool deliberately excludes dosing ([Google showcase, updated Jun 30 2026](https://developers.google.com/health-ai-developer-foundations/showcase/crane-ai)). [Company, feasibility stage]
- Enthusiasts' real local use: sensitive-text cleanup, photo descriptions for search, summarising, with coding dominant ([Ask HN](https://hn.svelte.dev/item/43125486); [r/LocalLLM, Feb 2025](https://redlib.ssps.io/r/LocalLLM/comments/1izrwhz/what_is_the_best_use_of_local_llm)). [Anecdote, older, technical users]
- Translation is a real consumer job: Naver's Papago is on a16z's mobile list ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). [Measured estimate]

### Inferences
Fit of a small local model on a typical laptop (my judgment from the evidence above, not measured job by job):

| Job | Local fit | Note |
|---|---|---|
| Rewrite, fix grammar, change tone | Good | Short text, facts supplied |
| Summarise a short document or page | Good | Long files need splitting |
| Translate common languages | Probably good | No independent benchmark found |
| Draft emails | Good on wording | Needs the email in hand; no connector yet |
| Meeting notes | Plausible | Local Whisper-style speech to text plus short-chunk summaries; audio capture is the real work |
| Study help from the user's own notes | Good | Sourced answers from a folder, which Noir already has |
| Plain how-to guidance | Fair | Stale or wrong facts; needs a warning or web search |
| Personal admin | Limited | Needs calendar and email access |
| Health questions | Risky | High demand, but the Uganda team found general models unsafe |
| Money questions | Risky | No evidence found; arithmetic should be done in code |
| Current events, prices, research | Poor | No live data without search |
| Multi-step agent work, coding | Poor | Cloud still leads |

- The health gap is the sharpest product decision: high demand, low local safety. A safe option is explaining the user's own papers, like a lab result, with cloud offered for harder cases and a plain note that she is not a doctor.

### Gaps
- No independent head-to-head of small local models against cloud models for translation, email or summarising on a typical laptop.
- No evidence on local model quality for money questions.
- Nothing on what share of real user requests a 4B-8B model on typical hardware handles to the user's satisfaction.

## What happened with agent or app marketplaces, what made them succeed or become ghost towns, and how do people discover and trust shared agents?

### Takeaway
Open marketplaces produced huge catalogues and thin use: a very small head gets nearly all attention. Where shared code can execute, attackers arrived within weeks. The stores that look healthiest are moderated ones with visible source and a rule against near-duplicates, though usage data for these is missing.

### Cited Findings

GPT Store (mostly older, 2024)
- 28.5% of custom GPTs had over 10 conversations, and the explore page showed only the top 12 per category, 0.36% of recorded GPTs ([arXiv 2405.10547, May 2024](https://arxiv.org/html/2405.10547v1)). [Measured, older]
- Of about 65,000 GPTs, about 50 had over 1,000 conversations and about 300 had over 100 ([OpenAI forum analysis](https://community.openai.com/t/some-more-gpt-analysis-only-300-gpts-gets-used-out-of-65-000/566841)). [Anecdote with scraped data, older]
- Of 36,000+ custom chatbots, about 5% had 150-500 daily users and most had one or two, with developers reporting fewer users than expected and spam a problem ([Spyglass, Mar 20 2024, citing The Information](https://spyglass.org/stop-making-app-stores.md)). [Reported, older]
- The revenue programme was limited to selected US builders and closed to new ones ([OpenAI forum](https://community.openai.com/t/what-is-the-status-with-gpt-store-revenue-share/839172)). Builders mostly earn indirectly, and an estimate of 3-5M GPTs comes with no OpenAI figures behind it ([Presenc, 2026](https://presenc.ai/research/ai-tool-marketplace-economics-2026)). [Reported and Weak]

ChatGPT apps (2025-2026)
- 220 apps in February 2026, and only about 11% of the combined catalogue overlapped with Claude's ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). Almost 900 ChatGPT apps and 353 Claude connectors by May 2026 ([ATDb on Digiday](https://www.theatdb.com/news/retailers-are-rushing-to-build-ai-apps-its-unclear-if-shoppers-will-use-them)). [Reported, counts vary by method]
- Developers complained of slow approval, buggy tools, thin analytics, and apps that are hard to find. Partners held back functions and resisted giving up the customer relationship ([Seeking Alpha on Bloomberg](https://seekingalpha.com/news/4570132-openais-chatgpt-app-store-initiative-sees-sluggish-start); [Bloomberg Law](https://news.bgov.com/legal-tech-and-ops/openai-plan-for-chatgpt-super-app-hobbled-by-gatekeeping-gripes)). [Reported]

Poe
- In January 2024 Quora raised $75M, mostly to pay bot creators, at a $500M valuation against $1.8B in 2017 ([TechCrunch](https://techcrunch.com/2024/01/09/quora-75m-funding-a16z-poe-ai-chat)). [Reported, older] I found nothing reliable from 2025-2026.

ClawHub and skill security
- OpenClaw's ClawHub accepted uploads from any GitHub account a week old. Koi Security flagged 341 of 2,857 skills, 335 of them pushing the Atomic Stealer through fake prerequisites ([The Hacker News, Feb 2026](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html)). [Measured]
- Snyk scanned 3,984 skills: 36.82% had a flaw, 13.4% critical, 76 confirmed malicious after human review, 8 still live at publication ([Snyk, Feb 5 2026](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub)). Later counts vary, including 1,184 for the same campaign, so check before citing. [Measured]
- OpenClaw's creator said reviewing the volume was impossible, and skills with more than three reports are hidden automatically ([Tom's Hardware](https://tomshardware.com/tech-industry/cyber-security/malicious-moltbot-skill-targets-crypto-users-on-clawhub)). [Reported]
- 26.1% of 31,132 agent skills had at least one vulnerability, and skills bundling scripts were 2.12x more likely to be vulnerable than instruction-only ones ([AI Weekly on arXiv 2601.10338](https://aiweekly.co/alerts/claude-skills-study-flags-26-vulnerability-rate)). [Measured, read secondhand]
- A USENIX Security 2026 study of 98,380 skills confirmed 157 malicious ones ([OWASP](https://owasp.org/www-project-agentic-skills-top-10/threat-intelligence.html)). [Measured, secondhand] Rates differ widely with definitions, from roughly 0.2% confirmed malicious to over a third with some flaw.
- Snyk's dangerous patterns include remote instructions fetched after review and hidden prompt injection ([Snyk](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub)). Passing review once is not enough when a skill can load content later.

Hermes
- One guide counts 90,697 skills across 11 registries on Aug 13 2026, with search and install from chat ([Agent37](https://www.agent37.com/blog/hermes-skills-hub)). [Weak, single source] Hermes Agent appears among spend-heavy automation tools ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Measured] No data on how many skills are actually used.

Raycast
- Extensions are pull requests to a public GitHub repo, reviewed first-in, first-out by community managers, with first contact aimed within a week ([Raycast docs](https://developers.raycast.com/basics/publish-an-extension)). Extensions too similar to an active one are refused ([Raycast guidelines](https://manual.raycast.com/extensions-guidelines)). [Primary documentation, no usage data]

Trust
- Among general-assistant-only users, barriers to trying specialised tools include privacy (27%) and not knowing which tool to trust (21%). Only 11% are unaware of specialised options ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). [Survey] So awareness is not the problem. Trust is.

### Inferences
- Ghost town recipe: anyone can publish, no duplicates rule, no reason to come back, thin analytics, and the store sits off the main path.
- Noir's recipes are data filled into a template, not code. That matches the safer instruction-only group, which is a real advantage worth keeping. It should stay a hard rule that shared agents cannot carry scripts or fetch new instructions after install.
- Her discovery page should be a small curated shelf, not a store. Each entry should show in plain words what it reads, what it can do and what it cannot, which her agent card already does. Showing "made and tested by Noir's team" is likely to beat star counts for non-technical users.
- Posting through GitHub fits Raycast's model, and it filters out spam by adding effort, but ordinary users will not do it. Curators would be the publishers.
- Put agents where the need arises, as she already does with starters, rather than expecting users to browse.

### Gaps
- No 2025-2026 measured GPT Store usage. OpenAI publishes none.
- No usage or adoption figures for Claude Skills as a marketplace; research mostly covers third-party registries. No usage data for Raycast's store or Poe in 2026.
- No study of how ordinary, non-technical users judge whether a shared agent is safe.

## What onboarding works for non-technical people?

### Takeaway
Evidence here is thinner than opinion suggests. The firmest points: non-users lack interest and trust more than skill, setup friction kills open-source agents, plain naming matters, and broad examples beat tutorials. Hard time-to-value figures for consumer AI could not be found.

### Cited Findings
- Reasons non-users give, major plus minor: not interested 83%, personal information 79%, accuracy 76%, do not know how 55%, judged by others 14%. 67% are not likely to use a chatbot in the next 12 months ([Pew](https://www.pewresearch.org/internet/2026/06/17/why-dont-people-use-chatbots/)). [Survey, strong]
- Among non-users: 83% prefer a person, 76% worry about privacy, 70% distrust the information (up from 58%), 47% do not know how ([Menlo 2026](https://menlovc.com/perspective/2026-the-state-of-consumer-ai/)). In 2025, 63% saw no need in daily life ([Menlo 2025](https://menlovc.com/perspective/2025-the-state-of-consumer-ai/)). [Survey]
- NN/g tested six new or nearly new users on three Chinese chatbots. Long tutorials and tips before the chat failed. Hover help worked. Broad examples like "Help me generate text" beat niche ones, and users returned to examples after the first session. A bot that misdescribed its own abilities damaged understanding ([NN/g, Mar 29 2024](https://www.nngroup.com/articles/new-AI-users-onboarding/)). [Measured, qualitative, n=6, older]
- Nielsen's articulation barrier says many people cannot express what they need in prose. His estimates vary and are not measured ([Nielsen](https://jakobnielsenphd.substack.com/p/prompt-driven-ai-ux-hurts-usability)). His suggested fixes include prompt builders, rewrites, related prompts and style galleries ([Nielsen](https://jakobnielsenphd.substack.com/p/prompt-augmentation)). [Anecdote, expert opinion]
- ChatGPT Agent's failure reasons include not knowing what it was for or that it existed ([The Decoder](https://the-decoder.com/chatgpt-agent-reportedly-lost-75-of-its-users-because-nobody-knew-what-it-was-actually-for/)). [Reported]
- OpenClaw needed terminal setup, and new visits to its setup site were flat despite GitHub fame ([a16z 6th](https://a16z.com/100-gen-ai-apps-6/)). a16z now says personal agents are usable by non-developers and free, which OpenClaw was not ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Reported, strong source]
- OpenClaw 2.0 moved configuration out of install into conversation with the agent, reportedly making setup much easier but not safer by default ([dsebastien, Oct 3 2026](https://www.dsebastien.net/2026-10-03-openclaw-2-0-easier-setup-shared-sessions-same-security-defaults/)). [Reported, via a blog]
- AI apps convert trials 52% better but retain worse ([TechCrunch on RevenueCat](https://techcrunch.com/2026/03/10/ai-powered-apps-struggle-with-long-term-retention-new-report-shows)). A strong first impression is common and does not secure a second month. [Measured]
- Benchmarks for time to value conflict and come from vendors, with one putting consumer apps under five minutes and another a median of 1.5 days across SaaS ([example of the genre](https://www.artisangrowthstrategies.com/md/blog/average-time-to-value-saas-category-2026-benchmark-report)). [Weak] A widely repeated stat that 63% omit context and 31% succeed first try has no traceable origin. Do not use it.

### Inferences
- Noir's Help me screen, with a rolling list and one line to write on, follows the evidence: broad examples, in place, no tutorial. Her setup by conversation matches what OpenClaw 2.0 moved towards.
- The first thing she does matters more than the tour. Doing one real thing to the user's own stuff, such as sorting Downloads with Undo or answering from their folder with sources, addresses the "no need" and "do not trust" reasons at once.
- Her privacy advantage answers the second-largest objection, so "nothing leaves your computer" should be shown plainly and early. She must also describe her own limits truthfully, since a bot misdescribing itself hurt in NN/g's test.
- Non-users saying "not interested" will not be moved by onboarding. Noir's audience is more likely the people already using a chatbot who have a privacy worry, plus family members they set up.

### Gaps
- I found no public consumer AI activation data (share reaching a first useful result, or the time it takes) from any major assistant. Reforge and Lenny material did not surface.
- No recent NN/g study on consumer AI onboarding; the one found is from 2024 with six people.

## Which hybrid approaches work well, where the local model handles private or simple work and the cloud handles hard work?

### Takeaway
Hybrid works in research and is now the mainstream design at Apple. The best evidence supports two patterns: route easy requests to the local model, and have a cloud model plan while the local model reads the private text. Neither fully hides everything from the cloud.

### Cited Findings
- MinionS: the cloud splits the task, the local model does subtasks over short chunks, recovering 97.9% of remote-only performance at 5.7x lower cost. The simpler Minion reaches 87.9% at 30.4x lower cost ([arXiv 2502.15964](https://arxiv.org/html/2502.15964v1); [Hazy Research](https://hazyresearch.stanford.edu/blog/2026-05-15-minions-to-openjarvis-retrospective)). With a 3B local model: 93.4% of performance at 16.6% of cost ([arXiv](https://arxiv.org/html/2502.15964v1)). [Measured, long-document question answering, January 2025 prices]
- Hybrid routing cut energy, compute and cost by 60-80% against a batched cloud baseline, mainly by sending easy queries to local models ([Hazy Research](https://hazyresearch.stanford.edu/blog/2026-05-15-minions-to-openjarvis-retrospective)). [Measured]
- Raw context stays with the local model in Minions ([Hazy Research, Feb 2025](https://hazyresearch.stanford.edu/blog/2025-02-24-minions)). A follow-up, Secure Minions, says some information still reaches the cloud and can be sensitive ([read only through a mirror copy, confirm on the original](https://mail233685.mx4414.netcup.net/blog/secureminions)). [Reported]
- Apple rebuilt Siri on a licensed Gemini model, about $1B a year, reported with on-device and server tiers ([DataNorth](https://datanorth.ai/news/apple-rebuilds-siri-with-gemini)). Sources conflict on hosting: Apple's Private Cloud Compute ([Computerworld](https://www.computerworld.com/article/4083274/apple-may-tap-google-gemini-for-apple-intelligence-ai.html)) against possible Google servers ([Gigazine on Bloomberg, Jan 2026](https://gigazine.net/gsc_news/en/20260122-new-siri-chatbot-run-google-servers/)). Apple says conversations are not shared with Google ([Storyboard18](https://www.storyboard18.com/digital/apple-assures-siri-users-their-data-stays-private-even-as-google-gemini-powers-new-ai-features-87507.htm)). [Reported, routing details unconfirmed]
- Venice, positioned around private AI, debuted at #43 on web ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)), so privacy can draw an audience outside local-only tools. [Measured estimate]
- OpenJarvis uses a cloud model to tune a stack that then runs entirely on-device, with traces kept local ([Hazy Research](https://hazyresearch.stanford.edu/blog/2026-05-15-minions-to-openjarvis-retrospective)). [Reported, the research team's own claim]

### Inferences
- For non-technical users the rule should be one sentence: Noir does it here unless she asks you first. Asking each time, showing what would be sent, fits her Question pattern and her trust promise.
- Sensible order: local by default; ask before cloud for live facts, long hard tasks, or strong reasoning; strip names and details where code can do so reliably, and tell the user plainly what remains.
- Local-first splitting is worth adopting even without cloud: both local weaknesses, long context and many steps, are addressed by breaking work into pieces in code. That matches the project's rule that reliability lives in code.
- MinionS assumes a frontier cloud model, which costs money. Noir's users on paid cloud would need clear costs per task, not tokens.

### Gaps
- No user research on how ordinary people feel about a local-to-cloud handoff, or whether they notice it.
- No confirmed primary details of Apple's routing.

## What creative or new product ideas are getting real traction in 2025-2026, and why did they catch on?

### Takeaway
The winners attach to something the user already does: meetings, typing, studying their own notes. They run in the background and hand back a useful result without a new habit. Always-on personal memory hardware and open daily feeds have the weakest record so far.

### Cited Findings

Meeting notes
- Granola raised $125M at $1.5B in March 2026, up from a $250M valuation in May 2025 ([Pulse 2.0](https://pulse2.com/granola-125-million-at-1-5-billion-valuation-raised-for-ai-meeting-context-platform/amp/); [Pulse 2.0, 2025](https://pulse2.com/granola-43-million-series-b-raised-for-ai-workspace-platform/)). It is moving towards team products ([TNW](https://thenextweb.com/news/granola-series-c-meeting-ai-enterprise-context)). [Reported] Some sources cite $1.3B or date the round in May; March is best supported.
- Competitor comparison pages say Granola's audio goes to the cloud for transcription and is then deleted, so it is not private by design ([BuildBetter comparison](https://blog.buildbetter.ai/best-granola-alternatives-private-meeting-notes-2026/)). [Weak, competitors, confirm on Granola's own policy] Local rivals exist, such as OpenWhispr using Whisper or Parakeet ([OpenWhispr](https://openwhispr.com/compare/granola)). [Company, no growth data]
- Plaud, a notetaker with hardware and a subscription, debuted at #16 on spend, and Superhuman at #4 ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Measured] Email and notes are where people pay.

Voice dictation
- Wispr raised $280M at $2B in August 2026, led by Menlo. Revenue is reported up over 150% in each of four quarters, used across 125,000+ businesses, with no revenue figure disclosed ([Pulse 2.0, Aug 17 2026](https://pulse2.com/wispr-raises-280-million-at-2-billion-valuation-as-revenue-grows-150-quarterly-and-voice-ai-push-accelerates); [ValueAdd](https://valueaddvc.com/blog/wispr-flow-2b-valuation-280m-series-b-ai-dictation-2026)). [Company]
- 60B+ words written with Flow, per Wispr's own announcement, as reported by a competitor's blog ([Weesper](https://weesperneonflow.ai/en/blog/2026-05-19-wispr-flow-2-billion-valuation-voice-ai-market-2026/)). [Company]
- Reliability complaints exist: 4.8/5 on the App Store against 2.7/5 on Trustpilot ([ValueAdd](https://valueaddvc.com/blog/wispr-flow-2b-valuation-280m-series-b-ai-dictation-2026)). [Anecdote]

NotebookLM
- Audio and video overviews reached 80+ languages ([Wikipedia](https://en.wikipedia.org/wiki/NotebookLM)). Google added personal class notebooks in Classroom on Apr 27 2026 ([Google Workspace Updates](https://workspaceupdates.googleblog.com/2026/04/students-can-now-create-personal-class-notebooks-with-NotebookLM-in-Google-Classroom.html?hl=gl)). [Reported]
- AppGoblin estimates about 3.2M monthly Android users and 31.6M installs ([AppGoblin](https://www.appgoblin.info/apps/com.google.android.apps.labs.language.tailwind)). No official figure was found, and higher claims are listed under Gaps. [Weak]

Personal agents and automations
- Instinct passed 100,000 users in about three weeks while invite-only. The founder says 40% connect a personal card within three weeks, and buyers average $1,300 a month ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Company]
- Meta's Muse reached a reported 250,000 daily actives in its first week and 5M downloads in under a month, but Amazon cut its access in under two weeks ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Reported] Connected agents depend on other companies allowing them.
- Spend-heavy categories include automation and building tools such as n8n, Manus and Hermes Agent ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). [Measured] These lean towards heavy, often technical users; coding and technical automation is the most-discussed agent use.

Daily briefings
- ChatGPT Pulse was folded into Scheduled tasks in June 2026 ([Gigazine](https://gigazine.net/gsc_news/en/20260619-chatgpt-scheduled-tasks/)). Gemini Daily Brief launched at I/O in May 2026 for paying US users, limited to Gmail, Calendar and Gemini chats, and one reviewer's test of scheduled actions returned stale stories ([review, read through a search summary](https://dantaylorwatt.substack.com/p/using-ai-to-create-a-personalised)). [Reported and Anecdote] Huxe came first on the idea; I found no 2026 usage data ([Times of AI](https://www.timesofai.com/news/chatgpt-pulse-looks-copies-from-huxe/)). [Anecdote]

Personal memory
- Meta bought Limitless, formerly Rewind, in December 2025. Pendant sales stopped and the Rewind desktop app stopped capturing ([AI Business](https://aibusiness.com/speech-recognition/meta-acquires-limitless)). [Reported] That is an exit rather than proof of demand, and it left users of a desktop memory app without one.

Market shape
- Only 11 first-time entries in the October 2026 list, the fewest of seven editions ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). Incumbents are absorbing ideas, as with Pulse and Gemini Daily Brief.

### Inferences
Why these caught on (my reading of the pattern):
- Attached to an existing moment: a meeting, a text box, a pile of lecture notes.
- Instant output that shows its worth once. A dictated paragraph or a tidy set of notes beats a promise.
- No new place to go, which is close to Noir's own goal of working inside the user's work.
- Bot-free. Granola's quiet capture lacks the social cost of a bot in the meeting.

Ideas with the best evidence for Noir, in order:
1. **Local dictation into any app.** Highlight agents already work system-wide. Speech to text can run locally, which answers privacy worries Wispr cannot, since its app can read keystrokes ([Wikipedia](https://en.wikipedia.org/wiki/Wispr_Flow)).
2. **Private meeting or lecture notes.** Strong pull, and on-device recording is a real difference from Granola. Lecture detection already exists in her watcher, and the Summarize Video job is listed as not built.
3. **Study from my own notes, with audio read-out.** Extends the documents agent, with NotebookLM as the model. Local text-to-speech quality was not researched.
4. **Simple local memory the user can read and edit.** Costs little, matches a leader's feature, and is private by default.
5. **Morning note from local things only.** Files, reservations and yesterday's jobs. Weakest of the five, because daily feeds have the poorest record and without connectors it has little to say.

### Gaps
- No independent usage figures for Granola, Wispr or NotebookLM; retention numbers are company claims or narrow panels.
- No figures for Huxe. No evidence that any screen-reading assistant has kept ordinary users. A search on Windows Recall usage returned nothing.
- Agent adoption numbers come mostly from founders.
- Unverified, from search summaries I could not tie to a page: Wispr's round at about $260M rather than $280M; 17M NotebookLM monthly users from a review with no source; Amazon's purchase of the Bee wristband.

## Is there a gap for an offline and private assistant in schools, clinics, law offices, small businesses, or countries with weak internet?

### Takeaway
Demand signals are real, especially privacy concern and confidentiality in law. Working pilots exist in health and schooling, but all are small. No one appears to serve non-technical offices with a simple offline assistant, though I found no direct survey proving they would adopt one, and hardware limits are the main barrier.

### Cited Findings

Demand
- 71% of Americans say AI will make personal data less secure ([TNW on Pew](https://thenextweb.com/news/pew-research-americans-ai-chatbot-skepticism-regulation-distrust-2026?type=AI)). Among non-users, privacy is a major reason for 54% ([Pew](https://www.pewresearch.org/internet/2026/06/17/why-dont-people-use-chatbots/)). [Survey, strong]
- Law: Clio's 2026 survey shows 71% of solos and 75% of small firms using AI, 57% and 55% with no AI policy, and only about a third reporting a revenue gain ([NC Bar, May 2026](https://ncbar.org/nc-lawyer/2026-05/by-the-numbers-what-surveys-show-about-law-firm-ai-adoption)). [Survey]
- 46% of legal professionals rank data privacy compliance and protecting sensitive information as top concerns, and 43% client confidentiality ([Wolters Kluwer, Mar 3 2026](https://www.wolterskluwer.com/en/expert-insights/information-security-gdpr-data-privacy-cyber-threats-legal)). [Survey, vendor-run]
- ILTA's 2026 survey put confidentiality, hallucinations and privilege as the top three risks, with disputes over whether cloud vendors keep uploaded material ([Lawxy summary](https://www.lawxyai.com/news/ilta-survey-spurs-shift-toward-ai-fact-analysis-tools-for-litigators)). [Reported, secondhand, vendor site]
- OpenEvidence, for physicians, debuted at #47 on web ([a16z 7th](https://a16z.com/100-gen-ai-apps-7/)). Trusted, specialised, sourced answers have a market in medicine. [Measured estimate]

Supply and pilots
- Uganda: EaseHealth ran MedGemma 4B offline on Samsung A16 phones with 8GB of RAM, in 15 health facilities with 268 consenting workers and 87+ assessments in five days, at about 40 seconds per answer. Most workers' phones lack the RAM, which is the main barrier. Further accuracy validation is still funded work ([Google showcase, updated Jun 30 2026](https://developers.google.com/health-ai-developer-foundations/showcase/crane-ai)). [Company, feasibility only, no outcome trial]
- Guatemala: Intel and World Wide Technology donated laptops with an offline tutor to a nonprofit school, with plans for India, Africa and South America ([Intel, Jul 2025](https://newsroom.intel.com/artificial-intelligence/intel-brings-offline-ai-opportunity-to-students-in-guatemala)). [Company, plans unconfirmed]
- South Africa: Mdali describes offline models on basic phones and a school pilot ([LinkedIn](https://linkedin.com/company/mdali)). [Company, weak] An offline-first education paper had its latest version withdrawn ([arXiv 2603.03339](https://arxiv.org/abs/2603.03339v3)), so do not rely on it.
- Ollama is reported at about 52M monthly downloads in Q1 2026 ([Vucense](https://vucense.com/ai-intelligence/local-llms/ollama-hits-52-million-downloads-local-ai/)) and 8.9M monthly active developers with a $65M Series B ([FeedBagel](https://feedbagel.com/post/save-what-matters-1783603265)). [Weak, low-authority, developers rather than ordinary users] Note these are download and developer counts, not ordinary people.
- Solo and small practices adopt slowly because upfront workflow work feels heavier than the payoff ([Enterprise DNA, Australia](https://enterprisedna.co/resources/blog/au-ai-legal-profession)). [Anecdote]

### Inferences
- The most reachable near-term buyers are small offices that already hold private client files on a Windows laptop: small law offices, accountants, therapists, tutors. Noir's folder agent with sources fits this job best, and a confidentiality promise is her strongest argument. No legal review was done, so she cannot claim compliance.
- Schools and clinics in low-connectivity settings are a real need, but they often lack the hardware. Uganda shows 8GB phones can work but slowly, while most existing phones cannot. Noir's hardware check gives her an honest answer here. A fixed-setup laptop or shared classroom machine may be more practical than personal devices.
- Clinics are the hardest fit: the Uganda team needed a medical model, strict filters and ethics approval. Noir should not go there as a clinical tool. Non-clinical paperwork in a clinic may be feasible.
- For weak-internet countries, the first install is the barrier: downloading a model of several gigabytes. Offline installs from a USB stick would be a direct answer. This is my reasoning, not a sourced finding.
- The category looks like an open gap, but the absence of a product may also reflect a small willingness to pay. That has not been tested.

### Gaps
- No survey on on-premise or local AI use in small law firms, clinics or schools, and no figures for how many would pay for it.
- No data on students or teachers specifically in Pew results found; no 2026 evidence of offline AI at scale in Africa or India.
- No evidence on typical laptop RAM in schools or small offices in target countries.
- Unverified, from search summaries I could not tie to a page: 21,639 publicly exposed OpenClaw instances with 63% lacking authentication, and Hermes reaching first place on OpenRouter around May 2026.
