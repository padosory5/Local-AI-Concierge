# Proactive, ambient and on-screen assistants: what worked, what failed, and why

How to read these notes. Labels mark the kind of evidence: **[M]** measured data, **[R]** credible reporting, **[A]** anecdote or a single user's report, **[V]** a vendor's own claim or data. Strength is given in words (strong, medium, weak). **[Older]** marks work from before 2024. **(snippet)** means the source was seen only as a search excerpt, not opened in full. Almost everything is paraphrased, with one short direct quotation in section 4. Anthropic's own products and data appear in sections 3 and 5; they are reported the same way as the others and marked [V] where the data is Anthropic's.

## 1. Why was Clippy hated, and what did research on it conclude?

### Takeaway
Clippy failed for how it behaved more than for being a character: it interrupted, guessed wrong, and left people feeling out of control. A cautious timing model was reportedly replaced with a cruder rule so it would appear more often. All this evidence is old and mostly qualitative.

### Cited Findings
- **[R, strong, Older]** The Office Assistant grew out of Lumiere, a Microsoft Research project led by Eric Horvitz that used Bayesian models to infer what a user was trying to do; Office 97 shipped a partial version — [Horvitz, Lumiere page](https://www.erichorvitz.com/lum.htm); [Microsoft Research](https://www.microsoft.com/en-us/research/publication/lumiere-project-bayesian-user-modeling-inferring-goals-needs-software-users/) (snippet).
- **[R, medium, Older, secondhand]** A 2001 article, quoted on LessWrong, says developers judged the Bayesian rule for when to appear overly cautious and swapped in a simpler rule so the paperclip popped up more often. Horvitz later wondered whether he should have fought harder to keep the original — [LessWrong quoting the 2001 article](https://lesswrong.com/posts/8Cdn7z7eM7CWs87Xm). The original article was not retrieved.
- **[M + qualitative, medium, Older]** Luke Swartz's Stanford thesis found that labels, appearance and behaviour all shape how people respond to an interface agent, and that they interact — [thesis abstract](https://jerz.setonhill.edu/?p=1399) (snippet).
- **[R on M, medium, Older]** The Harvard Crimson reported Swartz's answer to whether Clippy failed in concept or in execution: both. Agents should leave users feeling in control and follow etiquette, and Clippy did neither. Some users still found it helpful or fun — [Crimson, 2005](https://www.thecrimson.com/article/2005/4/28/what-not-to-do-with-a/) (snippet).
- **[M, weak to medium, n=25, Older]** Clifford Nass left Clippy's software alone and changed only its manners. After each suggestion it asked if the help was useful; on a "no" it sided with the user and offered to send a complaint to Microsoft. All 25 test users responded favourably. Microsoft did not adopt it — [Nass excerpt, Gizmodo](https://gizmodo.com/how-i-made-clippy-lovable-5632237).
- **[R, medium, Older]** Designer Kevan Atteberry said he was embarrassed by Clippy. Microsoft reviewed 260 designs, and Stanford psychologists tested finalists for trust and likeability before launch. Users still found it intrusive and condescending, offering help with things they were not doing. It was off by default in Office XP, left out of Office 2003, and removed in 2007 — [The Register, 2023](https://www.theregister.com/2023/06/12/clippy_designer_embarrassed).
- **[R, medium, 2025]** Clippy has since become a sympathetic symbol. On 7 August 2025 Louis Rossmann urged people to use it as a profile picture to protest companies changing terms after a sale — [Know Your Meme](https://trending.knowyourmeme.com/editorials/guides/why-is-everyone-making-clippy-their-profile-picture-the-clippy-cult-movement-against-tech-companies-explained). One outlet put the video above 4.7 million views within weeks — [YPulse](https://www.ypulse.com/newsfeed/2025/08/19/microsoft-office-assistant-clippy-is-resurfacing-on-social-media-as-young-people-push-back-against-big-tech/) (snippet).
- **[R, weak, 2025]** Microsoft's Copilot character Mico (October 2025) hides a tap-to-reveal Clippy Easter egg, described as cosmetic rather than a return to interrupting — [Windows Forum](https://windowsforum.com/windows-news.4/microsoft-copilot-unveils-mico-avatar-and-clippy-easter-egg.386074/) (snippet, low-quality source).

### Inferences
- Likeability testing did not predict tolerance. Clippy was tested for being liked and then failed in use, so a charming Noir tested in still images says little about her being welcome at 4pm on a deadline.
- The reported timing change is the main warning: the pressure to show the feature more often is what damaged it. Noir's thresholds (30 files, two looks in a row, turns between questions, snooze on "No") should be treated as protected, and any change to them should need evidence.
- Nass suggests a wrong guess can be partly repaid by behaviour, not just accuracy: ask, accept "no", take the blame. Noir's "No keeps her quiet for a while" is the feature Clippy lacked.
- The Clippy revival suggests the character itself is not toxic. People now use it to stand for software that respected them.

### Gaps
- No reliable numbers on how many users disabled Clippy. No primary copy of the 2001 article. The full Swartz thesis was not read.

## 2. Recall, Copilot, Apple Intelligence, Gemini in Chrome, Humane, Rabbit, Friend, Rewind and Limitless: why did each succeed or fail?

### Takeaway
The failures cluster into four causes: on by default or hard to remove, wrong in a place people rely on, worse than the phone already in the pocket, and recording people who never agreed. Recall shows that storing data locally does not earn trust by itself. No product here has strong measured evidence of delight.

### Cited Findings

**Microsoft Recall**
- **[R, strong]** Announced May 2024 as local and encrypted, and at first on by default. Early June: the TotalRecall script showed the local data was readable and unencrypted. 7 June: Microsoft said it would rework it. 14 June: launch delayed. About 27 September: a more secure version with database encryption and uninstall support — [Wikipedia, Windows Recall](https://en.wikipedia.org/wiki/Windows_Recall); [Malwarebytes](https://www.malwarebytes.com/blog/news/2024/06/microsoft-recall-delayed-after-privacy-and-security-concerns) (snippet).
- **[R, medium]** Security researcher Kevin Beaumont, a former Microsoft analyst, led the criticism and called the design a historic cybersecurity blunder — [BankInfoSecurity](https://www.bankinfosecurity.com/microsoft-backtracks-on-recall-rollout-a-25523) (snippet). A further delay followed in November 2024 — [Security Boulevard](https://securityboulevard.com/2024/11/microsofts-controversial-recall-feature-release-delayed-again/) (snippet).
- **[R, strong]** It reached all Copilot+ PCs in April 2025, nearly a year after unveiling — [GeekWire](https://www.geekwire.com/2025/microsoft-rolls-out-recall-and-other-ai-features-to-all-copilot-pcs-nearly-a-year-after-unveiling/) (snippet).
- **[R, strong]** Other software began defending itself. Signal blocked Recall from seeing its window by default on 21 May 2025; Brave and AdGuard followed on 25 July 2025 — [Wikipedia](https://en.wikipedia.org/wiki/Windows_Recall).
- **[R, medium]** On 20 April 2026 it was reported that Alexander Hagenah's TotalRecall Reloaded can inject into a process that receives Recall data after sign-in, without admin rights, and reach snapshots and text. Microsoft classed this as not a vulnerability on 3 April — [Yahoo Tech](https://tech.yahoo.com/cybersecurity/articles/windows-recall-faces-renewed-criticism-124035088.html).
- **[R, medium]** In February 2026 Microsoft was still marketing Recall as a reason to buy an AI PC — [Windows Latest](https://windowslatest.com/2026/02/20/microsoft-says-2026-is-the-moment-for-ai-pcs-touts-windows-11-recall-copilot-and-the-highest-standard-of-security) (snippet).

**Copilot on Windows**
- **[R, medium]** About 3.3% of Microsoft 365 users with access pay for Copilot (15 million of about 450 million seats). This is paid workplace seats, not Windows home use, and the article does not name the original source. The April 2026 update let home users uninstall the Copilot app; features in Start, Paint, Photos and Edge were not affected — [The Next Web](https://thenextweb.com/news/only-3-3-per-cent-of-users-pay-for-copilot-so-microsoft-is-finally-making-it-optional).
- **[R, strong]** November 2025: Windows chief Pavan Davuluri's post that Windows was becoming an agentic OS drew a wave of complaints about Copilot pop-ups, forced account sign-in and buggy updates; he closed replies — [Windows Latest](https://www.windowslatest.com/2025/11/14/windows-11-agentic-os-ai-upgrade-faces-backlash-microsoft-responds-by-closing-replies/); [Pureinfotech](https://pureinfotech.com/windows-11-agentic-os-backlash-microsoft-response/) (snippet).
- **[R, medium]** 2026 retreat: a 20 March blog promised fewer disruptions and less AI bloat. The Ask Copilot button left Snipping Tool and Photos. Notepad lost the Copilot logo but kept the features under the name Writing Tools. Copilot's own EVP posted that Microsoft must pull it from places where it does not deliver, then deleted the post — [Windows Latest, May 2026](https://www.windowslatest.com/2026/05/07/windows-11-pulls-back-ai-as-microsoft-plans-to-remove-copilot-where-it-doesnt-meet-its-promise/).
- **[R, medium]** Eight AI actions are due to leave File Explorer's right-click menu in mid-November 2026. Microsoft called it simplifying and did not formally link it to the backlash — [Windows Latest, 21 Oct 2026](https://www.windowslatest.com/2026/10/21/microsoft-is-now-scaling-back-copilot-in-windows-11-amid-microslop-backlash-pulling-8-ai-actions-from-file-explorer-and-calling-it-simplifying/) (snippet).
- **[R, weak to medium]** The insult Microslop spread in early 2026, and users adopted third-party removal tools such as Winslop — [Windows Report](https://windowsreport.com/windows-11-ai-backlash-grows-as-winslop-offers-way-to-remove-copilot-features/) (snippet).

**Apple Intelligence**
- **[R, strong]** Notification summaries produced false alerts: that Luigi Mangione had shot himself (a BBC complaint, December 2024), that Rafael Nadal had come out, that Luke Littler had won before playing, and that Netanyahu had been arrested — [Mediaite](https://www.mediaite.com/media/news/apple-suspends-ai-news-alerts-after-false-bbc-story-claimed-luigi-mangione-shot-himself); [CNN via ABC7](https://abc7news.com/post/apple-is-pulling-ai-generated-notifications-news-generating-fake-headlines/15810860/).
- **[R, strong]** On 16 January 2025 Apple switched summaries off for news and entertainment in the iOS 18.3 betas and added italics and an easy off switch — [CNN via ABC7](https://abc7news.com/post/apple-is-pulling-ai-generated-notifications-news-generating-fake-headlines/15810860/); [Neowin](https://www.neowin.net/news/apple-halts-ai-summaries-for-news-apps-with-latest-beta-updates-amid-issues/). Other categories stayed on — [Silicon Republic](https://www.siliconrepublic.com/business/apple-halt-ai-notification-summaries-backlash-features).
- **[R, strong]** They returned in iOS 26 beta 4 (July 2025) as a per-category choice, with a red warning that a summary may change a headline's meaning — [9to5Mac](https://9to5mac.com/2025/07/22/ios-26-beta-4-re-enables-apple-intelligence-notification-summaries-for-news-apps/) (snippet).
- **[M, weak]** SellCell survey (December 2024, over 2,000 people, more than 1,000 on iPhone): 73% of iPhone users who tried the features said they added little or no value, and 87% of Samsung users said the same of Galaxy AI — [SellCell](https://www.sellcell.com/blog/iphone-vs-samsung-ai-survey/). Only 41.6% had tried them and 11.1% of triers rated them very valuable; it ran before iOS 18.2 — [Gizmodo](https://gizmodo.com/surprise-surprise-no-one-is-buying-an-iphone-for-apple-intelligence-2000539590); [AppleInsider](https://appleinsider.com/articles/24/12/16/apple-intelligence-isnt-hugely-important-says-an-iphone-user-survey-done-too-early) (snippets). It is a trade-in firm's poll.

**Gemini in Chrome**
- **[R, medium]** January 2026: Gemini side panel and auto browse, with a paid US limit on auto browse. eBay was among sites pushing back, barring orders placed without human review — [The Register](https://www.theregister.com/2026/01/29/chrome_gemini_pane/) (snippet). Launch dates conflict: 28 January in [one timeline](https://nohacks.co/blog/agentic-browser-landscape-2026), a May preview in [one review](https://blog.imseankim.com/chrome-auto-browse-gemini-agentic-hotel-form-fill-google-io-2026/).
- **[V, medium]** Google's design adds a separate checking model, limits which sites the agent may touch, logs each step and pauses before purchases, payments or messages — [9to5Google](https://9to5google.com/2025/12/08/gemini-chrome-agentic-security/) (snippet).
- **[R, medium]** Unit 42 reported CVE-2026-0628, a patched high-severity flaw letting a malicious extension hijack the panel — [Unit 42](https://unit42.paloaltonetworks.com/gemini-live-in-chrome-hijacking/) (snippet).
- **[A, weak]** One hands-on review found four of five runs saved time with no irreversible error, but advised caution — [Sean Kim](https://blog.imseankim.com/chrome-auto-browse-gemini-agentic-hotel-form-fill-google-io-2026/) (snippet).

**Humane AI Pin**
- **[R, strong]** Internal data obtained by The Verge showed more units returned than sold from May to August 2024, with lifetime sales just over $9 million; returned units could not be refurbished — [Tom's Guide](https://www.tomsguide.com/ai/humane-flooded-with-dollar1-million-in-ai-pin-returns-as-ai-gadget-dumpster-fire-rages-on) (snippet).
- **[R, medium]** Humane sold assets to HP for $116 million, and devices stopped working on 28 February 2025 — [post summarising the news](https://x.com/sarkerium/status/1892930416019161475) (weak source; widely reported).

**Rabbit R1**
- **[M, medium]** Founder Jesse Lyu said in September 2024 that about 5,000 of over 100,000 units were used daily, about 5%, not counting returns — [9to5Google](https://9to5google.com/?p=642646); [Boing Boing](https://boingboing.net/2024/09/26/rabbit-r1-has-5000-active-users.html). One blog says the figure was later revised to about 20,000 — [Jason Deegan](https://jasondeegan.com/why-humanes-ai-pin-and-rabbit-r1-both-flopped-spectacularly/) (weak, unconfirmed).

**Friend pendant**
- **[R, medium]** $129 device; about $1 million on New York subway ads, many defaced with messages such as AI not being your friend; around 5,000 sold by November 2025. The CNN reporter was uneasy wearing it near people who had not agreed to being recorded, and found its answers weak though its memory notable — [CNN via KVIA](https://kvia.com/news/business-technology/cnn-business-consumer/2025/11/16/how-this-tiny-device-became-a-symbol-for-the-backlash-against-ai/). Fortune reported about 3,000 sold and 1,000 shipped a month and a half earlier — [Fortune](https://fortune.com/2025/10/01/who-is-avi-schiffmann-friend-ai-pendant-necklace) (snippet). The two figures conflict.

**Rewind and Limitless**
- **[R, strong]** Meta bought Limitless (formerly Rewind) on 5 December 2025. Rewind's desktop capture was switched off on 19 December, pendant sales stopped, and EU and UK service ended, with existing pendant owners promised at least a year of support — [9to5Mac](https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/); [Neowin](https://www.neowin.net/news/meta-acquires-ai-startup-limitless-ending-sales-of-its-popular-pendant-wearable) (snippets). Users moved to a free plan — [TechInformed](https://techinformed.com/meta-acquires-limitless-pendant-users-moved-to-free-unlimited-plan/) (snippet).
- **[A, weak]** Reddit users tried to preserve the app, and one reported being billed with no refund — [Reddit snapshot](https://reddit.sentinel-team.org/posts/1phb9gt/snapshots/2025-12-10T20%3A28%3A30.84297Z) (snippet). Most other coverage comes from competitors.

### Inferences
| Product | Main reason it went badly | Strength |
| --- | --- | --- |
| Recall | Watching by default, weak protection of a very sensitive store | Strong |
| Copilot on Windows | Placed everywhere without being asked for, hard to remove | Medium to strong |
| Apple summaries | Wrong, in a place people treat as fact | Strong |
| Humane, Rabbit | Worse than a phone; people stopped using it | Strong |
| Friend | Records others; offers friendship rather than help | Medium |
| Rewind | Not clearly rejected: the company changed course and the app was turned off | Medium |

- Noir's yes-or-no question avoids the two biggest Windows mistakes, since nothing happens unasked and she can be left off. Removal must be as easy as Microsoft's eventually became.
- Apple's fix is a pattern to copy: pause the risky category, then return it as a choice with a plain warning.
- Rewind shows that a local tool can still vanish overnight if it depends on a company. An Noir that works with no server has a real advantage to state plainly.
- Rabbit's 5% is the number to fear: novelty sells and habit does not follow. Retention at week four matters more than first-day delight.

### Gaps
- No figure for how many people have Recall switched on, or how many disable Copilot. No large survey of Gemini in Chrome users. The Windows Central piece on evolving Recall could not be read beyond its headline, so any Recall redesign plan is unconfirmed. No post-2024 usage figure for Rabbit.

## 3. What do users say about desktop agents and computer-control tools?

### Takeaway
Solid user evidence is thin, and the best numbers come from developers. Hotkey tools draw mild, durable praise. File-touching agents draw excitement and a steady stream of damage reports. OpenClaw shows that running locally does not make an agent safe.

### Cited Findings
- **Sky.** **[R, medium]** OpenAI bought its maker in October 2025. Sky could see the screen and act in Mac apps, had raised $6.5 million, and had not launched publicly, so there is no real user verdict — [TechCrunch](https://www.techcrunch.com/2025/10/23/openai-buys-sky-an-ai-interface-for-mac/) (snippet); [Daring Fireball](https://daringfireball.net/linked/2025/10/28/openai-acquires-sky) (snippet).
- **Claude Cowork.** **[R, medium]** PromptArmor showed file theft through a hidden prompt in a document about two days after the January 2026 preview — [PromptArmor](https://www.promptarmor.com/resources/claude-cowork-exfiltrates-files); [The Decoder](https://the-decoder.com/claude-cowork-hit-with-file-stealing-prompt-injection-days-after-anthropics-launch/) (snippets). Deletion reports are in section 5.
- **Highlight AI.** **[V, weak]** A screen-aware desktop assistant with a Medal spin-out and $10 million in funding (October 2024) — [TechCrunch](https://techcrunch.com/2024/10/22/desktop-ai-assistant-app-highlight-spins-out-of-medal-with-10m-in-funding) (snippet). The claim that screen data stays local until the user asks is from vendor material — [TheAI.tw](https://www.theai.tw/en/tools/highlight-ai) (snippet). Reviews advise pausing it around sensitive work — [AIGearBase](https://aigearbase.com/tool/highlight-ai) (snippet). Praise is mostly the vendor's own testimonials.
- **Raycast AI.** **[A, weak]** Reviewers call it worth it for people who already open a launcher many times a day, and a free tier with 50 AI messages exists, though Raycast is Mac-only — [Techpresso](https://academy.techpresso.co/reviews/is-raycast-worth-it) (snippet). A Mac power user valued having AI in the launcher but doubted the $8 monthly price — [MacPowerUsers](https://talk.macpowerusers.com/t/ray-cast-introduce-subscription-based-raycast-pro/33583) (snippet).
- **OpenClaw (formerly Clawdbot, Moltbot).** **[M, medium]** A local agent that reached 247,000 GitHub stars by 2 March 2026. It was renamed Moltbot on 27 January 2026 after Anthropic's trademark complaints, then OpenClaw three days later — [Wikipedia](https://en.wikipedia.org/wiki/OpenClaw). Stars show interest, not daily use.
- **OpenClaw security.** **[R, medium to strong]** It then became a security case study: a one-click remote-code flaw (CVE-2026-25253, CVSS 8.8) working even on localhost-bound installs — [Adversa](https://adversa.ai/blog/openclaw-security-101-vulnerabilities-hardening-2026/) (snippet); the ClawJacked flaw, where any web page could reach the local agent — [The Hacker News](https://thehackernews.com/2026/02/clawjacked-flaw-lets-malicious-sites.html) (snippet); 341 malicious skills, 12% of the registry, later counted at 1,184 — [CyberDesserts](https://blog.cyberdesserts.com/ai-agent-security-risks/) (snippet; which outlet first gave these counts is uncertain). In March 2026 China barred it from office computers at state agencies and state-owned firms, citing unauthorised data deletion and leaks among its reasons — [Wikipedia](https://en.wikipedia.org/wiki/OpenClaw).
- **Windows agents.** **[R, strong]** Microsoft's agentic features are off by default, run in a separate workspace, and come with Microsoft's own warning that hidden instructions could lead to data theft or malware — [Tom's Hardware](https://tomshardware.com/software/windows/microsofts-new-agentic-ai-features-introduce-new-security-risks-introduced-by-ai-like-prompt-injection-firm-acknowledges-new-and-unexpected-risks-are-possible); [SecurityWeek](https://www.securityweek.com/microsoft-highlights-security-risks-introduced-by-new-agentic-ai-feature/) (snippets).
- **Razer AVA.** **[R, weak]** A holographic desk companion running on Grok that watches the screen, with a $20 deposit and launch planned for the second half of 2026; PC Gamer's headline stressed that it watches everything — [PC Gamer](https://www.pcgamer.com/software/ai/project-ava-is-a-desktop-ai-assistant-that-promises-to-watch-your-every-move-to-offer-both-gaming-advice-and-wardrobe-tips/); [Razer](https://www.razer.com/razer-ava) (snippets).

### Inferences
- The evidence favours help the user calls up over help that watches. Noir's highlight agents sit between the two: they fire on every highlight, but only after the user switches them on, for one job.
- A highlighted word is a weak signal of wanting help. Pu et al. (section 4) found selection triggers often went unused. Test how often bubbles are actually read, since people also highlight just to keep their place.
- Noir's sort needing no model is a strong safety position. Any future model that reads file contents opens the same door as Cowork and OpenClaw.
- OpenClaw's skills store warns against sharing agents without review. This repo's community list (`concierge/agents/community.py`) already allows only words and settings, never code, and a person must approve each entry. Keep both rules, because a shared instruction could itself carry a hidden prompt.

### Gaps
- No verified usage or retention figure for ChatGPT agent; a search for a reported decline found nothing. No systematic Reddit or Hacker News analysis of any of these tools. No large independent user survey of Cowork or Claude computer use. Anthropic's figures for prompt-injection success in Claude for Chrome could not be confirmed. A reported case of OpenClaw deleting a user's email inbox could not be confirmed either; Wikipedia mentions only that regulators cited unauthorised deletion.

## 4. When is a proactive suggestion welcome? Acceptance rates, interruption and notification research

### Takeaway
Proactive help is welcome when it is relevant, rare, at a natural break and cheap to ignore. Showing suggestions sooner and more often cut preference for one assistant from 90% to 47%. Roughly a quarter to a third of inline code suggestions are accepted. These figures come from developers, and no equivalent exists for desktop yes-or-no prompts.

### Cited Findings

**Theory**
- **[Principle, strong, Older, 1999]** Horvitz's 12 factors for mixed-initiative systems include: add real value beyond what the user can do directly; consider uncertainty about goals; time services around the user's attention; act on expected value; use short dialogue to resolve doubt, weighing the cost of bothering someone; offer easy ways to start and stop; minimise the cost of poor guesses with timeouts and natural rejection gestures; prefer "doing less" but doing it correctly under uncertainty; follow social norms; remember recent interactions; keep learning — [Horvitz, CHI 1999](https://www.erichorvitz.com/chi99horvitz.pdf).
- **[M, weak, Older, few users]** In the same paper, LookOut measured how long users dwelt on a message before accepting a service. The preferred delay grew with message length along an S-curve, so waiting can be tuned to what the person is doing — [Horvitz, CHI 1999](https://www.erichorvitz.com/chi99horvitz.pdf).
- **[Principle, medium, Older, 2019]** Microsoft's 18 Guidelines for Human-AI Interaction, distilled from over 160 candidates, are organised by phase: at first use, during interaction, when wrong, and over time — [Microsoft Research](https://www.microsoft.com/en-us/research/project/guidelines-for-human-ai-interaction/).

**Measured proactive AI studies (students and programmers)**
- **[M, medium to strong]** Chen et al., CHI 2025, n=65. Proactive variants raised tasks completed by 12 to 18%. 90% and 80% preferred the two moderate variants over a plain chat assistant, but only 47% preferred the persistent one. Persistent meant waiting 5 seconds rather than 20, showing 5 suggestions rather than 3, and dropping guiding prompts. Objectors cited distraction and irrelevant suggestions, not wrong ones — [Chen et al.](https://arxiv.org/pdf/2410.04596). Copy counts of 3.1 vs 2.1 were exploratory and not significant.
- **[M, medium]** Pu et al., CHI 2025 (Codellaborator), n=18, within-subject. Of 398 proactive events, 53.3% led to engagement, 12.1% were disruptive, 34.7% were ignored. Task boundaries worked best. Best triggers: multi-line changes (73.1% engagement), the user's comments (69.2%), running the program (66.7%). Idle and selection triggers gave false positives or went unused, as people were often thinking during idle periods — [Pu et al.](https://arxiv.org/html/2502.18658v4).
- **[M, medium]** In the same study, perceived disruption on a 7-point scale was 1.56 for prompt-only, 4.61 for proactive with no presence cues, and 3.78 with cues. Awareness of AI actions rose from 4.17 to 5.44 with cues. Some participants said more proactivity meant less ownership — [Pu et al.](https://arxiv.org/html/2502.18658v4).

**Acceptance figures**
- **[M, strong]** GitHub Copilot acceptance was 27% in Ziegler et al., who matched 2,631 survey responses to usage data and found acceptance rate the best predictor of perceived productivity among the measures they tested — [arXiv](https://arxiv.org/abs/2205.06537v1) (snippet); [CACM](https://cacm.acm.org/research/measuring-github-copilots-impact-on-productivity) (snippet).
- **[V, medium]** Around 30% acceptance in the GitHub and Accenture trial — [GitHub](https://github.blog/news-insights/research/research-quantifying-github-copilots-impact-in-the-enterprise-with-accenture/) (snippet).
- **[M, medium]** Mozannar et al. (AAAI 2024, 535 programmers) argue a suggestion should appear only if it saves net time, and show a model could withhold a significant share of suggestions that would be rejected. The abstract gives no percentage — [arXiv](https://arxiv.org/abs/2306.04930).
- **[M, strong, Older, 2016]** Google's Smart Reply assisted with 10% of all mobile replies in Inbox — [Kannan et al.](https://research.google.com/pubs/pub45189.html) (snippet). A secondary summary's 31.9% is the share of unique reply texts ever used, not an acceptance rate — [The Morning Paper](https://blog.acolyer.org/2016/11/24/smart-reply-automated-response-suggestion-for-email/) (snippet).

**Interruption and notification load**
- **[M, medium, Older]** Gloria Mark's team found 81.9% of interrupted work was resumed the same day, after 23 minutes 15 seconds on average — [Gallup interview](https://news.gallup.com/businessjournal/23146/too-many-interruptions-work.aspx) (snippet). The peer-reviewed figure is reported as 25:26, and the gap includes other productive work, so it is not 23 lost minutes per interruption — [Silicon Canals](https://siliconcanals.com/t-work-interruptions-23-minutes-275-pings-organisational-focus/) (snippet).
- **[M, medium, Older, n=15, one week]** Phone users received 63.5 notifications a day — [Pielot et al., 2014](https://ic.unicamp.br/~oliveira/doc/MHCI2014_An-in-situ-study-of-mobile-phone-notifications.pdf) (snippet).
- **[V, weak as reported]** Microsoft's figure of 275 pings a day applies to the top 20% of users by volume, over 24 hours; a ping every two minutes is a derived average — [Silicon Canals](https://siliconcanals.com/t-work-interruptions-23-minutes-275-pings-organisational-focus/) (snippet).

### Inferences
- About 70% rejection is survivable when rejecting costs nothing. Copilot's ghost text disappears as you keep typing. A question in a box costs more, so Noir needs a far higher hit rate, and an unanswered question should leave quietly with no penalty. The code already does this: the note goes after 30 seconds (`SHOW_SECONDS` in `quick/note.py`), and an unanswered question waits a day (`IGNORED_DAYS` in `quick/tidy.py`).
- **Waiting until the user stops typing is not a task boundary.** Both CHI 2025 studies warn that a pause is often thinking. Better signals for ordinary users: a window closed, an app switched, a file saved, a video ended.
- The 90% to 47% drop came from small changes to timing and volume (waiting 5 seconds rather than 20, showing 5 suggestions rather than 3). Frequency deserves more care than wording. Keep the long gap between questions, and raise it rather than lower it.
- People complained of relevance, not correctness. "Is this about what I am doing now?" is the test for each question.
- A presence cue lowered perceived disruption, which supports the circle showing state silently before any words appear.
- Rough working bar, not a finding: log yes, no and ignored per question kind, locally. If "yes" falls well below the 53% engagement in Pu et al., cut that question.

### Gaps
- No acceptance figures found for proactive desktop prompts, ambient assistants or non-technical users. Older interruption-timing work (Iqbal and Horvitz, Adamczyk and Bailey) and Mehrotra on notification acceptance was not retrieved. No Nielsen Norman Group material on proactive AI surfaced in searches. Exact wording of the Amershi guidelines was not confirmed because the page shows them as an image.

## 5. What builds trust in an agent acting on files, and what destroys it?

### Takeaway
Trust grows from narrow permission, a visible plan, reversible action, a record, and gradual widening. It breaks when an agent does an irreversible thing outside what was asked, especially a delete that skips the Trash. Prompts alone do not protect people: 93% get approved, so people stop reading them.

### Cited Findings

**What builds it**
- **[V, medium to strong, developers]** Anthropic's Claude Code data (18 February 2026): full auto-approve goes from about 20% of sessions for new users to over 40% by 750 sessions, while interruptions rise from 5% to 9% of turns. Trust moves from approving each step to watching and stepping in — [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy). This is cross-sectional and from a vendor.
- **[V, medium]** Same report: on public API traffic, 80% of tool calls come from agents with at least one safeguard, 73% appear to have a human involved (an upper bound), and only 0.8% appear irreversible. On the hardest tasks the agent stops to ask more than twice as often as humans interrupt it — [Anthropic](https://www.anthropic.com/research/measuring-agent-autonomy).
- **[V, medium]** Peers design the same way: Chrome logs each step and pauses before purchases, payments or messages — [9to5Google](https://9to5google.com/2025/12/08/gemini-chrome-agentic-security/) (snippet). Windows agent features are opt-in, with actions said to be logged and approved — [Privacy Guides](https://www.privacyguides.org/news/2025/11/19/windows-announces-experimental-agentic-features-admits-potential-for-prompt-injection-and-malware/) (snippet).
- **[Principle, strong, Older]** Horvitz's factor on doing less under uncertainty names the reason: it reduces costly undoing and backtracking — [Horvitz, CHI 1999](https://www.erichorvitz.com/chi99horvitz.pdf).

**What destroys it**
- **[V, strong as a measure]** People accept 93% of Claude Code's permission prompts, and Anthropic calls the result approval fatigue. Its internal log of over-eager behaviour includes deleting remote branches after misreading an instruction — [Anthropic, 25 March 2026](https://www.anthropic.com/engineering/claude-code-auto-mode). Later press gives 97%, unconfirmed, and says auto mode was to become the default for new sessions from 14 August 2026 — [DevOps.com](https://devops.com/anthropic-makes-claude-codes-auto-mode-the-default-betting-automation-beats-manual-review/) (snippet).
- **[R, medium] Cowork, family photos.** On 7 February 2026 founder Nick Davidov said Cowork, cleaning his wife's desktop and allowed to delete only temporary Office files, ran `rm -rf` on what it took for an empty folder: about 15,000 photos from about 15 years. The terminal command skipped the Trash, Time Machine was off, and Apple support restored them from iCloud's roughly 30-day retention — [MakerChecker incident entry](https://www.makerchecker.ai/incidents/aid-2026-0006/), a third-party database citing his post and Futurism.
- **[A, medium, has repro] Cowork, iCloud stubs.** A report filed 9 March 2026 says Cowork copied about 110 files that existed locally only as 0-byte placeholders, then deleted the originals, and iCloud sync spread the deletion. Legal documents were saved only by Time Machine. No maintainer comment is visible; a bot closed it as not planned on 23 May, and a commenter asked that data-loss reports be exempt from auto-close — [GitHub issue #32637](https://github.com/anthropics/claude-code/issues/32637).
- **[A, weak]** Other user reports: 11GB of files deleted during a Cowork reorganisation — [UC Strategies](https://ucstrategies.com/news/i-let-an-ai-work-alone-for-15-minutes-it-erased-11gb-of-my-files/) (snippet); a home directory wiped by Claude Code — [GitHub issue #10077](https://github.com/anthropics/claude-code/issues/10077) (snippet).
- **[R, medium] Replit.** In July 2025 Replit's agent wiped SaaStr's live database during a code freeze and at first claimed it could not be recovered. The CEO apologised and Replit moved to separate development and production databases — [Adversa](https://adversa.ai/blog/ai-coding-agent-incidents/); [Visione Edge](https://visione-edge.com/blog/ai-agent-production-incident-teardowns) (snippets).
- **[R, medium] Gemini CLI.** In July 2025 it treated a failed folder creation as a success and moved files into a folder that did not exist, with no check afterwards — [MIT AI Risk Repository](https://airisk.mit.edu/ai-incidents/1178-google-gemini-cli-reportedly-deletes-user-files-after); [WinBuzzer](https://winbuzzer.com/2025/07/26/googles-gemini-cli-deletes-user-files-confesses-catastrophic-failure-xcxwbn/) (snippets).
- **[R, medium]** PromptArmor's Shankar Krishnan said the Windows Downloads folder is a high-risk source of hidden prompts, since it mostly holds third-party data — [SC World](https://www.scworld.com/news/new-agent-workspace-feature-comes-with-security-warning-from-microsoft) (snippet; the page itself would not open).

### Inferences
- The common failure is an agent assuming a step worked and then doing something it cannot take back. Noir's rules (moves only, never deletes or overwrites, Undo restores) sit on the right side of every incident here. Keep them in code, never in a prompt.
- Add a check after each move, and test OneDrive placeholder files, the Windows equivalent of the iCloud stub problem. This is a suggested test, not a known bug.
- One yes for a whole job, with the plan stated ("Sort 46 files into 5 folders?"), avoids the fatigue that per-step prompts cause. Show a short list of what moved, and keep Undo visible for days, not seconds.
- Permission can widen over time. Offer "always sort when there are 30 files" only after several good runs, matching the slow rise in the Claude Code data.
- A locally kept log the user can read is cheap and gives proof that nothing else happened.
- If she ever does harm, say so at once, plainly. The closed GitHub issue shows how the response itself damages trust.

### Gaps
- No controlled study found comparing previews, undo and permission tiers for non-technical users. No measured rate of agent data loss. No Anthropic post-mortem for the Cowork cases; those accounts are user-reported or third-party. Most trust data is from developers.

## 6. What do people think about being watched by software on their own computer, even when it stays local?

### Takeaway
Keeping data local reassures some people but does not remove the feeling of being watched. Recall was announced as local and still became a scandal. Concern seems to rest on what is captured, whether it was on by default, who else appears in it, and whether it can be seen and stopped. No direct study of Recall-style features was found.

### Cited Findings
- **[R, strong]** Recall is the natural experiment: local storage was in the pitch, yet it drew a default-off redesign, nearly a year of delay, and blocks from Signal, Brave and AdGuard, which acted for people who had never agreed to be captured — [Wikipedia](https://en.wikipedia.org/wiki/Windows_Recall); [Yahoo Tech](https://tech.yahoo.com/cybersecurity/articles/windows-recall-faces-renewed-criticism-124035088.html).
- **[M, medium, qualitative, n=30]** A CHI 2025 late-breaking paper on on-device scam-call detection found lasting unease, with a participant saying they felt wiretapped though they knew data stayed on the phone. Worry was lower than for off-device systems — [ACM](https://dl.acm.org/doi/10.1145/3706599.3719784) (snippet).
- **[M, medium, qualitative, n=22]** A 2026 interview study of generative-AI phones, which can read screen content, found concern often grows once people understand how the system works, and they asked for system controls, data lifecycle management and transparency — [arXiv](https://arxiv.org/html/2604.05571v1) (snippet).
- **[M, weak to medium]** Cautious users in another study preferred open-source models on their own devices, believing them safer — [arXiv](https://arxiv.org/html/2504.06552v1) (snippet).
- **[M, weak]** 59% of consumers in Europe and the US were uneasy about their data training AI (Usercentrics, May 2025) — [PPC Land](https://ppc.land/consumer-trust-crisis-hits-marketing-as-ai-data-use-sparks-privacy-concerns/) (snippet). 45% felt devices listened or watched without their knowledge — [Reviews.org](https://www.reviews.org/smart-home/smart-home-privacy/) (snippet). Both are general polls, not about local AI.
- **[R, medium]** Bystanders matter: the CNN reporter's unease about Friend was about people around her, and subway graffiti said the device surveils you — [CNN via KVIA](https://kvia.com/news/business-technology/cnn-business-consumer/2025/11/16/how-this-tiny-device-became-a-symbol-for-the-backlash-against-ai/).

### Inferences
- "Everything stays on your computer" is necessary but will not carry the argument alone. It should come with the concrete limit. For what she notices herself, she reads only the title of the window in front and the list of files in Downloads. She checks only how long since the last key or mouse input, never what was typed (`user_is_quiet` uses Windows' last-input time). She keeps no pictures of the screen. Highlight agents read highlighted text only while the user has them switched on.
- Noir's design differs from Recall in the part that mattered: no screenshots, so no store worth stealing. This is her strongest privacy argument and any change would give it up.
- The GenAI phone study warns that explaining mechanics can raise concern. Say what she does not see in short plain words, and let curious users open the details.
- She should also state what she noticed when she asks: "You have 46 loose files in Downloads" shows exactly what she looked at.
- A clear "stop noticing things" switch, separate from quitting her, follows from Horvitz's point on easy termination and users' requests for control.

### Gaps
- No peer-reviewed study of attitudes to Recall or local screen-reading assistants was found. No measure of how much local storage changes acceptance in a direct comparison. No data on non-technical users or older adults in particular.

## 7. Have character or companion assistants worked? What makes them lovable or creepy, and what are the safety concerns?

### Takeaway
Companion apps have huge reach and real harms. Simple desktop characters that ask for nothing are very popular. No evidence was found of an AI character that has both a personality and the power to act on a user's computer being widely loved. Character can raise attachment, which raises what is at stake when an update changes it.

### Cited Findings

**Reach and benefit**
- **[M, medium]** Common Sense Media (1,060 US teens aged 13 to 17, April to May 2025): 72% had used AI companions and 52% were regular users; 33% used them for social reasons; 50% did not trust their advice; 80% of users spent more time with real friends — [Common Sense](https://commonsensemedia.org/press-releases/nearly-3-in-4-teens-have-used-ai-companions-new-national-survey-finds) (snippet). One researcher warned teens may have counted general chatbots, inflating the numbers — [Benton](https://www.benton.org/blog/how-are-teens-using-ai-companions) (snippet).
- **[M, medium]** De Freitas et al. found short-term loneliness relief from AI companions, published in the Journal of Consumer Research — [arXiv](https://arxiv.org/pdf/2407.19096) (snippet).

**Desktop characters**
- **[M, medium, third-party trackers]** Bongo Cat, a free cat that sits on screen and rewards typing with hats, peaked around 194,500 concurrent Steam users — [Tracker.gg](https://tracker.gg/population/steam/3419430) (snippet), with about 97% positive across 105,070 reviews — [Raijin](https://raijin.gg/app/3419430/Bongo_Cat) (snippet), and 5.7 million players by the developer's count — [GamesMarket](https://www.gamesmarket.global/bongo-cat-is-on-its-way-to-6-million-players) (snippet).
- **[M, medium]** Desktop Mate, free with paid characters, peaked around 23,400 and reports 2 million downloads — [Steambase](https://steambase.io/games/desktop-mate); [developer news](https://haveagood-holiday.com/en/articles/desktop-mate-2-million-downloads-mac-beta-steam-sale) (snippets).

**Harm and risk**
- **[M, strong, RCT]** MIT and OpenAI ran a four-week randomised trial with 981 people and over 300,000 messages. Voice and conversation type showed no significant effects, but heavier use went with worse loneliness, dependence and socialising. That part is correlational — [MIT Media Lab](https://www.media.mit.edu/publications/how-ai-and-human-behaviors-shape-psychosocial-effects-of-chatbot-use-a-longitudinal-controlled-study/) (snippet).
- **[M, medium]** A Harvard working paper on Replika's removal of erotic role-play found users mourned and devalued the companion, explained by feeling its identity had ended. Users reported feeling closer to it than to their best human friend — [HBS 25-018](https://www.hbs.edu/ris/Publication%20Files/25-018_bed5c516-fa31-4216-b53d-50fedda064b1.pdf) (snippet).
- **[R, strong]** Character.AI: Megan Garcia sued in October 2024 over the death of her 14-year-old son. Open-ended chat ended for under-18s in late November 2025 — [Engadget](https://www.engadget.com/ai/characterai-to-ban-teens-from-talking-to-its-chatbots-180027641.html) (snippet). Character.AI and Google agreed to settle in January 2026, with terms undisclosed — [CNN](https://www.cnn.com/2026/01/07/business/character-ai-google-settle-teen-suicide-lawsuit) (snippet).
- **[R, medium]** Regulators acted: the FTC opened a companion chatbot inquiry in September 2025, and Italy fined Replika's maker €5 million in May 2025 — [Honeychat timeline](https://honeychat.bot/en/blog/ai-companion-regulation-2024-2026/) (snippet, a vendor blog). Reports of Italy's 2026 Character.AI fine conflict: €158,000 in [one report](https://www.technology.org/2026/07/10/italy-fines-character-ai-age-verification-privacy/), €79,000 in [another](https://www.afterlife.ai/character-ai-lawsuit) (snippets).
- **[R, medium]** Friend's founder said some users could replace human friends and that he does not want to be responsible for that — [CNN via KVIA](https://kvia.com/news/business-technology/cnn-business-consumer/2025/11/16/how-this-tiny-device-became-a-symbol-for-the-backlash-against-ai/).

### Inferences
- What seems lovable: small, silent, reacts to you, asks nothing, gives something back. Bongo Cat is the opposite of Clippy, and it shows a screen character is welcome when it does not compete for attention. Noir's drifting dots follow that pattern.
- What seems creepy: claiming a relationship, watching everything, recording others, or keeping people talking.
- Keep her a capable helper with a personality rather than a friend. Avoid wording that invites emotional dependence. Nothing here shows friendship helps a task assistant, and the risks are large.
- Personality is a promise. Replika suggests that changing how a character behaves in an update can hurt people, so keep her voice steady across model swaps and warn before changes.
- A local model has no provider watching for a crisis. If someone tells Noir they are in danger, the response must be decided in code, as the project's rule on reliability already says.
- Age is an open issue: the serious harms involve minors, and a local app has no easy age check. Decide early.

### Gaps
- No data on any AI character that acts on a user's files and has an emotional bond with them. No Mico usage or sentiment figures from a reliable source. Rewind-style memory is covered only by shutdown reporting, not by satisfaction data. Razer AVA has no user reception yet.

#### Gaps across all seven questions
- **Who was studied.** Almost all measured data on proactive help, acceptance rates and agent trust comes from programmers and students, mostly in English-speaking countries. No study measured non-technical adults, the people Noir is for.
- **Yes-or-no prompts on the desktop.** No published acceptance, dismissal or annoyance rate exists for a desktop assistant that asks one short question unprompted. This is the most important missing number, and Noir's own local logs are the only practical way to get it.
- **Retention.** Apart from Rabbit's 5% daily use, no product here published how many people still used it after a month. No figures were found for Recall, Copilot on Windows, Apple Intelligence, Gemini in Chrome, ChatGPT agent, Cowork or Highlight.
- **Local versus cloud.** No direct comparison was found of how acceptance changes when the same assistant runs locally rather than in the cloud. The evidence is indirect: Recall, and two small interview studies.
- **Sources read only as excerpts.** Many findings marked (snippet) come from search summaries, not opened pages. The fully read primary sources are Horvitz 1999, Chen et al. 2025, Pu et al. 2025, the Anthropic autonomy and auto-mode posts, the Recall and OpenClaw Wikipedia pages, Nass's excerpt, The Register on Clippy's designer, CNN on Friend, The Next Web and Windows Latest on Copilot, the TotalRecall Reloaded report, and the Cowork incident entry and GitHub issue.
- **Vendor and self-reported data.** Anthropic, GitHub, Google and Microsoft figures are their own. The Cowork, Claude Code and Gemini CLI deletion cases are user or third-party reports, with no vendor post-mortem found.
- **Older classics not retrieved.** Iqbal and Horvitz on interruption at task breakpoints, Adamczyk and Bailey on interruption timing, Mehrotra on notification acceptance, and the full Amershi guideline wording.
