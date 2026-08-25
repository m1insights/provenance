# Devpost submission — Provenance

**Track:** Taskmaster (complete workflow automation)
**Repo:** https://github.com/m1insights/provenance
**Live:** https://provenance-console-vwe3lj6lwq-uc.a.run.app

---

## Elevator pitch (200 characters)

An agent fleet reads health research nightly, verifies every quantitative claim, and proposes tested changes to a live iOS health algorithm as human-reviewed draft pull requests.

## Inspiration

I built **synqology**, an iOS longevity app whose Vitality Index scores users across eleven components, including sleep, cardiovascular activity, VO₂ max, and heart-rate variability. Every threshold in the algorithm came from published health research.

But the literature changes constantly. As the person maintaining the algorithm, the app, and its content, I realized that the delay between “a relevant study was published” and “the product reflects that evidence” was simply however long it took me to notice.

An agent that reads papers would be a start. But the problem is trust. A language model can easily hallucinate, misquote, or attach a real statistic to the wrong conclusion.

That made the real challenge much more interesting than retrieval: could I build an agentic system whose work I could review and potentially act on without reconstructing every step myself?

That became **Provenance**.

## What it does

Provenance is an evidence-to-code agent fleet that reads new health research, identifies findings that could affect synqology’s scoring algorithm, and proposes tested changes to the live iOS repository.

It is not given a static topic list. Provenance derives its research agenda from synqology’s specification and the Swift files that implement the scoring rules. If the algorithm credits a cardiovascular-activity day after 20 minutes and expects activity across three days each week, Provenance searches for evidence about bout duration, weekly frequency, and “weekend warrior” activity patterns—not merely papers saying exercise is beneficial.

That agenda is now automated too. When a governing Vitality Index file changes on synqology’s production branch, GitHub Actions checks out the exact private source revision, authenticates to Google Cloud with a short-lived identity, derives the updated agenda with Gemini, and publishes it to Firestore. The nightly Cloud Run job consumes that published agenda. Retries for an unchanged source digest reuse the existing agenda without another model call, and the private Swift source never enters the Cloud Run image.

The agenda also includes a content lane for familiar health claims people encounter every day: 10,000 steps, eight hours of sleep, coffee, income, resting heart rate, and similar numbers worth checking against the literature.

Every night, Provenance:

1. Searches **PubMed** and **Europe PMC** against the algorithm-derived agenda.
2. Deduplicates papers using a DOI-first identity.
3. Uses **Gemini 3.5 Flash-Lite** for inexpensive relevance screening.
4. Uses **Gemini 3.7 Flash** to assign a GRADE-inspired evidence tier, identify study design, sample size, and follow-up, and extract quantitative claims.
5. Requires every claim to carry a sentence quoted verbatim from the retrieved paper.
6. Pulls full text from PubMed Central when available, allowing claims to ground against results tables and the paper body rather than only the abstract.
7. Verifies in code that the quotation exists and that every number attached to a claim appears inside that quoted passage.
8. Records papers, appraisals, findings, rejections, and run outcomes in Firestore.
9. Preserves unfinished work in a durable appraisal backlog. Each completed wave is saved before the next begins, so a quota interruption cannot erase earlier results or strand papers permanently.
10. Sends a briefing that distinguishes “nothing qualified” from “analysis was incomplete,” including how much work remains queued.

For algorithm changes, a Finding opens only when at least three distinct papers challenge the same component, at least one is tier A or B, and the evidence comes from more than one DOI registrant. An operator can then invoke the Engineer, which resolves the real symbol in the live synqology repository, prepares the coordinated edits required by the project, runs the iOS scoring tests, and opens a **draft** pull request.

Pull-request creation is deliberately not part of the unattended nightly run. There is no merge tool. A callback blocks non-draft pull requests and branches outside Provenance’s namespace. A human reviews every proposal.

Provenance also supports a separate, manual content workflow built on the same grounded evidence. I run a custom Claude Code command, `/social`, inside the local Provenance repository. Claude and I select a grounded appraisal or Finding, choose the angle, and build a JSON animation specification. Every on-screen number is copied from a grounded claim, and the specification contains a `_provenance` record pairing each figure with its claim identifier and verbatim quotation.

That reviewed specification is rendered locally and deterministically into a 12-second, 1080×1920 reel at 30 frames per second. The cloud agent fleet does not choose the story, write the animation specification, render media, or post anything. I add audio, review the finished reel, and publish it myself.

