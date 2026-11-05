# Local AI tools and open agent apps: what real users love, hate and give up on

Prepared 2026-11-01.

**Evidence labels.** [M] measured or counted data. [P] primary source: project docs, a security lab's own research, or a first-hand technical report. [A] anecdote from one user or reviewer. [V] vendor, competitor or SEO content with an interest or no shown method. Strength follows each label where it matters: strong, moderate or weak.

**Read these limits first.**
- Reddit could not be read. The search and fetch tools here refuse reddit.com, so r/LocalLLaMA, r/ollama, r/LMStudio and r/selfhosted are absent except where another page reports them second-hand. This is the largest hole in these notes, because Reddit is where most of the user stories are. Hacker News (HN) and GitHub stand in for it, and both lean heavily towards developers.
- Non-technical users barely appear in any of these sources. They do not file GitHub issues or post on HN. Almost everything said about them comes from technical people speaking for them.
- Almost everything here is paraphrased, with one verbatim quote in the whole file. Each paraphrase links to its source so the wording can be checked.
- GitHub numbers were pulled from GitHub's public API at the time of writing (repo pages linked below). Stars are not users. HN dates, points and the one quote were checked against the HN Algolia API.

## 1. What do users love about each tool, and why do they choose one over another?

### Takeaway
People choose along three lines: no terminal (LM Studio), one command plus plumbing for other apps (Ollama), or openness and control (Jan, Open WebUI, AnythingLLM). The tool most often recommended to non-technical people, GPT4All, has not shipped a release since February 2025, and reviews still present it as active.

### Cited Findings

**Scale and activity [M, strong for activity; stars are only a rough signal of interest]**

