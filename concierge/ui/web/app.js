// Draws the events the engine sends (see concierge/events.py) and passes the
// user's text and clicks back through window.pywebview.api. Nothing here
// decides anything: it only shows what the engine says.
//
// Text from the engine is always set with textContent, never as HTML, so
// whatever the model writes is shown as plain text.

window.app = (() => {
  const $ = (id) => document.getElementById(id);
  const messages = $("messages");
  const empty = $("empty");
  const input = $("input");
  const sendButton = $("send");
  const newChatButton = $("new-chat");

  let api = null;
  let busy = false;
  let bubble = null; // Elaina's message that streamed text is added to
  let typing = null; // the "..." row shown until the first event arrives

  // ------------------------------------------------------------- drawing

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Keep the newest message in view, unless the user scrolled up to read.
  function follow(change) {
    const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
    change();
    if (atBottom) messages.scrollTop = messages.scrollHeight;
  }

  function addRow(who, content) {
    const row = el("div", `row ${who}`);
    row.append(content);
    empty.hidden = true;
    follow(() => messages.append(row));
    return row;
  }

  function message(who, text) {
    const node = el("div", `bubble ${who}`, text);
    addRow(who, node);
    return node;
  }

  function list(className, items) {
    const node = el("ul", className);
    node.append(...items.map((item) => el("li", "", item)));
    return node;
  }

  function choiceButtons(id, options) {
    const group = el("div", "choices");
    for (const option of options) {
      const button = el("button", "choice", option);
      button.type = "button";
      button.addEventListener("click", () => {
        if (busy) return;
        button.classList.add("picked");
        message("user", option);
        run(() => api.choose(id, option));
      });
      group.append(button);
    }
    return group;
  }

  function finishBubble() {
    if (bubble && !bubble.textContent.trim()) bubble.parentElement.remove();
    bubble = null;
  }

  function showTyping() {
    typing = el("div", "bubble elaina typing");
    typing.append(el("span"), el("span"), el("span"));
    addRow("elaina", typing);
  }

  function hideTyping() {
    if (typing) typing.parentElement.remove();
    typing = null;
  }

  // One function per event type in events.py.
  const draw = {
    SystemInfo(e) {
      $("model-line").textContent = `Running on ${e.in_use} · ${e.device}`;
      $("note").textContent = e.note;
      $("note").hidden = !e.note;
      $("about-hardware").replaceChildren(...e.hardware.map((line) => el("li", "", line)));
      $("about-recommended").textContent = e.recommended || "None fits this computer yet";
      $("about-in-use").textContent = e.in_use;
      $("about-device").textContent = e.device;
    },

    ElainaText(e) {
      if (!bubble) bubble = message("elaina", "");
      follow(() => bubble.append(e.text));
    },

    ElainaDone() {
      finishBubble();
    },

    Question(e) {
      const row = message("elaina", e.text).parentElement;
      if (e.choices && e.choices.length) row.append(choiceButtons(e.id, e.choices));
    },

    AgentCard(e) {
      const card = el("div", "card");
      card.append(el("div", "card-name", e.name), el("div", "card-kind", e.kind));
      card.append(el("div", "card-label", "Reads"), list("card-list", e.reads));
      card.append(el("div", "card-label", "Can do"), list("card-list", e.can_do));
      card.append(el("div", "card-label", "Cannot do"), list("card-list", e.cannot_do));
      card.append(el("div", "card-label", "Runs on"), el("div", "card-value", e.runs_on));
      card.append(choiceButtons(e.id, e.actions));
      addRow("elaina", card);
    },

    Progress(e) {
      $("progress-text").textContent = e.text;
      $("progress").hidden = false;
    },

    Result(e) {
      const box = el("div", "result");
      box.append(el("div", "result-agent", e.agent), el("div", "result-text", e.text));
      if (e.sources.length) {
        const quoted = e.sources.map((s) => (s.quote ? `${s.path}: “${s.quote}”` : s.path));
        box.append(list("sources", quoted));
      }
      addRow("elaina", box);
    },

    AgentList(e) {
      const names = e.agents.length
        ? e.agents.map((name) => el("li", "agent", name))
        : [el("li", "muted", "No agents yet")];
      $("agents").replaceChildren(...names);
    },

    Error(e) {
      message("error", e.text);
    },
  };

  // Called from Python (ChatBridge._push) with events.to_dict(event).
  function onEvent(event) {
    hideTyping();
    // Progress is cleared by any other event, as events.py asks.
    if (event.type !== "Progress") $("progress").hidden = true;
    // Anything drawn in the chat ends the message Elaina was streaming into.
    if (["Question", "AgentCard", "Result", "Error"].includes(event.type)) finishBubble();

    const handler = draw[event.type];
    if (handler) handler(event);
    else console.warn("No drawing for event", event);
  }

  // ------------------------------------------------------------- calling

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value || !input.value.trim();
    newChatButton.disabled = value;
  }

  // Runs one engine call. The input stays off until Python returns, which is
  // after the last event of the call has been drawn.
  async function run(call, { showDots = true } = {}) {
    // Old questions and cards are answered once the user moves on.
    document.querySelectorAll(".choices button").forEach((b) => (b.disabled = true));
    setBusy(true);
    if (showDots) showTyping();
    try {
      await call();
    } catch (err) {
      console.error(err);
      draw.Error({ text: "Something went wrong on my side. Please try again." });
    } finally {
      hideTyping();
      finishBubble();
      $("progress").hidden = true;
      setBusy(false);
      input.focus();
    }
  }

  function submit() {
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    grow();
    message("user", text);
    run(() => api.send(text));
  }

  function grow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    sendButton.disabled = busy || !input.value.trim();
  }

  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    submit();
  });

  input.addEventListener("keydown", (e) => {
    // isComposing: Enter also confirms a Korean, Japanese or Chinese
    // character while typing it, and must not send the message then.
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      submit();
    }
  });

  input.addEventListener("input", grow);

  newChatButton.addEventListener("click", async () => {
    if (busy) return;
    await api.reset();
    bubble = null;
    messages.replaceChildren(empty);
    empty.hidden = false;
    input.focus();
  });

  $("about-open").addEventListener("click", () => $("about").showModal());

  // ------------------------------------------------------------- startup

  function start() {
    if (api) return;
    api = window.pywebview.api;
    run(() => api.startup(), { showDots: false });
  }

  // pywebview adds window.pywebview.api after the page loads, then fires
  // pywebviewready. Check first in case that already happened.
  if (window.pywebview && window.pywebview.api && window.pywebview.api.startup) start();
  else window.addEventListener("pywebviewready", start);

  return { onEvent };
})();