## How I built it

I built Provenance around specialized roles using Google’s **Agent Development Kit**. ADK `LlmAgent` components handle appraisal, synthesis, and engineering. `FunctionTool` gives the Engineer tightly scoped, read-only navigation of the subject repository, while `before_tool_callback` enforces draft-only GitHub guardrails.

**Gemini 3.5 Flash-Lite** performs the high-volume relevance pass. **Gemini 3.7 Flash** handles deeper scientific appraisal, synthesis, engineering, and the structured extraction that turns synqology’s source code into a versioned research agenda.

Both models run through **Vertex AI**. The deployed system uses Google Cloud service identities, so no static Gemini API key is stored.

Agenda synchronization runs in **GitHub Actions**. A path-filtered workflow in the private synqology repository runs only when one of the three governing files changes on the `launch` production branch. It uses **Workload Identity Federation** to obtain a short-lived Google credential, calls an idempotent agenda-publication command, and leaves the last valid Firestore agenda intact if generation or publication fails.

### The cloud system consists of

- **Vertex AI** for Gemini 3.5 Flash-Lite and Gemini 3.7 Flash.
- **Cloud Run Jobs** for the nightly research pipeline.
- **Cloud Scheduler** to start the pipeline at 3:00 AM.
- **Firestore** for agendas, papers, triage state, appraisals, quotations, rejection reasons, findings, run records, the durable backlog, and human decisions.
- A **Cloud Run Service** for the pull-request review console.
- **Secret Manager** for the credentials needed by GitHub and notifications.
- **GitHub Actions** plus Google Cloud Workload Identity Federation for production-source-to-agenda synchronization without a long-lived cloud key.

The nightly workload is intentionally bounded. It appraises at most ten papers per run, processes at most three appraisal calls concurrently, and divides capacity between newly retrieved papers and the oldest backlog. Unused capacity is lent to the other group. Completed waves are committed atomically to Firestore; work that is not selected or hits a temporary quota limit remains pending for the next run.

The content workflow is intentionally local and human-operated. I work with Claude Code through `/social` to select grounded evidence and construct the animation specification. That reviewed specification—not a visual prompt—is passed to a renderer built with **Node.js, Puppeteer, HTML, CSS, headless Chrome, and ffmpeg**.

Motion is captured frame by frame from an explicit progress value, making the same input specification produce the same visual output. No image model touches the chart, and no cloud Provenance agent operates the renderer.

The core contract is:

> **Gemini reads and grounds the science. Code verifies every number. A human decides what becomes code and how the evidence is communicated.**

## Challenges we ran into

The first major problem was retrieval quality. Early searches returned approximately 96% irrelevant results and no papers capable of challenging an algorithm constant. The fault was not the model; it was my query design.

I had combined a broad subject heading with a phrase so specific that nearly every result arrived through the broad clause. Rebuilding the searches around shorter phrases, study-design filters, and proper Boolean relationships dramatically increased the number of strong, relevant studies.

The most important automation failure appeared after deployment. One nightly run retrieved and stored 217 papers, then identified 33 as relevant. Vertex AI returned a quota error before the appraisal results were persisted. The Cloud Run retry saw the papers as already known, skipped them, and left that work effectively stranded.

The fix was not another retry. I changed pending appraisal work into durable Firestore state. Triage results are persisted before appraisal begins, appraisals are saved in small atomic waves, and unfinished papers remain discoverable on the next run. Quota exhaustion now stops additional model work, preserves completed results, skips downstream proposal generation, and sends an honest “analysis incomplete” briefing instead of claiming there was nothing to propose.

Automating the research agenda exposed a different boundary. The nightly Cloud Run image cannot—and should not—contain synqology’s private source repository. Previously, publishing a new agenda depended on a local developer command. I moved that handoff to the private repository’s GitHub Actions workflow, where the source already exists, and used branch-restricted Workload Identity Federation instead of storing a Google service-account key.

Grounding against abstracts also proved insufficient for some of the most useful findings. Dose-response points and subgroup results often live in tables or the body of a paper. Provenance now retrieves available PubMed Central full text and extracts each tabulated point as a separate grounded claim rather than collapsing an entire curve into a highest-versus-lowest summary.

Counting papers presented another subtle problem. When 22 papers supported a weekend-warrior finding, Provenance identified that nine were UK Biobank re-analyses. Twenty-two papers did not represent twenty-two independent populations, so that caveat went into the pull request.

