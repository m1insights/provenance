# Devpost submission — Provenance

**Track:** Taskmaster (complete workflow automation)
**Repo:** https://github.com/m1insights/provenance
**Live:** https://provenance-console-vwe3lj6lwq-uc.a.run.app

Final text as submitted on 2026-08-25. The Devpost "About the project" page is
the copy of record; this file mirrors it so the video script and runbook stay
consistent with what the judges read.

---

## Provenance - Taskmaster Agent Fleet

## Inspiration

I built synqology, an iOS longevity app. Its Vitality Index scores users across eleven components — sleep, cardio activity, VO2 max, HRV, and more — and every threshold in that scoring algorithm is and has to be backed by published research.

My problem, like many solo founders, is that I am the only one maintaining it. Along with handling bug fixes, adding new features, marketing and customer service. My time is limited. In addition, new studies come out constantly, and the gap between "a relevant paper existed" and "the app actually reflects it" is just however long it took me to stumble across that paper myself or go out into the wild and manually research. As a PharmD, researching clinical studies is certainly within my skillset but it's not an efficient system when the product is live and making health claims to real users.

There's a second side to this same problem: organic content is a core growth channel for synqology, and the posts that actually work are built on a specific, checkable claim — "10,000 steps is a made-up number," "the rich live this many years longer," that kind of thing. So I was really solving the same trust problem twice. The same grounded evidence that keeps the algorithm honest needs to keep the content honest — a wrong number in a reel does the same damage as a wrong number in the app, just faster.

My first instinct was: have an AI read the papers for me. But that's the easy part and also the dangerous part — an LLM will confidently hallucinate a number or misread a table, and I wasn't about to let that anywhere near a live scoring algorithm, or a post going out to thousands of people, on trust alone.

So the actual problem I had to solve wasn't "can an agent read science." It was "can I build a system whose output I can actually check, without personally redoing its work every time" — one grounded evidence pipeline that could feed both the algorithm and the content queue. That system is Provenance.

## What it does

Provenance is a fleet of agents that reads new health research, figures out which findings could actually change synqology's scoring algorithm, and proposes tested code changes to the live iOS repo.

I didn't give it a fixed list of topics to search. Provenance builds its own research agenda by reading synqology's spec and the actual Swift files that implement the scoring rules. So if the algorithm currently credits a cardio day after 20 minutes of activity spread across three days a week, Provenance goes looking for evidence about bout duration, weekly frequency, and "weekend warrior" patterns specifically — not just any paper that says exercise is good for you.

That agenda-building step is automated now too. When one of the files that governs the Vitality Index changes on synqology's production branch, a GitHub Action checks out that exact version, authenticates to Google Cloud, has Gemini derive the updated research agenda, and publishes it to Firestore. The nightly Cloud Run job just picks up whatever's published. If the source hasn't actually changed, it reuses the existing agenda instead of burning another model call, and the private Swift source code never has to leave that GitHub Action — it never touches the Cloud Run image.

The agenda also has a content lane, for the everyday health claims people repeat without checking: 10,000 steps, eight hours of sleep, coffee, income and longevity, resting heart rate — the kind of numbers worth actually verifying against the literature.

Every night, Provenance:
1. Searches PubMed and Europe PMC against that agenda.
2. Deduplicates papers by their DOI (digital object identifier), so the same study doesn't get counted twice under two different titles.
3. Uses Gemini 3.5 Flash-Lite to do a cheap first pass on relevance.
4. Uses Gemini 3.7 Flash to grade the evidence quality (a GRADE-inspired tier, similar to how clinical guidelines rate evidence strength), identify the study design, sample size, and follow-up length, and pull out the actual quantitative claims.
5. Requires every claim to come with a sentence quoted directly from the paper.
6. Pulls full text from PubMed Central when it's available, so claims can be grounded in results tables and the body of the paper, not just the abstract.
7. Checks in code — not just trusting the model — that the quote actually exists in the source and that any number attached to a claim is actually inside that quote.
8. Logs every paper, appraisal, finding, rejection, and run outcome to Firestore.
9. Keeps unfinished work in a backlog that survives interruptions. Completed batches get saved before the next one starts, so a quota error can't wipe out earlier results or leave papers stuck in limbo.
10. Sends me a briefing via email (Resend) that's honest about the difference between "nothing qualified" and "I didn't get through everything" — including how much is still queued.

