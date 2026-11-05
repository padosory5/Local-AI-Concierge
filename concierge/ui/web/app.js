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
  let ownName = ""; // her own model, for an answer made here when the menu says Auto
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
      if (/^\*\*.+\*\*$/.test(piece)) {
        const strong = el("strong");
        strong.dataset.label = piece.slice(2, -2); // where a photo of the place it names goes
        strong.append(...keys(piece.slice(2, -2)));
        parts.push(strong);
      } else if (/^`.+`$/.test(piece)) parts.push(el("code", "", piece.slice(1, -1)));
      else if (piece) parts.push(...keys(piece));
    }
    return parts;
  }

  // Keys drawn as keys: "Win + Shift + S" is three keys to press, so it shows as
  // three. A combination starts with a key held down; Print Screen is a key alone.
  const KEY = String.raw`(?:Ctrl|Control|Alt|Shift|Win|Windows|Cmd|Command|Option|Fn|Tab|Esc|Enter|Space|Delete|Del|Backspace|PrtScn|PrtSc|Print Screen|Home|End|PgUp|PgDn|F\d{1,2}|[A-Z0-9]|[↑↓←→])`;
  const HELD = String.raw`(?:Ctrl|Control|Alt|Shift|Win|Windows|Cmd|Command|Option|Fn)`;
  const COMBO = new RegExp(String.raw`\b${HELD}(?:\s*\+\s*${KEY})+(?!\w)|\b(?:PrtScn|PrtSc|Print Screen)\b`, "gi");

  function keys(text) {
    const parts = [];
    let last = 0;
    for (const match of text.matchAll(COMBO)) {
      if (match.index > last) parts.push(text.slice(last, match.index));
      const combo = el("span", "keys");
      match[0].split(/\s*\+\s*/).forEach((key, i) => {
        if (i) combo.append(el("span", "key-plus", "+"));
        combo.append(el("kbd", "", key));
      });
      parts.push(combo);
      last = match.index + match[0].length;
    }
    if (last < text.length) parts.push(text.slice(last));
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

  function tokens(count) {
    if (count >= 1000000) return `${(count / 1000000).toFixed(1)}M`;
    if (count >= 10000) return `${Math.round(count / 1000)}k`;
    return count >= 1000 ? `${(count / 1000).toFixed(1)}k` : String(count);
  }

  // Which model wrote an answer, as a dot at the start of the line under it: blue
  // on this computer, yellow from a plan or key, turning red as the plan fills up.
  // `info` is the ElainaDone, or a saved transcript item (both have where, by,
  // saved, plan_used). Set phrases and chats saved before this have no `where`.
  function whoAnswered(row, info) {
    if (!info || !info.where) return;
    const line = row.lastElementChild; // the line details() just added
    const dot = el("span", `who-dot ${info.where}`);
    const used = info.plan_used >= 0 ? Math.min(info.plan_used, 1) : 0;
    if (info.where === "cloud") dot.style.setProperty("--hue", String(Math.round(48 - 48 * used)));
    const by = info.by || modelName;
    dot.title = info.where === "here" ? `Written on this computer${by ? ` by ${by}` : ""}`
      : `Written by ${by || "a model over the internet"}`
        + (info.plan_used >= 0 ? `. Your plan was ${Math.round(info.plan_used * 100)}% used after it.` : "");
    dot.setAttribute("role", "img");
    dot.setAttribute("aria-label", dot.title);
    line.prepend(dot);
    if (info.where === "here" && info.saved > 0) {
      const saved = el("span", "meta-saved", `Saved about ${tokens(info.saved)} tokens`);
      saved.title = "Answered on this computer instead of your plan. About what it would have used, "
        + "counting the instructions its app sends with every question.";
      line.querySelector(".meta-copy") ? line.insertBefore(saved, line.querySelector(".meta-copy")) : line.append(saved);
    }
  }

  function sentBy(user, files) {
    clearAfter(); // the buttons under the last answer would ask the wrong question now
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

  // The row of buttons under the newest answer, made once and shared: Ask X instead
  // (Auto kept the answer here), then Shorter and More detail. Cleared by the next message.
  function buttonRow(row) {
    let buttons = row.querySelector(".follow-ups");
    if (!buttons) {
      buttons = el("div", "follow-ups after");
      row.append(buttons);
    }
    return buttons;
  }

  // Auto kept this answer on the computer: one click asks the plan's model instead.
  // Only the newest answer has it, because it asks the last question again.
  function askInstead(row, name) {
    const again = el("button", "follow-up follow-instead", `Ask ${name} instead`);
    again.type = "button";
    again.title = `Ask the same question again, answered by ${name}. Uses some of your plan.`;
    again.addEventListener("click", () => {
      if (busy) return;
      const words = `Ask ${name} instead`;
      sentBy(words);
      run(() => api.ask_again(words));
    });
    buttonRow(row).prepend(again);
  }

  function finishBubble(done) {
    if (bubble && !bubble.textContent.trim()) bubble.parentElement.remove();
    else if (bubble) {
      const took = Math.max(1, Math.round((Date.now() - turnStarted) / 1000));
      // With Auto, the reply says which model wrote it; the menu only says "Auto".
      const who = (done && done.by) || (done && done.where === "here" ? ownName || "This computer" : modelName);
      details(bubble.parentElement, [clock(), who, `${took}s`].filter(Boolean).join(" · "), bubbleText);
      whoAnswered(bubble.parentElement, done);
      if (done && done.instead) askInstead(bubble.parentElement, done.instead);
      afterAnswer(bubble.parentElement, bubble, bubbleText);
    }
    bubble = null;
    bubbleText = "";
  }

  // ------------------------------------------------- under her answer

  // Shorter and More detail, so more is one click away instead of a question
  // tacked on the end. Only under the newest answer, and only under a real answer
  // (the engine says which: a setup's message has nothing to shorten).
  const FOLLOW_UPS = { shorter: "Shorter, please.", more: "Tell me more." }; // the same words as engine.FOLLOW_UPS
  const SHORTER_FROM_WORDS = 30;

  async function afterAnswer(row, node, text) {
    if (!api || !api.after_answer) return;
    const can = (await api.after_answer(text)) || {};
    if (!row.isConnected || messages.lastElementChild !== row) return; // something newer has started
    // Older answers lose their buttons; this answer keeps the Ask X instead it may already have.
    messages.querySelectorAll(".after").forEach((node) => {
      if (!row.contains(node)) node.remove();
    });
    if (can.follow_ups) {
      const buttons = buttonRow(row);
      if (text.trim().split(/\s+/).length >= SHORTER_FROM_WORDS) buttons.append(followButton("shorter", "Shorter"));
      buttons.append(followButton("more", "More detail"));
    }
    const photos = photosSetting();
    if (photos === "on") showPictures(node, await api.pictures(text));
    else if (photos === null && can.places) askAboutPhotos(row, node, text);
  }

  function followButton(which, label) {
    const button = el("button", "follow-up", label);
    button.type = "button";
    button.addEventListener("click", () => {
      if (busy) return;
      sentBy(FOLLOW_UPS[which]);
      run(() => api.follow_up(which, thinkMode));
    });
    return button;
  }

  function clearAfter() {
    messages.querySelectorAll(".after").forEach((node) => node.remove());
  }

  // Photos of places come from Wikipedia, so nothing is looked up until the user
  // says yes once, here or on What I see. Kept in the page, like Think.
  function photosSetting() {
    try {
      return localStorage.getItem("photos");
    } catch {
      return "off";
    }
  }

  function setPhotos(on) {
    try {
      localStorage.setItem("photos", on ? "on" : "off");
    } catch {}
  }

  function askAboutPhotos(row, node, text) {
    const ask = el("div", "photo-ask after");
    const yes = el("button", "follow-up", "Show photos");
    const no = el("button", "follow-up", "No thanks");
    yes.type = no.type = "button";
    yes.addEventListener("click", async () => {
      setPhotos(true);
      ask.remove();
      showPictures(node, await api.pictures(text));
    });
    no.addEventListener("click", () => {
      setPhotos(false);
      ask.remove();
    });
    ask.append(el("span", "", "This plan names places. Show their photos from Wikipedia? Only the place names are looked up."), yes, no);
    follow(() => row.append(ask));
  }

  // Each photo goes right beside the line it shows, not in a gallery at the end:
  // people connect a picture with the words next to it.
  function showPictures(node, found) {
    for (const picture of found || []) {
      const label = [...node.querySelectorAll("strong")].find((strong) => strong.dataset.label === picture.label);
      const line = label && label.closest("li, p, h4");
      if (!line || line.querySelector(".beside")) continue;
      const figure = el("figure", "beside");
      const image = el("img");
      image.alt = picture.title;
      image.addEventListener("error", () => figure.remove());
      image.src = picture.image;
      figure.title = [picture.about, "Photo from Wikipedia"].filter(Boolean).join(" · ");
      figure.append(image, el("figcaption", "", picture.title));
      line.classList.add("with-picture");
      follow(() => line.prepend(figure));
    }
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

    ElainaDone(e) {
      finishBubble(e);
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
          if (who === "elaina") {
            details(node.parentElement, item.by || "", item.text);
            whoAnswered(node.parentElement, item); // the same dot as when it was written
          }
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

  // What the + button added, waiting above the text until it's sent. A long paste
  // comes here too, with its words, so a click can put them back in the box.
  function attach(paths, pasted = "") {
    for (const path of paths) {
      if (!attached.some((file) => file.path === path)) {
        attached.push(pasted ? { path, name: "Pasted text", pasted } : { path, name: path.split(/[\\/]/).pop() });
      }
    }
    drawAttached();
    input.focus();
  }

  function drawAttached() {
    const chips = attached.map((file) => {
      const chip = el("span", "chip", file.name);
      if (file.pasted) {
        const lines = file.pasted.split("\n").length;
        chip.classList.add("pasted");
        chip.append(el("span", "chip-lines", lines > 1 ? `${lines} lines` : `${file.pasted.length} letters`));
        chip.title = "Click to put it back in the box";
        chip.addEventListener("click", (event) => {
          if (event.target.closest("button")) return;
          attached = attached.filter((other) => other !== file);
          input.setRangeText(file.pasted, input.selectionStart, input.selectionEnd, "end");
          drawAttached();
          grow();
          input.focus();
        });
      }
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

  function setModelName(name, own = "") {
    modelName = name;
    ownName = own || ownName;
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

  // A long paste becomes a file above the box, the way other AI apps do it, so the
  // box stays small and the chat shows "Pasted text" instead of a wall of words.
  // It goes to her like any added file, cut to what a small model can read.
  const PASTE_AS_FILE_CHARS = 1500;
  const PASTE_AS_FILE_LINES = 20;
  input.addEventListener("paste", async (e) => {
    const text = e.clipboardData ? e.clipboardData.getData("text/plain") : "";
    if (!text || !api || !api.paste_text) return;
    if (text.length < PASTE_AS_FILE_CHARS && text.split("\n").length < PASTE_AS_FILE_LINES) return;
    e.preventDefault();
    attach(await api.paste_text(text), text);
  });

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