| Project | Stars | Latest release | Open issues plus PRs |
| --- | --- | --- | --- |
| [OpenClaw](https://github.com/openclaw/openclaw) | 393,671 | v2026.10.9, 29 Oct 2026 | 7,698 |
| [Hermes Agent](https://github.com/NousResearch/hermes-agent) | 259,585 | v0.22.5, 23 Oct 2026 | 52,262 |
| [Ollama](https://github.com/ollama/ollama) | 185,631 | v0.40.13, 28 Oct 2026 | 4,540 |
| [Open WebUI](https://github.com/open-webui/open-webui) | 157,507 | v0.12.5, 29 Oct 2026 | 165 |
| [GPT4All](https://github.com/nomic-ai/gpt4all) | 77,345 | **v3.10.0, 25 Feb 2025**; last push 27 May 2025 | 776 |
| [AnythingLLM](https://github.com/Mintplex-Labs/anything-llm) | 67,841 | v1.19.0, 26 Oct 2026 | 363 |
| [Jan](https://github.com/janhq/jan) | 45,279 | v0.8.8, 28 Oct 2026 | 567 |
| [LM Studio](https://github.com/lmstudio-ai/lmstudio-bug-tracker) | App is closed source; public bug tracker only | Not on GitHub | 2,026 |

**Ollama**
- Raised $65M in a Series B on 9 Jul 2026, with nearly 9M developers reported. The figure comes from the company and its basis varies between outlets (one says 8.9M monthly active developers) — [TNW](https://thenextweb.com/news/ollama-65m-series-b-theory-ventures-open-models), [BetaKit](https://betakit.com/kitematic-founders-nab-65-million-usd-to-help-devs-run-ai-models-locally-with-ollama/) [V, moderate: the raise is solid, the user figure is unverified]
- Why people stay: a single command, automatic hardware handling, a curated model library, and on Mac it simply works. Why people leave: llama.cpp ran the same model faster for some users, models are stored under hashed names other apps cannot reuse, and credit to llama.cpp was slow in coming. This comes from a 648-point HN thread of 16 Apr 2026 — [HN](https://news.ycombinator.com/item?id=47788385) [A, moderate because many voices agree]
- The speed claim is not settled. The figure of 1.8 times slower is one [write-up's summary](https://note.com/hacklog_stealth/n/n8244ae42b876?hl=en) of a claim, not an independent benchmark [V, weak]
- A public request about licence notices has 283 upvotes and has been open since March 2024 — [#3185](https://github.com/ollama/ollama/issues/3185) [M]
- Ollama's model labels led casual users to believe they were running the full DeepSeek model — [HN, kgwgk](https://news.ycombinator.com/item?id=47788385) [A]

**LM Studio**
- Liked because it has a GUI, needs no terminal and hides the backend — [HN](https://news.ycombinator.com/item?id=44135827), [HN](https://news.ycombinator.com/item?id=43755735), [XDA](https://www.xda-developers.com/ditched-lm-studio-for-open-source-alternative/) [A, moderate because the reports are consistent; these threads are mostly 2025]
- The standing objection is that it is closed source with access to machine details. Defenders reply that it can be firewalled, and one saw no suspicious network calls using Little Snitch — [HN](https://news.ycombinator.com/item?id=47624999), [HN](https://news.ycombinator.com/item?id=46349037) [A]
- The most upvoted request across all eight trackers is Intel Mac support: 422 upvotes and 444 comments, open since May 2024 — [#9](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/9) [M]
- Users object to it editing their shell config files — [#656](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/656), 56 upvotes [M]

**Jan**
- Won XDA's 19 Jun 2026 test of LM Studio, llama.cpp, Jan and AnythingLLM with Gemma 4 E4B, because it reached the model's audio and vision features and had easy MCP toggles. The test is one reviewer, with hardware described only as a desktop PC — [XDA](https://www.xda-developers.com/tested-local-llm-different-tools-and-only-one-unleashed-its-potential/) [A, weak to moderate]
- Sumguy's comparison (30 Jul 2026, updated 5 Sep) calls Jan riskier than LM Studio to hand to a non-technical relative — [Sumguy](https://sumguy.com/lm-studio-vs-jan-vs-gpt4all/) [V, weak]
- Its top-voted bug is models failing to download in v0.7.8 (10 upvotes, 32 comments, Mar 2026) — [#7728](https://github.com/janhq/jan/issues/7728) [M]

**GPT4All**
- Still recommended for non-technical people who want to chat with their documents, for its built-in LocalDocs and curated model list — [Sumguy](https://sumguy.com/lm-studio-vs-jan-vs-gpt4all/), [ML Journey](https://mljourney.com/gpt4all-review-2026-is-it-still-worth-using/) [V, weak]
- **Fans overstate this.** ML Journey's October 2026 review says the team ships new versions regularly, but GitHub shows the last release was 20 months earlier — [ML Journey](https://mljourney.com/gpt4all-review-2026-is-it-still-worth-using/), contradicted by [GPT4All releases](https://github.com/nomic-ai/gpt4all/releases) [M, strong]

**Open WebUI**
- Moved from plain BSD-3 to a custom licence in April 2025, adding a branding clause that matters mainly for rebranding above 50 users. It drew backlash and talk of forking — [Aliteq](https://aliteq.com/open-webui-license-explained-2026), [BigGo, Nov 2025](https://biggo.com/news/202511041923_open-webui-license-change-backlash) [V, moderate on the facts]

**AnythingLLM**
- It is a document-focused frontend, not a model runner, so a reviewer could not tell whether results reflected the app or the model behind it. Its memory worked well, but it has no audio input — [XDA](https://www.xda-developers.com/tested-local-llm-different-tools-and-only-one-unleashed-its-potential/) [A, weak]
- Its top request is fine-grained access control (59 upvotes), which suggests a team audience — [#1787](https://github.com/Mintplex-Labs/anything-llm/issues/1787) [M]

**Msty**
- Free for personal use, and paid commercial use needs a per-user licence — [Msty licence](https://msty.app/license) [P]
- The $149 per user, per year Aurum price appears only on a development domain and a directory, and another listing calls pricing opaque — [Msty pricing page](https://msty-studio-site.nuxt.dev/pricing), [Toolradar](https://toolradar.com/tools/msty/pricing) [V, weak]

### Inferences
- The easy tools stay out of the way, and the capable ones expose settings. No tool here shows an answer to the question of what a non-technical person should do first.
- Reviews of local AI tools are unreliable on freshness. Release dates should be checked directly rather than taken from a comparison post.

### Gaps
- I found no real user sentiment on Msty: no reviews, complaints or threads. Treat it as unknown.
- I found no neutral count of how many people actually use each tool. Stars and company claims do not answer that.

## 2. Where do they get stuck?

### Takeaway
The documented stuck points are broken updates, and defaults that make a model seem worse than it is. Ollama's default context on ordinary PCs is 4K, while its own docs ask for 64K for agents. Confusion over GB, VRAM, quantization and GGUF is plain to see, but I found no study that measures it.

### Cited Findings

**Defaults**
- Ollama gives under 24 GiB VRAM a 4K context, 24 to 48 GiB gets 32K, and 48 GiB or more gets 256K. The same page says agents, web search and coding tools need at least 64K — [Ollama docs](https://docs.ollama.com/context-length) [P, strong]
- An HN thread of 22 Aug 2026 (511 points) names the causes of a model seeming dumb: template and parser bugs, heavy quantization, sampling and context handling. One commenter reported a parser bug that caused self-correction loops growing worse over long sessions. Commenters also said a Qwen template defaulted to the highest reasoning effort, and lowering it helped — [HN](https://news.ycombinator.com/item?id=49402232) [A, moderate; article itself not read]
- In the same thread, one user wished for better tools to isolate such problems — [HN, shostack](https://news.ycombinator.com/item?id=49402232) [A]
- Gemma 4's reasoning leaked into the visible answer in LM Studio — [XDA, 19 Jun 2026](https://www.xda-developers.com/tested-local-llm-different-tools-and-only-one-unleashed-its-potential/) [A]

**Broken updates**
- Ollama 0.23.3 froze a Windows 11 machine by reserving huge amounts of memory (May 2026) — [#16123](https://github.com/ollama/ollama/issues/16123) [P, single report]
- Llama 3.2-vision stopped loading after an update, and a maintainer advised rolling back to 0.24.0. Comments continued into October — [#16490](https://github.com/ollama/ollama/issues/16490) [P]
- 0.30.0 broke the OpenCode integration (June 2026), and one user removed Ollama from their server. A fix came in July — [#16424](https://github.com/ollama/ollama/issues/16424) [P]
- In October 2026 a user reported a working install broken by an update and not repaired by reinstalling, with downloaded models missing from the list — [#19276](https://github.com/ollama/ollama/issues/19276) [P, single report]
- New models can fail on arrival: Gemma 4 on Apple's MLX would not load in LM Studio (54 upvotes, Apr 2026) — [#1741](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/1741) [M]

**Install and first run**
- Hermes Desktop failed setup with a GitHub HTTP 429 error before later reaching the main app, and its source launcher failed under system Python while the venv launcher worked (Aug 2026, Mac mini) — [Zentor](https://zentor.ai/blog/hermes-agent-desktop-review) [V: Zentor sells a competing product, but this is a dated hands-on log]
- Sumguy's advice is not to hand a relative a terminal and a curl command — [Sumguy](https://sumguy.com/lm-studio-vs-jan-vs-gpt4all/) [V, weak]

**Choosing a model**
- Guides converge on Q4_K_M as the safe default, but they assume the reader already knows VRAM, context length and file sharding — [Logeshwaran](https://www.logeshwaran.org/2026/10/gguf-quantization-types-explained.html), [Tech Insider](https://tech-insider.org/gguf-model-quantization-2026/) [V, weak]

**Speed and heat**
- Sustained local inference runs hot and drains laptop batteries. One user watched a model spin for twenty minutes and then fail, and another said it wasn't interactive enough for them — [HN, 22 Aug 2026](https://news.ycombinator.com/item?id=49402232) [A]
- One writer saw 10 to 30 seconds per basic output against under a second from the OpenAI API — [Medium, mid-2025, older](https://medium.com/@Shamimw/why-i-stopped-using-ollama-and-local-models-and-switched-back-to-openai-2d125f303e1c) [A, weak]

### Inferences
- A model on an ordinary PC under Ollama's default gets about one sixteenth of the context Ollama itself asks for in agent work (4K against 64K). An app built on Ollama must set this itself instead of trusting the default.
- Users cannot tell a bad model from a bad setup. Experts in the HN thread could not always tell either, so a beginner has no chance without help.

### Gaps
- I found no usability study of non-technical users choosing a model or understanding GB, VRAM or GGUF. Searches returned only guides.
- I found no measured install failure rate, no crash telemetry and no first-week drop-off numbers for any tool.
- A search result claimed Ollama does not accelerate integrated graphics as of v0.24. The [hardware guide](https://www.myaihardware.com/ollama-hardware-guide) it seemed to come from does not say this, so it is unconfirmed. This matters for laptops without a graphics card.

## 3. What is the honest quality gap, and what do users really use local AI for?

### Takeaway
The best open models trail the frontier by about four months, but people cannot run those on a normal PC, so that figure says little about their experience. I found no measured comparison of small local models with cloud models on everyday tasks. Users report local working for simple text jobs and cloud being kept for hard ones.

### Cited Findings
- The top closed model led the top open model by 3.3% on the Arena leaderboard in March 2026, up from 0.5% in August 2024. Six of the top ten Arena models are closed — [Stanford AI Index 2026](https://hai.stanford.edu/ai-index/2026-ai-index-report/technical-performance) [M, strong for what it measures: human preference votes]
- Since January 2026, the most capable open-weight models have trailed frontier closed models by four months on average, or 8 points on Epoch's capability index — [Epoch AI, 29 May 2026](https://epoch.ai/data-insights/open-closed-eci-gap) [M, strong, again for top models only]
- **Fans overstate this.** InsiderLLM's table shows local models beating GPT-4o, but GPT-4o was retired on 13 Feb 2026. The same article puts GPT-5.2 at 93.2% on GPQA Diamond against about 50% for GPT-4o, says the best open result is about 80%, and says GPT-5.2 has no local equivalent for hard problems. The article shows no test method — [InsiderLLM, updated 15 Oct 2026](https://insiderllm.com/guides/local-llms-vs-chatgpt-honest-comparison/) [V, weak on numbers]
- The same article rates a 32B local model as handling email drafts, summaries and creative writing. It rates local as poor at multi-step web research and weak on graduate-level science. A 32B model is already well beyond a typical PC — [InsiderLLM](https://insiderllm.com/guides/local-llms-vs-chatgpt-honest-comparison/) [V, weak]
- Real use on an 8 GB M2 MacBook Air: summarizing, rewriting, pulling data from images, simple coding, and removing account numbers from bank statements before sending them to a cloud model. He also uses it for simple tasks to save his Claude limits, and keeps complex work for Claude — [How-To Geek, 21 Mar 2026](https://www.howtogeek.com/why-i-use-chatgpt-and-local-llms/) [A, moderate as the clearest low-end report]
- For developers, Python and sysadmin help, memory-safety review and casual chat were the reported uses — [HN, 8 Aug 2025, older and only 16 points](https://news.ycombinator.com/item?id=44837130) [A, weak]
- One user replaced OpenClaw with Hermes for home-server admin and found it better with small chunks of work — [HN, Jun 2026](https://news.ycombinator.com/item?id=48419000) [A]
- Another found a local model surprisingly capable, but unreliable and slow past about 80K of context — [HN, jonplackett, Aug 2026](https://news.ycombinator.com/item?id=49402232) [A]

### Inferences
- The honest statement for an ordinary PC is that local can do bounded text tasks where a person checks the result, and cloud stays ahead for research, hard reasoning and long multi-step work. This is inferred from anecdotes, not measured.
- Stanford's and Epoch's gaps should not be quoted as if they describe a small model on a home PC. That would flatter local AI.
- Redaction before cloud use is a task local does better than cloud by its nature, and it suits non-technical users.

### Gaps
- **Most important gap:** I found no independent benchmark of 4B to 8B models against current ChatGPT or Gemini on everyday tasks such as emails, summaries and simple questions.
- A claim of an 8 to 10 month gap on private benchmarks appeared in search results. Epoch's report that I opened is from November 2024 and does not contain it, so I could not source it and left it out.
- I found no survey of what ordinary people use local AI for. Searches turned up no Ollama user survey.

## 4. Why do people abandon local AI after trying it? Why do they stay?

### Takeaway
The stated reasons to leave are speed, quality, and upkeep when updates break things. People stay for privacy, control, and freedom from limits and filters. Most stable users are hybrid. Money is not a good reason for most people, because the hardware rarely pays for itself against a $20 subscription.

### Cited Findings

**Leaving**
- A non-technical-seeming relative abandoned an agent. An HN user gave his brother an OpenClaw, and the brother's final feedback before dropping it was: "It feels like I need to know programming." — [HN, sshine, 9 Jun 2026](https://news.ycombinator.com/item?id=48419000) [A, weak as data but the most direct case found; the brother's skills are not stated]
- One developer went back to OpenAI because local was slow, repetitive and inaccurate, with wrong math — [Medium, mid-2025, older](https://medium.com/@Shamimw/why-i-stopped-using-ollama-and-local-models-and-switched-back-to-openai-2d125f303e1c) [A, weak]
- An OpenClaw update broke the dashboard and WhatsApp link. Experienced users needed 30 to 60 minutes to repair it, and less experienced users waited days on Reddit — [OpenClawDC](https://openclawdc.com/blog/openclaw-self-hosting-risks/) [V, weak]
- Ownership is a real cost: reading logs, picking models and fixing problems locally. Non-technical users are told to allow time before trusting daily workflows — [Zentor](https://zentor.ai/blog/hermes-agent-desktop-review) [V, conflicted]

**Money**
- Break-even for a used RTX 3090 (about $1,500, plus about $70 a year in power) against ChatGPT Plus is 106 months. A Mac Mini against Plus is 110 months. The article withdrew its earlier 5 and 10 month claims, which used Pro-tier pricing. Against heavy API use ($250 a month), break-even is 7 months — [InsiderLLM](https://insiderllm.com/guides/local-llms-vs-chatgpt-honest-comparison/) [V, the arithmetic checks out; prices are eBay-based]

**Staying**
- The pattern in the recent pieces is hybrid: local for private or simple work, cloud for hard work — [XDA](https://www.xda-developers.com/local-vs-cloud-llms-workflow/), [How-To Geek](https://www.howtogeek.com/why-i-use-chatgpt-and-local-llms/) [A, moderate because the reports repeat]
- Even a writer who stopped paying for ChatGPT keeps it as a fallback when his home server cannot be reached — [XDA](https://www.xda-developers.com/local-llm-home-server-tailscale-replace-chatgpt/) [A]
- Reasons given for staying include privacy, and fewer content filters for roleplay and creative work — [How-To Geek](https://www.howtogeek.com/why-i-use-chatgpt-and-local-llms/) [A]

### Inferences
- A pitch built on saving money would mislead most people. A pitch built on privacy and on using what you already own is honest, and it does not need a hardware purchase.
- Full replacement is the expectation that breaks. Tools that frame local as a helper for particular jobs ask less of it, which fits how lasting users describe their setups.

### Gaps
- I found no retention numbers from any vendor or researcher.
- I found no 2026 first-person account of dropping local AI and returning to ChatGPT. This likely reflects who writes such posts, since people who quit rarely publish about it, so it should not be read as evidence that few people quit.

## 5. Agents, skills and marketplaces in Hermes, OpenClaw and similar tools

### Takeaway
OpenClaw's marketplace problems are well documented: about 12% of audited skills were malicious in early 2026, and scanners added afterwards still missed some. **Solid evidence on Hermes is thin.** It consists of GitHub issues, one security audit, one commercially conflicted hands-on test and one small HN thread, with nothing on long-term reliability or on non-technical users.

### Cited Findings

**OpenClaw and ClawHub: malicious skills**
- Koi Security documented 341 malicious skills, over 300 of them sharing one pattern. Bitdefender found about 17% of the skills it analyzed carried malicious payloads in early February 2026. The 341 is about 12% of the 2,857 audited — [Unit 42, 23 Jun 2026](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/), [vendor press release, 26 Mar 2026](https://www.tradingview.com/news/reuters.com,2026-03-26:newsml_ACN105904:0-openclawd-ships-verified-skill-screening-after-security-researchers-find-12-of-openclaw-marketplace-skills-are-malware/) [P, strong for early 2026; the rates depend on when and what was sampled]
- Snyk scanned 3,984 skills from ClawHub and skills.sh on 5 Feb 2026. 36.82% had any security issue, 13.4% had a critical issue, and 76 were confirmed malicious. **The common claim that 36% are malicious or prompt injection is wrong:** the 36% covers any flaw at any severity, including hardcoded keys, and the page gives a 2.6% prompt injection rate on ClawHub — [Snyk](https://snyk.io/blog/toxicskills-malicious-ai-agent-skills-clawhub) [P, strong; detection claims are Snyk's own]
- After VirusTotal and ClawScan screening began, Unit 42 still found five unblocked malicious skills between February and May 2026. They included infostealers and one skill hiding behind a 22 MB padded README to exceed scanner limits. Attacker infrastructure stayed up for over three months after first disclosure. ClawHub announced NVIDIA screening on 1 Jun 2026 — [Unit 42](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/) [P, strong]
- **The attack worked on the user's trust, not on code.** Fake prerequisite steps got agents to run hidden commands, and fake error messages got users to paste commands that installed Atomic Stealer. One skill, money-radar, quietly steered financial advice towards affiliate links — [Unit 42](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/) [P]. The fake error messages are reported in a [vendor press release](https://www.tradingview.com/news/reuters.com,2026-03-26:newsml_ACN105904:0-openclawd-ships-verified-skill-screening-after-security-researchers-find-12-of-openclaw-marketplace-skills-are-malware/) [V]

**OpenClaw: other security and cost**
- Nine OpenClaw CVEs came out over 18 to 21 Mar 2026, including CVE-2026-22172 at CVSS 9.9. The note's title and address frame them around Hermes, but these nine are OpenClaw's — [CSA note, 4 May 2026](https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/) [P, moderate: cites databases, not independently verified]
- Exposed-instance counts conflict: 135,000, 63,070, 40,214 and 21,000 all circulate — [CyberDesserts](https://blog.cyberdesserts.com/openclaw-malicious-skills-security/), [OpenClawDC](https://openclawdc.com/blog/openclaw-self-hosting-risks/), [API Stronghold](https://www.apistronghold.com/blog/21k-exposed-openclaw-instances-why-your-ai-agent-tokens-are-leaking) [V, weak on any single number; the existence of large exposure is not in doubt]
- China's industry ministry warned about users running it with weak security settings — [MarketScreener](https://sa.marketscreener.com/news/china-warns-of-security-risks-linked-to-openclaw-open-source-ai-agent-ce7e5adbdf8bf321) [moderate]
- Sandboxing for its code execution is off by default, according to OpenClaw's own comparison page — [OpenClaw docs](https://docs.openclaw.ai/start/why-openclaw/openclaw-and-hermes-agent) [P, via search summary, page not opened]
- Reported API costs run from about $40 for a misconfigured job to $3,600 a month for one heavy user, and a headline claims $750 a month. These are examples, not typical bills — [Medium](https://medium.com/@reza.ra/openclaw-the-ai-agent-that-burns-through-your-api-budget-and-how-to-fix-it-050fc57552c9), [PickYourAITool](https://pickyouraitool.com/blog/openclaw-real-cost-2026/) [A/V, weak]

**OpenClaw with local models**
- The docs give an 8 GiB host-memory floor for the smallest curated recipe, warn this does not guarantee useful speed, and use 64K context. They advise avoiding small or heavily quantized variants, and warn that a model passing a short test may still fail a full agent turn. Local models also lack hosted safety filters — [OpenClaw docs](https://docs.openclaw.ai/gateway/local-models) [P, strong]

**Hermes: what is established**
- Exists and is very active: 259,585 stars, MIT licence, and a native Windows PowerShell installer that does not need WSL. Its Skills Hub is listed as a community resource pointing to agentskills.io — [GitHub](https://github.com/NousResearch/hermes-agent) [M/P]
- A hands-on test of v0.20.4 (21 Aug 2026, Mac mini, with a cloud model) passed chat, a file task and session resume, and showed 78 bundled skills. It hit setup errors, browser tools were not fully available, and no lasting memory files appeared during the short test. Long-term reliability, browser automation and email were not evaluated — [Zentor](https://zentor.ai/blog/hermes-agent-desktop-review) [V: competitor]
- Any use requires a model route: provider account, OAuth, API key or local endpoint. That is a first-run decision a non-technical person cannot easily make — [Zentor](https://zentor.ai/blog/hermes-agent-desktop-review) [V]
- The desktop app arrived as a public preview on 2 to 3 Jun 2026, and on Windows its in-app terminal pane still needs WSL2 — [Digital Applied, 5 Jun 2026](https://www.digitalapplied.com/blog/hermes-agent-desktop-app-complete-guide-2026) [V, moderate: checked on the page]

**Hermes: reliability reports**
- Bug reports say the agent reads stored rules without following them, and that skill and memory recall decays over time — [#49764](https://github.com/NousResearch/hermes-agent/issues/49764), [#76307](https://github.com/NousResearch/hermes-agent/issues/76307) [P, individual reports]
- Changes to memory reach the system prompt only in the next session, which explains some reports of it forgetting — [Hermes docs](https://hermes-agent.nousresearch.com/docs/guides/troubleshooting-agent-quality) [P]
- Tutorials report overwritten skills and a limit of about 2,200 characters on MEMORY.md. A skills guide calls forgetting to use installed skills the top Reddit complaint, which I could not check — [Qwe tutorial](https://www.qwe.edu.pl/tutorial/hermes-agent-self-improving-ai/), [Opsily](https://opsily.com/blog/hermes-agent-skills) [V, weak]
- HN thread of 5 Jun 2026 (52 points, 42 comments): one user found it slow to start and over-engineered and stopped early, another disliked its flickery CLI, and another runs it with local inference and likes that everything stays home. Much of the thread is a plagiarism dispute instead, and the linked hermes-agent.org site states it is not affiliated with Nous — [HN](https://news.ycombinator.com/item?id=48419000) [A, weak]
- Compared with OpenClaw, Hermes was praised as more dependable for one user's small tasks, but cost was only touched on, in a comment that these agents burn tokens quickly — [HN](https://news.ycombinator.com/item?id=48419000) [A, weak]

**Hermes with local models**
- On an M1 Max with 32 GB, Hermes v0.17.0 hung with no output on three local models with the full toolset, for up to five minutes, while the same models answered in seconds through raw Ollama. It was still open when I read it, with only an AI-generated triage reply and no confirmed fix — [#56994, 2 Jul 2026](https://github.com/NousResearch/hermes-agent/issues/56994) [P, one report; labelled a duplicate, which suggests others hit it]
- The same report says Hermes refuses to start below a 64,000-token context, and checks Ollama's reported value, not the model's true limit — [#56994](https://github.com/NousResearch/hermes-agent/issues/56994). Asking for a model's full advertised context caused memory errors and slow starts for another user — [#46833](https://github.com/NousResearch/hermes-agent/issues/46833) [P]
- Hermes docs admit that 3B and 7B models sometimes ignore tool-call instructions and output plain text, and they recommend bigger models. They also describe auto-repair and a fallback to the cloud after three local failures — [Hermes docs](https://hermes-agent.nousresearch.com/docs/guides/local-ollama-setup) [P, via search summary]

**Hermes: security**
- An independent audit of v0.8.0 (issue #7826, 11 Apr 2026) reported 4 Critical and 9 High findings in the default configuration, including unrestricted shell use and a skill manager that allows persistence. This is one researcher's review, with no CVEs assigned — [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/) [P, moderate]
- Three CVEs at CVSS 4.0 to 5.3 were public by May 2026, which dates claims of zero CVEs — [CSA note](https://labs.cloudsecurityalliance.org/research/csa-research-note-hermes-agent-cves-20260504-csa-styled/), contrast [MeshWorld](https://meshworld.in/blog/ai/agents/hermes-agent-security/). Another write-up lists CVE-2026-9353 in Skills Guard, fixed in 0.15.0 — [Repello](https://repello.ai/blog/hermes-agent-security) [V, not checked against NVD]
- Sources conflict on the marketplace. Some say Hermes has none, so malicious skills are an OpenClaw problem, but its README lists a Skills Hub, and third-party HermesHub exists and claims to scan every listing — [HackerNoon](https://hackernoon.com/hermes-agent-vs-openclaw-which-ai-agent-framework-wins-in-2026), [GitHub README](https://github.com/NousResearch/hermes-agent), [HermesHub](https://github.com/Almured/hermeshub)

### Inferences
- A marketplace carries the same supply-chain risk as any app store, while the code runs with the agent's own powers. Screening helps but has failed in practice, as Unit 42 shows. Curated, tested recipes avoid most of this.
- Small models are the weakest at the very thing agents need, which is structured tool calls. Both projects' own docs steer people to bigger models or to the cloud, so local-only agents on ordinary hardware are not well supported by either.
- The non-technical failure is less about security than about usefulness: a person asks for something simple and it does not work. Security problems are then a risk those users cannot see or judge.
- Hermes's 52,262 open items can be read as a sign of heavy use or of a backlog beyond what the team can review. The data does not settle which, and some triage is AI-generated.

### Gaps
- **Hermes:** I found no solid evidence on long-term reliability, real costs, adoption by non-technical users or abandonment. No measured skill quality data exists for it. Do not fill this with blog claims.
- One blog's summary said reaction to the Hermes Desktop release skewed positive. I could not trace this to real threads, so I am not treating it as evidence.
- Nous Portal pricing is unverified. The figures online trace to a Nous social post rather than a pricing page — [Digital Applied](https://www.digitalapplied.com/blog/hermes-agent-desktop-app-complete-guide-2026).
- Lookalike sites are a hazard for this research. hermes-agent.org says it is unaffiliated, and I did not establish the status of other domains using the name.
- I found no direct user accounts of quitting because of an agent bill.

## 6. What hardware do people have, and how much of the normal consumer market can run a useful model well?

### Takeaway
Among Steam gamers, who are better equipped than the average buyer, 8 GB is again the most common graphics memory and nearly 4 in 10 have 8 GB or less. I found no figure for ordinary non-gaming PCs. Chat and simple text jobs on small models are within reach, while agent work is a much harder fit, and PC prices are rising.

### Cited Findings
- Steam, October 2026, all platforms, VRAM: 8 GB 26.92% (+0.21), 16 GB 26.35% (−0.86), 12 GB 12.91%, 4 GB 5.54%, 24 GB 5.40%, 6 GB 5.20% — [Steam survey](https://store.steampowered.com/hwsurvey/) [M, strong as a measure of Steam users]
- This reverses a story still circulating. 16 GB overtook 8 GB in July (25.90% against 25.32%, a 0.58-point lead) and held on through September, but October puts 8 GB back on top. The October delta matches September's reported 27.21% for 16 GB — [Igor's Lab, 5 Aug 2026](https://www.igorslab.de/en/16-gb-vram-overtakes-8-gb-steam-survey-gaming-pcs/), [PCGamesN](https://www.pcgamesn.com/steam/hardware-survey-july-2026-gpus), [Tech Insider](https://tech-insider.org/steam-hardware-survey-august-2026/) [M]
- Steam publishes no confidence interval, and Valve has confirmed that some cards' memory was for a time recorded wrongly. Small month-to-month leads and long-term trends should both be read loosely — [Igor's Lab](https://www.igorslab.de/en/16-gb-vram-overtakes-8-gb-steam-survey-gaming-pcs/) [P, moderate]
- On Windows alone, 8 GB is reported further ahead, at 35.78% in September — [Tech Insider](https://tech-insider.org/steam-hardware-survey-august-2026/) [V, not checked against Valve's Windows table]
- System RAM, October 2026: 16 GB 41.42% (+3.60), 32 GB 37.06% (−5.16), 8 GB 7.52%, 64 GB 3.94%, 12 GB 2.45%. A 5-point move in a month points to sampling swings. OS share: Windows 93.70%, Linux 3.95%, macOS 2.35% — [Steam survey](https://store.steampowered.com/hwsurvey/) [M]
- PC shipments are forecast to fall 11.3% in 2026 and average prices to rise 17%, with no meaningful memory relief before the end of 2027 and limited availability of some configurations — [IDC, 2 Jun 2026](https://www.idc.com/resource-center/blog/pc-market-enters-volatile-territory-as-memory-shortage-persists-through-2027/) [M/forecast, strong source]
- Rule-of-thumb sizes: a 7B to 8B model at Q4_K_M needs about 5 GB of graphics memory, a 30B to 34B model about 20 GB. The guide says these are approximate and assume an 8K context, so agent work at 64K needs more — [Ollama hardware guide](https://www.myaihardware.com/ollama-hardware-guide) [V, unmeasured]
- HN enthusiasts report M1 Max to M5 Max Macs with 36 to 128 GB, RTX 4090 and 5090 cards, some 4 to 8 GB machines, and rented GPUs — [HN, 22 Aug 2026](https://news.ycombinator.com/item?id=49402232) [A]
- An 8 GB M2 Air remained useful for small jobs — [How-To Geek](https://www.howtogeek.com/why-i-use-chatgpt-and-local-llms/) [A]

### Inferences
- From Steam's numbers, 37.66% are at 8 GB or less (26.92 + 5.54 + 5.20), and 31.75% are at 16 GB or 24 GB. The six rows returned add up to 82.32%, so about 18% fall elsewhere, including sizes below 4 GB.
- Steam likely overstates the general market, because gamers buy graphics cards and many ordinary laptops have none. This is reasoning, not data.
- Three rough tiers follow, and none is measured: (1) chat, rewriting and summarizing on small models fit many machines, (2) document questions fit fewer, (3) dependable local agents fit few, since the docs ask for 64K context and bigger models.
- The memory shortage works against the usual advice to upgrade, so software should fit the machine people have.
- Memory figures from guides should not be used as facts. This project already requires measuring the card.

### Gaps
- I could not find the share of PCs with integrated graphics only, or the share of laptops at 8 GB or 16 GB. This would need paid IDC or Jon Peddie data.
- I found no measured figure for what share of consumer PCs can run a useful model at an acceptable speed. Any such number would be an estimate.
- The sum for 8 GB or less leaves out cards under 4 GB, since the fetched rows did not show them.

## 7. Which features are repeatedly requested but missing?

### Takeaway
Upvote counts show developers asking for tool connections (MCP), better document search, wider hardware support, control over where files go, voice, and faster support for new models. This tells us little about non-technical users, whose likely needs do not show up in these trackers at all.

### Cited Findings
All counts are upvotes on open issues, [M, moderate]. They are from developers, older issues have had longer to collect votes, and a request may be partly met elsewhere.

- **Tool connections (MCP):** [Ollama #7865](https://github.com/ollama/ollama/issues/7865) 222, [GPT4All #3546](https://github.com/nomic-ai/gpt4all/issues/3546) 52, [Jan #7556](https://github.com/janhq/jan/issues/7556) 9.
- **Better document search (reranking, data sources):** [Ollama #3368](https://github.com/ollama/ollama/issues/3368) 289, the second highest of all counts here, [Open WebUI #5872](https://github.com/open-webui/open-webui/issues/5872) 51, [LM Studio #470](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/470) 44, [AnythingLLM #4012](https://github.com/Mintplex-Labs/anything-llm/issues/4012) 15.
- **Wider hardware:** [LM Studio #9 Intel Mac](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/9) 422, [#171 SYCL](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/171) 49, [#581 Intel NPU](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/581) 45.
- **Control over files and the computer:** [Ollama #228](https://github.com/ollama/ollama/issues/228) 165 (not cluttering the home folder, open since 2023), [LM Studio #656](https://github.com/lmstudio-ai/lmstudio-bug-tracker/issues/656) 56, [AnythingLLM #3087](https://github.com/Mintplex-Labs/anything-llm/issues/3087) 24. Users said the same on [HN](https://news.ycombinator.com/item?id=47788385).
- **Voice:** [Jan #5486](https://github.com/janhq/jan/issues/5486) 7 (reading aloud), [Jan #6166](https://github.com/janhq/jan/issues/6166) 6 (voice input), [Open WebUI #23357](https://github.com/open-webui/open-webui/issues/23357) 15. Lack of audio input counted against LM Studio and AnythingLLM in [XDA's test](https://www.xda-developers.com/tested-local-llm-different-tools-and-only-one-unleashed-its-potential/). One mobile app calls voice among its most requested features — [LMSA](https://lmsa.app/blog?page=2) [V, weak].
- **Phone access:** [Open WebUI #8414](https://github.com/open-webui/open-webui/issues/8414) 26. XDA's workaround is a home server over [Tailscale](https://www.xda-developers.com/local-llm-home-server-tailscale-replace-chatgpt/) [A].
- **Fast support for new models:** [Ollama #8618](https://github.com/ollama/ollama/issues/8618) 260, [Ollama #10792](https://github.com/ollama/ollama/issues/10792) 175, [GPT4All #3576](https://github.com/nomic-ai/gpt4all/issues/3576) 17.
- **Agent apps:** [Hermes #18715](https://github.com/NousResearch/hermes-agent/issues/18715) 43 (remote agent with local tools), [#38519](https://github.com/NousResearch/hermes-agent/issues/38519) 35 (a desktop frontend-only install), [#5941](https://github.com/NousResearch/hermes-agent/issues/5941) 30 (private web search), [#12238](https://github.com/NousResearch/hermes-agent/issues/12238) 27 (built-in backup of agent data), [OpenClaw #6615](https://github.com/openclaw/openclaw/issues/6615) 8 (a denylist for commands). OpenClaw's votes are low overall, so the count says little there.
- **Memory:** a review argues persistent memory is now a baseline expectation, and local options attract people who want it without giving their history to a cloud — [Vellum](https://vellum.ai/blog/best-personal-ai-assistants-with-memory) [V, weak]. Hermes's own reports show this is unsolved — [#76307](https://github.com/NousResearch/hermes-agent/issues/76307).
- **Diagnosis:** one experienced user wanted better tools to isolate why a model behaves badly — [HN](https://news.ycombinator.com/item?id=49402232) [A]. Ollama offers `ollama ps` to check the context in use and whether a model is fully on the GPU, a developer tool — [Ollama docs](https://docs.ollama.com/context-length) [P].

### Inferences
- The likely non-technical needs are not in these lists: telling them plainly what this computer can do, choosing for them, explaining a failure in plain words, updating without breaking, and proving nothing left the machine. The silence reflects who posts, not a lack of need. This is my reading, not a finding.
- Backup, undo and a clear record of what an agent did are requests with obvious value to ordinary users, and Hermes's backup request points that way.
- Requests for control over files and shell settings show that even technical users dislike apps changing things without asking.

### Gaps
- No cross-tool tally of requested features exists, so the list above is my own count of top open issues, not a survey.
- Reddit feature threads were not reachable.
- GitHub Discussions were not searched. Open WebUI has only 165 open issues for a project of its size, so its requests are probably kept somewhere else, such as Discussions, and its counts here understate demand. I did not check this.
- LM Studio's roadmap is not public, so closed requests and shipped items could not be compared.