I also discovered that a correct number can still produce a misleading chart. One locally rendered chart displayed values clustered around a null result—0.98, 1.01, 0.99, and 1.00—but stretched them across the full plotting area. Every value was accurate while the visual implied a dramatic effect. The local renderer now enforces a minimum domain spread so it cannot manufacture visual significance.

Finally, I had to choose the correct boundary for content automation. Grounding can prove where a number came from, but it cannot decide which interpretation is useful, which framing is fair, or whether an animation communicates the evidence honestly. Provenance therefore ranks and supplies verified evidence; the `/social` session remains manual, and I remain responsible for the argument and the finished post.

## Accomplishments that we're proud of

Provenance produced a pull request I would seriously consider merging into a live health product.

Twenty-two papers converged on evidence that completing weekly exercise across one or two days is associated with mortality outcomes comparable to spreading it across more days. Provenance translated that finding into eleven coordinated edits across five files, updated the affected call sites and tests, and ran synqology’s scoring suite. All 51 tests passed.

Reading the diff then uncovered an existing shift-worker accommodation whose two branches had silently become identical. The green suite had not caught it because both expected values had been updated independently to the same number.

The obvious repair—restoring the earlier ratio—would have introduced another error because the consuming code both truncated and divided by that value. I fixed the rule with a relational test asserting that the shift-worker threshold must remain strictly easier than the default. Reintroducing the original bug now causes three tests to fail.

The production automation now closes two operational gaps as well. A relevant change to synqology’s production scoring sources automatically publishes the matching research agenda without my Mac being online, and a repeated publication for the same digest performs no duplicate Gemini generation. The nightly pipeline now carries incomplete evidence work safely across runs instead of losing it when a model quota is exhausted.

The same grounded evidence system supports my manual content workflow. Fourteen dated evidence folders preserve the specification, rendered reel, caption, and verification frames for each post.

One 10,000-steps dose-response reel reached approximately **84,000 views**, compared with an account baseline of roughly 2,000. A later reel that broke the format’s open-loop headline rule reached about 1,900. That contrast showed me the format—not simply the topic—was the lever, so the content queue now searches explicitly for sweep-shaped evidence.

One recent reel, built on August 23, asks: **“The rich live longer. By how much?”** It animates a two-line race comparing men and women by income rank using Chetty et al.’s 2016 JAMA study: 1.4 billion person-years and 15 grounded claims, with every displayed number linked to a verified quotation.

## What we learned

The difficult part of building an agent that reads science is not getting it to read more. It is deciding what the system must refuse to infer, change, lose, or publish.

A valid quotation is not enough if the reported number comes from another sentence. A real number is not enough if the surrounding interpretation implies causation the study cannot establish. A technically correct chart can still exaggerate a null result. Twenty-two papers can represent far fewer independent populations.

I also learned that retryability is a data-model problem, not merely an infrastructure setting. If pending work exists only in the memory of one job, a retry can succeed operationally while silently losing the actual work. The durable backlog makes unfinished analysis explicit state.

Human oversight works best as an architectural boundary, not a sentence in a prompt. Provenance cannot merge because the capability does not exist. The nightly run does not open pull requests by default. The cloud fleet cannot render or publish content. Rejection reasons and incomplete runs are persisted instead of disappearing.

The agent did not replace my judgment. It brought the evidence, code, tests, caveats, operational state, and uncertainty to the exact place where that judgment could be useful.

The most valuable behavior in the system is not generation. It is refusal—and recovery—with a reason.

## What's next for Provenance: Evidence-to-Code Agent Fleet

Cohort-overlap detection currently relies on study metadata and recognizable cohort names; I want to make it more systematic.

The backtest currently reports test results, but it should also simulate how a proposed algorithm change affects score distributions across a representative user cohort.

The content queue can already identify dose-response, J-shaped, graded, and per-unit evidence. Next, I want to improve its ability to recognize which grounded relationships will remain understandable when animated for a general audience—without moving the editorial decision out of human hands.

Provenance currently follows one application’s algorithm. Because the subject is represented through configuration and source mappings, the next major step is applying the same evidence-to-code workflow to additional health products.

Most importantly, I want to preserve the boundary at the center of the project: agents can search, appraise, propose, test, and explain their evidence—but a human remains responsible for deciding what becomes real.