For an algorithm change, Provenance only opens a Finding if at least three separate papers challenge the same part of the algorithm, at least one of them is high-quality evidence (tier A or B), and they're not all from the same publisher or the same underlying dataset — otherwise "three papers" can just mean one study got cited three times. Once that bar is cleared, I can tell the Engineer agent to go make the change: it finds the real code, makes the coordinated edits, runs synqology's scoring tests, and opens a draft pull request.

Opening pull requests is deliberately not something the unattended nightly job can do on its own — there's no merge capability anywhere in the system, and a callback blocks anything that isn't a draft PR on Provenance's own branch. I review every single proposal myself.

As a bonus, that same grounded evidence also feeds a separate, manual content workflow I use to write social posts.

## How I built it

I built Provenance around specialized roles using Google's Agent Development Kit. ADK `LlmAgent` components handle appraisal, synthesis, and engineering. `FunctionTool` gives the Engineer tightly scoped, read-only navigation of the subject repository, while `before_tool_callback` enforces draft-only GitHub guardrails.

Gemini 3.5 Flash-Lite performs the high-volume relevance pass. Gemini 3.7 Flash handles deeper scientific appraisal, synthesis, engineering, and the structured extraction that turns synqology's source code into a versioned research agenda.

Both models run through Vertex AI. The deployed system uses Google Cloud service identities, so no static Gemini API key is stored anywhere.

Agenda synchronization runs in GitHub Actions. A path-filtered workflow in the private synqology repository runs only when one of the three governing files changes on the `launch` production branch. It uses Workload Identity Federation to get a short-lived Google credential (instead of a stored key), calls an idempotent agenda-publication command, and leaves the last valid Firestore agenda alone if generation or publication fails.

### The cloud system consists of
- **Vertex AI** for Gemini 3.5 Flash-Lite and Gemini 3.7 Flash.
- **Cloud Run Jobs** for the nightly research pipeline.
- **Cloud Scheduler** to kick off the pipeline at 3:00 AM.
- **Firestore** for agendas, papers, triage state, appraisals, quotations, rejection reasons, findings, run records, the durable backlog, and human decisions.
- A **Cloud Run Service** for the pull-request review console.
- **Secret Manager** for the credentials GitHub and notifications need.
- **GitHub Actions** plus **Workload Identity Federation** to sync the research agenda from production source without a long-lived cloud key sitting around.

The nightly workload is intentionally limited: it appraises at most ten papers per run, runs at most three appraisal calls at once, and splits capacity between newly retrieved papers and the oldest backlog items — unused capacity from one gets lent to the other. Completed batches commit to Firestore atomically; anything not selected, or anything that hits a temporary quota limit, stays pending for the next run.

The content workflow is intentionally local and human-operated. The core contract for the whole system is: Gemini reads and grounds the science, code verifies every number, and I decide what becomes code and how the evidence gets communicated.

## Challenges I ran into

**First problem: my searches were garbage.** About 96% of what came back was irrelevant, and nothing strong enough to actually challenge a constant in the algorithm. Not the model's fault. It was my query design. I'd combined one broad subject heading with one overly-specific phrase, so almost everything matched through the broad half and ignored the specific half. Once I rebuilt the searches with shorter phrases, study-design filters, and actual Boolean logic instead of one long string, the quality jumped.

**The bigger failure showed up after I deployed it.** One nightly run pulled in 217 papers, flagged 33 as relevant, then Vertex AI threw a quota error before those appraisals got saved. The next run saw those 217 papers as "already seen," skipped them, and quietly lost that work.

Retrying harder wasn't the fix. The real problem was that pending work only existed in one job's memory — so I moved it into Firestore as durable state instead. Triage results get saved before appraisal even starts, appraisals save in small batches as they finish, and anything unfinished is still there for the next run to pick up. Now if the quota runs out mid-run, it stops, keeps what it already finished, skips proposal generation, and tells me honestly that the analysis is incomplete — instead of just reporting "nothing found" like it had actually looked.

**Automating the research agenda ran into a different wall.** I'd originally been publishing a new agenda by running a command on my own laptop, which meant the whole thing depended on my Mac being on. I moved that step into synqology's own GitHub Actions, where the source already lives, and used Workload Identity Federation scoped to that branch instead of dropping a long-lived service-account key in there.

