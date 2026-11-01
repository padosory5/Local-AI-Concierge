// Sample data for the workspace preview, all in one place so real data can
// replace it piece by piece. Anything marked `sample` is drawn with a "Sample"
// tag: it shows how a screen will look, but it does not run.
//
// The three agents marked `starter` are real (concierge/agents/starters.yaml),
// and so is `ask-documents`, which starts Elaina's real setup. Their words are
// repeated here only because no event sends a catalog to the UI yet.

window.ws = window.ws || {};

ws.mock = (() => {
  const OK = { level: "ok", text: "Works on this computer" };
  const ELAINA = "Elaina's model, no extra memory";
  const CANNOT = [
    { label: "Change your files", allowed: false },
    { label: "Send anything over the internet", allowed: false },
  ];

  const categories = [
    { id: "writing", name: "Writing & Documents", icon: "doc", blurb: "Fix, shorten and explain text" },
    { id: "files", name: "File Management", icon: "folder", blurb: "Find and sort your files" },
    { id: "research", name: "Research", icon: "book", blurb: "Read and summarize papers" },
    { id: "coding", name: "Coding", icon: "code", blurb: "Understand and review code" },
    { id: "productivity", name: "Productivity", icon: "check", blurb: "Notes, tasks and meetings" },
    { id: "learning", name: "Learning & Education", icon: "cap", blurb: "Study and understand faster" },
    { id: "creative", name: "Creative Work", icon: "spark", blurb: "Ideas, drafts and captions" },
    { id: "custom", name: "Custom Tasks", icon: "wand", blurb: "Describe it, Elaina builds it" },
  ];

  const agents = [
    {
      id: "highlight-explainer", name: "Highlight Explainer", category: "learning", type: "native", starter: true,
      switchable: true,
      description: "Highlight any text and get a plain explanation right above it.",
      purpose: "For the moment you hit a word or sentence you don't understand. Switch it on, highlight text in any program, and the explanation appears above it.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["featured"], favorite: true,
      tools: ["Highlighted text", "Bubble above the text"],
      permissions: [{ label: "Read the text you highlight, while it's on", allowed: true }, ...CANNOT],
      config: [["When it works", "While it's switched on"], ["Result", "A bubble above the text"], ["Stays", "Until you unhighlight"]],
    },
    {
      id: "grammar-fixer", name: "Grammar Fixer", category: "writing", type: "native", starter: true,
      description: "Paste a sentence and get it back with the mistakes fixed.",
      purpose: "Corrects grammar and spelling and keeps your meaning and tone. Start a message with its name: \"Grammar Fixer: me and him goes\".",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["popular"],
      tools: ["Text you send in the chat"],
      permissions: [{ label: "Read the text you send it", allowed: true }, ...CANNOT],
      config: [["When it works", "When you ask in the chat"], ["Result", "An answer in the chat"]],
    },
    {
      id: "quick-summarizer", name: "Quick Summarizer", category: "research", type: "native", starter: true,
      description: "Turns long text into three short points.",
      purpose: "Paste anything long and get the main points back. Start a message with its name: \"Quick Summarizer: your text\".",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["popular"],
      tools: ["Text you send in the chat"],
      permissions: [{ label: "Read the text you send it", allowed: true }, ...CANNOT],
      config: [["When it works", "When you ask in the chat"], ["Result", "An answer in the chat"]],
    },
    {
      id: "ask-documents", name: "Ask My Documents", category: "research", type: "native",
      setup: "Make an agent for my documents",
      description: "Answers questions about a folder of your files and shows where it found each answer.",
      purpose: "Pick a folder of PDFs, Word files or notes. Ask a question and it answers only from those files, quoting its source.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["featured"],
      tools: ["Files in the folder you pick", "Search index on this computer"],
      permissions: [{ label: "Read the folder you pick", allowed: true }, ...CANNOT],
      config: [["Reads", "The folder you pick"]],
    },
    {
      id: "downloads-tidy", name: "Downloads Tidy", category: "files", type: "native", sample: true,
      description: "Sorts your Downloads folder into clear groups, with a preview first.",
      purpose: "Shows every move before it happens, and you can undo it afterwards.",
      runtime: "Elaina", model: ELAINA, compat: { level: "warn", text: "Moving files isn't built yet" }, shelves: ["recent"],
      tools: ["Files in Downloads", "Move files"],
      permissions: [{ label: "Read Downloads", allowed: true }, { label: "Move files, after you confirm", allowed: true }, CANNOT[1]],
      config: [["Folder", "Downloads"], ["Preview first", "Always"]],
    },
    {
      id: "paper-digest", name: "Paper Digest", category: "research", type: "community", sample: true, installed: true,
      description: "Summarizes research papers into question, method and findings.",
      purpose: "Point it at a folder of papers and get a one-page digest of each.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["popular"], favorite: true,
      tools: ["Files in the folder you pick"],
      permissions: [{ label: "Read the folder you pick", allowed: true }, ...CANNOT],
      config: [["Length", "One page"], ["Sections", "Question, method, findings"]],
    },
    {
      id: "course-organizer", name: "Course Organizer", category: "learning", type: "imported", sample: true, installed: true,
      description: "Reads due dates and sorts documents by course.",
      purpose: "Keeps assignments in order: one folder per course and a list of what's due.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: [],
      tools: ["Files in the folder you pick", "Move files"],
      permissions: [{ label: "Read the folder you pick", allowed: true }, { label: "Move files, after you confirm", allowed: true }, CANNOT[1]],
      config: [["Folder", "Documents\\University"]],
    },
    {
      id: "hermes-researcher", name: "Hermes Research Agent", category: "research", type: "external", sample: true, installed: true,
      framework: "Hermes",
      description: "Your own Hermes agent, managed from here.",
      purpose: "Runs in Hermes with its own memory and skills. Elaina starts it, follows its progress and keeps its results here.",
      runtime: "Hermes", model: "Chosen in Hermes", compat: { level: "ok", text: "Connected" }, shelves: [],
      tools: ["Skills from Hermes"],
      unsupported: ["permissions", "config"],
    },
    {
      id: "meeting-notes", name: "Meeting Notes Cleaner", category: "productivity", type: "native", sample: true,
      description: "Turns rough notes into decisions and next steps.",
      purpose: "Paste messy notes and get decisions, owners and next steps.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["recent"],
      tools: ["Text you send in the chat"],
      permissions: [{ label: "Read the text you send it", allowed: true }, ...CANNOT],
      config: [["Result", "Decisions, owners, next steps"]],
    },
    {
      id: "study-cards", name: "Study Cards", category: "learning", type: "community", sample: true,
      description: "Makes question and answer cards from your notes.",
      purpose: "Paste your notes and get cards to test yourself with.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["community"],
      tools: ["Text you send in the chat"],
      permissions: [{ label: "Read the text you send it", allowed: true }, ...CANNOT],
      config: [["Cards", "10"]],
    },
    {
      id: "caption-writer", name: "Caption Writer", category: "creative", type: "community", sample: true,
      description: "Gives you five short captions for a post or a photo idea.",
      purpose: "Describe the post and pick the caption you like.",
      runtime: "Elaina", model: ELAINA, compat: OK, shelves: ["recent"],
      tools: ["Text you send in the chat"],
      permissions: [{ label: "Read the text you send it", allowed: true }, ...CANNOT],
      config: [["Captions", "5"]],
    },
    {
      id: "repo-guide", name: "Repo Guide", category: "coding", type: "external", sample: true, framework: "Hermes",
      description: "Explains how a code project is put together.",
      purpose: "Runs through Hermes and reads a project you point it at.",
      runtime: "Hermes", model: "Chosen in Hermes", compat: { level: "warn", text: "Needs Hermes connected" }, shelves: ["featured"],
      tools: ["Skills from Hermes"],
      unsupported: ["permissions", "config"],
    },
    {
      id: "code-reviewer", name: "Code Reviewer", category: "coding", type: "community", sample: true,
      description: "Reads a change and points out likely bugs.",
      purpose: "Needs a coding model much bigger than Elaina's.",
      runtime: "Ollama", model: "A coding model, about 12 GB",
      compat: { level: "no", text: "Needs a bigger model than Elaina's" }, shelves: ["community"],
      tools: ["Files in the folder you pick"],
      permissions: [{ label: "Read the folder you pick", allowed: true }, ...CANNOT],
      config: [],
    },
  ];

  const workflows = [
    { id: "weekly-reading", name: "Weekly reading list", category: "research", blurb: "Digest new papers, then keep a list of what to read.", uses: ["Paper Digest", "Quick Summarizer"] },
    { id: "assignment-tracker", name: "Assignment tracker", category: "learning", blurb: "Sort course files, then pull out every due date.", uses: ["Course Organizer"] },
    { id: "clean-draft", name: "Clean up a draft", category: "writing", blurb: "Fix the grammar, then shorten it.", uses: ["Grammar Fixer", "Quick Summarizer"] },
  ];

  const models = [
    { id: "small", name: "Small helper model", size: "About 3 GB", blurb: "Fast everyday tasks. Elaina can use this kind.", fit: "Fits this computer" },
    { id: "vision", name: "Vision model", size: "About 6 GB", blurb: "Reads images and screenshots.", fit: "Fits this computer" },
    { id: "coding", name: "Coding model", size: "About 12 GB", blurb: "Writes and reviews code.", fit: "Tight fit" },
  ];

  const integrations = [
    { id: "filesystem", name: "Files on this computer", kind: "Tool", blurb: "Lets an agent read the folders you allow." },
    { id: "mcp-github", name: "GitHub", kind: "MCP server", blurb: "Read issues and code from a repository." },
    { id: "mcp-notion", name: "Notion", kind: "MCP server", blurb: "Read and write pages in your workspace." },
  ];

  // minutes: how long ago it started. Only running tasks have progress and
  // pace (points per tick); `finished` is what the task says once it's done.
  const activity = [
    { id: "run-1", agent: "Paper Digest", task: "Summarizing 12 papers", finished: "Summarized 12 papers", status: "running", progress: 34, pace: 0.2, minutes: 2, took: "", sample: true },
    { id: "run-2", agent: "Course Organizer", task: "Sorted 31 files by course", status: "completed", minutes: 46, took: "1m 12s", sample: true,
      output: "31 files went into 4 course folders. 3 due dates were added to your list.", files: ["University\\due-dates.txt"] },
    { id: "run-3", agent: "Hermes Research Agent", task: "Compare three market reports", status: "failed", minutes: 180, took: "8s", sample: true,
      error: "Elaina couldn't reach Hermes. Check that it's running, then try again." },
    { id: "run-4", agent: "Paper Digest", task: "Summarized 4 papers", status: "completed", minutes: 1500, took: "2m 03s", sample: true,
      output: "4 one-page digests are ready.", files: ["Papers\\digests.txt"] },
  ];

  const runtimes = [
    { name: "Ollama", state: "Connected", real: true, blurb: "Runs Elaina on this computer." },
    { name: "LM Studio", state: "Not connected", blurb: "Use models you already have there." },
  ];

  // What each framework can tell Elaina. Not every one offers everything, so
  // the screens show what's missing instead of an empty control.
  const frameworks = [
    { id: "hermes", name: "Hermes Agent", blurb: "Bring your Hermes agents, skills and memory.", field: "Where Hermes is running", placeholder: "Address on this computer",
      capabilities: [["Start tasks", true], ["Follow progress", true], ["See results", true], ["Read logs", true], ["Change permissions", false], ["Change settings", false]] },
    { id: "mcp", name: "MCP server", blurb: "Give your agents tools from any MCP server.", field: "Server command or address", placeholder: "Command or address",
      capabilities: [["List tools", true], ["Use tools", true], ["Follow progress", false], ["Read logs", false]] },
    { id: "api", name: "Custom agent", blurb: "Connect an agent that has its own local address.", field: "Address", placeholder: "Address on this computer",
      capabilities: [["Start tasks", true], ["See results", true], ["Follow progress", false], ["Read logs", false]] },
  ];

  const tools = ["Files in a folder", "Highlighted text", "Clipboard", "Move files", "Save a file"];
  const mcpServers = ["GitHub", "Notion"];

  return { categories, agents, workflows, models, integrations, activity, runtimes, frameworks, tools, mcpServers };
})();
