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
  let thinkMode = false; // the Think button: Elaina shows her full thinking
  let thinking = null; // the fog box of the current turn, while it is open

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
      addRow("elaina", box);
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
      currentChat = e.current;
      if (!$("chats")) return;
      const items = e.chats.map((chat) => {
        const open = itemButton("item-main", "", () => {
          if (chat.id !== currentChat) run(() => api.open_chat(chat.id), { showDots: false });
        });
        open.append(el("span", "item-title", chat.title), el("span", "item-when", whenWas(chat.updated)));
        open.title = `${chat.title}\nLast message ${new Date(chat.updated).toLocaleString()}`;
        const remove = itemButton("item-delete", "✕", () => confirmDelete(remove, chat.id));
        remove.setAttribute("aria-label", `Delete chat: ${chat.title}`);
        remove.title = "Delete this chat";
        const li = el("li", chat.id === e.current ? "current" : "");
        li.append(open, remove);
        return li;
      });
      $("chats").replaceChildren(...(items.length ? items : [el("li", "muted", "No chats yet")]));
    },

    Transcript(e) {
      bubble = null;
      messages.replaceChildren(empty);
      empty.hidden = e.items.length > 0;
      for (const item of e.items) {
        if (item.role === "result") draw.Result(item);
        else message(item.role === "user" ? "user" : item.role === "error" ? "error" : "elaina", item.text);
      }
      messages.scrollTop = messages.scrollHeight;
    },
  };

  // "12:43", "Yesterday" or "Oct 30": enough to find a chat by.
  function whenWas(moment) {
    const then = new Date(moment);
    const days = Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(then).setHours(0, 0, 0, 0)) / 86400000);
    if (days <= 0) return then.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    if (days === 1) return "Yesterday";
    return then.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function itemButton(className, text, onClick) {
    const button = el("button", className, text);
    button.type = "button";
    button.addEventListener("click", () => {
      if (!busy) onClick();
    });
    return button;
  }

  // Deleting a chat cannot be undone, so the first click only arms the
  // button ("Delete?") and a second click within a few seconds deletes.
  function confirmDelete(button, id) {
    if (!button.classList.contains("confirm")) {
      button.classList.add("confirm");
      button.textContent = "Delete?";
      setTimeout(() => {
        button.classList.remove("confirm");
        button.textContent = "✕";
      }, 3000);
      return;
    }
    run(() => api.delete_chat(id), { showDots: false });
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
    thinking.header.textContent = thinking.thought ? `Thought for ${seconds}s` : `Worked it out in ${steps}`;
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
    sendButton.disabled = value || !input.value.trim();
    newChatButton.disabled = value;
    document.querySelectorAll(".item-main, .item-delete").forEach((b) => (b.disabled = value));
  }

  function begin({ showDots = true } = {}) {
    // Old questions and cards are answered once the user moves on.
    document.querySelectorAll(".choices button").forEach((b) => (b.disabled = true));
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
      if (m.user) message("user", m.user);
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

  function submit() {
    const text = input.value.trim();
    if (!text || busy) return;
    input.value = "";
    grow();
    message("user", text);
    run(() => api.send(text, thinkMode));
  }

  function grow() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    sendButton.disabled = busy || !input.value.trim();
  }

  // The full window acts through the chat, so Elaina's replies and
  // questions land in one place. Each returns false while she is busy.

  function say(text) {
    if (!api || busy) return false;
    message("user", text);
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

  $("think").addEventListener("click", () => {
    thinkMode = !thinkMode;
    $("think").setAttribute("aria-pressed", String(thinkMode));
    $("think").classList.toggle("on", thinkMode);
    if ($("think-hint")) {
      $("think-hint").textContent = thinkMode
        ? "Think is on: Elaina shows her thinking first (slower)"
        : "Think is off";
    }
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

  return { onEvent, mirror, shown, say, prefill, toggleAgent, deleteAgent };
})();