**I also found that abstracts alone weren't enough** for the findings I actually cared about. Dose-response data and subgroup breakdowns almost always live in a table somewhere in the body of the paper, not the abstract. So Provenance now pulls full text from PubMed Central when it's available and grounds each point on a curve as its own separate claim, instead of flattening a whole dose-response relationship into one "highest vs lowest" summary.

**Then there's a subtler problem: paper count isn't population count.** When 22 papers backed a "weekend warrior" finding, nine of them turned out to be re-analyses of the same UK Biobank dataset. 22 papers is not 22 independent populations, and that caveat needed to be in the pull request, not buried.

**Last one: I had to decide where automation should stop on the content side.** Grounding can prove a number is real. It can't tell me which interpretation is fair, which framing is honest, or whether an animation actually communicates what the data says. So Provenance ranks and hands me verified evidence, and I still run the `/social` session myself — I'm the one responsible for the argument and the final post.

## Accomplishments I'm proud of

Provenance actually produced a pull request I'd seriously consider merging into a live product people use.

Twenty-two papers pointed to the same finding: cramming your weekly exercise into one or two days looks about as good for mortality outcomes as spreading it across the week. Provenance turned that into eleven coordinated edits across five files, updated the affected call sites and tests, and ran synqology's full scoring suite. All 51 tests passed.

Reading through the diff, I found something the tests hadn't caught: an existing accommodation for shift workers had two code branches that had quietly become identical over time. The suite stayed green because both expected values had been updated to the same number independently, at different points — nobody would've caught that just from tests passing.

My first fix — just restoring the old ratio — would've introduced a different bug, because the code that consumes that value both truncates and divides by it. So instead I added a relational test that just asserts the shift-worker threshold has to stay strictly easier than the default one. If that bug ever comes back, three tests fail immediately instead of the check silently disappearing again.

The automation side closed two real gaps too. A change to synqology's production scoring files now publishes an updated research agenda on its own — I don't have to be at my laptop for it to happen — and republishing for something that hasn't actually changed doesn't burn another Gemini call. And the nightly pipeline now carries unfinished work across runs instead of losing it whenever it hits a quota limit.

That same evidence pipeline also runs my manual content workflow. The first 5 reels I created based on research gathered by Provenance have garnered **over 400,000 views** on instagram. **All organic**. @synqology on instagram, if you'd like to check it out.

## What I learned

Getting an agent to read more science turned out to be the easy part. The hard part was figuring out everything I needed the system to refuse to do — refuse to guess, refuse to lose work, refuse to publish anything without a reason attached.

A quote being real doesn't mean the number next to it is real — it might've come from a different sentence entirely. A real number can still mislead if the sentence around it implies a cause-and-effect the study never proved — a classic clinical-research trap I built checks for on purpose. A chart can be technically correct and still lie. And twenty-two papers can be way fewer than twenty-two real, independent populations.

The engineering lesson that surprised me most: losing work on a retry isn't really a coding bug, it's a design problem. If the "in-progress" work only lives in one job's memory and nowhere else, a retry can look successful while quietly throwing away real results. Once I started saving that in-progress work to Firestore instead of just hoping the job finished, that problem went away.

I also learned that "a human checks this before it goes live" only actually holds up if it's built into the system, not just something I told myself I'd always remember to do. Provenance literally cannot merge code — I never gave it that ability. It doesn't open pull requests on its own. It can't publish content on its own. Anything it rejects, or any run that doesn't finish, gets saved and shown to me instead of just disappearing.

None of this replaced my own judgment. It just did the grunt work — pulled the papers, wrote the code, ran the tests, flagged what looked off — and put it all in front of me at the point where I actually needed to make a call. And as a busy solo founder that's exactly what I needed.

## What's next for Provenance: Evidence-to-Code Agent Fleet

Right now, Provenance catches papers that lean on the same underlying dataset — like several studies all built on UK Biobank data — mostly by recognizing familiar dataset names when they show up. I want to make that check more reliable instead of relying on names I happen to recognize.

Right now the system just tells me whether the existing tests still pass after a proposed change. I want it to go further and show me how that change would actually shift real users' scores before I merge anything.

Right now Provenance is scoped to one app's algorithm. Because the subject matter is defined through configuration and source mappings rather than hardcoded, the next real step is pointing the same evidence-to-code workflow at my other products.

Most importantly, I want to keep the one thing that matters most about this project intact: agents can search, appraise, propose, test, and explain their evidence. Ultimately as a solo founder it lands on me to decide what to implement in production.
