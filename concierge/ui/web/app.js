// Draws the events the engine sends (see concierge/events.py) and passes the
// user's text and clicks back through window.pywebview.api. Nothing here
// decides anything: it only shows what the engine says.
//
// Text from the engine is always set with textContent, never as HTML, so
// whatever the model writes is shown as plain text.
//
// The full window (today.html) uses this script. The see-through window
// (glass.html) has its own, and Python sends every event to both, so both show
// the same conversation (see ChatHub in window.py).

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
  let currentChat = null; // id of the open conversation, from ChatList
  let thinkMode = true; // the Think button: Elaina shows her full thinking
  let thinking = null; // the fog box of the current turn, while it is open
  let bubbleText = ""; // what's been said so far in that message, before formatting
  let modelName = ""; // who is answering, shown under each reply
  let turnStarted = 0;
  let attached = []; // { path, name } waiting to go with the next message

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
    const node = el("div", `bubble ${who}`);
    if (who === "elaina") node.append(...rich(text));
    else node.textContent = text;
    addRow(who, node);
    return node;
  }

  // Elaina's replies come with small marks for lists, bold words and code. They
  // are turned into real elements here, still never as HTML.
  function inline(text) {
    const parts = [];
    for (const piece of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/)) {
      if (/^\*\*.+\*\*$/.test(piece)) parts.push(el("strong", "", piece.slice(2, -2)));
      else if (/^`.+`$/.test(piece)) parts.push(el("code", "", piece.slice(1, -1)));
      else if (piece) parts.push(piece);
    }
    return parts;
  }

  function rich(text) {
    const out = [];
    let group = null; // the list or code block being added to
    for (const line of text.split("\n")) {
      if (group && group.tagName === "PRE") {
        if (line.startsWith("```")) group = null;
        else group.append(`${line}\n`);
        continue;
      }
      const bullet = line.match(/^\s*[-*•]\s+(.*)/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)/);
      const heading = line.match(/^#{1,4}\s+(.*)/);
      if (line.startsWith("```")) {
        group = el("pre");
        out.push(group);
      } else if (bullet || numbered) {
        const tag = bullet ? "UL" : "OL";
        if (!group || group.tagName !== tag) {
          group = el(tag.toLowerCase());
          out.push(group);
        }
        const item = el("li");
        item.append(...inline((bullet || numbered)[1]));
        group.append(item);
      } else if (line.trim()) {
        group = null;
        const paragraph = el(heading ? "h4" : "p");
        paragraph.append(...inline(heading ? heading[1] : line));
        out.push(paragraph);
      } else if (group) {
        group = null;
      }
    }
    return out;
  }

  function clock() {
    // In English like the rest of the app, not half in the computer's own language.
    return new Date().toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  }

  // A small line under a message: when, who, how long, and Copy.
  function details(row, words, text) {
    const line = el("div", "meta", words);
    if (text) {
      const copy = el("button", "meta-copy", "Copy");
      copy.type = "button";
      copy.addEventListener("click", async () => {
        await navigator.clipboard.writeText(text);
        copy.textContent = "Copied";
        setTimeout(() => (copy.textContent = "Copy"), 1500);
      });
      line.append(copy);
    }
    row.append(line);
  }

  function sentBy(user, files) {
    const node = message("user", user);
    if (files && files.length) {
      const names = el("div", "sent-files");
      names.append(...files.map((name) => el("span", "sent-file", name)));
      node.parentElement.insertBefore(names, node);
      if (!user) node.remove();
    }
    details(node.parentElement || messages.lastElementChild, clock());
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
        sentBy(option);
        run(() => api.choose(id, option));
      });
      group.append(button);
    }
    return group;
  }

  function finishBubble() {
    if (bubble && !bubble.textContent.trim()) bubble.parentElement.remove();
    else if (bubble) {
      const took = Math.max(1, Math.round((Date.now() - turnStarted) / 1000));
      details(bubble.parentElement, [clock(), modelName, `${took}s`].filter(Boolean).join(" · "), bubbleText);
    }
    bubble = null;
    bubbleText = "";
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
      if (!$("about")) return; // the panel shows only the model line
      $("note").textContent = e.note;
      $("note").hidden = !e.note;
      $("about-hardware").replaceChildren(...e.hardware.map((line) => el("li", "", line)));
      $("about-recommended").textContent = e.recommended || "None fits this computer yet";
      $("about-in-use").textContent = e.in_use;
      $("about-device").textContent = e.device;
    },

    // Elaina working it out: faded "fog" that streams in, then folds into
    // one line ("Thought for 12s") as soon as anything else arrives.
    Thinking(e) {
      const box = thinkingBox();
      if (e.kind === "thought") {
        if (!box.thought) {
          box.thought = el("div", "thinking-thought");
          box.body.append(box.thought);
        }
        box.thought.append(e.text);
      } else {
        box.body.append(el("div", "thinking-step", e.text));
        box.steps += 1;
      }
      box.body.scrollTop = box.body.scrollHeight;
      follow(() => {});
    },

    ElainaText(e) {
      if (!bubble) bubble = message("elaina", "");
      bubbleText += e.text;
      follow(() => bubble.replaceChildren(...rich(bubbleText)));
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

    IdeaCard(e) {
      const words = { ready: "Ready", not_built: "Not built yet", not_possible: "Not possible", unclear: "Not sure" };
      const steps = el("ul", "idea-steps");
      for (const step of e.steps) {
        const li = el("li", "idea-step");
        const text = el("span", "", step.text);
        if (step.note) text.append(el("span", "idea-note", step.note));
        li.append(el("span", `idea-status ${step.status}`, words[step.status] || step.status), text);
        steps.append(li);
      }
      const card = el("div", `card idea ${e.level}`);
      card.append(el("div", "card-name", e.title), el("div", "card-kind", "Your idea"));
      card.append(el("div", "card-label", "What it needs"), steps);
      if (e.difficulty) card.append(el("div", "card-label", "On this computer"), el("div", "card-value", e.difficulty));
      card.append(el("div", "idea-verdict", e.verdict));
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
      details(addRow("elaina", box), "", e.text);
    },

    AgentList(e) {
      if (!$("agents")) return;
      const switchable = new Set(e.switchable || []);
      const active = new Set(e.active || []);
      const items = e.agents.map((name) => {
        let use;
        if (switchable.has(name)) {
          // Switch-on agents work outside the chat: clicking switches them.
          const on = active.has(name);
          use = itemButton("item-main", "", () => run(() => api.toggle_agent(name), { showDots: false }));
          use.append(el("span", "item-name", name), el("span", `switch ${on ? "on" : "off"}`, on ? "On" : "Off"));
          use.title = on ? `${name} is on. Click to switch it off` : `Click to switch ${name} on`;
          use.setAttribute("aria-pressed", String(on));
        } else {
          // Clicking an agent starts a message to it, which is how it is used.
          use = itemButton("item-main", name, () => {
            input.value = `${name}: `;
            grow();
            input.focus();
          });
          use.title = `Ask ${name} something`;
        }
        // Elaina asks to confirm in the chat, so the engine decides.
        const remove = itemButton("item-delete", "✕", () => run(() => api.delete_agent(name)));
        remove.setAttribute("aria-label", `Delete ${name}`);
        remove.title = `Delete ${name}`;
        const li = el("li", "agent");
        li.append(use, remove);
        return li;
      });
      $("agents").replaceChildren(...(items.length ? items : [el("li", "muted", "No agents yet")]));
    },

    Error(e) {
      message("error", e.text);
    },

    ChatList(e) {
      currentChat = e.current; // today.js draws the list, with pins and search
    },

    Transcript(e) {
      bubble = null;
      messages.replaceChildren(empty);
      empty.hidden = e.items.length > 0;
      for (const item of e.items) {
        if (item.role === "result") draw.Result(item);
        else {
          const who = item.role === "user" ? "user" : item.role === "error" ? "error" : "elaina";
          const node = message(who, item.text);
          if (who === "elaina") details(node.parentElement, "", item.text);
        }
      }
      messages.scrollTop = messages.scrollHeight;
    },
  };

  function itemButton(className, text, onClick) {
    const button = el("button", className, text);
    button.type = "button";
    button.addEventListener("click", () => {
      if (!busy) onClick();
    });
    return button;
  }

  function thinkingBox() {
    if (thinking) return thinking;
    const box = el("div", "thinking live open");
    const header = el("button", "thinking-header", "Thinking");
    header.type = "button";
    header.addEventListener("click", () => box.classList.toggle("open"));
    const body = el("div", "thinking-body");
    box.append(header, body);
    addRow("elaina", box);
    thinking = { box, header, body, started: Date.now(), steps: 0, thought: null };
    return thinking;
  }

  function finishThinking() {
    if (!thinking) return;
    const seconds = Math.max(1, Math.round((Date.now() - thinking.started) / 1000));
    const steps = `${thinking.steps} step${thinking.steps === 1 ? "" : "s"}`;
    // One decision says more as itself than as "1 step".
    const only = thinking.steps === 1 && !thinking.thought && thinking.body.textContent;
    thinking.header.textContent = only || (thinking.thought ? `Thought for ${seconds}s` : `Worked it out in ${steps}`);
    thinking.box.classList.remove("live", "open");
    thinking = null;
  }

  // Called from Python (ChatBridge._push) with events.to_dict(event).
  function onEvent(event) {
    hideTyping();
    // The fog folds away as soon as the answer, or anything else, arrives.
    if (event.type !== "Thinking") finishThinking();
    // Progress is cleared by any other event, as events.py asks.
    if (event.type !== "Progress") $("progress").hidden = true;
    // Anything drawn in the chat ends the message Elaina was streaming into.
    if (["Question", "AgentCard", "IdeaCard", "Result", "Error"].includes(event.type)) finishBubble();

    const handler = draw[event.type];
    if (handler) handler(event);
    else console.warn("No drawing for event", event);
    // The full window's other views read the same events (today.js).
    window.dispatchEvent(new CustomEvent("engine-event", { detail: event }));
  }

  // ------------------------------------------------------------- calling

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value || !canSend();
    newChatButton.disabled = value;
    document.querySelectorAll(".item-main, .item-delete").forEach((b) => (b.disabled = value));
  }

  function begin({ showDots = true } = {}) {
    // Old questions and cards are answered once the user moves on.
    document.querySelectorAll(".choices button").forEach((b) => (b.disabled = true));
    turnStarted = Date.now();
    setBusy(true);
    if (showDots) showTyping();
  }

  function end() {
    finishThinking();
    hideTyping();
    finishBubble();
    $("progress").hidden = true;
    setBusy(false);
  }

  // Runs one engine call. The input stays off until Python returns, which is
  // after the last event of the call has been drawn.
  async function run(call, options) {
    begin(options);
    try {
      await call();
    } catch (err) {
      console.error(err);
      draw.Error({ text: "Something went wrong on my side. Please try again." });
    } finally {
      end();
      input.focus();
    }
  }

  // Called from Python when the other page starts or finishes a call, so this
  // page shows the user's message and waits along with it.
  function mirror(m) {
    if (m.state === "start") {
      if (m.user) sentBy(m.user);
      begin({ showDots: m.dots });
    } else {
      end();
    }
  }

  // Called from Python each time this page's window is shown.
  function shown() {
    messages.scrollTop = messages.scrollHeight;
    input.focus();
    window.dispatchEvent(new CustomEvent("page-shown"));
  }

  function canSend() {
    return Boolean(input.value.trim() || attached.length);
  }

  function submit() {
    const text = input.value.trim();
    if (!canSend() || busy) return;
    const files = attached;
    attached = [];
    drawAttached();
    input.value = "";
    grow();
    sentBy(text, files.map((file) => file.name));
    if (files.length) run(() => api.send_files(text, files.map((file) => file.path), thinkMode));
    else run(() => api.send(text, thinkMode));
  }

  function grow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    input.style.overflowY = input.scrollHeight > 160 ? "auto" : "hidden";
    sendButton.disabled = busy || !canSend();
  }

  // What the + button added, waiting above the text until it's sent.
  function attach(paths) {
    for (const path of paths) {
      if (!attached.some((file) => file.path === path)) {
        attached.push({ path, name: path.split(/[\\/]/).pop() });
      }
    }
    drawAttached();
    input.focus();
  }

  function drawAttached() {
    const chips = attached.map((file) => {
      const chip = el("span", "chip", file.name);
      const remove = el("button", "chip-remove", "×");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${file.name}`);
      remove.addEventListener("click", () => {
        attached = attached.filter((other) => other !== file);
        drawAttached();
      });
      chip.append(remove);
      return chip;
    });
    $("attached").replaceChildren(...chips);
    $("attached").hidden = !chips.length;
    sendButton.disabled = busy || !canSend();
  }

  // The full window acts through the chat, so Elaina's replies and
  // questions land in one place. Each returns false while she is busy.

  function say(text) {
    if (!api || busy) return false;
    sentBy(text);
    run(() => api.send(text, thinkMode));
    return true;
  }

  function prefill(text) {
    input.value = text;
    grow();
    input.focus();
  }

  function toggleAgent(name) {
    if (!api || busy) return false;
    run(() => api.toggle_agent(name), { showDots: false });
    return true;
  }

  function deleteAgent(name) {
    if (!api || busy) return false;
    run(() => api.delete_agent(name));
    return true;
  }

  async function addRecipe(id) {
    if (!api || busy) return false;
    await run(() => api.add_recipe(id), { showDots: false });
    return true;
  }

  function openChat(id) {
    if (api && !busy && id !== currentChat) run(() => api.open_chat(id), { showDots: false });
    return !busy;
  }

  function deleteChat(id) {
    if (api && !busy) run(() => api.delete_chat(id), { showDots: false });
  }

  function setModelName(name) {
    modelName = name;
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

  // The engine keeps the current chat in the list and sends an empty
  // Transcript, which clears the chat area.
  newChatButton.addEventListener("click", () => {
    if (!busy) run(() => api.new_chat(), { showDots: false });
  });

  if ($("about-open")) $("about-open").addEventListener("click", () => $("about").showModal());

  function drawThink() {
    $("think").setAttribute("aria-pressed", String(thinkMode));
    $("think").classList.toggle("on", thinkMode);
  }

  // Remembered between runs, in this page only. If it can't be read, Think is on.
  try {
    thinkMode = localStorage.getItem("think") !== "off";
  } catch {}
  drawThink();

  $("think").addEventListener("click", () => {
    thinkMode = !thinkMode;
    drawThink();
    try {
      localStorage.setItem("think", thinkMode ? "on" : "off");
    } catch {}
    input.focus();
  });

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

  return { onEvent, mirror, shown, say, prefill, toggleAgent, deleteAgent, openChat, deleteChat, attach, setModelName, addRecipe };
})();
